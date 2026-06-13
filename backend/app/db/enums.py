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
    INDEXED = "indexed"
    FAILED = "failed"


class RunKind(StrEnum):
    FULL = "full"
    INCREMENTAL = "incremental"
    ESCALATION = "escalation"


class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
