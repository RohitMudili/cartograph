"""Local-route Q&A — retrieve, classify question type, synthesize a cited answer, verify.

The Week-1 milestone: ask the graph a question, get an answer grounded in real
code with **verified** `file:line` citations. Flow:

1. **Classify** the question into a type (onboarding / architecture / specific-symbol /
   how-to / comparison / general) using the cheap Flash-tier model.
2. **Retrieve** hybrid context (BM25 + dense + graph), adjusting breadth per type.
3. Ask the reasoning model for an answer + structured citations, given ONLY that
   context and a **type-tailored system prompt**. The prompt shapes the answer's
   structure (e.g. onboarding leads with purpose, then orientation; specific-symbol
   goes straight to precision).
4. Verify every citation against the indexed source (verifier.py).
5. If any citation fails: ONE regeneration attempt naming the violations. If it
   still fails, ship the answer with the bad citations stripped and a visible
   `unverified` flag — never silently keep a fake citation.

The answer object carries the question type, route, verified citations, and the
retrieved context's identity, so the UI can render the transparency strip.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import StrEnum

import structlog
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.llm import UsageLedger, fast, reasoning
from app.query.retrieval import RetrievedItem, Retriever
from app.query.verifier import Citation, CitationVerifier, VerifiedCitation

log = structlog.get_logger(__name__)

# ── Question type classification ───────────────────────────────────────────


class QuestionType(StrEnum):
    ONBOARDING = "onboarding"
    ARCHITECTURE = "architecture"
    SPECIFIC_SYMBOL = "specific_symbol"
    HOW_TO = "how_to"
    COMPARISON = "comparison"
    GENERAL = "general"


class _QuestionTypeOut(BaseModel):
    """Structured output from the classifier."""

    type: QuestionType = Field(description="The question's intent category.")
    reasoning: str = Field(
        default="", description="Brief one-sentence justification for the classification."
    )


_CLASSIFIER_SYSTEM = (
    "You classify coding questions about a repository into one of these types:\n"
    "- onboarding: getting started, project purpose, how to contribute\n"
    "- architecture: high-level design, how components fit together, data flow\n"
    "- specific_symbol: what a specific function/class/variable does\n"
    "- how_to: how to use something, how to make a change, steps\n"
    "- comparison: difference or trade-off between two or more things\n"
    "- general: anything else that doesn't fit the above\n"
    "Respond with the type and a brief one-sentence justification."
)


_TOP_K_BY_TYPE: dict[QuestionType, int] = {
    QuestionType.ONBOARDING: 15,  # broad — onboarding needs breadth
    QuestionType.ARCHITECTURE: 15,  # broad — architecture needs cross-cutting context
    QuestionType.SPECIFIC_SYMBOL: 8,  # tight — a specific symbol wants precision
    QuestionType.HOW_TO: 10,  # moderate
    QuestionType.COMPARISON: 12,  # moderate-broad — needs both sides
    QuestionType.GENERAL: 10,  # default
}


# ── Type-tailored system prompts ───────────────────────────────────────────


_SYSTEM_ONBOARDING = (
    "You are a technical onboarding guide. A new developer is asking about this repository. "
    "Lead with **purpose** — what this codebase does and why.\n"
    "Then give **orientation** — which files/symbols to read first and why.\n"
    "If applicable, include **how to make common changes or contribute** "
    "(tests, conventions, likely change sites).\n"
    "Cite entry points and key files. Answer ONLY from the provided context — "
    "never invent files, symbols, or behavior not shown. If a previous conversation "
    "is shown, use it for continuity but still answer from the provided code context. "
    " Every concrete claim about the code MUST cite the "
    "exact file and line range it comes from, using the citations field. Quote a "
    "short verbatim snippet from the cited lines so it can be verified."
)

_SYSTEM_ARCHITECTURE = (
    "You are a systems architect explaining a codebase's design. Focus on **how "
    "components fit together**, data flow across layers, and system boundaries.\n"
    "Describe the roles of key modules and how they connect. Use the citations to "
    "point to the architectural boundaries and interfaces.\n"
    "Answer ONLY from the provided context — never invent files, symbols, or behavior "
    "not shown. If a previous conversation is shown, use it for continuity but still "
    "answer from the provided code context. Every concrete claim about the code "
    "MUST cite the exact file and line range it comes from, using the citations field. "
    "Quote a short verbatim snippet from the cited lines so it can be verified."
)

_SYSTEM_SPECIFIC_SYMBOL = (
    "You are a precise code analyst. The user is asking about a specific symbol "
    "(function, class, variable, method).\n"
    "State what it does, its signature/parameters/return value, where it's defined "
    "and key call sites or usage. Be exact — cite the definition line and at least "
    "one call site if the context shows one.\n"
    "Answer ONLY from the provided context — never invent files, symbols, or behavior "
    "not shown. If a previous conversation is shown, use it for continuity but still "
    "answer from the provided code context. Every concrete claim about the code "
    "MUST cite the exact file and line range it comes from, using the citations field. "
    "Quote a short verbatim snippet from the cited lines so it can be verified."
)

_SYSTEM_HOW_TO = (
    "You are a developer experience guide. The user wants to **do something** with "
    "this codebase — use an API, add a feature, make a change.\n"
    "Give step-by-step guidance with real code examples from the context. Show the "
    "relevant patterns, parameters, and conventions.\n"
    "Answer ONLY from the provided context — never invent files, symbols, or behavior "
    "not shown. If a previous conversation is shown, use it for continuity but still "
    "answer from the provided code context. Every concrete claim about the code "
    "MUST cite the exact file and line range it comes from, using the citations field. "
    "Quote a short verbatim snippet from the cited lines so it can be verified."
)

_SYSTEM_COMPARISON = (
    "You are a technical analyst comparing parts of this codebase. Contrast the two "
    "or more things, explaining their **differences in purpose, behavior, and when "
    "each is used**.\n"
    "Use a balanced structure: explain each side fairly, then highlight key "
    "differences. Cite relevant definitions and usage sites for both.\n"
    "Answer ONLY from the provided context — never invent files, symbols, or behavior "
    "not shown. If a previous conversation is shown, use it for continuity but still "
    "answer from the provided code context. Every concrete claim about the code "
    "MUST cite the exact file and line range it comes from, using the citations field. "
    "Quote a short verbatim snippet from the cited lines so it can be verified."
)

_SYSTEM_GENERAL = (
    "You are a precise code-understanding assistant answering questions about a "
    "specific repository. Answer ONLY from the provided context — never invent "
    "files, symbols, or behavior not shown. If a previous conversation is shown, "
    "use it for continuity but still answer from the provided code context. "
    "If the context doesn't contain the "
    "answer, say so plainly. Every concrete claim about the code MUST cite the "
    "exact file and line range it comes from, using the citations field. Quote a "
    "short verbatim snippet from the cited lines so it can be verified. Keep the "
    "answer focused and technical."
)


_SYSTEM_BY_TYPE: dict[QuestionType, str] = {
    QuestionType.ONBOARDING: _SYSTEM_ONBOARDING,
    QuestionType.ARCHITECTURE: _SYSTEM_ARCHITECTURE,
    QuestionType.SPECIFIC_SYMBOL: _SYSTEM_SPECIFIC_SYMBOL,
    QuestionType.HOW_TO: _SYSTEM_HOW_TO,
    QuestionType.COMPARISON: _SYSTEM_COMPARISON,
    QuestionType.GENERAL: _SYSTEM_GENERAL,
}


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
    question_type: QuestionType
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


class QuestionClassifier:
    """Classifies a question into a type so the answerer can adapt its prompt.

    Uses the fast (Flash) model — cheap enough to call inline before retrieval.
    Falls back to `general` on any error so the question never blocks.
    """

    @staticmethod
    async def classify(
        question: str,
        *,
        ledger: UsageLedger | None = None,
    ) -> QuestionType:
        cls_prompt = f"Classify this question about a codebase:\n\n{question}"
        try:
            out = await fast(ledger).complete_structured(
                cls_prompt, _QuestionTypeOut, system=_CLASSIFIER_SYSTEM
            )
            log.debug("question.classified", type=out.type.value, reasoning=out.reasoning)
            return out.type
        except Exception:  # noqa: BLE001  # classifier failure must never block the question
            log.warning("question.classification.failed", exc_info=True)
            return QuestionType.GENERAL


class Answerer:
    """Answers a question about one repo with verified citations (local route).

    Classifies the question type first, then tailors the system prompt and
    retrieval breadth accordingly.
    """

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
        qtype: QuestionType | None = None,
        repo_model: dict | None = None,
        community_lines: list[str] | None = None,
        route: str = "local",
    ) -> Answer:
        """Answer with verified citations.

        The router (query/router.py) may pre-classify (`qtype`), attach
        repo-level enrichment (`repo_model` + `community_lines` for the global
        route), and label the `route`. Called bare, it behaves as the plain
        local route. Verified per-node annotations are always merged in.
        """
        # 1. Classify the question to determine how to answer (unless pre-classified).
        if qtype is None:
            qtype = await QuestionClassifier.classify(question, ledger=ledger)
        top_k = _TOP_K_BY_TYPE.get(qtype, 10)

        items = await self.retriever.retrieve(question, top_k=top_k, ledger=ledger)
        used_nodes = [it.node_id for it in items if it.node_id is not None]

        # Enrichment: verified agent findings on the retrieved nodes (always),
        # plus the repo model / community summaries when the router supplies them
        # (global route). Background knowledge — claims were critic-verified at
        # index time, but line citations must still come from the code context.
        from app.query.enrichment import format_enrichment_block, load_annotations_for_nodes

        annotations = await load_annotations_for_nodes(self.session, self.repo_id, used_nodes)
        enrichment = format_enrichment_block(repo_model, annotations, community_lines or [])

        # Unanswerable only when BOTH retrieval and enrichment came back empty —
        # a big-picture question can be answered from the repo model alone even
        # when no individual chunk matches it.
        if not items and not enrichment:
            return Answer(
                question=question,
                text="I couldn't find anything relevant to that in this repository.",
                question_type=qtype,
                route=route,
                citations=[],
                answerable=False,
                fully_verified=True,
            )

        parts = [p for p in (_format_context(items), enrichment) if p]
        context = "\n\n".join(parts)

        system = _SYSTEM_BY_TYPE.get(qtype, _SYSTEM_GENERAL)

        out = await self._synthesize(
            question,
            context,
            system=system,
            ledger=ledger,
            conversation_history=session_context,
        )
        verified = await self.verifier.verify_all(_to_citations(out.citations))

        # If any citation failed, regenerate once, naming the violations.
        if out.citations and not all(v.verified for v in verified):
            bad = [v.reason for v in verified if not v.verified]
            log.info("answer.citation_retry", repo_id=str(self.repo_id), failures=bad)
            out = await self._synthesize(
                question,
                context,
                system=system,
                ledger=ledger,
                prior_failures=bad,
                conversation_history=session_context,
            )
            verified = await self.verifier.verify_all(_to_citations(out.citations))

        fully_verified = all(v.verified for v in verified)
        return Answer(
            question=question,
            text=out.answer,
            question_type=qtype,
            route=route,
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
        system: str,
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
        return await reasoning(ledger).complete_structured(prompt, _AnswerOut, system=system)


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
