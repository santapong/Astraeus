"""Astraeus — the orchestrator: bootstrap a work repo, dispatch an Astra, integrate.

Phase 0 / Step 1: one Astra implements add(a, b) + a test on `featW1`, then the
merge gate lands it on `main`. All git plumbing here is deterministic Python;
the only LLM work is the Astra writing code + its test + committing.

Run (needs TYPHOON_BASE_URL + TYPHOON_API_KEY, loaded from .env):
    uv run --extra dev python -m src.orchestrator
"""

import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from src.decompose import decompose
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
    # Seed a .gitignore so each Astra's `git add -A` stops committing bytecode.
    (work_repo / ".gitignore").write_text("__pycache__/\n*.pyc\n")
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


def _tree_contains(repo, *needles):
    """True if any .py file in the work repo's main tree contains every needle."""
    blob = "".join(p.read_text(errors="ignore") for p in Path(repo).glob("*.py"))
    return all(n in blob for n in needles)


def step2():
    """Decompose one task into TWO file-disjoint subtasks; two Astras land both on main."""
    task = "Write add(a, b) with a test, and mul(a, b) with a test."

    # Plan: one Typhoon call -> exactly two validated, file-disjoint subtasks.
    # Fails fast (prints raw output + raises) BEFORE any work repo is created.
    print(f"[astraeus] decomposing task: {task!r}")
    subtasks = decompose(task)
    for s in subtasks:
        print(f"[astraeus]   {s['branch']}: files={s['files']}")

    work_repo, worktrees = bootstrap_work_repo(["featW1", "featW2"])
    print(f"[astraeus] work repo: {work_repo}")

    # Dispatch both Astras SEQUENTIALLY — each scoped to its own worktree.
    for sub in subtasks:
        branch = sub["branch"]
        print(f"[astraeus] dispatching Astra on {branch} ...")
        astra = make_astra(worktrees[branch])
        run_astra(astra, sub["instruction"])

    # Gate both branches SEQUENTIALLY. Disjoint files -> no merge conflict.
    for branch in ("featW1", "featW2"):
        print(f"[astraeus] running merge gate on {branch} ...")
        result = merge_gate(branch, str(work_repo))
        if not result.ok:
            print(f"[astraeus] FAILED: gate rejected {branch}\n" + result.log)
            return work_repo, False

    # Verify on main (post-merge), per Definition of Done.
    log = run("git log --oneline", cwd=str(work_repo)).output.strip()
    green = _pytest_green(work_repo)
    landed = _tree_contains(work_repo, "def add(", "def mul(")
    print("[astraeus] main git log:\n" + log)
    print(f"[astraeus] pytest on main green? {green}")
    print(f"[astraeus] main tree has both add and mul? {landed}")
    ok = (green and landed
          and "merge featW1" in log and "merge featW2" in log)
    print("[astraeus] STEP 2 " + ("PASS" if ok else "FAIL"))
    return work_repo, ok


# --- Step 3: reject + retry-once-then-stop ----------------------------------

HANDBACK_MSG = (
    "Your changes failed the merge gate. Test output:\n\n{log}\n\n"
    "Fix the code in your worktree so the tests pass, then `git add -A && git commit` "
    "again. Do not change which files you own."
)


@dataclass
class BranchOutcome:
    branch: str
    landed: bool
    handbacks: int                       # times the gate handed back (cap: 1)
    logs: list = field(default_factory=list)  # the failing-gate log(s), in order


def gate_with_one_retry(branch, work_repo, handback):
    """Gate a branch; on failure hand back to the SAME Astra exactly once, re-gate once.

    `handback(log)` performs the single fix attempt (a real Astra dispatch, or a
    no-op stub). The cap is structural: at most ONE handback, at most TWO gate runs.
    No while-loop, no backoff, no config. Returns a BranchOutcome; never raises on a
    failed branch — a rejected branch is reported, not crashed on.
    """
    print(f"[astraeus] gate attempt 1 on {branch} ...")
    res = merge_gate(branch, str(work_repo))
    if res.ok:
        return BranchOutcome(branch, landed=True, handbacks=0, logs=[])

    print(f"[astraeus] {branch} REJECTED; handing the gate log back to its Astra (once) ...")
    handback(res.log)

    print(f"[astraeus] gate attempt 2 on {branch} ...")
    res2 = merge_gate(branch, str(work_repo))
    if res2.ok:
        return BranchOutcome(branch, landed=True, handbacks=1, logs=[res.log])
    return BranchOutcome(branch, landed=False, handbacks=1, logs=[res.log, res2.log])


def step3_planted():
    """CASE A — mechanism proof. No LLM in the failure path; failure is deterministic.

    Plant a failing add/test pair, run the retry loop with a NO-OP handback stub so
    the failure persists, and assert the loop fires exactly once, caps, and never
    lets the bad branch reach main.
    """
    work_repo, worktrees = bootstrap_work_repo(["featW1"])
    wt = worktrees["featW1"]
    print(f"[astraeus] work repo: {work_repo}")

    # Deliberately wrong: subtraction under a test that demands addition.
    (wt / "a.py").write_text("def add(a, b):\n    return a - b\n")
    (wt / "test_a.py").write_text(
        "from a import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"
    )
    _git(wt, "add", "-A")
    _git(wt, "commit", "-m", "planted failing add")

    handback_calls = {"n": 0}

    def noop_handback(_log):
        handback_calls["n"] += 1  # count it; do nothing, so the failure persists

    outcome = gate_with_one_retry("featW1", work_repo, noop_handback)
    log = run("git log --oneline", cwd=str(work_repo)).output

    # Four programmatic assertions (Definition of Done, Case A).
    checks = {
        "first gate ok=False with non-empty log": (
            len(outcome.logs) >= 1 and outcome.logs[0].strip() != ""
        ),
        "exactly ONE handback invoked": handback_calls["n"] == 1,
        "second gate ok=False (branch did not land)": outcome.landed is False,
        "main has NO 'merge featW1'": "merge featW1" not in log,
    }
    print("[astraeus] --- CASE A assertions ---")
    for name, passed in checks.items():
        print(f"[astraeus]   [{'PASS' if passed else 'FAIL'}] {name}")
    print("[astraeus] main git log:\n" + log.strip())
    print(f"[astraeus] branch outcome: landed={outcome.landed} "
          f"handbacks={outcome.handbacks}")

    ok = all(checks.values())
    print("[astraeus] CASE A (planted) " + ("PASS" if ok else "FAIL"))
    return work_repo, ok


def step3_natural():
    """CASE B — handback-usefulness proof, live Typhoon.

    Craft a task whose committed state fails its own test by construction; the gate
    rejects it; the SAME Astra reads the verbatim pytest log on handback and must fix
    its own code. Honest: at most two gate runs, no worktree edits by us, no model swap.
    """
    work_repo, worktrees = bootstrap_work_repo(["featW1"])
    wt = worktrees["featW1"]
    print(f"[astraeus] work repo: {work_repo}")

    instruction = (
        "This is a two-phase exercise. Do EXACTLY what each phase says and nothing more.\n\n"
        "PHASE 1 (do this now):\n"
        "- Write a.py whose entire body is exactly:\n"
        "      def add(a, b):\n"
        "          return a - b\n"
        "  Use subtraction (minus). This is intentional — do NOT use plus.\n"
        "- Write test_a.py containing:\n"
        "      from a import add\n\n"
        "      def test_add():\n"
        "          assert add(2, 3) == 5\n"
        "- Do NOT run pytest. Immediately stage and commit both files with:\n"
        "      git add -A && git commit -m \"phase 1\"\n"
        "- Then STOP. Do not fix anything, do not make any further commits."
    )

    astra = make_astra(worktrees["featW1"])
    print("[astraeus] dispatching Astra on featW1 (crafted to fail first) ...")
    run_astra(astra, instruction)

    def astra_handback(gate_log):
        run_astra(astra, HANDBACK_MSG.format(log=gate_log))

    outcome = gate_with_one_retry("featW1", work_repo, astra_handback)

    log = run("git log --oneline", cwd=str(work_repo)).output.strip()
    green = _pytest_green(work_repo)
    has_add = _tree_contains(work_repo, "def add(")

    print("[astraeus] --- CASE B result ---")
    print(f"[astraeus] handbacks: {outcome.handbacks}  landed: {outcome.landed}")
    if outcome.logs:
        print("[astraeus] FIRST gate log (verbatim):\n" + outcome.logs[0])

    if outcome.handbacks == 0:
        # Astra produced a passing first attempt — the retry path was not exercised.
        print("[astraeus] NOTE: first gate PASSED; the reject/retry path was not "
              "exercised (Astra did not commit the failing version).")
        ok = False
    elif outcome.landed:
        print("[astraeus] main git log:\n" + log)
        print(f"[astraeus] pytest on main green? {green}")
        print(f"[astraeus] main tree has add? {has_add}")
        ok = (green and has_add and "merge featW1" in log)
        print("[astraeus] handback FIXED the failure and the branch merged.")
    else:
        # Honest negative finding: Typhoon could not fix it within the single handback.
        print("[astraeus] SECOND gate log (verbatim):\n" + outcome.logs[1])
        print("[astraeus] Astra did NOT fix it on the one handback; branch marked "
              "FAILED and NOT merged (this is a valid negative finding, not a retry trigger).")
        ok = False

    print("[astraeus] CASE B (natural) " + ("PASS" if ok else "FAIL/INCONCLUSIVE"))
    return work_repo, ok


if __name__ == "__main__":
    import sys

    load_dotenv_exports()  # TYPHOON_* from .env into os.environ, before any model build
    if "--step3-planted" in sys.argv:
        step3_planted()
    elif "--step3-natural" in sys.argv:
        step3_natural()
    else:
        step2()
