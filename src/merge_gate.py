"""The automated quality gate — the one place that lands an Astra's branch on main.

Operates on the WORK repo (a separate throwaway repo, never this source repo).
All git plumbing is deterministic Python here; no LLM touches git.
"""

import subprocess
from dataclasses import dataclass


@dataclass
class MergeResult:
    ok: bool
    log: str = ""


@dataclass
class RunResult:
    # named to read like the spec pseudocode: tests.exit_code / tests.output
    exit_code: int
    output: str


def run(cmd, cwd=None) -> RunResult:
    p = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
    return RunResult(p.returncode, (p.stdout or "") + (p.stderr or ""))


def log(msg):
    # one-line sanity logging; deliberately not a logging framework (Phase 0)
    print(msg)


def worktree_for(branch, work_repo) -> str:
    """Look up the worktree path the harness already created for `branch`.

    This is a lookup, not creation — the orchestrator owns worktree creation.
    """
    out = run(f"git -C {work_repo} worktree list --porcelain").output
    path = None
    for line in out.splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree "):]
        elif line.strip() == f"branch refs/heads/{branch}":
            return path
    raise ValueError(f"no worktree found for branch {branch} in {work_repo}")


def merge_gate(branch, work_repo, test_cmd="pytest -q") -> MergeResult:
    """Run the branch's tests in its worktree; merge to main only if green.

    `work_repo` is explicit: the spec's signature omits it, but the gate must
    know which repo to act on. Subtlety: tests run in the branch's worktree,
    while `git checkout main` / `git merge` run in the work repo's MAIN tree.
    `main` is checked out in no worktree (only featW* are), so checking it out
    in `work_repo` is safe — do not collapse the two cwds.
    """
    wt = worktree_for(branch, work_repo)

    log(run(f"git -C {wt} diff main..{branch}").output)  # sanity, log only

    tests = run(test_cmd, cwd=wt)
    if tests.exit_code != 0:
        # hand the failure back to the Astra (the orchestrator decides retry)
        return MergeResult(ok=False, log=tests.output)

    checkout = run("git checkout main", cwd=work_repo)
    if checkout.exit_code != 0:
        # never merge onto an unknown branch if we couldn't get onto main
        return MergeResult(ok=False, log=checkout.output)
    # Double quotes, not single: run() uses shell=True, and Windows cmd.exe treats
    # single quotes as literal chars (git would read 'merge / {branch}' as extra
    # merge targets and fail). Double quotes work on both cmd.exe and /bin/sh.
    merge = run(f'git merge --no-ff {branch} -m "merge {branch}"', cwd=work_repo)
    if merge.exit_code != 0:
        # a merge that didn't land must not report success (don't trust it blindly)
        return MergeResult(ok=False, log=merge.output)
    return MergeResult(ok=True, log=merge.output)
