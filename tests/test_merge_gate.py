"""Unit tests for the merge gate. No LLM — real temp git repos only.

These exercise merge_gate against a tiny WORK repo built per test: a main
commit, a feature branch + worktree carrying a test file, then the gate.
"""

import subprocess
from pathlib import Path

from src.merge_gate import merge_gate, worktree_for, run


def _git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True,
                   capture_output=True, text=True)


def _make_work_repo(tmp_path: Path, branch: str, test_body: str):
    """Build a work repo on main, then a `branch` worktree holding a test file."""
    work_repo = tmp_path / "work"
    work_repo.mkdir()
    _git(work_repo, "init", "-b", "main")
    _git(work_repo, "config", "user.email", "astra@example.com")
    _git(work_repo, "config", "user.name", "Astra")
    _git(work_repo, "config", "commit.gpgsign", "false")  # throwaway repo, no signing
    (work_repo / "README").write_text("seed\n")
    _git(work_repo, "add", "-A")
    _git(work_repo, "commit", "-m", "init")

    _git(work_repo, "branch", branch)
    wt = tmp_path / branch  # sibling dir, outside the work repo
    _git(work_repo, "worktree", "add", str(wt), branch)

    (wt / "test_feature.py").write_text(test_body)
    _git(wt, "add", "-A")
    _git(wt, "commit", "-m", f"work on {branch}")
    return work_repo, wt


def _head_subject(repo):
    return subprocess.run(["git", "-C", str(repo), "log", "-1", "--pretty=%s"],
                          capture_output=True, text=True).stdout.strip()


def test_worktree_for_finds_branch_path(tmp_path):
    work_repo, wt = _make_work_repo(tmp_path, "featW1", "def test_ok():\n    assert True\n")
    assert Path(worktree_for("featW1", str(work_repo))).resolve() == wt.resolve()


def test_passing_branch_merges_to_main(tmp_path):
    work_repo, _ = _make_work_repo(tmp_path, "featW1", "def test_ok():\n    assert True\n")
    res = merge_gate("featW1", str(work_repo))
    assert res.ok is True
    # the change landed on main via a --no-ff merge commit
    assert _head_subject(work_repo) == "merge featW1"
    assert (work_repo / "test_feature.py").exists()


def test_failing_branch_is_rejected_and_main_unchanged(tmp_path):
    work_repo, _ = _make_work_repo(tmp_path, "featW1", "def test_bad():\n    assert False\n")
    before = _head_subject(work_repo)
    res = merge_gate("featW1", str(work_repo))
    assert res.ok is False
    assert res.log.strip() != ""          # the failure log is handed back
    assert _head_subject(work_repo) == before  # nothing merged
    assert not (work_repo / "test_feature.py").exists()
