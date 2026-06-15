"""Hybrid retrieval: BM25 + dense (pgvector) + graph expansion, fused via RRF.

Given a question and a repo, find the most relevant code so the answerer has
grounded context with exact `file:line` ranges for citations. Three signals,
because no single one is enough for code:

- **BM25 (keyword)** over the chunk full-text (`tsv`). Code questions are often
  exact-identifier lookups ("where is `refresh_token`") where embeddings
  underperform — keyword search nails these.
- **Dense (vector)** cosine over chunk + node-summary embeddings. Catches
  semantic/paraphrased questions ("how does auth work") that share no keywords
  with the code.
- **Graph expansion**: from the top hits, pull 1-hop neighbours (callers,
  callees, container, siblings) so the context *explains* rather than just
  matches — the GraphRAG advantage.

Signals are merged with **Reciprocal Rank Fusion** (RRF): rank-based, scale-free,
no score normalization needed — robust when combining a BM25 score with a cosine
distance. Each retrieved item carries the node/chunk identity and exact line
range, so citations are mechanical downstream.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import structlog
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.llm import UsageLedger, embed_query
from app.db.enums import EdgeKind
from app.db.models import Chunk, Edge, Node

log = structlog.get_logger(__name__)

# RRF constant: dampens the contribution of low-ranked items. 60 is the standard
# value from the original RRF paper and works well in practice.
_RRF_K = 60


@dataclass(slots=True)
class RetrievedItem:
    """One piece of retrieved context, with everything needed to cite it."""

    node_id: int | None
    fqname: str
    kind: str
    path: str | None
    start_line: int | None
    end_line: int | None
    summary: str | None
    snippet: str | None  # source text when available (from a chunk)
    score: float  # fused RRF score
    signals: list[str] = field(default_factory=list)  # which retrievers hit it


def _rrf_merge(ranked_lists: dict[str, list[int]]) -> dict[int, tuple[float, list[str]]]:
    """Reciprocal-rank-fuse several ranked id lists.

    Returns id -> (fused_score, [signal names that ranked it]). An id ranked
    highly by multiple signals rises to the top.
    """
    fused: dict[int, float] = {}
    signals: dict[int, list[str]] = {}
    for signal, ids in ranked_lists.items():
        for rank, _id in enumerate(ids):
            fused[_id] = fused.get(_id, 0.0) + 1.0 / (_RRF_K + rank + 1)
            signals.setdefault(_id, []).append(signal)
    return {i: (fused[i], signals[i]) for i in fused}


class Retriever:
    """Hybrid retriever for one repo."""

    def __init__(self, session: AsyncSession, repo_id: uuid.UUID) -> None:
        self.session = session
        self.repo_id = repo_id

    async def retrieve(
        self,
        question: str,
        *,
        top_k: int = 10,
        per_signal: int = 20,
        expand: bool = True,
        ledger: UsageLedger | None = None,
    ) -> list[RetrievedItem]:
        """Return up to `top_k` retrieved items, fused across all signals."""
        # Each signal returns a ranked list of NODE ids (we map chunk hits to
        # their node) so fusion happens in one id space.
        bm25_ids = await self._bm25_node_ids(question, per_signal)
        dense_ids = await self._dense_node_ids(question, per_signal, ledger=ledger)

        fused = _rrf_merge({"bm25": bm25_ids, "dense": dense_ids})
        if not fused:
            return []

        # Take the fused top-k as seeds.
        seeds = sorted(fused.items(), key=lambda kv: kv[1][0], reverse=True)[:top_k]
        seed_ids = [nid for nid, _ in seeds]

        # Graph expansion: add 1-hop neighbours of the seeds (lower base score).
        expanded: dict[int, tuple[float, list[str]]] = dict(fused)
        if expand and seed_ids:
            neighbours = await self._neighbours(seed_ids)
            for nid in neighbours:
                if nid not in expanded:
                    # Expansion items get a small score so they rank below direct
                    # hits but provide explaining context.
                    expanded[nid] = (1.0 / (_RRF_K * 4), ["graph"])

        # Final ranking + hydrate into RetrievedItem with chunk snippets.
        ranked = sorted(expanded.items(), key=lambda kv: kv[1][0], reverse=True)[:top_k]
        return await self._hydrate(ranked)

    async def _bm25_node_ids(self, question: str, limit: int) -> list[int]:
        """Keyword search over chunk tsv → ranked node ids."""
        # plainto_tsquery is robust to arbitrary user text (no syntax errors).
        stmt = (
            select(
                Chunk.node_id,
                func.ts_rank(Chunk.tsv, func.plainto_tsquery("english", question)).label("rank"),
            )
            .where(
                Chunk.repo_id == self.repo_id,
                Chunk.node_id.isnot(None),
                Chunk.tsv.op("@@")(func.plainto_tsquery("english", question)),
            )
            .order_by(text("rank DESC"))
            .limit(limit)
        )
        rows = (await self.session.execute(stmt)).all()
        # Dedup node ids preserving rank order.
        seen: set[int] = set()
        out: list[int] = []
        for node_id, _ in rows:
            if node_id is not None and node_id not in seen:
                seen.add(node_id)
                out.append(node_id)
        return out

    async def _dense_node_ids(
        self, question: str, limit: int, *, ledger: UsageLedger | None
    ) -> list[int]:
        """Vector search over node summary embeddings → ranked node ids.

        We search node `summary_embedding` (one vector per symbol) rather than
        chunks, so a hit is directly a node; chunk embeddings back the snippet
        hydration. Cosine distance via pgvector's `<=>` operator.
        """
        qvec = await embed_query(question, ledger=ledger)
        stmt = (
            select(Node.id)
            .where(Node.repo_id == self.repo_id, Node.summary_embedding.isnot(None))
            .order_by(Node.summary_embedding.cosine_distance(qvec))
            .limit(limit)
        )
        return list((await self.session.scalars(stmt)).all())

    async def _neighbours(self, node_ids: list[int]) -> set[int]:
        """1-hop neighbours of the seed nodes across meaningful edge kinds."""
        kinds = [EdgeKind.CALLS, EdgeKind.CONTAINS, EdgeKind.IMPORTS, EdgeKind.INHERITS]
        out: set[int] = set()
        # Outgoing (callees, children, imports, bases)
        out_rows = await self.session.scalars(
            select(Edge.dst_node_id).where(
                Edge.repo_id == self.repo_id,
                Edge.src_node_id.in_(node_ids),
                Edge.kind.in_(kinds),
            )
        )
        out.update(out_rows.all())
        # Incoming (callers, container, importers, subclasses)
        in_rows = await self.session.scalars(
            select(Edge.src_node_id).where(
                Edge.repo_id == self.repo_id,
                Edge.dst_node_id.in_(node_ids),
                Edge.kind.in_(kinds),
            )
        )
        out.update(in_rows.all())
        out.difference_update(node_ids)  # neighbours only, not the seeds
        return out

    async def _hydrate(
        self, ranked: list[tuple[int, tuple[float, list[str]]]]
    ) -> list[RetrievedItem]:
        """Load node rows + best chunk snippet for each ranked id."""
        if not ranked:
            return []
        ids = [nid for nid, _ in ranked]
        nodes = {
            n.id: n
            for n in (await self.session.scalars(select(Node).where(Node.id.in_(ids)))).all()
        }
        # One representative chunk per node for the snippet.
        chunk_rows = (
            await self.session.execute(
                select(Chunk.node_id, Chunk.text, Chunk.start_line, Chunk.end_line)
                .where(Chunk.node_id.in_(ids))
                .order_by(Chunk.node_id, Chunk.start_line)
            )
        ).all()
        snippet_by_node: dict[int, str] = {}
        for node_id, ctext, _s, _e in chunk_rows:
            if node_id is not None and node_id not in snippet_by_node:
                snippet_by_node[node_id] = ctext

        items: list[RetrievedItem] = []
        for nid, (score, signals) in ranked:
            n = nodes.get(nid)
            if n is None:
                continue
            items.append(
                RetrievedItem(
                    node_id=n.id,
                    fqname=n.fqname,
                    kind=n.kind.value,
                    path=n.path,
                    start_line=n.start_line,
                    end_line=n.end_line,
                    summary=n.summary,
                    snippet=snippet_by_node.get(nid),
                    score=score,
                    signals=signals,
                )
            )
        return items
