"""Domain enums shared by the ORM models and the indexer.

Stored as native Postgres enums for integrity. Python-side they are plain str
enums so they serialize cleanly to JSON and compare against literals.
"""

from __future__ import annotations

from enum import StrEnum


class NodeKind(StrEnum):
    REPO = "repo"
    PACKAGE = "package"
    FILE = "file"
    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"
    CONFIG = "config"
    DOC = "doc"
    TEST = "test"


class EdgeKind(StrEnum):
    CONTAINS = "contains"
    IMPORTS = "imports"
    CALLS = "calls"
    INHERITS = "inherits"
    IMPLEMENTS = "implements"
    TESTS = "tests"


class RepoStatus(StrEnum):
    PENDING = "pending"
    CLONING = "cloning"
    PARSING = "parsing"
    SUMMARIZING = "summarizing"
    ENRICHING = "enriching"  # agent fleet is exploring/annotating the graph
    INDEXED = "indexed"
    FAILED = "failed"


class AgentRole(StrEnum):
    """Who is acting in the enrichment fleet (PLAN.md §2.2)."""

    PLANNER = "planner"
    EXPLORER = "explorer"
    SYNTHESIZER = "synthesizer"
    CRITIC = "critic"
    LIBRARIAN = "librarian"
    SUPERVISOR = "supervisor"  # the graph itself: phase transitions, run lifecycle


class AgentEventType(StrEnum):
    """The kind of thing an agent event records — the Mission Control stream
    vocabulary and the replay/debug log (PLAN.md §3, §4.3)."""

    SPAWN = "spawn"  # an agent (or N explorers) started
    TOOL_CALL = "tool_call"  # an explorer used a tool (read_file, search_graph, …)
    FINDING = "finding"  # an explorer emitted a structured claim
    VERDICT = "verdict"  # the critic accepted/rejected a finding
    PHASE = "phase"  # supervisor phase transition (planning → exploring → …)
    ERROR = "error"  # an agent failed / was cancelled / budget hit
    DONE = "done"  # an agent (or the run) finished


class RunKind(StrEnum):
    FULL = "full"
    INCREMENTAL = "incremental"
    ESCALATION = "escalation"


class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
