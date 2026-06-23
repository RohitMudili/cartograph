"""Read-only, repo-scoped tools the enrichment agents use to investigate code.

Everything is served from Postgres — the static graph (`nodes`/`edges`) and the
stored source slices (`chunks`). No re-clone, no filesystem access: the workspace
is already gone by the time the fleet runs, and chunks hold the exact source with
line ranges. This also keeps tools cheap, deterministic, and safe to expose to an
LLM (it can only read, never write or execute).

`RepoTools` bundles the tools for one repo and counts tool calls so the
orchestrator can enforce a per-explorer budget (PLAN.md §2.2 "hard budgets").
Every tool result is a plain dict/list so it serializes straight into a prompt.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Chunk, Edge, Node
from app.query.retrieval import Retriever

log = structlog.get_logger(__name__)

# Per-call output caps — keep tool results prompt-sized, never dump a whole repo.
_MAX_FILE_CHARS = 16_000
_MAX_GREP_HITS = 40
_MAX_NEIGHBORS = 40
_MAX_SEARCH = 12


@dataclass(slots=True)
class RepoTools:
    """Read-only graph/source tools scoped to a single repo, with a call counter."""

    session: AsyncSession
    repo_id: uuid.UUID
    calls: int = field(default=0)

    def _count(self) -> None:
        self.calls += 1

    async def read_file(self, path: str, *, max_chars: int = _MAX_FILE_CHARS) -> dict:
        """Return a file's source, reconstructed from its stored chunks.

        Chunks are per-symbol source slices; concatenating a path's chunks in line
        order rebuilds (most of) the file. Returns the text plus the line span it
        covers. Truncated to `max_chars` so a huge file can't blow the prompt.
        """
        self._count()
        rows = (
            await self.session.scalars(
                select(Chunk)
                .where(Chunk.repo_id == self.repo_id, Chunk.path == path)
                .order_by(Chunk.start_line)
            )
        ).all()
        if not rows:
            return {"path": path, "found": False, "text": "", "note": "no indexed content"}

        # Dedupe overlapping chunks by line range; join distinct slices.
        seen: set[tuple[int, int]] = set()
        parts: list[str] = []
        first_line = rows[0].start_line
        last_line = rows[0].end_line
        for c in rows:
            key = (c.start_line, c.end_line)
            if key in seen:
                continue
            seen.add(key)
            parts.append(c.text)
            first_line = min(first_line, c.start_line)
            last_line = max(last_line, c.end_line)
        text = "\n".join(parts)
        truncated = len(text) > max_chars
        return {
            "path": path,
            "found": True,
            "start_line": first_line,
            "end_line": last_line,
            "truncated": truncated,
            "text": text[:max_chars],
        }

    async def get_node(self, fqname: str) -> dict | None:
        """Look up one node by fully-qualified name. Includes summary + metrics."""
        self._count()
        node = await self.session.scalar(
            select(Node).where(Node.repo_id == self.repo_id, Node.fqname == fqname)
        )
        if node is None:
            return None
        return _node_brief(node)

    async def get_neighbors(self, fqname: str, *, limit: int = _MAX_NEIGHBORS) -> dict:
        """Return the node's graph neighborhood: who it calls/imports/contains and
        who calls/imports/contains it. The structural context for understanding a
        symbol's role."""
        self._count()
        node = await self.session.scalar(
            select(Node.id).where(Node.repo_id == self.repo_id, Node.fqname == fqname)
        )
        if node is None:
            return {"fqname": fqname, "found": False, "outgoing": [], "incoming": []}

        out_rows = (
            await self.session.execute(
                select(Edge.kind, Node.fqname, Node.kind, Edge.confidence)
                .join(Node, Node.id == Edge.dst_node_id)
                .where(Edge.src_node_id == node)
                .limit(limit)
            )
        ).all()
        in_rows = (
            await self.session.execute(
                select(Edge.kind, Node.fqname, Node.kind, Edge.confidence)
                .join(Node, Node.id == Edge.src_node_id)
                .where(Edge.dst_node_id == node)
                .limit(limit)
            )
        ).all()
        return {
            "fqname": fqname,
            "found": True,
            "outgoing": [
                {"edge": str(k), "fqname": fq, "kind": str(nk), "confidence": conf}
                for k, fq, nk, conf in out_rows
            ],
            "incoming": [
                {"edge": str(k), "fqname": fq, "kind": str(nk), "confidence": conf}
                for k, fq, nk, conf in in_rows
            ],
        }

    async def search_graph(self, query: str, *, top_k: int = _MAX_SEARCH) -> list[dict]:
        """Hybrid search (BM25 + dense + graph expansion) over the repo, reusing
        the same retriever the query pipeline uses. Returns ranked nodes with
        summaries and source snippets."""
        self._count()
        items = await Retriever(self.session, self.repo_id).retrieve(
            query, top_k=top_k, expand=True
        )
        return [
            {
                "fqname": it.fqname,
                "kind": it.kind,
                "path": it.path,
                "start_line": it.start_line,
                "end_line": it.end_line,
                "summary": it.summary,
                "snippet": (it.snippet[:600] if it.snippet else None),
            }
            for it in items
        ]

    async def grep(self, pattern: str, *, limit: int = _MAX_GREP_HITS) -> list[dict]:
        """Regex search over stored source chunks. Returns matching lines with
        their path:line, like a code-aware grep. Invalid regex is reported, not
        raised."""
        self._count()
        try:
            rx = re.compile(pattern)
        except re.error as exc:
            return [{"error": f"invalid regex: {exc}"}]

        rows = (
            await self.session.scalars(
                select(Chunk).where(Chunk.repo_id == self.repo_id).order_by(Chunk.path)
            )
        ).all()
        hits: list[dict] = []
        for c in rows:
            for offset, line in enumerate(c.text.splitlines()):
                if rx.search(line):
                    hits.append(
                        {
                            "path": c.path,
                            "line": c.start_line + offset,
                            "text": line.strip()[:200],
                        }
                    )
                    if len(hits) >= limit:
                        return hits
        return hits


def _node_brief(node: Node) -> dict:
    """A compact, prompt-friendly view of a node."""
    return {
        "fqname": node.fqname,
        "kind": str(node.kind),
        "path": node.path,
        "start_line": node.start_line,
        "end_line": node.end_line,
        "signature": node.signature,
        "summary": node.summary,
        "metrics": node.metrics or {},
    }
