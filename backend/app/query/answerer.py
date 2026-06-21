"""Local-route Q&A — retrieve, synthesize a cited answer, verify the citations.

The Week-1 milestone: ask the graph a question, get an answer grounded in real
code with **verified** `file:line` citations. Flow:

1. Retrieve hybrid context for the question (BM25 + dense + graph).
2. Ask the reasoning model for an answer + structured citations, given ONLY that
   context (so it can't invent files it never saw).
3. Verify every citation against the indexed source (verifier.py).
4. If any citation fails: ONE regeneration attempt naming the violations. If it
   still fails, ship the answer with the bad citations stripped and a visible
   `unverified` flag — never silently keep a fake citation.

The answer object carries the route, the verified citations, the (un)verified
flag, and the retrieved context's identity, so the UI can render the
transparency strip and the consulted subgraph.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import structlog
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.llm import UsageLedger, reasoning
from app.query.retrieval import RetrievedItem, Retriever
from app.query.verifier import Citation, CitationVerifier, VerifiedCitation

log = structlog.get_logger(__name__)

_SYSTEM = (
    "You are a precise code-understanding assistant answering questions about a "
    "specific repository. Answer ONLY from the provided context — never invent "
    "files, symbols, or behavior not shown. If a previous conversation is shown, "
    "use it for continuity but still answer from the provided code context. "
    " If the context doesn't contain the "
    "answer, say so plainly. Every concrete claim about the code MUST cite the "
    "exact file and line range it comes from, using the citations field. Quote a "
    "short verbatim snippet from the cited lines so it can be verified. Keep the "
    "answer focused and technical."
)


class _CitationOut(BaseModel):
    path: str = Field(description="Repo-relative file path, exactly as in the context.")
    start_line: int = Field(description="First line of the cited range (1-based).")
    end_line: int = Field(description="Last line of the cited range.")
    quoted_snippet: str = Field(description="A short verbatim quote from those lines.")


class _AnswerOut(BaseModel):
    answer: str = Field(description="The answer, grounded in the context.")
    citations: list[_CitationOut] = Field(default_factory=list)
    answerable: bool = Field(description="False if the context doesn't contain the answer.")


@dataclass(slots=True)
class Answer:
    question: str
    text: str
    route: str
    citations: list[VerifiedCitation]
    answerable: bool
    fully_verified: bool
    used_nodes: list[int] = field(default_factory=list)

    @property
    def verified_citations(self) -> list[Citation]:
        return [vc.citation for vc in self.citations if vc.verified]


def _format_context(items: list[RetrievedItem]) -> str:
    """Render retrieved items as a numbered context block for the prompt."""
    blocks: list[str] = []
    for i, it in enumerate(items, 1):
        header = f"[{i}] {it.fqname} ({it.kind})"
        if it.path is not None:
            header += f" — {it.path}:{it.start_line}-{it.end_line}"
        body = it.snippet or it.summary or ""
        blocks.append(f"{header}\n{body}")
    return "\n\n".join(blocks)


class Answerer:
    """Answers a question about one repo with verified citations (local route)."""

    def __init__(self, session: AsyncSession, repo_id: uuid.UUID) -> None:
        self.session = session
        self.repo_id = repo_id
        self.retriever = Retriever(session, repo_id)
        self.verifier = CitationVerifier(session, repo_id)

    async def answer(
        self,
        question: str,
        *,
        session_context: str | None = None,
        ledger: UsageLedger | None = None,
    ) -> Answer:
        items = await self.retriever.retrieve(question, top_k=10, ledger=ledger)
        if not items:
            return Answer(
                question=question,
                text="I couldn't find anything relevant to that in this repository.",
                route="local",
                citations=[],
                answerable=False,
                fully_verified=True,
            )

        context = _format_context(items)
        used_nodes = [it.node_id for it in items if it.node_id is not None]

        out = await self._synthesize(
            question, context, ledger=ledger, conversation_history=session_context
        )
        verified = await self.verifier.verify_all(_to_citations(out.citations))

        # If any citation failed, regenerate once, naming the violations.
        if out.citations and not all(v.verified for v in verified):
            bad = [v.reason for v in verified if not v.verified]
            log.info("answer.citation_retry", repo_id=str(self.repo_id), failures=bad)
            out = await self._synthesize(
                question,
                context,
                ledger=ledger,
                prior_failures=bad,
                conversation_history=session_context,
            )
            verified = await self.verifier.verify_all(_to_citations(out.citations))

        fully_verified = all(v.verified for v in verified)
        return Answer(
            question=question,
            text=out.answer,
            route="local",
            citations=verified,
            answerable=out.answerable,
            fully_verified=fully_verified,
            used_nodes=used_nodes,
        )

    async def _synthesize(
        self,
        question: str,
        context: str,
        *,
        ledger: UsageLedger | None,
        prior_failures: list[str] | None = None,
        conversation_history: str | None = None,
    ) -> _AnswerOut:
        parts: list[str] = []
        if conversation_history:
            parts.append(conversation_history)
        parts.append(f"Context:\n{context}")
        parts.append(f"Question: {question}")
        prompt = "\n\n".join(parts)
        if prior_failures:
            prompt += (
                "\n\nYour previous citations failed verification:\n"
                + "\n".join(f"- {f}" for f in prior_failures)
                + "\nCite only file:line ranges present in the context above, and "
                "quote the snippet exactly as it appears."
            )
        return await reasoning(ledger).complete_structured(prompt, _AnswerOut, system=_SYSTEM)


def _to_citations(out: list[_CitationOut]) -> list[Citation]:
    return [
        Citation(
            path=c.path,
            start_line=c.start_line,
            end_line=c.end_line,
            quoted_snippet=c.quoted_snippet,
        )
        for c in out
    ]
