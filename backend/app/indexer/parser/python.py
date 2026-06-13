"""Python source extractor (tree-sitter).

Walks a Python file's AST and emits symbols (modules, classes, functions,
methods), imports, and call sites with exact 1-based line ranges. No code is
executed — tree-sitter reads bytes only.

Design choices:
- fqname is derived from the module path (file path → dotted module) plus the
  lexical nesting, so "app/auth/jwt.py" with a class `Token` and method `decode`
  yields `app.auth.jwt.Token.decode`. This is what citations and edge resolution
  key on.
- A function nested directly under a class is a METHOD; otherwise a FUNCTION.
  Nested functions keep their lexical parent in the fqname.
- Calls record the textual callee ("helper", "self.decode", "os.path.join");
  resolution + confidence is the graph builder's job, not the parser's.
- Docstrings and signatures are captured for the summary/embedding layer.
"""

from __future__ import annotations

from pathlib import PurePosixPath

import tree_sitter_python as tspython
from tree_sitter import Language, Node, Parser

from app.db.enums import NodeKind
from app.indexer.parser.types import (
    FileExtract,
    RawCall,
    RawImport,
    RawSymbol,
)

_LANGUAGE = Language(tspython.language())
_parser = Parser(_LANGUAGE)


def module_fqname(path: str) -> str:
    """Map a repo-relative file path to a dotted module name.

    'app/auth/jwt.py'        -> 'app.auth.jwt'
    'app/__init__.py'        -> 'app'
    'scripts/run.py'         -> 'scripts.run'
    """
    p = PurePosixPath(path)
    parts = list(p.parts)
    if parts and parts[-1] == "__init__.py":
        parts = parts[:-1]
    elif parts:
        parts[-1] = p.stem
    return ".".join(parts)


def _text(node: Node, src: bytes) -> str:
    return src[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _line_range(node: Node) -> tuple[int, int]:
    # tree-sitter points are 0-based (row, col); we store 1-based inclusive lines.
    return node.start_point[0] + 1, node.end_point[0] + 1


def _docstring(body: Node | None, src: bytes) -> str | None:
    """Return the docstring if the first body statement is a string expression."""
    if body is None:
        return None
    for child in body.named_children:
        # First named statement only.
        if child.type == "expression_statement":
            inner = child.named_children[0] if child.named_children else None
            if inner is not None and inner.type == "string":
                raw = _text(inner, src)
                return raw.strip().strip("\"'").strip()
        return None
    return None


def _signature(node: Node, src: bytes) -> str:
    """First line of a def/class — the signature without the body."""
    name = node.child_by_field_name("name")
    params = node.child_by_field_name("parameters")
    end = params.end_byte if params is not None else (name.end_byte if name else node.start_byte)
    sig = src[node.start_byte : end].decode("utf-8", errors="replace")
    return " ".join(sig.split())


def _base_names(node: Node, src: bytes) -> list[str]:
    """Base-class identifiers from a class definition's superclasses list."""
    supers = node.child_by_field_name("superclasses")
    if supers is None:
        return []
    bases: list[str] = []
    for child in supers.named_children:
        # Keyword args (metaclass=...) are not bases; identifiers / attributes are.
        if child.type in ("identifier", "attribute"):
            bases.append(_text(child, src))
    return bases


class _Walker:
    """Single-pass AST walker accumulating symbols, imports, and calls."""

    def __init__(self, path: str, src: bytes) -> None:
        self.path = path
        self.src = src
        self.module = module_fqname(path)
        self.symbols: list[RawSymbol] = []
        self.imports: list[RawImport] = []
        self.calls: list[RawCall] = []
        self.had_errors = False

    def run(self, root: Node) -> None:
        # Emit the module symbol itself.
        start, end = _line_range(root)
        self.symbols.append(
            RawSymbol(
                kind=NodeKind.FILE,
                fqname=self.module,
                name=PurePosixPath(self.path).name,
                path=self.path,
                start_line=start,
                end_line=end,
                docstring=_docstring(root, self.src),
                source=_text(root, self.src),
            )
        )
        # `enclosing` is the fqname of the current lexical scope for calls/methods.
        self._visit_block(root, parent_fqname=self.module, enclosing=self.module, in_class=False)

    def _visit_block(
        self, node: Node, *, parent_fqname: str, enclosing: str, in_class: bool
    ) -> None:
        for child in node.named_children:
            self._visit(child, parent_fqname=parent_fqname, enclosing=enclosing, in_class=in_class)

    def _visit(self, node: Node, *, parent_fqname: str, enclosing: str, in_class: bool) -> None:
        t = node.type
        if t == "ERROR":
            self.had_errors = True
            return
        if t == "import_statement":
            self._handle_import(node)
            return
        if t == "import_from_statement":
            self._handle_import_from(node)
            return
        if t == "class_definition":
            self._handle_class(node, parent_fqname)
            return
        if t == "function_definition":
            self._handle_function(node, parent_fqname, in_class)
            return
        if t == "call":
            self._handle_call(node, enclosing)
        # Recurse into compound statements (if/for/with/try) to find nested
        # defs, imports, and calls — but defs/classes handle their own bodies.
        if t not in ("class_definition", "function_definition"):
            self._visit_block(
                node, parent_fqname=parent_fqname, enclosing=enclosing, in_class=in_class
            )

    def _handle_class(self, node: Node, parent_fqname: str) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        name = _text(name_node, self.src)
        fqname = f"{parent_fqname}.{name}"
        start, end = _line_range(node)
        body = node.child_by_field_name("body")
        self.symbols.append(
            RawSymbol(
                kind=NodeKind.CLASS,
                fqname=fqname,
                name=name,
                path=self.path,
                start_line=start,
                end_line=end,
                signature=_signature(node, self.src),
                docstring=_docstring(body, self.src),
                parent_fqname=parent_fqname,
                source=_text(node, self.src),
                bases=_base_names(node, self.src),
            )
        )
        if body is not None:
            self._visit_block(body, parent_fqname=fqname, enclosing=fqname, in_class=True)

    def _handle_function(self, node: Node, parent_fqname: str, in_class: bool) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        name = _text(name_node, self.src)
        fqname = f"{parent_fqname}.{name}"
        start, end = _line_range(node)
        body = node.child_by_field_name("body")
        self.symbols.append(
            RawSymbol(
                kind=NodeKind.METHOD if in_class else NodeKind.FUNCTION,
                fqname=fqname,
                name=name,
                path=self.path,
                start_line=start,
                end_line=end,
                signature=_signature(node, self.src),
                docstring=_docstring(body, self.src),
                parent_fqname=parent_fqname,
                source=_text(node, self.src),
            )
        )
        # A nested function's lexical parent is this function; it is not a method.
        if body is not None:
            self._visit_block(body, parent_fqname=fqname, enclosing=fqname, in_class=False)

    def _handle_import(self, node: Node) -> None:
        line = node.start_point[0] + 1
        for child in node.named_children:
            if child.type == "dotted_name":
                self.imports.append(
                    RawImport(
                        path=self.path,
                        module=_text(child, self.src),
                        imported=None,
                        alias=None,
                        line=line,
                    )
                )
            elif child.type == "aliased_import":
                name_node = child.child_by_field_name("name")
                alias_node = child.child_by_field_name("alias")
                if name_node is not None:
                    self.imports.append(
                        RawImport(
                            path=self.path,
                            module=_text(name_node, self.src),
                            imported=None,
                            alias=_text(alias_node, self.src) if alias_node else None,
                            line=line,
                        )
                    )

    def _handle_import_from(self, node: Node) -> None:
        line = node.start_point[0] + 1
        module_node = node.child_by_field_name("module_name")
        # Leading dots → relative import. tree-sitter represents the module as
        # `relative_import` wrapping an optional dotted_name.
        relative = False
        level = 0
        module = ""
        if module_node is not None:
            if module_node.type == "relative_import":
                relative = True
                import_prefix = module_node.child(0)
                level = len(_text(import_prefix, self.src)) if import_prefix is not None else 1
                dotted = module_node.child_by_field_name("name")
                # Some grammars expose the dotted name as a child, not a field.
                if dotted is None:
                    for c in module_node.named_children:
                        if c.type == "dotted_name":
                            dotted = c
                            break
                module = _text(dotted, self.src) if dotted is not None else ""
            else:
                module = _text(module_node, self.src)

        # Imported names: each `name:` field child (dotted_name / aliased_import).
        for child in node.named_children:
            if child is module_node:
                continue
            if child.type == "dotted_name":
                self.imports.append(
                    RawImport(
                        path=self.path,
                        module=module,
                        imported=_text(child, self.src),
                        alias=None,
                        line=line,
                        relative=relative,
                        relative_level=level,
                    )
                )
            elif child.type == "aliased_import":
                name_node = child.child_by_field_name("name")
                alias_node = child.child_by_field_name("alias")
                if name_node is not None:
                    self.imports.append(
                        RawImport(
                            path=self.path,
                            module=module,
                            imported=_text(name_node, self.src),
                            alias=_text(alias_node, self.src) if alias_node else None,
                            line=line,
                            relative=relative,
                            relative_level=level,
                        )
                    )
            elif child.type == "wildcard_import":
                self.imports.append(
                    RawImport(
                        path=self.path,
                        module=module,
                        imported="*",
                        alias=None,
                        line=line,
                        relative=relative,
                        relative_level=level,
                    )
                )

    def _handle_call(self, node: Node, enclosing: str) -> None:
        fn = node.child_by_field_name("function")
        if fn is None:
            return
        callee = _text(fn, self.src)
        self.calls.append(
            RawCall(
                path=self.path,
                caller_fqname=enclosing,
                callee=callee,
                line=node.start_point[0] + 1,
            )
        )


def extract_python(path: str, source: bytes) -> FileExtract:
    """Parse one Python file's bytes into a FileExtract. Never raises on bad source."""
    tree = _parser.parse(source)
    walker = _Walker(path, source)
    walker.run(tree.root_node)
    return FileExtract(
        path=path,
        language="python",
        symbols=walker.symbols,
        imports=walker.imports,
        calls=walker.calls,
        had_errors=walker.had_errors or tree.root_node.has_error,
    )
