"""Citation verification — the trust layer (PLAN.md §2.3).

Every answer must cite `file:line` ranges, and **every citation is checked
against the actual indexed source before the answer is shown**. A hallucinated
citation (wrong file, wrong lines, or a quoted snippet that isn't really there)
is caught here, not displayed.

We verify against the `chunks` table (the exact source slices we stored at index
time with precise line ranges) — no re-clone needed. A citation is VERIFIED when:

1. Its `path` exists in the repo's chunks, and
2. The cited line range overlaps a chunk for that path, and
3. The `quoted_snippet` (if given) actually appears in that path's source within
   a tolerance window around the cited lines.

Unverifiable citations are flagged, never silently kept. The caller (answerer)
decides what to do — regenerate once, or downgrade the claim to "unverified" and
strip the bad citation. The point: the UI never shows a citation we couldn't
confirm against real code.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Chunk

log = structlog.get_logger(__name__)

# How many lines of slack to allow between the cited range and where the snippet
# actually appears. The model may be off by a line or two; a fake citation is
# off by much more (or the snippet doesn't exist at all).
_LINE_TOLERANCE = 5


@dataclass(slots=True)
class Citation:
    path: str
    start_line: int
    end_line: int
    quoted_snippet: str | None = None


@dataclass(slots=True)
class VerifiedCitation:
    citation: Citation
    verified: bool
    reason: str  # why it passed/failed (for logging + UI transparency)


def _normalize(s: str) -> str:
    """Collapse whitespace so snippet matching tolerates reformatting."""
    return " ".join(s.split())


class CitationVerifier:
    """Verifies citations against a repo's stored source chunks."""

    def __init__(self, session: AsyncSession, repo_id: uuid.UUID) -> None:
        self.session = session
        self.repo_id = repo_id

    async def verify_all(self, citations: list[Citation]) -> list[VerifiedCitation]:
        return [await self.verify(c) for c in citations]

    async def verify(self, citation: Citation) -> VerifiedCitation:
        # 1. Path must exist in the repo's chunks.
        path_chunks = (
            await self.session.scalars(
                select(Chunk).where(Chunk.repo_id == self.repo_id, Chunk.path == citation.path)
            )
        ).all()
        if not path_chunks:
            return VerifiedCitation(citation, False, f"path '{citation.path}' not in repo")

        # 2. The cited line range must overlap a chunk for that path.
        overlapping = [
            ch
            for ch in path_chunks
            if ch.start_line <= citation.end_line and ch.end_line >= citation.start_line
        ]
        if not overlapping:
            return VerifiedCitation(
                citation,
                False,
                f"no source at {citation.path}:{citation.start_line}-{citation.end_line}",
            )

        # 3. If a snippet was quoted, it must actually appear in the source near
        #    the cited range (within tolerance). Gather candidate chunk text in a
        #    window around the citation and match the normalized snippet.
        if citation.quoted_snippet and citation.quoted_snippet.strip():
            lo = citation.start_line - _LINE_TOLERANCE
            hi = citation.end_line + _LINE_TOLERANCE
            window = [ch.text for ch in path_chunks if ch.start_line <= hi and ch.end_line >= lo]
            haystack = _normalize("\n".join(window))
            needle = _normalize(citation.quoted_snippet)
            if needle not in haystack:
                return VerifiedCitation(
                    citation, False, "quoted snippet not found near cited lines"
                )

        return VerifiedCitation(citation, True, "ok")
