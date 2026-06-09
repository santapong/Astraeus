"""The automated quality gate — sandboxed (Phase 1).

The gate spins an EPHEMERAL container, clones the bare origin, checks out the
branch under test, and runs pytest INSIDE that container. The host never
executes agent-written code. On green it merges to main and pushes; on red (or a
merge conflict) it leaves origin's main untouched and hands the log back.

All docker/git ops are list-form via dcmd() and check their exit codes.
"""

from dataclasses import dataclass, field

from src.docker_backend import IMAGE, ORIGIN_VOLUME, dcmd

GATE_CONTAINER = "astraeus_gate"


@dataclass
class MergeResult:
    ok: bool
    log: str = ""
    conflicts: list = field(default_factory=list)  # files in conflict (git diff --diff-filter=U)


def _combined(p):
    return (p.stdout or "") + (p.stderr or "")


def merge_gate(branch, origin_volume=ORIGIN_VOLUME, image=IMAGE):
    """Test `branch` in a sandbox; merge to origin's main only if green.

    Returns MergeResult(ok, log). `log` carries the gate's pytest output (on red)
    or the merge/push failure (on a conflict), so the orchestrator can hand it back.
    """
    dcmd(["rm", "-f", GATE_CONTAINER], check=False)
    dcmd(["run", "-d", "--name", GATE_CONTAINER, "--network", "none",
          "-v", f"{origin_volume}:/origin", "-w", "/workspace", image, "sleep", "infinity"])
    try:
        # Orchestrator-owned git plumbing: clone the bare origin, check out the branch.
        dcmd(["exec", GATE_CONTAINER, "git", "clone", "/origin", "/workspace"])
        dcmd(["exec", "-w", "/workspace", GATE_CONTAINER, "git", "checkout", branch])

        # Run the branch's tests INSIDE the gate container. Host never runs this code.
        tests = dcmd(["exec", "-w", "/workspace", GATE_CONTAINER,
                      "python", "-m", "pytest", "-q"], check=False)
        if tests.returncode != 0:
            return MergeResult(ok=False, log=_combined(tests))  # red → main untouched

        # Green → merge to main and push. list-form -m message (no shell quoting).
        dcmd(["exec", "-w", "/workspace", GATE_CONTAINER, "git", "checkout", "main"])
        merge = dcmd(["exec", "-w", "/workspace", GATE_CONTAINER,
                      "git", "merge", "--no-ff", branch, "-m", f"merge {branch}"], check=False)
        if merge.returncode != 0:
            # A real conflict: record the unmerged files, then abort cleanly so
            # origin's main stays untouched.
            u = dcmd(["exec", "-w", "/workspace", GATE_CONTAINER,
                      "git", "diff", "--name-only", "--diff-filter=U"], check=False)
            conflicts = [f for f in u.stdout.split() if f]
            dcmd(["exec", "-w", "/workspace", GATE_CONTAINER, "git", "merge", "--abort"], check=False)
            return MergeResult(ok=False, log=_combined(merge), conflicts=conflicts)
        push = dcmd(["exec", "-w", "/workspace", GATE_CONTAINER, "git", "push", "origin", "main"], check=False)
        if push.returncode != 0:
            return MergeResult(ok=False, log=_combined(push))

        return MergeResult(ok=True, log=_combined(tests))
    finally:
        dcmd(["rm", "-f", GATE_CONTAINER], check=False)
