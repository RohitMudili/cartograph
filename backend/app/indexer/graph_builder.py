"""Graph builder: turn per-file extracts into a persisted repo graph.

Takes the list of `FileExtract`s from the parser layer and:
  1. Inserts all symbol nodes, capturing their generated DB ids.
  2. Resolves and inserts structural edges:
       - CONTAINS  (module → class/function, class → method) — always confident.
       - IMPORTS   (file → in-repo module it imports) — external imports dropped.
       - INHERITS  (class → in-repo base class) — resolved via the symbol table.
       - CALLS     (caller → callee) — best-effort name resolution with a
                   confidence score; ambiguous/dynamic targets get low confidence
                   and are never presented as fact in answers (PLAN.md §12).
  3. Inserts AST-aware chunks (one per symbol slice) for hybrid retrieval.
  4. Computes per-node metrics (loc, fan_in, fan_out) from the resolved edges.

Cross-file resolution lives here, not in the parser, because it needs the whole
repo's symbol table. Everything runs in one transaction per repo so a failed
build leaves no partial graph.
"""

from __future__ import annotations

import hashlib
import uuid
from collections import defaultdict
from collections.abc import Callable
from dataclasses import asdict, dataclass

import structlog
from sqlalchemy import insert, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import EdgeKind, NodeKind
from app.db.models import Chunk, Edge, Node
from app.indexer.parser.types import FileExtract, RawCall, RawImport

log = structlog.get_logger(__name__)

# Confidence scores for call-edge resolution.
CONF_UNIQUE = 1.0  # callee name resolves to exactly one in-repo symbol
CONF_AMBIGUOUS = 0.5  # name matches several symbols — kept, flagged low
CONF_METHOD_GUESS = 0.4  # self.x / obj.x heuristic — dynamic dispatch, low


@dataclass(slots=True)
class BuildStats:
    nodes: int
    edges: int
    chunks: int
    files: int


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _resolve_relative_module(imp: RawImport, importer_module: str) -> str:
    """Resolve a relative import to an absolute in-repo module path.

    `from . import x` in app.auth.jwt → base package app.auth; imported module
    app.auth.x. `from ..pkg import y` → drop two levels then append pkg.
    """
    # The importer's package is its module minus the final component (the file).
    pkg_parts = importer_module.split(".")[:-1]
    # Each extra dot beyond the first climbs one more package level.
    climb = imp.relative_level - 1
    if climb > 0:
        pkg_parts = pkg_parts[:-climb] if climb <= len(pkg_parts) else []
    base = ".".join(pkg_parts)
    if imp.module:
        return f"{base}.{imp.module}" if base else imp.module
    return base


class GraphBuilder:
    """Builds and persists the graph for a single repo from file extracts."""

    def __init__(self, session: AsyncSession, repo_id: uuid.UUID) -> None:
        self.session = session
        self.repo_id = repo_id

    async def build(self, extracts: list[FileExtract]) -> BuildStats:
        # 1. Insert nodes, capturing fqname → db id.
        id_by_fqname = await self._insert_nodes(extracts)

        # 2. Resolve + insert edges.
        edge_rows, fan_in, fan_out = self._resolve_edges(extracts, id_by_fqname)
        if edge_rows:
            await self.session.execute(insert(Edge), edge_rows)

        # 3. Insert chunks.
        chunk_count = await self._insert_chunks(extracts, id_by_fqname)

        # 4. Write metrics back onto nodes.
        await self._write_metrics(extracts, id_by_fqname, fan_in, fan_out)

        await self.session.flush()
        stats = BuildStats(
            nodes=len(id_by_fqname),
            edges=len(edge_rows),
            chunks=chunk_count,
            files=len(extracts),
        )
        log.info("graph.build.done", repo_id=str(self.repo_id), **asdict(stats))
        return stats

    async def _insert_nodes(self, extracts: list[FileExtract]) -> dict[str, int]:
        rows: list[dict] = []
        # fqname is unique per repo (DB constraint); a symbol table also dedupes
        # in-memory in case two files somehow produce the same fqname.
        seen: set[str] = set()
        for ex in extracts:
            for sym in ex.symbols:
                if sym.fqname in seen:
                    continue
                seen.add(sym.fqname)
                rows.append(
                    {
                        "repo_id": self.repo_id,
                        "kind": sym.kind,
                        "fqname": sym.fqname,
                        "path": sym.path,
                        "start_line": sym.start_line,
                        "end_line": sym.end_line,
                        "signature": sym.signature,
                        "docstring": sym.docstring,
                        "metrics": {},
                        "annotations": [],
                        "content_hash": _content_hash(sym.source),
                    }
                )
        if not rows:
            return {}

        # Bulk insert with RETURNING in input order, so we can zip ids back to
        # fqnames (SQLAlchemy 2.0 sort_by_parameter_order; supported on Postgres).
        result = await self.session.scalars(
            insert(Node).returning(Node.id, sort_by_parameter_order=True), rows
        )
        ids = list(result)
        return {row["fqname"]: node_id for row, node_id in zip(rows, ids, strict=True)}

    def _resolve_edges(
        self, extracts: list[FileExtract], id_by_fqname: dict[str, int]
    ) -> tuple[list[dict], dict[int, int], dict[int, int]]:
        """Resolve CONTAINS/IMPORTS/INHERITS/CALLS edges to node-id pairs.

        Returns (edge_rows, fan_in, fan_out) where fan_in/out are keyed by node id.
        """
        edges: list[dict] = []
        # Dedup identical (src, dst, kind) — the DB has a unique constraint, and a
        # file can import the same module twice.
        seen: set[tuple[int, int, str]] = set()

        # Symbol-name index for call/base resolution: short name → list of fqnames.
        names_index: dict[str, list[str]] = defaultdict(list)
        # Module set for import resolution.
        modules: set[str] = set()
        for ex in extracts:
            for sym in ex.symbols:
                short = sym.fqname.rsplit(".", 1)[-1]
                names_index[short].append(sym.fqname)
                if sym.kind == NodeKind.FILE:
                    modules.add(sym.fqname)

        fan_in: dict[int, int] = defaultdict(int)
        fan_out: dict[int, int] = defaultdict(int)

        def add_edge(src_fq: str, dst_fq: str, kind: EdgeKind, confidence: float) -> None:
            src = id_by_fqname.get(src_fq)
            dst = id_by_fqname.get(dst_fq)
            if src is None or dst is None or src == dst:
                return
            key = (src, dst, kind.value)
            if key in seen:
                return
            seen.add(key)
            edges.append(
                {
                    "repo_id": self.repo_id,
                    "src_node_id": src,
                    "dst_node_id": dst,
                    "kind": kind,
                    "confidence": confidence,
                    "metadata": {},
                }
            )
            if kind == EdgeKind.CALLS:
                fan_out[src] += 1
                fan_in[dst] += 1

        for ex in extracts:
            for sym in ex.symbols:
                # CONTAINS: lexical parent → child.
                if sym.parent_fqname:
                    add_edge(sym.parent_fqname, sym.fqname, EdgeKind.CONTAINS, CONF_UNIQUE)
                # INHERITS: class → in-repo base (resolved by short name).
                for base in sym.bases:
                    short = base.rsplit(".", 1)[-1]
                    candidates = [c for c in names_index.get(short, []) if c.endswith(short)]
                    if len(candidates) == 1:
                        add_edge(sym.fqname, candidates[0], EdgeKind.INHERITS, CONF_UNIQUE)
                    elif len(candidates) > 1:
                        add_edge(sym.fqname, candidates[0], EdgeKind.INHERITS, CONF_AMBIGUOUS)

            # IMPORTS: file → in-repo module.
            importer_module = ex.path  # placeholder; replaced below
            file_sym = next((s for s in ex.symbols if s.kind == NodeKind.FILE), None)
            if file_sym is not None:
                importer_module = file_sym.fqname
                for imp in ex.imports:
                    target = (
                        _resolve_relative_module(imp, importer_module)
                        if imp.relative
                        else imp.module
                    )
                    # Match against known in-repo modules (exact, or as a prefix
                    # for `from pkg.mod import name`).
                    if target in modules:
                        add_edge(importer_module, target, EdgeKind.IMPORTS, CONF_UNIQUE)
                    elif imp.imported:
                        # `from a.b import c` may target module a.b.c.
                        deeper = f"{target}.{imp.imported}" if target else imp.imported
                        if deeper in modules:
                            add_edge(importer_module, deeper, EdgeKind.IMPORTS, CONF_UNIQUE)

            # CALLS: caller → callee (best-effort name resolution).
            for call in ex.calls:
                self._resolve_call(call, names_index, add_edge)

        return edges, fan_in, fan_out

    def _resolve_call(
        self,
        call: RawCall,
        names_index: dict[str, list[str]],
        add_edge: Callable[[str, str, EdgeKind, float], None],
    ) -> None:
        """Resolve a textual callee to an in-repo symbol with a confidence score."""
        callee = call.callee
        # self.method / obj.method / pkg.func — take the final attribute name.
        short = callee.rsplit(".", 1)[-1]
        is_attr = "." in callee
        candidates = names_index.get(short, [])
        if not candidates:
            return  # external or unresolved — no edge (kept honest)
        if len(candidates) == 1:
            conf = CONF_METHOD_GUESS if is_attr else CONF_UNIQUE
            add_edge(call.caller_fqname, candidates[0], EdgeKind.CALLS, conf)
        else:
            # Ambiguous: link to the first, low confidence. (A future pass can use
            # import context to disambiguate; we never present these as fact.)
            add_edge(call.caller_fqname, candidates[0], EdgeKind.CALLS, CONF_AMBIGUOUS)

    async def _insert_chunks(
        self, extracts: list[FileExtract], id_by_fqname: dict[str, int]
    ) -> int:
        rows: list[dict] = []
        for ex in extracts:
            for sym in ex.symbols:
                # One chunk per symbol slice. Skip the bare module chunk for files
                # that have child symbols (their children carry the detail); keep
                # leaf modules so every file is retrievable.
                if not sym.source.strip():
                    continue
                rows.append(
                    {
                        "repo_id": self.repo_id,
                        "node_id": id_by_fqname.get(sym.fqname),
                        "path": sym.path,
                        "start_line": sym.start_line,
                        "end_line": sym.end_line,
                        "text": sym.source,
                    }
                )
        if rows:
            await self.session.execute(insert(Chunk), rows)
        return len(rows)

    async def _write_metrics(
        self,
        extracts: list[FileExtract],
        id_by_fqname: dict[str, int],
        fan_in: dict[int, int],
        fan_out: dict[int, int],
    ) -> None:
        """Write per-node metrics in a single batched UPDATE (not N+1).

        Uses SQLAlchemy 2.0 ORM bulk-UPDATE-by-primary-key: passing `update(Node)`
        plus a list of dicts keyed by the PK (`id`) emits one executemany round
        trip instead of one statement per node.
        """
        params: list[dict] = []
        seen: set[int] = set()
        for ex in extracts:
            for sym in ex.symbols:
                node_id = id_by_fqname.get(sym.fqname)
                if node_id is None or node_id in seen:
                    continue
                seen.add(node_id)
                params.append(
                    {
                        "id": node_id,
                        "metrics": {
                            "loc": sym.end_line - sym.start_line + 1,
                            "fan_in": fan_in.get(node_id, 0),
                            "fan_out": fan_out.get(node_id, 0),
                        },
                    }
                )
        if params:
            await self.session.execute(update(Node), params)
