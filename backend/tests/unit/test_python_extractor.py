"""Tests for the Python tree-sitter extractor.

These assert exact extraction output against known source — the contract the
graph builder depends on. Line numbers are 1-based inclusive.
"""

from __future__ import annotations

from app.db.enums import NodeKind
from app.indexer.parser.python import extract_python, module_fqname

SOURCE = b'''"""Module docstring."""
import os
import os.path as osp
from a.b import c, d as e
from . import sibling
from ..pkg import thing


class Token(Base, mixins.Serializable):
    """A token."""

    def decode(self, raw):
        """Decode it."""
        return helper(raw)


def helper(x):
    return os.path.join(x)
'''


def _by_fqname(extract, fqname):
    return next(s for s in extract.symbols if s.fqname == fqname)


def test_module_fqname() -> None:
    assert module_fqname("app/auth/jwt.py") == "app.auth.jwt"
    assert module_fqname("app/__init__.py") == "app"
    assert module_fqname("run.py") == "run"


def test_symbols_extracted() -> None:
    ex = extract_python("app/auth/jwt.py", SOURCE)
    fqnames = {s.fqname: s.kind for s in ex.symbols}

    assert fqnames["app.auth.jwt"] == NodeKind.FILE
    assert fqnames["app.auth.jwt.Token"] == NodeKind.CLASS
    assert fqnames["app.auth.jwt.Token.decode"] == NodeKind.METHOD
    assert fqnames["app.auth.jwt.helper"] == NodeKind.FUNCTION


def test_class_bases_and_docstring() -> None:
    ex = extract_python("app/auth/jwt.py", SOURCE)
    token = _by_fqname(ex, "app.auth.jwt.Token")
    # keyword args (none here) excluded; identifier + attribute bases kept.
    assert token.bases == ["Base", "mixins.Serializable"]
    assert token.docstring == "A token."
    assert token.parent_fqname == "app.auth.jwt"


def test_method_line_range_and_signature() -> None:
    ex = extract_python("app/auth/jwt.py", SOURCE)
    decode = _by_fqname(ex, "app.auth.jwt.Token.decode")
    assert decode.start_line == 12
    assert decode.signature == "def decode(self, raw)"
    assert decode.docstring == "Decode it."


def test_imports() -> None:
    ex = extract_python("app/auth/jwt.py", SOURCE)
    # plain import
    assert any(i.module == "os" and i.imported is None for i in ex.imports)
    # aliased import
    assert any(i.module == "os.path" and i.alias == "osp" for i in ex.imports)
    # from-import with two names, one aliased
    assert any(i.module == "a.b" and i.imported == "c" for i in ex.imports)
    assert any(i.module == "a.b" and i.imported == "d" and i.alias == "e" for i in ex.imports)
    # relative imports
    rel1 = next(i for i in ex.imports if i.imported == "sibling")
    assert rel1.relative and rel1.relative_level == 1
    rel2 = next(i for i in ex.imports if i.imported == "thing")
    assert rel2.relative and rel2.relative_level == 2 and rel2.module == "pkg"


def test_calls() -> None:
    ex = extract_python("app/auth/jwt.py", SOURCE)
    callees = {(c.caller_fqname, c.callee) for c in ex.calls}
    assert ("app.auth.jwt.Token.decode", "helper") in callees
    assert ("app.auth.jwt.helper", "os.path.join") in callees


def test_bad_source_does_not_raise() -> None:
    ex = extract_python("broken.py", b"def f(:\n  x = ")
    assert ex.had_errors
    # the module symbol is still emitted
    assert any(s.kind == NodeKind.FILE for s in ex.symbols)
