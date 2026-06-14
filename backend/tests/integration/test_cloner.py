"""Tests for the sandboxed cloner.

The URL-validation tests run offline (no network). The live-clone test hits a
tiny public GitHub repo and is marked `network` so it can be skipped in offline
CI lanes if needed.
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.indexer.cloner import (
    CloneError,
    PrivateRepoError,
    _validate_url,
    cleanup_workspace,
    clone_repo,
)


def test_rejects_non_allowlisted_host() -> None:
    settings = Settings(allowed_git_hosts="github.com")
    with pytest.raises(CloneError, match="not allowed"):
        _validate_url("https://evil.example.com/x/y", settings)


def test_rejects_non_https_scheme() -> None:
    settings = Settings(allowed_git_hosts="github.com")
    with pytest.raises(CloneError, match="git URLs are allowed"):
        _validate_url("ssh://git@github.com/x/y", settings)


def test_accepts_allowlisted_host() -> None:
    settings = Settings(allowed_git_hosts="github.com")
    # Should not raise.
    _validate_url("https://github.com/owner/repo", settings)


@pytest.mark.network
async def test_clone_small_repo() -> None:
    """Clone a tiny real repo end-to-end and assert the result shape."""
    settings = Settings(allowed_git_hosts="github.com", max_repo_files=5000, max_repo_mb=500)
    result = await clone_repo(
        "https://github.com/octocat/Hello-World",
        workspace_id="test-hello-world",
        settings=settings,
    )
    try:
        assert result.workspace.exists()
        assert len(result.head_commit) == 40  # full SHA
        assert result.file_count >= 1
    finally:
        cleanup_workspace(result.workspace)
        assert not result.workspace.exists()


@pytest.mark.network
async def test_private_repo_fails_fast_with_guidance() -> None:
    """A private/nonexistent repo must raise PrivateRepoError quickly (not hang
    on a credential prompt) so the API can prompt the user to connect GitHub."""
    settings = Settings(allowed_git_hosts="github.com")
    with pytest.raises(PrivateRepoError, match=r"[Cc]onnect GitHub"):
        await clone_repo(
            "https://github.com/paygraph-ai/this-repo-does-not-exist-xyz",
            workspace_id="test-private-nonexistent",
            settings=settings,
        )
