"""TypeScript / JavaScript source extractor (tree-sitter).

One extractor for the whole JS family — `.ts`, `.tsx`, `.js`, `.jsx`, `.mjs`,
`.cjs` — dispatching to the right grammar per extension. Emits the same
language-agnostic shapes as the Python extractor (symbols, imports, calls with
exact 1-based line ranges); no code is executed.

Design choices, where the JS world differs from Python:
- fqname derives from the file path with the extension stripped and a trailing
  `index` segment dropped (`src/utils/index.ts` → `src.utils`, mirroring how
  `__init__.py` collapses to its package), plus lexical nesting.
- Import specifiers are paths, not dotted modules, so RELATIVE specifiers
  (`./utils`, `../lib/foo`) are resolved to dotted module fqnames HERE — the
  graph builder's exact-match module resolution then works unchanged. Bare
  specifiers (`react`, `@scope/pkg`, unresolved aliases) pass through verbatim
  and fall out as external imports downstream.
- Interfaces and enums are emitted as CLASS nodes: they are named type
  containers, which is what retrieval and the graph care about; the signature
  keeps the `interface`/`enum` keyword so answers stay honest.
- `const f = () => {}` / `const f = function () {}` count as functions, and a
  class-property arrow (`onClick = () => {}`) counts as a method — both idioms
  carry most real-world JS/TS code.
- A JSDoc block (`/** … */`) immediately preceding a declaration — or its
  wrapping `export` statement — becomes the docstring.
- CommonJS `const x = require("./y")` is recorded as an import.
"""

from __future__ import annotations

from pathlib import PurePosixPath

import tree_sitter_javascript as tsjavascript
import tree_sitter_typescript as tstypescript
from tree_sitter import Language, Node, Parser

from app.db.enums import NodeKind
from app.indexer.parser.types import (
    FileExtract,
    RawCall,
    RawImport,
    RawSymbol,
)

_TS_LANGUAGE = Language(tstypescript.language_typescript())
_TSX_LANGUAGE = Language(tstypescript.language_tsx())
_JS_LANGUAGE = Language(tsjavascript.language())

# Extension → (grammar, language label). The label lands on FileExtract.language.
_GRAMMARS: dict[str, tuple[Language, str]] = {
    ".ts": (_TS_LANGUAGE, "typescript"),
    ".tsx": (_TSX_LANGUAGE, "tsx"),
    ".js": (_JS_LANGUAGE, "javascript"),
    ".jsx": (_JS_LANGUAGE, "javascript"),
    ".mjs": (_JS_LANGUAGE, "javascript"),
    ".cjs": (_JS_LANGUAGE, "javascript"),
}

# Declaration node types that produce a CLASS symbol.
_CLASSLIKE = {
    "class_declaration",
    "abstract_class_declaration",
    "interface_declaration",
    "enum_declaration",
}

_FUNCTIONLIKE = {"function_declaration", "generator_function_declaration"}

# Value node types that make a variable declarator a function binding.
_FUNCTION_VALUES = {"arrow_function", "function_expression", "function"}


def module_fqname_ts(path: str) -> str:
    """Map a repo-relative JS-family file path to a dotted module name.

    'src/lib/api.ts'          -> 'src.lib.api'
    'src/utils/index.ts'      -> 'src.utils'
    'app.tsx'                 -> 'app'
    """
    p = PurePosixPath(path)
    parts = list(p.parts)
    if parts:
        parts[-1] = p.stem
        if parts[-1] == "index":
            parts = parts[:-1]
    return ".".join(parts)


def resolve_specifier(importer_path: str, spec: str) -> str | None:
    """Resolve a RELATIVE import specifier to a dotted in-repo module fqname.

    Returns None for bare/aliased specifiers ('react', '@scope/pkg', '@/lib/x')
    — those are external to path-based resolution. Extensions and a trailing
    '/index' collapse the same way module_fqname_ts does, so both
    './utils' → 'src/utils.ts' and './utils' → 'src/utils/index.ts' land on the
    same fqname.
    """
    if not spec.startswith("."):
        return None
    parts = list(PurePosixPath(importer_path).parent.parts)
    for seg in spec.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if parts:
                parts.pop()
        else:
            parts.append(seg)
    if not parts:
        return None
    last = PurePosixPath(parts[-1])
    if last.suffix in _GRAMMARS:
        parts[-1] = last.stem
    if parts[-1] == "index":
        parts = parts[:-1]
    return ".".join(parts) if parts else None


def _text(node: Node, src: bytes) -> str:
    return src[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _line_range(node: Node) -> tuple[int, int]:
    # tree-sitter points are 0-based (row, col); we store 1-based inclusive lines.
    return node.start_point[0] + 1, node.end_point[0] + 1


def _string_value(node: Node | None, src: bytes) -> str | None:
    """The unquoted value of a string literal node."""
    if node is None:
        return None
    raw = _text(node, src)
    return raw.strip("\"'`") or None


def _jsdoc(anchor: Node, src: bytes) -> str | None:
    """A `/** … */` block immediately preceding `anchor`, cleaned of comment
    furniture. Plain `//` and `/* */` comments are not doc comments."""
    prev = anchor.prev_named_sibling
    if prev is None or prev.type != "comment":
        return None
    raw = _text(prev, src)
    if not raw.startswith("/**"):
        return None
    body = raw.removeprefix("/**").removesuffix("*/")
    lines = [line.strip().lstrip("*").strip() for line in body.splitlines()]
    doc = "\n".join(line for line in lines if line).strip()
    return doc or None


def _signature(node: Node, src: bytes) -> str:
    """The declaration head — everything before the body/block."""
    body = node.child_by_field_name("body")
    end = body.start_byte if body is not None else node.end_byte
    sig = src[node.start_byte : end].decode("utf-8", errors="replace")
    return " ".join(sig.split()).rstrip(" {")


def _class_bases(node: Node, src: bytes) -> list[str]:
    """`extends` targets from a class declaration's heritage.

    TS grammar: class_heritage → extends_clause(value) [+ implements_clause,
    which we deliberately skip — implementing an interface is not inheritance].
    JS grammar: class_heritage → the extended expression directly.
    """
    bases: list[str] = []
    for child in node.children:
        if child.type != "class_heritage":
            continue
        for sub in child.named_children:
            if sub.type == "extends_clause":
                for value in sub.named_children:
                    if value.type in ("identifier", "member_expression"):
                        bases.append(_text(value, src))
            elif sub.type in ("identifier", "member_expression"):
                bases.append(_text(sub, src))
    return bases


class _Walker:
    """Single-pass AST walker accumulating symbols, imports, and calls."""

    def __init__(self, path: str, src: bytes, language: str) -> None:
        self.path = path
        self.src = src
        self.language = language
        self.module = module_fqname_ts(path)
        self.symbols: list[RawSymbol] = []
        self.imports: list[RawImport] = []
        self.calls: list[RawCall] = []
        self.had_errors = False

    def run(self, root: Node) -> None:
        start, end = _line_range(root)
        self.symbols.append(
            RawSymbol(
                kind=NodeKind.FILE,
                fqname=self.module,
                name=PurePosixPath(self.path).name,
                path=self.path,
                start_line=start,
                end_line=end,
                source=_text(root, self.src),
            )
        )
        self._visit_block(root, parent_fqname=self.module, enclosing=self.module, in_class=False)

    def _visit_block(
        self, node: Node, *, parent_fqname: str, enclosing: str, in_class: bool
    ) -> None:
        for child in node.named_children:
            self._visit(child, parent_fqname=parent_fqname, enclosing=enclosing, in_class=in_class)

    def _visit(
        self,
        node: Node,
        *,
        parent_fqname: str,
        enclosing: str,
        in_class: bool,
        doc_anchor: Node | None = None,
    ) -> None:
        t = node.type
        if t == "ERROR":
            self.had_errors = True
            return
        if t == "import_statement":
            self._handle_import(node)
            return
        if t == "export_statement":
            # Re-export (`export { x } from './y'`) — record the import edge.
            source = node.child_by_field_name("source")
            if source is not None:
                self._handle_reexport(node, source)
            # Exported declaration — visit it, keeping the export statement as
            # the JSDoc anchor (the comment precedes `export`, not the decl).
            decl = node.child_by_field_name("declaration")
            if decl is not None:
                self._visit(
                    decl,
                    parent_fqname=parent_fqname,
                    enclosing=enclosing,
                    in_class=in_class,
                    doc_anchor=node,
                )
            return
        anchor = doc_anchor or node
        if t in _CLASSLIKE:
            self._handle_classlike(node, parent_fqname, anchor)
            return
        if t in _FUNCTIONLIKE:
            self._handle_function(node, parent_fqname, in_class=False, anchor=anchor)
            return
        if t == "method_definition":
            self._handle_function(node, parent_fqname, in_class=in_class, anchor=anchor)
            return
        if t == "public_field_definition":
            self._handle_field(node, parent_fqname, in_class=in_class, anchor=anchor)
            return
        if t in ("lexical_declaration", "variable_declaration"):
            self._handle_variable_declaration(node, parent_fqname, enclosing, anchor)
            return
        if t == "call_expression":
            self._handle_call(node, enclosing)
        elif t == "new_expression":
            self._handle_new(node, enclosing)
        # Recurse into compound statements (if/for/try/blocks/JSX) for nested
        # declarations and calls — declarations above handle their own bodies.
        self._visit_block(node, parent_fqname=parent_fqname, enclosing=enclosing, in_class=in_class)

    # ── declarations ────────────────────────────────────────────────────────

    def _handle_classlike(self, node: Node, parent_fqname: str, anchor: Node) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        name = _text(name_node, self.src)
        fqname = f"{parent_fqname}.{name}"
        start, end = _line_range(node)
        is_class = node.type in ("class_declaration", "abstract_class_declaration")
        self.symbols.append(
            RawSymbol(
                kind=NodeKind.CLASS,
                fqname=fqname,
                name=name,
                path=self.path,
                start_line=start,
                end_line=end,
                signature=_signature(node, self.src),
                docstring=_jsdoc(anchor, self.src),
                parent_fqname=parent_fqname,
                source=_text(node, self.src),
                bases=_class_bases(node, self.src) if is_class else [],
            )
        )
        body = node.child_by_field_name("body")
        if body is not None:
            self._visit_block(body, parent_fqname=fqname, enclosing=fqname, in_class=is_class)

    def _handle_function(
        self, node: Node, parent_fqname: str, *, in_class: bool, anchor: Node
    ) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None or name_node.type == "computed_property_name":
            return
        name = _text(name_node, self.src)
        fqname = f"{parent_fqname}.{name}"
        start, end = _line_range(node)
        self.symbols.append(
            RawSymbol(
                kind=NodeKind.METHOD if in_class else NodeKind.FUNCTION,
                fqname=fqname,
                name=name,
                path=self.path,
                start_line=start,
                end_line=end,
                signature=_signature(node, self.src),
                docstring=_jsdoc(anchor, self.src),
                parent_fqname=parent_fqname,
                source=_text(node, self.src),
            )
        )
        body = node.child_by_field_name("body")
        if body is not None:
            self._visit_block(body, parent_fqname=fqname, enclosing=fqname, in_class=False)

    def _handle_field(
        self, node: Node, parent_fqname: str, *, in_class: bool, anchor: Node
    ) -> None:
        """A class property. Only function-valued properties (arrow methods)
        become symbols; plain data fields stay part of the class chunk."""
        value = node.child_by_field_name("value")
        if value is None or value.type not in _FUNCTION_VALUES:
            return
        name_node = node.child_by_field_name("name")
        if name_node is None or name_node.type == "computed_property_name":
            return
        name = _text(name_node, self.src)
        fqname = f"{parent_fqname}.{name}"
        start, end = _line_range(node)
        self.symbols.append(
            RawSymbol(
                kind=NodeKind.METHOD if in_class else NodeKind.FUNCTION,
                fqname=fqname,
                name=name,
                path=self.path,
                start_line=start,
                end_line=end,
                signature=_signature(value, self.src),
                docstring=_jsdoc(anchor, self.src),
                parent_fqname=parent_fqname,
                source=_text(node, self.src),
            )
        )
        body = value.child_by_field_name("body")
        if body is not None:
            self._visit_block(body, parent_fqname=fqname, enclosing=fqname, in_class=False)

    def _handle_variable_declaration(
        self, node: Node, parent_fqname: str, enclosing: str, anchor: Node
    ) -> None:
        for declarator in node.named_children:
            if declarator.type != "variable_declarator":
                continue
            name_node = declarator.child_by_field_name("name")
            value = declarator.child_by_field_name("value")
            if name_node is None or name_node.type != "identifier":
                # Destructuring (`const [a, b] = f()`) — no symbol, but the
                # initializer still carries calls worth recording.
                if value is not None:
                    self._visit(
                        value, parent_fqname=parent_fqname, enclosing=enclosing, in_class=False
                    )
                continue
            name = _text(name_node, self.src)
            # `const x = require('./y')` — a CommonJS import binding.
            if value is not None and value.type == "call_expression":
                fn = value.child_by_field_name("function")
                if fn is not None and _text(fn, self.src) == "require":
                    args = value.child_by_field_name("arguments")
                    spec_node = args.named_children[0] if args and args.named_children else None
                    if spec_node is not None and spec_node.type == "string":
                        spec = _string_value(spec_node, self.src) or ""
                        self.imports.append(
                            RawImport(
                                path=self.path,
                                module=resolve_specifier(self.path, spec) or spec,
                                imported=None,
                                alias=name,
                                line=node.start_point[0] + 1,
                            )
                        )
                        continue
            # `const f = () => {}` / `const f = function () {}` — a function.
            if value is not None and value.type in _FUNCTION_VALUES:
                fqname = f"{parent_fqname}.{name}"
                start, end = _line_range(declarator)
                self.symbols.append(
                    RawSymbol(
                        kind=NodeKind.FUNCTION,
                        fqname=fqname,
                        name=name,
                        path=self.path,
                        start_line=start,
                        end_line=end,
                        signature=_signature(value, self.src),
                        docstring=_jsdoc(anchor, self.src),
                        parent_fqname=parent_fqname,
                        source=_text(declarator, self.src),
                    )
                )
                body = value.child_by_field_name("body")
                if body is not None:
                    self._visit_block(body, parent_fqname=fqname, enclosing=fqname, in_class=False)
                continue
            # Any other initializer may still contain calls (e.g. `const x = f()`).
            if value is not None:
                self._visit(value, parent_fqname=parent_fqname, enclosing=enclosing, in_class=False)

    # ── imports ─────────────────────────────────────────────────────────────

    def _handle_import(self, node: Node) -> None:
        line = node.start_point[0] + 1
        spec = _string_value(node.child_by_field_name("source"), self.src)
        if spec is None:
            return
        module = resolve_specifier(self.path, spec) or spec
        clause = next((c for c in node.named_children if c.type == "import_clause"), None)
        if clause is None:
            # Side-effect import: `import './polyfills'`.
            self.imports.append(
                RawImport(path=self.path, module=module, imported=None, alias=None, line=line)
            )
            return
        for child in clause.named_children:
            if child.type == "identifier":
                # Default import: the local name binds the module's default.
                self.imports.append(
                    RawImport(
                        path=self.path,
                        module=module,
                        imported="default",
                        alias=_text(child, self.src),
                        line=line,
                    )
                )
            elif child.type == "namespace_import":
                ident = next((c for c in child.named_children if c.type == "identifier"), None)
                self.imports.append(
                    RawImport(
                        path=self.path,
                        module=module,
                        imported="*",
                        alias=_text(ident, self.src) if ident else None,
                        line=line,
                    )
                )
            elif child.type == "named_imports":
                for sub in child.named_children:
                    if sub.type != "import_specifier":
                        continue
                    name_node = sub.child_by_field_name("name")
                    alias_node = sub.child_by_field_name("alias")
                    if name_node is not None:
                        self.imports.append(
                            RawImport(
                                path=self.path,
                                module=module,
                                imported=_text(name_node, self.src),
                                alias=_text(alias_node, self.src) if alias_node else None,
                                line=line,
                            )
                        )

    def _handle_reexport(self, node: Node, source: Node) -> None:
        spec = _string_value(source, self.src)
        if spec is None:
            return
        self.imports.append(
            RawImport(
                path=self.path,
                module=resolve_specifier(self.path, spec) or spec,
                imported=None,
                alias=None,
                line=node.start_point[0] + 1,
            )
        )

    # ── calls ───────────────────────────────────────────────────────────────

    def _handle_call(self, node: Node, enclosing: str) -> None:
        fn = node.child_by_field_name("function")
        if fn is None:
            return
        callee = _text(fn, self.src)
        if callee == "require":
            return  # handled as an import where it binds; bare requires are noise
        self.calls.append(
            RawCall(
                path=self.path,
                caller_fqname=enclosing,
                callee=callee,
                line=node.start_point[0] + 1,
            )
        )

    def _handle_new(self, node: Node, enclosing: str) -> None:
        ctor = node.child_by_field_name("constructor")
        if ctor is None or ctor.type not in ("identifier", "member_expression"):
            return
        self.calls.append(
            RawCall(
                path=self.path,
                caller_fqname=enclosing,
                callee=_text(ctor, self.src),
                line=node.start_point[0] + 1,
            )
        )


def extract_typescript(path: str, source: bytes) -> FileExtract:
    """Parse one JS-family file's bytes into a FileExtract. Never raises on bad
    source; the grammar is picked from the file extension (default: TypeScript)."""
    grammar, language = _GRAMMARS.get(PurePosixPath(path).suffix, _GRAMMARS[".ts"])
    tree = Parser(grammar).parse(source)
    walker = _Walker(path, source, language)
    walker.run(tree.root_node)
    return FileExtract(
        path=path,
        language=language,
        symbols=walker.symbols,
        imports=walker.imports,
        calls=walker.calls,
        had_errors=walker.had_errors or tree.root_node.has_error,
    )
