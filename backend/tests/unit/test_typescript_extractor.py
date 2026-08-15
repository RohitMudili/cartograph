"""Tests for the TypeScript/JavaScript tree-sitter extractor.

These assert exact extraction output against known source — the contract the
graph builder depends on. Line numbers are 1-based inclusive.
"""

from __future__ import annotations

from app.db.enums import NodeKind
from app.indexer.parser.typescript import (
    extract_typescript,
    module_fqname_ts,
    resolve_specifier,
)

SOURCE = b"""/** Module-level comment (not attached to a symbol). */
import { createClient } from "./supabase/client";
import React from "react";
import * as fs from "node:fs";
import "./polyfills";
export { ApiError as PublicError } from "../errors";

/** A typed API error. */
export class ApiError extends Error {
  detail = "";
  onRetry = () => {
    this.report();
  };
  report() {
    return fetch(this.detail);
  }
}

export interface Repo {
  id: string;
}

enum Kind {
  A,
  B,
}

/** Fetch one repo. */
export async function getRepo(id: string): Promise<Repo> {
  const client = createClient();
  return await request(id);
}

const shortUrl = (url: string) => url.replace("x", "y");

function outer() {
  function inner() {
    return new ApiError();
  }
  return inner;
}
"""


def _by_fqname(extract, fqname):
    return next(s for s in extract.symbols if s.fqname == fqname)


def test_module_fqname_ts() -> None:
    assert module_fqname_ts("src/lib/api.ts") == "src.lib.api"
    assert module_fqname_ts("src/utils/index.ts") == "src.utils"
    assert module_fqname_ts("app.tsx") == "app"
    assert module_fqname_ts("scripts/run.cjs") == "scripts.run"


def test_resolve_specifier() -> None:
    # sibling / parent / explicit index+extension all collapse to module fqnames
    assert resolve_specifier("src/a/b.ts", "./c") == "src.a.c"
    assert resolve_specifier("src/a/b.ts", "../c") == "src.c"
    assert resolve_specifier("src/a/b.ts", "./d/index.ts") == "src.a.d"
    assert resolve_specifier("src/a/b.ts", "./c.js") == "src.a.c"
    # bare packages and aliases are not path-resolvable
    assert resolve_specifier("src/a/b.ts", "react") is None
    assert resolve_specifier("src/a/b.ts", "@/lib/x") is None


def test_symbols_extracted() -> None:
    ex = extract_typescript("src/lib/api.ts", SOURCE)
    fqnames = {s.fqname: s.kind for s in ex.symbols}

    assert ex.language == "typescript"
    assert not ex.had_errors
    assert fqnames["src.lib.api"] == NodeKind.FILE
    assert fqnames["src.lib.api.ApiError"] == NodeKind.CLASS
    assert fqnames["src.lib.api.ApiError.report"] == NodeKind.METHOD
    # a class-property arrow function is a method
    assert fqnames["src.lib.api.ApiError.onRetry"] == NodeKind.METHOD
    # interfaces and enums are CLASS nodes (named type containers)
    assert fqnames["src.lib.api.Repo"] == NodeKind.CLASS
    assert fqnames["src.lib.api.Kind"] == NodeKind.CLASS
    assert fqnames["src.lib.api.getRepo"] == NodeKind.FUNCTION
    # const-arrow binding is a function; nested function keeps lexical nesting
    assert fqnames["src.lib.api.shortUrl"] == NodeKind.FUNCTION
    assert fqnames["src.lib.api.outer.inner"] == NodeKind.FUNCTION
    # a plain data field is NOT a symbol
    assert "src.lib.api.ApiError.detail" not in fqnames


def test_class_bases_jsdoc_and_signature() -> None:
    ex = extract_typescript("src/lib/api.ts", SOURCE)
    err = _by_fqname(ex, "src.lib.api.ApiError")
    # the JSDoc precedes `export`; it still attaches to the declaration
    assert err.docstring == "A typed API error."
    assert err.bases == ["Error"]
    assert err.signature == "class ApiError extends Error"
    assert err.parent_fqname == "src.lib.api"

    get_repo = _by_fqname(ex, "src.lib.api.getRepo")
    assert get_repo.docstring == "Fetch one repo."
    assert get_repo.signature == "async function getRepo(id: string): Promise<Repo>"
    assert get_repo.start_line == 29

    # interfaces keep their keyword in the signature and carry no bases
    repo = _by_fqname(ex, "src.lib.api.Repo")
    assert repo.signature == "interface Repo"
    assert repo.bases == []


def test_imports() -> None:
    ex = extract_typescript("src/lib/api.ts", SOURCE)
    # relative named import — specifier resolved to a dotted module fqname
    assert any(
        i.module == "src.lib.supabase.client" and i.imported == "createClient" for i in ex.imports
    )
    # default import from a bare package — module kept verbatim (external)
    assert any(
        i.module == "react" and i.imported == "default" and i.alias == "React" for i in ex.imports
    )
    # namespace import
    assert any(i.module == "node:fs" and i.imported == "*" and i.alias == "fs" for i in ex.imports)
    # side-effect import
    assert any(i.module == "src.lib.polyfills" and i.imported is None for i in ex.imports)
    # re-export records the import edge (parent-relative resolution)
    assert any(i.module == "src.errors" for i in ex.imports)


def test_calls() -> None:
    ex = extract_typescript("src/lib/api.ts", SOURCE)
    calls = {(c.caller_fqname, c.callee) for c in ex.calls}
    assert ("src.lib.api.getRepo", "createClient") in calls
    assert ("src.lib.api.getRepo", "request") in calls
    # method attribution: the arrow method's body calls this.report
    assert ("src.lib.api.ApiError.onRetry", "this.report") in calls
    # `new X()` records a call to the constructor's class
    assert ("src.lib.api.outer.inner", "ApiError") in calls


def test_tsx_and_destructured_calls() -> None:
    src = b"""import { useState } from "react";
export default function App() {
  const [n, setN] = useState(0);
  return <button onClick={() => setN(n + 1)}>{n}</button>;
}
"""
    ex = extract_typescript("src/components/App.tsx", src)
    assert ex.language == "tsx"
    assert not ex.had_errors
    assert any(s.fqname == "src.components.App.App" for s in ex.symbols)
    calls = {(c.caller_fqname, c.callee) for c in ex.calls}
    # a destructured initializer still records its call
    assert ("src.components.App.App", "useState") in calls
    assert ("src.components.App.App", "setN") in calls


def test_commonjs_require() -> None:
    src = b"""const path = require("path");
const helper = require("./lib/helper");
function main() {
  return helper.run(path.join());
}
"""
    ex = extract_typescript("scripts/run.cjs", src)
    assert ex.language == "javascript"
    assert any(i.module == "path" and i.alias == "path" for i in ex.imports)
    assert any(i.module == "scripts.lib.helper" and i.alias == "helper" for i in ex.imports)
    calls = {(c.caller_fqname, c.callee) for c in ex.calls}
    assert ("scripts.run.main", "helper.run") in calls
    # the require() binding itself is an import, not a call
    assert not any(c.callee == "require" for c in ex.calls)


def test_bad_source_never_raises() -> None:
    ex = extract_typescript("src/broken.ts", b"export class {{{ nope ===")
    assert ex.had_errors
    # the file symbol still exists so the file remains retrievable
    assert any(s.kind == NodeKind.FILE for s in ex.symbols)
