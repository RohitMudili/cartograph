"""Language-agnostic extraction types.

The parser layer produces these plain dataclasses; the graph builder (Phase 2,
part 4) translates them into ORM rows. Keeping extraction output decoupled from
the database means parsers are pure, fast, and unit-testable without a DB, and
adding a language is a new extractor producing the same shapes — not a schema
change.

Symbols carry *local* names and unresolved references. Cross-file resolution
(turning an imported name or a call target into an edge to a concrete node) is
the graph builder's job, because it needs the whole-repo symbol table.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.db.enums import NodeKind


@dataclass(slots=True)
class RawSymbol:
    """A symbol defined in a file: a module, class, function, or method."""

    kind: NodeKind
    # Fully-qualified name within the repo, e.g. "app.auth.jwt.decode_token".
    fqname: str
    # The short local name, e.g. "decode_token".
    name: str
    path: str
    start_line: int  # 1-based, inclusive
    end_line: int
    signature: str | None = None
    docstring: str | None = None
    # fqname of the lexical parent (the class for a method, the module for a
    # top-level function). None for the module symbol itself.
    parent_fqname: str | None = None
    # Source text of this symbol's slice — used for the chunk and content hash.
    source: str = ""
    # Base classes named in the definition (local identifiers), for INHERITS
    # edges. Resolved against the symbol table by the graph builder.
    bases: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RawImport:
    """An import statement: binds a local name to a (possibly external) module/symbol.

    `module` is the dotted module path as written ("a.b.c"); `imported` is the
    specific name imported from it (None for plain `import x`); `alias` is the
    local binding. The graph builder resolves these against in-repo modules to
    create IMPORTS edges, leaving external imports (stdlib, third-party) as
    annotations rather than edges.
    """

    path: str  # the importing file
    module: str
    imported: str | None
    alias: str | None
    line: int
    # True for `from . import x` / `from .pkg import y` — resolved relative to
    # the importing file's package.
    relative: bool = False
    # Number of leading dots for relative imports (1 = current package).
    relative_level: int = 0


@dataclass(slots=True)
class RawCall:
    """A call site: caller symbol invokes some callee name.

    `callee` is the textual target as written ("helper", "os.path.join",
    "self.method"). Resolution to a concrete node — and the confidence of that
    resolution — is the graph builder's job (PLAN.md §12: dynamic dispatch gets
    low confidence, never presented as fact).
    """

    path: str
    caller_fqname: str  # the enclosing function/method; module-level if top-level
    callee: str
    line: int


@dataclass(slots=True)
class FileExtract:
    """Everything extracted from one source file."""

    path: str
    language: str
    symbols: list[RawSymbol] = field(default_factory=list)
    imports: list[RawImport] = field(default_factory=list)
    calls: list[RawCall] = field(default_factory=list)
    # Parse errors (tree-sitter ERROR nodes) — surfaced for diagnostics, never
    # fatal. A file that won't parse still contributes a FILE node.
    had_errors: bool = False
