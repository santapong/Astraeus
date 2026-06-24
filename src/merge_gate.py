"""The automated quality gate — sandboxed (Phase 1).

The gate spins an EPHEMERAL container, clones the bare origin, checks out the
branch under test, and runs pytest INSIDE that container. The host never
executes agent-written code. On green it merges to main and pushes; on red (or a
merge conflict) it leaves origin's main untouched and hands the log back.

All docker/git ops are list-form via dcmd() and check their exit codes.
"""

import subprocess
from dataclasses import dataclass, field

from src.docker_backend import IMAGE, ORIGIN_VOLUME, _runtime_args, dcmd

GATE_CONTAINER = "astraeus_gate"
GATE_TEST_TIMEOUT = 300  # seconds; a suite that exceeds this is a clean red, not a crash


@dataclass
class MergeResult:
    ok: bool
    log: str = ""
    conflicts: list = field(default_factory=list)  # files in conflict (git diff --diff-filter=U)
    failures: list = field(default_factory=list)   # failing test FILE paths parsed from a red pytest summary


def _combined(p):
    return (p.stdout or "") + (p.stderr or "")


def _failing_files(output):
    """Parse pytest's short-test-summary `FAILED <nodeid>` / `ERROR <nodeid>` lines into the
    failing test FILE paths (first-seen order, deduped). `pytest -q` already emits this
    summary on red, so the gate needs no extra flags. A nodeid is `path::test`, so we take
    the part before `::`; collection errors (`ERROR path - msg`) have no `::` and yield the
    path directly. Lets the orchestrator route a red gate to the owning worker by exact file
    instead of regex-scanning the whole log."""
    files = []
    for raw in output.splitlines():
        line = raw.strip()
        for prefix in ("FAILED ", "ERROR "):
            if line.startswith(prefix):
                nodeid = line[len(prefix):].split(" - ", 1)[0].strip()
                path = nodeid.split("::", 1)[0].strip()
                if path.endswith(".py") and path not in files:
                    files.append(path)
                break
    return files


def merge_gate(branch, origin_volume=ORIGIN_VOLUME, image=IMAGE):
    """Test `branch` in a sandbox; merge to origin's main only if green.

    Returns MergeResult(ok, log). `log` carries the gate's pytest output (on red)
    or the merge/push failure (on a conflict), so the orchestrator can hand it back.
    """
    dcmd(["rm", "-f", GATE_CONTAINER], check=False)
    # gVisor-hardened when ASTRAEUS_RUNTIME is set: the gate runs agent-written pytest.
    dcmd(["run", *_runtime_args(), "-d", "--name", GATE_CONTAINER, "--network", "none",
          "-v", f"{origin_volume}:/origin", "-w", "/workspace", image, "sleep", "infinity"])
    try:
        # Orchestrator-owned git plumbing: clone the bare origin, check out the branch.
        dcmd(["exec", GATE_CONTAINER, "git", "clone", "/origin", "/workspace"])
        dcmd(["exec", "-w", "/workspace", GATE_CONTAINER, "git", "checkout", branch])

        # Run the branch's tests INSIDE the gate container. Host never runs this code.
        # A suite that overruns the cap is a clean red verdict, not an uncaught crash
        # (the finally below removes the container, killing the runaway pytest).
        try:
            tests = dcmd(["exec", "-w", "/workspace", GATE_CONTAINER,
                          "python", "-m", "pytest", "-q"], check=False, timeout=GATE_TEST_TIMEOUT)
        except subprocess.TimeoutExpired:
            return MergeResult(ok=False, log=f"gate pytest timed out after {GATE_TEST_TIMEOUT}s")
        if tests.returncode != 0:
            out = _combined(tests)
            # red → main untouched; hand back the log + the structured failing files
            return MergeResult(ok=False, log=out, failures=_failing_files(out))

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
