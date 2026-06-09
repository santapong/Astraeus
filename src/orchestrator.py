"""Astraeus — the orchestrator: bootstrap a work repo, dispatch an Astra, integrate.

Phase 0 / Step 1: one Astra implements add(a, b) + a test on `featW1`, then the
merge gate lands it on `main`. All git plumbing here is deterministic Python;
the only LLM work is the Astra writing code + its test + committing.

Run (needs TYPHOON_BASE_URL + TYPHOON_API_KEY, loaded from .env):
    uv run --extra dev python -m src.orchestrator
"""

import subprocess
import tempfile
from pathlib import Path

from src.env import load_dotenv_exports
from src.merge_gate import merge_gate, run
from src.worker import make_astra, run_astra


def _git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True,
                   capture_output=True, text=True)


def bootstrap_work_repo(branches):
    """Create a throwaway work repo on `main`, plus a branch + worktree per name.

    Returns (work_repo, {branch: worktree_path}). The work repo lives OUTSIDE
    this source repo (a temp dir); worktrees are sibling dirs next to it.
    """
    base = Path(tempfile.mkdtemp(prefix="astraeus_work_"))
    work_repo = base / "repo"
    work_repo.mkdir()

    _git(work_repo, "init", "-b", "main")
    _git(work_repo, "config", "user.email", "astra@example.com")
    _git(work_repo, "config", "user.name", "Astra")
    _git(work_repo, "config", "commit.gpgsign", "false")  # throwaway repo, no signing

    (work_repo / "README").write_text("astraeus work repo\n")
    _git(work_repo, "add", "-A")
    _git(work_repo, "commit", "-m", "init")

    worktrees = {}
    for branch in branches:
        _git(work_repo, "branch", branch)
        wt = base / branch  # sibling of the repo, outside it
        _git(work_repo, "worktree", "add", str(wt), branch)
        worktrees[branch] = wt
    return work_repo, worktrees


def _pytest_green(repo):
    return run("pytest -q", cwd=str(repo)).exit_code == 0


def step1():
    """One Astra → commit on featW1 → merge_gate → merge. Get green."""
    work_repo, worktrees = bootstrap_work_repo(["featW1"])
    print(f"[astraeus] work repo: {work_repo}")

    # Hardcoded subtask (no decompose yet in Step 1). Flat files keep the test
    # trivially importable under pytest's default import mode.
    instruction = (
        "Implement a function add(a, b) that returns a + b in a file named a.py. "
        "Write a pytest test in test_a.py that imports add from a and checks "
        "add(2, 3) == 5. Make `pytest -q` pass, then commit."
    )

    astra = make_astra(worktrees["featW1"])
    print("[astraeus] dispatching Astra on featW1 ...")
    run_astra(astra, instruction)

    print("[astraeus] running merge gate on featW1 ...")
    result = merge_gate("featW1", str(work_repo))
    if not result.ok:
        print("[astraeus] FAILED: gate rejected featW1\n" + result.log)
        return work_repo, False

    # Verify on main (post-merge), per Definition of Done.
    log = run("git log --oneline", cwd=str(work_repo)).output.strip()
    green = _pytest_green(work_repo)
    print("[astraeus] main git log:\n" + log)
    print(f"[astraeus] pytest on main green? {green}")
    ok = green and "merge featW1" in log
    print("[astraeus] STEP 1 " + ("PASS" if ok else "FAIL"))
    return work_repo, ok


if __name__ == "__main__":
    load_dotenv_exports()  # TYPHOON_* from .env into os.environ, before any model build
    step1()
