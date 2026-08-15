"""CLI entry: `uv run python -m evals [--repo URL] [--golden PATH] [--index]`.

Loads the golden set, finds (or, with --index, indexes) the repo in the
configured database, runs every case through the real query router, and writes
the markdown scoreboard to evals/results/.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import sys
from pathlib import Path

from sqlalchemy import select

from app.config import get_settings
from app.db.enums import RepoStatus
from app.db.models import Repo
from app.db.session import get_sessionmaker
from app.indexer.pipeline import index_repo
from evals.runner import render_markdown, run_eval
from evals.schema import GoldenSet

_DEFAULT_GOLDEN = Path(__file__).parent / "golden" / "pybktree.json"
_RESULTS_DIR = Path(__file__).parent / "results"


async def _main() -> int:
    # Windows consoles default to cp1252, which can't print the scoreboard's
    # ✓/✗ marks — force UTF-8 (and never crash a finished eval over a glyph).
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(prog="evals", description="Cartograph eval harness")
    parser.add_argument("--golden", type=Path, default=_DEFAULT_GOLDEN, help="golden-set JSON")
    parser.add_argument("--repo", default=None, help="repo URL (default: the golden set's)")
    parser.add_argument(
        "--index", action="store_true", help="index the repo first if it isn't indexed yet"
    )
    args = parser.parse_args()

    golden = GoldenSet.model_validate_json(args.golden.read_text(encoding="utf-8"))
    repo_url = args.repo or golden.repo_url

    if not get_settings().llm_available:
        print("No LLM key configured (.env) — the eval asks real questions.", file=sys.stderr)
        return 2

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        repo = await session.scalar(
            select(Repo).where(Repo.url == repo_url).order_by(Repo.created_at.desc()).limit(1)
        )
        if repo is None or repo.status != RepoStatus.INDEXED:
            if not args.index:
                print(
                    f"{repo_url} is not indexed. Re-run with --index to index it first "
                    "(spends LLM quota).",
                    file=sys.stderr,
                )
                return 2
            print(f"Indexing {repo_url} …")
            result = await index_repo(session, repo_url)
            await session.commit()
            repo = await session.get(Repo, result.repo_id)
            assert repo is not None

        print(f"Running {len(golden.cases)} golden cases against {repo_url} …")
        report = await run_eval(session, repo.id, golden)

    markdown = render_markdown(report)
    _RESULTS_DIR.mkdir(exist_ok=True)
    slug = repo_url.rstrip("/").rsplit("/", 1)[-1]
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%d-%H%M%S")
    out = _RESULTS_DIR / f"{slug}-{stamp}.md"
    out.write_text(markdown, encoding="utf-8")

    # The aggregate line + table for the terminal; full answers live in the file.
    print("\n".join(markdown.splitlines()[:20]))
    print(f"\nFull report: {out}")
    errors = [r for r in report.results if r.error]
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
