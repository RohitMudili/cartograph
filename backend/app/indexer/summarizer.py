"""Semantic layer: per-symbol summaries + embeddings.

Runs *after* the static graph is built. For each symbol node it writes a concise
1-2 line summary, then embeds the summary (for `summary_embedding`) and each chunk
(for `chunk.embedding`) into pgvector. This is the only LLM cost in the indexing
path before the agent fleet — and it's all on the cheap `fast` tier.

Design:
- **Bottom-up.** Leaf symbols (functions/methods) are summarized first; container
  summaries (class, file) are generated afterwards and given their children's
  summaries as context, so a file summary reflects what's actually inside it
  without re-reading every line. This keeps prompts small (cost) and summaries
  coherent (quality) — the GraphRAG bottom-up summarization move.
- **Concurrent + bounded.** Summaries fan out with a semaphore (max_agent_concurrency)
  so a big repo doesn't open thousands of simultaneous requests.
- **Structured output.** Each summary call returns a validated Pydantic object.
- **Cost-tracked.** Every call records into the run's UsageLedger.
- **Embeddings batched.** Summaries and chunk texts are embedded in batches.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass

import structlog
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.llm import UsageLedger, embed_texts, fast
from app.config import get_settings
from app.db.enums import NodeKind
from app.db.models import Chunk, Node

log = structlog.get_logger(__name__)

# Order symbols are summarized in: leaves first, containers last, so a container
# can be summarized with its children's summaries in context.
_KIND_ORDER = {
    NodeKind.FUNCTION: 0,
    NodeKind.METHOD: 0,
    NodeKind.CLASS: 1,
    NodeKind.FILE: 2,
    NodeKind.PACKAGE: 3,
    NodeKind.REPO: 4,
    NodeKind.CONFIG: 0,
    NodeKind.DOC: 0,
    NodeKind.TEST: 0,
}

# Cap how much source/context we send per summary — keeps prompts cheap and
# bounded regardless of a giant function or a huge file.
_MAX_SOURCE_CHARS = 4000
_MAX_CHILD_SUMMARIES = 30
_EMBED_BATCH = 100

_SYSTEM = (
    "You summarize source-code symbols for a codebase knowledge graph. "
    "Write ONE or TWO plain sentences describing what the symbol does and its role. "
    "Be concrete and specific; name what it operates on. No preamble, no markdown, "
    "no restating the signature. If it's a file or class, describe its overall "
    "responsibility, not a list of members."
)


class _Summary(BaseModel):
    summary: str = Field(description="A concise 1-2 sentence description of the symbol.")


@dataclass(slots=True)
class SummarizeStats:
    summarized: int
    embedded_summaries: int
    embedded_chunks: int


def _build_prompt(node: Node, child_summaries: list[str]) -> str:
    parts: list[str] = [f"Kind: {node.kind.value}", f"Name: {node.fqname}"]
    if node.signature:
        parts.append(f"Signature: {node.signature}")
    if node.docstring:
        parts.append(f"Docstring: {node.docstring[:500]}")
    if child_summaries:
        # Containers: summarize from children, not raw source.
        joined = "\n".join(f"- {s}" for s in child_summaries[:_MAX_CHILD_SUMMARIES])
        parts.append(f"Contains (child summaries):\n{joined}")
    return "\n".join(parts)


class Summarizer:
    """Generates and persists summaries + embeddings for one repo's nodes."""

    def __init__(self, session: AsyncSession, repo_id: uuid.UUID, *, ledger: UsageLedger) -> None:
        self.session = session
        self.repo_id = repo_id
        self.ledger = ledger
        self._sem = asyncio.Semaphore(get_settings().max_agent_concurrency)
        # fqname -> generated summary, used to feed container prompts.
        self._summaries: dict[str, str] = {}

    async def run(self) -> SummarizeStats:
        nodes = list(
            (await self.session.scalars(select(Node).where(Node.repo_id == self.repo_id))).all()
        )
        # Map each container to its children's fqnames for bottom-up context.
        children: dict[str, list[str]] = {}
        for n in nodes:
            parent = _parent_fqname(n.fqname)
            if parent:
                children.setdefault(parent, []).append(n.fqname)

        # Summarize in waves by kind order (leaves -> containers).
        for _, wave in _grouped_by_order(nodes):
            await asyncio.gather(*(self._summarize_node(n, children) for n in wave))

        summarized = len(self._summaries)

        # Persist summaries, then embed summaries + chunks.
        await self._persist_summaries(nodes)
        n_sum = await self._embed_summaries(nodes)
        n_chunk = await self._embed_chunks()

        await self.session.flush()
        stats = SummarizeStats(summarized, n_sum, n_chunk)
        log.info("summarize.done", repo_id=str(self.repo_id), **_asdict(stats))
        return stats

    async def _summarize_node(self, node: Node, children: dict[str, list[str]]) -> None:
        child_summaries = [
            self._summaries[c] for c in children.get(node.fqname, []) if c in self._summaries
        ]
        prompt = _build_prompt(node, child_summaries)
        async with self._sem:
            try:
                result = await fast(self.ledger).complete_structured(
                    prompt, _Summary, system=_SYSTEM
                )
                self._summaries[node.fqname] = result.summary.strip()
            except Exception as exc:  # noqa: BLE001 — one bad summary must not kill the run
                log.warning("summarize.node_failed", fqname=node.fqname, error=str(exc))

    async def _persist_summaries(self, nodes: list[Node]) -> None:
        params = [
            {"id": n.id, "summary": self._summaries[n.fqname]}
            for n in nodes
            if n.fqname in self._summaries
        ]
        if params:
            await self.session.execute(update(Node), params)

    async def _embed_summaries(self, nodes: list[Node]) -> int:
        targets = [(n.id, self._summaries[n.fqname]) for n in nodes if n.fqname in self._summaries]
        count = 0
        for batch in _batched(targets, _EMBED_BATCH):
            vectors = await embed_texts([t[1] for t in batch], ledger=self.ledger)
            params = [
                {"id": nid, "summary_embedding": vec}
                for (nid, _), vec in zip(batch, vectors, strict=True)
            ]
            await self.session.execute(update(Node), params)
            count += len(params)
        return count

    async def _embed_chunks(self) -> int:
        chunks = list(
            (await self.session.scalars(select(Chunk).where(Chunk.repo_id == self.repo_id))).all()
        )
        count = 0
        for batch in _batched(chunks, _EMBED_BATCH):
            texts = [c.text[:_MAX_SOURCE_CHARS] for c in batch]
            vectors = await embed_texts(texts, ledger=self.ledger)
            params = [{"id": c.id, "embedding": vec} for c, vec in zip(batch, vectors, strict=True)]
            await self.session.execute(update(Chunk), params)
            count += len(params)
        return count


def _parent_fqname(fqname: str) -> str | None:
    return fqname.rsplit(".", 1)[0] if "." in fqname else None


def _grouped_by_order(nodes: list[Node]) -> list[tuple[int, list[Node]]]:
    buckets: dict[int, list[Node]] = {}
    for n in nodes:
        buckets.setdefault(_KIND_ORDER.get(n.kind, 0), []).append(n)
    return sorted(buckets.items())


def _batched(items: list, size: int) -> list[list]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _asdict(stats: SummarizeStats) -> dict:
    return {
        "summarized": stats.summarized,
        "embedded_summaries": stats.embedded_summaries,
        "embedded_chunks": stats.embedded_chunks,
    }
