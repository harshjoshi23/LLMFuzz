"""Verify commit provenance with Git-managed refs and worktrees."""

import subprocess

from src.run_index import _git_commit_hash


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def test_commit_hash_handles_packed_refs_and_worktrees(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "-c", "user.name=Test", "-c", "user.email=test@example.com",
        "commit", "--allow-empty", "-m", "fixture")
    expected = git(repo, "rev-parse", "HEAD")
    git(repo, "pack-refs", "--all", "--prune")
    assert _git_commit_hash(repo) == expected

    worktree = tmp_path / "worktree"
    git(repo, "worktree", "add", "--detach", str(worktree))
    assert _git_commit_hash(worktree) == expected


def test_non_repository_returns_none(tmp_path):
    assert _git_commit_hash(tmp_path) is None
