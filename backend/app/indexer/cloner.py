"""Sandboxed git cloner for untrusted repositories (PLAN.md §9).

Cloning arbitrary user-supplied repos is the main attack surface, so this module
is deliberately defensive:

- Host allowlist (config-driven) — only clone from approved git hosts.
- Shallow, single-branch clone (`--depth 1`) — no history, no submodule recursion.
- Hooks disabled (`core.hooksPath=/dev/null`) and `protocol.file.allow=never` —
  a malicious repo cannot run code on clone, and cannot pull in local-file
  submodules.
- Size guardrails enforced *after* clone (file count + byte size); the run aborts
  and the workspace is cleaned if exceeded.
- We never execute repo code. The tree-sitter parser reads bytes only.

The cloner returns a `CloneResult` with the workspace path and resolved head
commit. Callers are responsible for cleanup via `cleanup_workspace` (the indexing
pipeline does this in a finally block).
"""

from __future__ import annotations

import asyncio
import os
import shutil
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import structlog

from app.config import Settings, get_settings

log = structlog.get_logger(__name__)

# Root under which all clones live. Gitignored; mounted on a quota'd volume in
# production. Each clone gets an isolated subdirectory.
WORKSPACE_ROOT = Path("workspaces")

# Hard wall-clock ceiling on the clone subprocess.
CLONE_TIMEOUT_SECONDS = 300


class CloneError(Exception):
    """Raised when a repo cannot be safely or successfully cloned."""


class PrivateRepoError(CloneError):
    """The repo is private/not found anonymously — authentication is required.

    Distinct from a generic CloneError so the API can prompt the user to connect
    GitHub (see PLAN.md §9A) instead of returning an opaque failure. Until the
    OAuth flow lands, this is the honest signal for any auth-requiring repo.
    """


@dataclass(frozen=True, slots=True)
class CloneResult:
    workspace: Path
    head_commit: str
    default_branch: str
    file_count: int
    size_bytes: int


def _validate_url(url: str, settings: Settings) -> None:
    """Reject anything not on the host allowlist or not an https git URL."""
    parsed = urlparse(url)
    if parsed.scheme not in ("https", "http"):
        raise CloneError(f"Only http(s) git URLs are allowed, got scheme '{parsed.scheme}'")
    host = (parsed.hostname or "").lower()
    if host not in settings.allowed_git_hosts_set:
        raise CloneError(
            f"Host '{host}' is not allowed. Allowed: {sorted(settings.allowed_git_hosts_set)}"
        )


async def _run_git(*args: str, cwd: Path | None = None, timeout_s: int) -> tuple[int, str, str]:
    """Run a git command with a hard timeout, returning (rc, stdout, stderr)."""
    # Disable interactive credential prompts: a private repo must FAIL FAST with
    # an auth error, not hang waiting for a username until the timeout. Both vars
    # are belt-and-suspenders (GIT_TERMINAL_PROMPT covers git's own prompt;
    # GCM_INTERACTIVE=never stops the Git Credential Manager popping a GUI).
    env = {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",
        "GCM_INTERACTIVE": "never",
    }
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=str(cwd) if cwd else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        async with asyncio.timeout(timeout_s):
            stdout, stderr = await proc.communicate()
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise CloneError(f"git {args[0]} timed out after {timeout_s}s") from None
    return proc.returncode or 0, stdout.decode(errors="replace"), stderr.decode(errors="replace")


def _measure_workspace(workspace: Path, settings: Settings) -> tuple[int, int]:
    """Count files and total bytes (excluding .git), enforcing caps.

    Raises CloneError if the repo exceeds configured limits.
    """
    max_bytes = settings.max_repo_mb * 1024 * 1024
    file_count = 0
    size_bytes = 0
    for p in workspace.rglob("*"):
        # Skip the .git directory — it's metadata, not source we index.
        if ".git" in p.parts:
            continue
        if p.is_file():
            file_count += 1
            try:
                size_bytes += p.stat().st_size
            except OSError:
                continue
            if file_count > settings.max_repo_files:
                raise CloneError(
                    f"Repo exceeds file cap ({settings.max_repo_files} files). "
                    "Cartograph targets repos up to this size."
                )
            if size_bytes > max_bytes:
                raise CloneError(f"Repo exceeds size cap ({settings.max_repo_mb} MB).")
    return file_count, size_bytes


def _on_rm_error(func: Callable[[str], object], path: str, _exc: object) -> None:
    """rmtree error handler: clear the read-only bit and retry.

    Git pack files under .git are written read-only; on Windows `shutil.rmtree`
    can't unlink them without this. Cross-platform safe (chmod +w is a no-op
    where it isn't needed).
    """
    os.chmod(path, stat.S_IWRITE)
    func(path)


def cleanup_workspace(workspace: Path) -> None:
    """Remove a clone's workspace, including read-only git objects. Idempotent."""
    if not workspace.exists():
        return
    # `onexc` (3.12+) supersedes the deprecated `onerror`.
    shutil.rmtree(workspace, onexc=_on_rm_error)


async def clone_repo(
    url: str,
    workspace_id: str,
    *,
    branch: str | None = None,
    settings: Settings | None = None,
) -> CloneResult:
    """Safely clone `url` into an isolated workspace.

    Args:
        url: The repository URL (validated against the host allowlist).
        workspace_id: Unique id for this clone's directory (typically the repo UUID).
        branch: Optional branch to check out; defaults to the remote HEAD.

    Returns a CloneResult; raises CloneError on any safety or clone failure.
    """
    settings = settings or get_settings()
    _validate_url(url, settings)

    workspace = WORKSPACE_ROOT / workspace_id
    # Filesystem prep is blocking I/O — offload so we don't stall the event loop.
    await asyncio.to_thread(WORKSPACE_ROOT.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread(cleanup_workspace, workspace)

    # Defense-in-depth git config flags applied to the clone itself.
    safety_flags = [
        "-c",
        "core.hooksPath=/dev/null",  # no clone/checkout hooks execute
        "-c",
        "protocol.file.allow=never",  # block file:// submodules
        "-c",
        "core.symlinks=false",  # don't materialize symlinks out of the tree
    ]
    clone_args = [
        *safety_flags,
        "clone",
        "--depth",
        "1",
        "--single-branch",
        "--no-tags",
    ]
    if branch:
        clone_args += ["--branch", branch]
    clone_args += [url, str(workspace)]

    log.info("clone.start", url=url, workspace=str(workspace), branch=branch)
    rc, _out, err = await _run_git(*clone_args, timeout_s=CLONE_TIMEOUT_SECONDS)
    if rc != 0:
        await asyncio.to_thread(cleanup_workspace, workspace)
        # Classify: an anonymous clone of a private (or nonexistent) repo fails
        # with an auth/not-found message. Surface it as PrivateRepoError so the
        # API can prompt the user to connect GitHub (PLAN.md §9A), rather than
        # returning an opaque "clone failed".
        low = err.lower()
        if any(
            sig in low
            for sig in (
                "authentication failed",
                "could not read username",
                "terminal prompts disabled",
                "repository not found",
                "fatal: could not read",
                "403",
                "404",
            )
        ):
            raise PrivateRepoError(
                "This repository is private or could not be found anonymously. "
                "Connect GitHub to index private repositories."
            )
        raise CloneError(f"git clone failed: {err.strip()[:500]}")

    try:
        # rglob over the whole tree is blocking — run it off the event loop.
        file_count, size_bytes = await asyncio.to_thread(_measure_workspace, workspace, settings)
        head_commit = (await _run_git("rev-parse", "HEAD", cwd=workspace, timeout_s=30))[1].strip()
        resolved_branch = (
            branch
            or (await _run_git("rev-parse", "--abbrev-ref", "HEAD", cwd=workspace, timeout_s=30))[
                1
            ].strip()
        )
    except CloneError:
        await asyncio.to_thread(cleanup_workspace, workspace)
        raise

    log.info(
        "clone.done",
        workspace=str(workspace),
        head_commit=head_commit,
        files=file_count,
        size_mb=round(size_bytes / 1024 / 1024, 1),
    )
    return CloneResult(
        workspace=workspace,
        head_commit=head_commit,
        default_branch=resolved_branch,
        file_count=file_count,
        size_bytes=size_bytes,
    )
