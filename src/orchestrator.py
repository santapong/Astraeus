"""Astraeus — the orchestrator (Phase 1): bare origin on a docker volume, one
sandboxed Astra per branch, a sandboxed gate that lands work on origin's main.

Phase 1 / Step 1: one Astra implements add(a, b) + a test on `featW1` INSIDE its
container, the orchestrator pushes the branch, and the sandboxed merge gate tests
+ merges it onto origin's main. The host never executes agent-written code; the
containers never hold the API key; every git/docker op is list-form and checks
its exit code.

Run (needs TYPHOON_BASE_URL + TYPHOON_API_KEY from .env, and a running docker daemon):
    uv run --extra dev python -m src.orchestrator
"""

import json
import re
import threading
import time
import uuid

from src.decompose import decompose
from src.docker_backend import (
    IMAGE,
    ORIGIN_VOLUME,
    WORKSPACE_VOLUME,
    DockerError,
    _docker,
    _runtime_args,
    dcmd,
)
from src.env import load_dotenv_exports
from src.merge_gate import merge_gate
from src.worker import (
    ASTRA_HARNESS_TEMPLATE,
    ASTRA_SHARED_SYSTEM_PROMPT,
    SleepyModel,
    make_astra,
    run_astra,
)

WORKER_CONTAINER = "astraeus_w1"


# --- git plumbing (orchestrator-owned, list-form inside containers) ----------

def reset_origin_volume():
    """Recreate the bare-origin volume fresh (Amendment 2: NOT removed at run end)."""
    dcmd(["volume", "rm", "-f", ORIGIN_VOLUME], check=False)
    dcmd(["volume", "create", ORIGIN_VOLUME])
    # Seed a bare repo with an initial `main` (README + .gitignore) in one throwaway
    # container. The sh -c runs INSIDE the container; the host call is list-form.
    seed = (
        "git init -q --bare /origin && rm -rf /tmp/seed && git clone -q /origin /tmp/seed && "
        "cd /tmp/seed && printf 'astraeus work repo\\n' > README && "
        "printf '__pycache__/\\n*.pyc\\n.pytest_cache/\\n' > .gitignore && "
        "git add -A && git commit -q -m init && git push -q origin HEAD:main"
    )
    dcmd(["run", "--rm", "--network", "none", "-v", f"{ORIGIN_VOLUME}:/origin", IMAGE, "sh", "-c", seed])


def start_worker(name, branch):
    """Run a fresh worker container (no network) and clone+branch it for the Astra."""
    dcmd(["rm", "-f", name], check=False)
    dcmd(["run", *_runtime_args(), "-d", "--name", name, "--network", "none",
          "-v", f"{ORIGIN_VOLUME}:/origin", "-w", "/workspace", IMAGE, "sleep", "infinity"])
    dcmd(["exec", name, "git", "clone", "/origin", "/workspace"])
    dcmd(["exec", "-w", "/workspace", name, "git", "checkout", "-b", branch])


def push_branch(name, branch):
    """Orchestrator pushes the Astra's committed branch to origin."""
    dcmd(["exec", "-w", "/workspace", name, "git", "push", "origin", branch])


def origin_main_log():
    """origin's main log, read via a throwaway container (proof artifact)."""
    return dcmd(["run", "--rm", "--network", "none", "-v", f"{ORIGIN_VOLUME}:/origin",
                 IMAGE, "git", "-C", "/origin", "log", "--oneline", "main"]).stdout.strip()


def origin_show(path, ref="main"):
    """Read `ref:path` from origin via a throwaway container."""
    return dcmd(["run", "--rm", "--network", "none", "-v", f"{ORIGIN_VOLUME}:/origin",
                 IMAGE, "git", "-C", "/origin", "show", f"{ref}:{path}"], check=False).stdout


def volume_inspect_oneliner():
    """Amendment 2: prove the origin volume survived the run."""
    return dcmd(["volume", "inspect", ORIGIN_VOLUME,
                 "--format", "{{.Name}} created={{.CreatedAt}} mountpoint={{.Mountpoint}}"]).stdout.strip()


# --- Phase 2: central shared workspace (one tree every sandbox mounts) --------

def _docker_available():
    """True if the docker daemon answers — an explicit precondition (phase1 GAP #5)."""
    try:
        return _docker(["info"], timeout=15).returncode == 0
    except Exception:  # noqa: BLE001 — any failure means "not available"
        return False


def reset_workspace_volume(origin_volume=ORIGIN_VOLUME, workspace_volume=WORKSPACE_VOLUME):
    """Recreate the shared workspace volume fresh as a checkout of origin's main.

    Unlike the bare origin (history, reachable only through git), this is a live
    working tree mounted at /workspace in every Astra — the central filesystem all
    sandboxes read/write directly.
    """
    dcmd(["volume", "rm", "-f", workspace_volume], check=False)
    dcmd(["volume", "create", workspace_volume])
    dcmd(["run", "--rm", "--network", "none",
          "-v", f"{origin_volume}:/origin", "-v", f"{workspace_volume}:/workspace",
          IMAGE, "git", "clone", "/origin", "/workspace"])


def seed_workspace_file(rel_path, content, workspace_volume=WORKSPACE_VOLUME):
    """Write `content` (str or bytes) to /workspace/<rel_path> in the shared tree.

    Bytes go in over stdin (same mechanism as DockerSandbox.upload_files) so file
    content is never subject to host-shell quoting; parent dirs are created.
    """
    if isinstance(content, str):
        content = content.encode("utf-8")
    p = _docker(
        ["run", "--rm", "-i", "--network", "none",
         "-v", f"{workspace_volume}:/workspace", "-w", "/workspace", IMAGE,
         "sh", "-c", 'mkdir -p "$(dirname "$1")" && cat > "$1"', "_", rel_path],
        input_bytes=content, timeout=120,
    )
    if p.returncode != 0:
        raise DockerError(f"seed_workspace_file({rel_path!r}) failed:\n"
                          + (p.stderr or b"").decode("utf-8", "replace"))


def workspace_show(path, workspace_volume=WORKSPACE_VOLUME):
    """Read /workspace/<path> from the shared tree via a throwaway container."""
    return dcmd(["run", "--rm", "--network", "none", "-v", f"{workspace_volume}:/workspace",
                 IMAGE, "cat", f"/workspace/{path}"], check=False).stdout


def workspace_git(args, origin_volume=ORIGIN_VOLUME, workspace_volume=WORKSPACE_VOLUME, check=True):
    """Run a git command in the shared tree (both volumes mounted so push/fetch to
    the bare origin work). Orchestrator-owned — Astra never run git in the tree.
    """
    return dcmd(["run", "--rm", "--network", "none",
                 "-v", f"{origin_volume}:/origin", "-v", f"{workspace_volume}:/workspace",
                 "-w", "/workspace", IMAGE, "git", *args], check=check)


def commit_workspace(msg, origin_volume=ORIGIN_VOLUME, workspace_volume=WORKSPACE_VOLUME):
    """Stage everything and commit the shared tree (tolerates 'nothing to commit')."""
    workspace_git(["add", "-A"], origin_volume=origin_volume,
                  workspace_volume=workspace_volume, check=False)
    workspace_git(["commit", "-m", msg], origin_volume=origin_volume,
                  workspace_volume=workspace_volume, check=False)


def push_candidate(candidate="candidate", origin_volume=ORIGIN_VOLUME, workspace_volume=WORKSPACE_VOLUME):
    """Publish the shared tree's HEAD to origin as the candidate branch for the gate. main
    is untouched; the gate tests this branch and merges only on green. `candidate` is a
    per-run unique ref (run_task passes `candidate-<run_id>`) so overlapping runs never
    collide on a shared ref.
    """
    workspace_git(["push", "origin", f"HEAD:{candidate}"], origin_volume=origin_volume,
                  workspace_volume=workspace_volume)


def start_shared_worker(name, workspace_volume=WORKSPACE_VOLUME):
    """Run a fresh worker container (no network) attached to the SHARED tree. No
    clone, no branch — the worker reads/writes the one /workspace all sandboxes see.
    """
    dcmd(["rm", "-f", name], check=False)
    dcmd(["run", *_runtime_args(), "-d", "--name", name, "--network", "none",
          "-v", f"{workspace_volume}:/workspace", "-w", "/workspace", IMAGE, "sleep", "infinity"])


def _discard_worker_changes(subtask, origin_volume=ORIGIN_VOLUME, workspace_volume=WORKSPACE_VOLUME):
    """Drop the working-tree changes a non-READY (stalled/errored) worker left for its
    OWN files, so partial/garbage work is never committed into the candidate. Within a
    round files are disjoint (schedule() guarantees it), so this never touches a READY
    sibling's work. Restores tracked files and removes untracked ones it created.
    """
    for f in subtask["files"]:
        workspace_git(["checkout", "--", f], origin_volume=origin_volume,
                      workspace_volume=workspace_volume, check=False)
        workspace_git(["clean", "-f", "--", f], origin_volume=origin_volume,
                      workspace_volume=workspace_volume, check=False)


def _enforce_ownership(round_subtasks, workspace_volume=WORKSPACE_VOLUME):
    """Code-enforce "write only your files": after a round, drop any changed/untracked path NOT
    owned by some worker in the round (and not under the orchestrator's `.astraeus/`), so a worker
    that wrote outside its lane can't smuggle a stray file into the candidate. Runs BEFORE the
    round commit (like _syntax_check), reusing the working-tree discard. The gate stays the backstop
    for *in-file* violations (clobbering a sibling's function); this closes the *new-file* hole that
    was previously only prompt-discouraged. Returns the discarded stray paths (best-effort)."""
    owned = set()
    for s in round_subtasks:
        owned.update(s["files"])
    status = workspace_git(["status", "--porcelain"], workspace_volume=workspace_volume, check=False)
    stray = []
    for line in (status.stdout or "").splitlines():
        path = line[3:]                    # porcelain: 2 status chars + space + path
        if " -> " in path:                 # a rename reports "old -> new"; the new path is on disk
            path = path.split(" -> ", 1)[1]
        path = path.strip().strip('"')
        if not path or path in owned or path.startswith(".astraeus/"):
            continue
        stray.append(path)
    for path in stray:
        workspace_git(["checkout", "--", path], workspace_volume=workspace_volume, check=False)
        workspace_git(["clean", "-fd", "--", path], workspace_volume=workspace_volume, check=False)
    return stray


def _syntax_check(files, workspace_volume=WORKSPACE_VOLUME):
    """Compile a worker's owned *.py files with py_compile in a throwaway sandbox over the
    shared tree. Returns True iff they all compile. A syntax error in ONE worker's file
    crashes pytest COLLECTION for the whole suite at the gate — masking every sibling — so
    run_task drops any worker that fails this BEFORE its round is committed, and only
    importable code ever reaches the gate. Non-.py files can't raise an import-time syntax
    error, so they're skipped (no container is spun when a worker owns none)."""
    py = [f for f in files if f.endswith(".py")]
    if not py:
        return True
    p = dcmd(["run", "--rm", "--network", "none",
              "-v", f"{workspace_volume}:/workspace", "-w", "/workspace",
              IMAGE, "python", "-m", "py_compile", *py], check=False)
    return p.returncode == 0


# --- Step 1 ------------------------------------------------------------------

def step1():
    """One sandboxed Astra → commit on featW1 → sandboxed gate → land on origin main."""
    reset_origin_volume()
    print(f"[astraeus] seeded bare origin on volume {ORIGIN_VOLUME!r}")

    instruction = (
        "Implement a function add(a, b) that returns a + b in a file named "
        "/workspace/a.py. Write a pytest test in /workspace/test_a.py that does "
        "`from a import add` and asserts add(2, 3) == 5. Then commit."
    )

    try:
        start_worker(WORKER_CONTAINER, "featW1")
        print(f"[astraeus] worker container {WORKER_CONTAINER!r} (--network none) cloned + on featW1")
        astra = make_astra(WORKER_CONTAINER)
        print("[astraeus] dispatching Astra on featW1 ...")
        run_astra(astra, instruction)
        push_branch(WORKER_CONTAINER, "featW1")
        print("[astraeus] pushed featW1 to origin")
    finally:
        dcmd(["rm", "-f", WORKER_CONTAINER], check=False)
        print(f"[astraeus] removed worker container {WORKER_CONTAINER!r}")

    print("[astraeus] running sandboxed merge gate on featW1 ...")
    result = merge_gate("featW1")
    if not result.ok:
        print("[astraeus] FAILED: gate rejected featW1\n" + result.log)
        return False

    # Proof, per Definition of Done.
    log = origin_main_log()
    print("\n[astraeus] gate pytest output (FROM INSIDE the gate container):\n" + result.log.strip())
    print("[astraeus] (the host never executed the agent-written test - it ran in the gate container)")
    print("\n[astraeus] origin main log (read via a container):\n" + log)
    print("\n[astraeus] origin volume survived: " + volume_inspect_oneliner())
    ok = "merge featW1" in log
    print("\n[astraeus] STEP 1 " + ("PASS" if ok else "FAIL"))
    return ok


# --- Step 2: two Astras + a real merge conflict ------------------------------

# §6 conflict-handback message. The orchestrator first materializes the merge in
# the worker (so real markers are on disk), then hands this to the SAME Astra.
HANDBACK_MSG = (
    "Your branch conflicts with origin/main, which advanced after you started. "
    "Conflicting file(s): {files}.\n"
    "Each conflicting file now contains git conflict markers: <<<<<<<, =======, >>>>>>>. "
    "The section above ======= is your work; the section below is what landed on main.\n"
    "Edit each file in {files} to combine BOTH changes correctly so all tests pass, and "
    "remove every conflict marker. Then run: git add -A && git commit --no-edit. "
    "Do not touch any other file.\n\n"
    "Example. A file containing this conflict:\n\n"
    "<<<<<<< HEAD\n"
    "def foo(x):\n"
    "    return x + 1\n"
    "=======\n"
    "def bar(y):\n"
    "    return y - 1\n"
    ">>>>>>> origin/main\n\n"
    "is correctly resolved by KEEPING BOTH sections and DELETING the three marker "
    "lines, giving:\n\n"
    "def foo(x):\n"
    "    return x + 1\n\n"
    "def bar(y):\n"
    "    return y - 1\n\n"
    "Apply the same procedure to every conflicting file: keep both sections, delete "
    "every marker line, and make sure the file is valid Python."
)


def read_container_file(container, path):
    """Read a file's text out of a container (for proof artifacts)."""
    return dcmd(["exec", container, "cat", path], check=False).stdout


def materialize_conflict(worker, branch):
    """Orchestrator plumbing: pull origin/main into the worker's branch so real
    conflict markers land on disk. Returns the list of conflicted files.
    (`git fetch`/`merge` read the local /origin volume — no network needed.)
    """
    dcmd(["exec", "-w", "/workspace", worker, "git", "fetch", "origin"])
    dcmd(["exec", "-w", "/workspace", worker, "git", "merge", "--no-edit", "origin/main"], check=False)
    u = dcmd(["exec", "-w", "/workspace", worker, "git", "diff", "--name-only", "--diff-filter=U"], check=False)
    return [f for f in u.stdout.split() if f]


def step2():
    """Two Astras both touch a shared file; the second conflicts; ONE handback
    asks the SAME Astra to resolve. Exactly two gate runs for featW2.

    The two subtasks are hardcoded (not produced by decompose) so the conflict is
    deterministic — both write the SAME files calc.py + test_calc.py. (decompose
    was validated in Phase 0 Step 2; Phase-0 file-disjointness is intentionally
    relaxed here, which is the whole point of this step.)
    """
    reset_origin_volume()
    print(f"[astraeus] seeded bare origin on volume {ORIGIN_VOLUME!r}")

    SHARED = "calc.py"
    subtasks = [
        {"branch": "featW1", "worker": "astraeus_w1",
         "instruction": (
             "Implement a function add(a, b) that returns a + b in /workspace/calc.py. "
             "Write a pytest test in /workspace/test_calc.py that does `from calc import add` "
             "and asserts add(2, 3) == 5. Then commit.")},
        {"branch": "featW2", "worker": "astraeus_w2",
         "instruction": (
             "Implement a function mul(a, b) that returns a * b in /workspace/calc.py. "
             "Write a pytest test in /workspace/test_calc.py that does `from calc import mul` "
             "and asserts mul(2, 3) == 6. Then commit.")},
    ]
    print("\n[astraeus] (1) two subtasks (HARDCODED to force a shared file):")
    for s in subtasks:
        print(f"    {s['branch']} -> writes calc.py + test_calc.py | {s['instruction']}")
    print(f"    shared file (forces the conflict): {SHARED} (+ test_calc.py)")

    astras = {}
    result_ok = False
    r2b = None
    try:
        # Start both workers (no network), clone+branch, build their Astras.
        for s in subtasks:
            start_worker(s["worker"], s["branch"])
            astras[s["branch"]] = make_astra(s["worker"])
        # Dispatch both SEQUENTIALLY (concurrency is Step 3), then push both.
        for s in subtasks:
            print(f"[astraeus] dispatching Astra on {s['branch']} ...")
            run_astra(astras[s["branch"]], s["instruction"])
            push_branch(s["worker"], s["branch"])

        # featW1 lands clean (first).
        print("\n[astraeus] gate featW1 ...")
        r1 = merge_gate("featW1")
        if not r1.ok:
            print("[astraeus] FAIL: featW1 unexpectedly rejected\n" + r1.log)
            return False
        print("[astraeus] featW1 landed on origin main.")

        # featW2, gate attempt 1 -> must conflict.
        main_before = origin_main_log()
        print("\n[astraeus] gate featW2 attempt 1 ...")
        r2 = merge_gate("featW2")
        if r2.ok:
            print("[astraeus] WARNING: featW2 merged CLEANLY - the conflict did NOT fire; "
                  "the make-or-break was NOT tested. (Re-craft needed.)")
            return False
        print("\n[astraeus] (2) featW2 attempt 1 - CONFLICT detected")
        print(f"    git diff --diff-filter=U (unmerged files): {r2.conflicts}")
        print("    gate merge log:\n" + r2.log.strip())
        print(f"    merge aborted; origin main untouched at this point? "
              f"{origin_main_log() == main_before}")
        if not r2.conflicts:
            print("[astraeus] FAIL: featW2 rejected but NOT by conflict (red test):\n" + r2.log)
            return False

        # Materialize the markers in featW2's worker, then ONE handback.
        w2 = "astraeus_w2"
        conflicted = materialize_conflict(w2, "featW2")
        print("\n[astraeus] (3) materialized conflict files in the worker: " + str(conflicted))
        for f in conflicted:
            print(f"    --- /workspace/{f} WITH markers (exactly as handed to the Astra) ---")
            print(read_container_file(w2, "/workspace/" + f))

        msg = HANDBACK_MSG.format(files=", ".join(conflicted))
        print("[astraeus] (4) handback message sent to the featW2 Astra:\n" + msg)

        print("\n[astraeus] handing back to the SAME featW2 Astra (exactly once) ...")
        run_astra(astras["featW2"], msg)

        print("\n[astraeus] (5) Astra-resolved files + commit:")
        for f in conflicted:
            print(f"    --- /workspace/{f} after the Astra resolved it ---")
            print(read_container_file(w2, "/workspace/" + f))
        commits = dcmd(["exec", "-w", "/workspace", w2, "git", "log", "--oneline", "-4"], check=False).stdout
        print("    featW2 commits:\n" + commits)
        push_branch(w2, "featW2")

        # featW2, gate attempt 2 (final).
        print("[astraeus] gate featW2 attempt 2 (final) ...")
        r2b = merge_gate("featW2")
        print("\n[astraeus] (6) re-gate result:")
        if r2b.ok:
            print("    featW2 RESOLVED + merged. gate pytest (in-container):\n" + r2b.log.strip())
        else:
            print("    featW2 STILL FAILING after one handback - NEGATIVE FINDING.")
            print("    gate log:\n" + r2b.log.strip())
            print("    unresolved /workspace/calc.py:\n" + read_container_file(w2, "/workspace/calc.py"))
        result_ok = r2b.ok
    finally:
        for s in subtasks:
            dcmd(["rm", "-f", s["worker"]], check=False)
        print("[astraeus] removed worker containers")

    # (7) final proof. A correct conflict resolution must keep BOTH contributions:
    # checking only the merge commits + green pytest is too weak (a resolution that
    # drops one side AND its test would pass that). Verify both functions survive.
    log = origin_main_log()
    both_merges = ("merge featW1" in log) and ("merge featW2" in log)
    final_calc = origin_show("calc.py")
    has_add = "def add(" in final_calc
    has_mul = "def mul(" in final_calc
    print("\n[astraeus] (7) final origin main log (read via a container):\n" + log)
    print("\n[astraeus] final origin main:calc.py:\n" + final_calc)
    print(f"[astraeus] both contributions survived on main? add={has_add} mul={has_mul}")
    print("[astraeus] origin volume survived: " + volume_inspect_oneliner())

    ok = bool(result_ok and both_merges and has_add and has_mul)
    if result_ok and both_merges and not (has_add and has_mul):
        print("[astraeus] NEGATIVE FINDING: the merge landed but the conflict resolution "
              "DROPPED a contribution (add present=%s, mul present=%s) - Typhoon kept only "
              "one side instead of combining both." % (has_add, has_mul))
    print("\n[astraeus] STEP 2 " + ("PASS (real conflict resolved correctly + both landed)"
                                    if ok else "FAIL / NEGATIVE FINDING (conflict not resolved correctly)"))
    return ok


# --- Step 3: concurrency + deterministic stall ------------------------------

ASTRA_CAP_SECONDS = 300  # hard per-Astra wall-clock cap (production default)


def origin_branches():
    """Branch refs present on origin, read via a throwaway container."""
    return dcmd(["run", "--rm", "--network", "none", "-v", f"{ORIGIN_VOLUME}:/origin",
                 IMAGE, "git", "-C", "/origin", "branch"]).stdout.strip()


# Optional in-process event sink for live observers (e.g. the TUI). Default OFF, so a
# headless run is byte-identical; when set, record()/round/gate progress also push a
# (kind, id, payload) event here. An observer must never break a run, so emit() swallows.
_EMIT = None


def set_emit(fn):
    """Register (or clear, with None) the event sink: fn(kind, id, payload)."""
    global _EMIT
    _EMIT = fn


def emit(kind, id, payload=None):
    """Push one event to the sink if one is registered; never raises."""
    if _EMIT is not None:
        try:
            _EMIT(kind, id, payload)
        except Exception:  # noqa: BLE001 — an observer must never break a run
            pass


def _run_with_cap(subtasks, cap, work):
    """Run work(s, record) for each subtask in its OWN daemon thread, concurrently,
    under a shared wall-clock `cap`. A thread still alive at the cap is a stall: its
    subtask is FAILED and its container is rm -f'd (the lever — a Python thread can't
    be force-killed; killing the container unblocks any in-flight docker exec, and
    daemon=True lets the process exit even while the thread is still blocked).

    `work(s, record)` does the per-subtask semantic work and returns truthy on
    success; each subtask carries "branch" (its identifier) and "worker" (container).
    Returns (timeline, outcomes, start) where outcomes[branch] is "READY"/
    "FAILED_TIMEOUT"/"FAILED_ERROR".
    """
    timeline, lock, done, threads = [], threading.Lock(), {}, {}

    def record(branch, event):
        with lock:
            timeline.append((time.monotonic(), branch, event))
        emit("timeline", branch, event)

    def runner(s):
        b = s["branch"]
        record(b, "thread start")
        try:
            done[b] = bool(work(s, record))
        except Exception as e:  # noqa: BLE001 — a worker failure must not crash the run
            record(b, f"ERROR {type(e).__name__}: {e}")
            done[b] = False

    start = time.monotonic()
    for s in subtasks:
        t = threading.Thread(target=runner, args=(s,), daemon=True)  # Amendment 5: daemon
        threads[s["branch"]] = t
        t.start()

    deadline = start + cap
    for t in threads.values():
        t.join(timeout=max(0.0, deadline - time.monotonic()))

    outcomes = {}
    for s in subtasks:
        b = s["branch"]
        if threads[b].is_alive():
            record(b, f"TIMEOUT at cap={cap}s -> FAILED (container rm -f'd, thread abandoned)")
            dcmd(["rm", "-f", s["worker"]], check=False)
            outcomes[b] = "FAILED_TIMEOUT"
        else:
            outcomes[b] = "READY" if done.get(b) else "FAILED_ERROR"
    return timeline, outcomes, start


def run_parallel(subtasks, cap):
    """Phase 1 path: each subtask in its OWN isolated clone + branch, run concurrently
    under the cap, then its branch pushed. Unchanged behaviour — used by step3/
    step3_stall. Returns (timeline, outcomes, start)."""
    for s in subtasks:
        start_worker(s["worker"], s["branch"])

    def work(s, record):
        b = s["branch"]
        astra = make_astra(s["worker"], s.get("model"))
        record(b, "astra dispatch begin")
        run_astra(astra, s["instruction"])
        record(b, "astra dispatch end (committed)")
        push_branch(s["worker"], b)
        record(b, "pushed branch")
        return True

    return _run_with_cap(subtasks, cap, work)


def run_round(subtasks, cap, workspace_volume=WORKSPACE_VOLUME):
    """Phase 2 path: dispatch a round of subtasks concurrently on the SHARED tree.

    Every subtask in a round is file-disjoint (schedule() guarantees it), so their
    writes never collide. Workers do NOT commit — the orchestrator commits the tree
    after the round. Same wall-clock cap + container-kill stall lever as run_parallel.
    """
    for s in subtasks:
        start_shared_worker(s["worker"], workspace_volume=workspace_volume)

    def work(s, record):
        b = s["branch"]
        astra = make_astra(s["worker"], s.get("model"),
                           system_prompt=ASTRA_SHARED_SYSTEM_PROMPT, harness=s.get("harness", ""))
        record(b, "astra dispatch begin")
        run_astra(astra, s["instruction"])
        record(b, "astra dispatch end")
        return True

    return _run_with_cap(subtasks, cap, work)


def schedule(subtasks):
    """Group subtasks into ROUNDS so same-file work is sequenced, disjoint work runs
    in parallel. Two subtasks sharing any file land in different rounds; the
    orchestrator runs rounds in order, committing between them, so a later writer
    reads the earlier one's committed code — git never has to merge. Greedy first-fit,
    deterministic in input order. All-disjoint subtasks => a single round.
    """
    rounds, round_files = [], []
    for s in subtasks:
        files = {f.lower() for f in s["files"]}
        for i, used in enumerate(round_files):
            if used.isdisjoint(files):
                rounds[i].append(s)
                round_files[i] = used | files
                break
        else:
            rounds.append([s])
            round_files.append(files)
    return rounds


def _print_timeline(timeline, start, label):
    print(f"\n[astraeus] {label} - per-thread timeline (+seconds from start, interleaved):")
    for t, b, ev in sorted(timeline):
        print(f"    +{t - start:7.2f}s [{b}] {ev}")
    spans = {}
    for t, b, ev in timeline:
        if ev == "astra dispatch begin":
            spans.setdefault(b, [None, None])[0] = t
        elif ev.startswith("astra dispatch end"):
            spans.setdefault(b, [None, None])[1] = t
    ended = {b: s for b, s in spans.items() if s[0] is not None and s[1] is not None}
    if len(ended) == 2:
        (b1, s1), (b2, s2) = ended.items()
        overlap = min(s1[1], s2[1]) - max(s1[0], s2[0])
        if overlap > 0:
            print(f"[astraeus] TRUE OVERLAP: {b1} and {b2} were dispatching simultaneously "
                  f"for {overlap:.2f}s (not sequential).")
        else:
            print("[astraeus] NOTE: dispatch intervals did not overlap.")


SUBTASK_A = {"branch": "featW1", "worker": "astraeus_w1",
             "instruction": (
                 "Implement a function add(a, b) that returns a + b in /workspace/a.py. "
                 "Write a pytest test in /workspace/test_a.py that does `from a import add` "
                 "and asserts add(2, 3) == 5. Then commit.")}
SUBTASK_B = {"branch": "featW2", "worker": "astraeus_w2",
             "instruction": (
                 "Implement a function mul(a, b) that returns a * b in /workspace/b.py. "
                 "Write a pytest test in /workspace/test_b.py that does `from b import mul` "
                 "and asserts mul(2, 3) == 6. Then commit.")}


def _gate_ready(subtasks, outcomes):
    """Gate the READY branches sequentially (disjoint files => clean merges)."""
    landed, logs = [], {}
    for s in subtasks:
        b = s["branch"]
        if outcomes[b] != "READY":
            print(f"[astraeus] skipping gate for {b} (outcome={outcomes[b]})")
            continue
        print(f"[astraeus] gate {b} ...")
        r = merge_gate(b)
        logs[b] = r.log
        if r.ok:
            landed.append(b)
            print(f"[astraeus] {b} landed. gate pytest (in-container):\n" + r.log.strip())
        else:
            print(f"[astraeus] {b} REJECTED by gate:\n" + r.log)
    return landed, logs


def step3():
    """Part A — parallel happy path: two file-disjoint Astras run concurrently."""
    reset_origin_volume()
    print(f"[astraeus] seeded bare origin on volume {ORIGIN_VOLUME!r}")
    subtasks = [SUBTASK_A, SUBTASK_B]
    print("[astraeus] file-disjoint subtasks: featW1 -> a.py/test_a.py ; featW2 -> b.py/test_b.py")

    try:
        timeline, outcomes, start = run_parallel(subtasks, cap=ASTRA_CAP_SECONDS)
        _print_timeline(timeline, start, "PART A (parallel)")
        print(f"[astraeus] outcomes: {outcomes}")
        print("[astraeus] both branch refs on origin (concurrent-push safety):\n" + origin_branches())
        landed, _ = _gate_ready(subtasks, outcomes)
    finally:
        for s in subtasks:
            dcmd(["rm", "-f", s["worker"]], check=False)
        print("[astraeus] removed worker containers")

    log = origin_main_log()
    both = ("merge featW1" in log) and ("merge featW2" in log)
    print("\n[astraeus] final origin main log:\n" + log)
    print("[astraeus] origin volume survived: " + volume_inspect_oneliner())
    ok = both and set(landed) == {"featW1", "featW2"}
    print("\n[astraeus] STEP 3 PART A " + ("PASS (both landed, ran concurrently)" if ok else "FAIL"))
    return ok


def step3_stall(cap=75, sleep_seconds=600):
    """Part B — deterministic stall: one worker hangs (SleepyModel); the cap bounds
    it, the other branch still lands, the process exits cleanly (no 19-minute freeze).
    """
    reset_origin_volume()
    print(f"[astraeus] seeded bare origin on volume {ORIGIN_VOLUME!r}")
    # featW1 = real Typhoon worker (must land); featW2 = stalled stub (must time out).
    stalled = dict(SUBTASK_B, model=SleepyModel(sleep_seconds=sleep_seconds))
    subtasks = [SUBTASK_A, stalled]
    print(f"[astraeus] featW1 = real Astra ; featW2 = SleepyModel(sleep={sleep_seconds}s) ; cap={cap}s")

    t0 = time.monotonic()
    try:
        timeline, outcomes, start = run_parallel(subtasks, cap=cap)
        _print_timeline(timeline, start, "PART B (stall)")
        print(f"[astraeus] outcomes: {outcomes}")
        landed, _ = _gate_ready(subtasks, outcomes)
    finally:
        for s in subtasks:
            dcmd(["rm", "-f", s["worker"]], check=False)
        print("[astraeus] removed worker containers")

    elapsed = time.monotonic() - t0
    log = origin_main_log()
    print("\n[astraeus] final origin main log:\n" + log)
    print("[astraeus] origin volume survived: " + volume_inspect_oneliner())
    print(f"[astraeus] total wall time: {elapsed:.1f}s (cap={cap}s; the stalled "
          f"SleepyModel would have run {sleep_seconds}s - proof the cap bounds the hang)")
    ok = (outcomes.get("featW2") == "FAILED_TIMEOUT"
          and "featW1" in landed and "merge featW1" in log
          and elapsed < sleep_seconds)
    print("\n[astraeus] STEP 3 PART B " + (
        "PASS (stalled branch FAILED at the cap; other branch landed; clean exit)"
        if ok else "FAIL"))
    return ok


# --- Phase 2: the real end-to-end loop (decompose -> collaborate -> gate) -----

DEFAULT_TASK = ("Write a function add(a, b) that returns a + b with a pytest test, "
                "and a function mul(a, b) that returns a * b with a pytest test.")

# Red-test handback (NOT a conflict handback — conflicts cannot occur in the one
# integrated tree). The owning worker reads its own pytest failure and fixes its file.
RED_TEST_HANDBACK_MSG = (
    "The test suite is failing and your file(s) {files} are involved. Here is the "
    "pytest output:\n\n{log}\n\n"
    "FIRST, in one or two sentences, reflect on the failure: what the test expected, "
    "what your code actually did, and what you will change. THEN fix your file(s) so the "
    "tests pass. Edit ONLY {files}. Do NOT run git. When the logic is correct, stop — "
    "the orchestrator will re-run the tests."
)


def _build_harness(s, plan):
    """Per-worker shared-tree context: what it owns + who its siblings are."""
    others = [p for p in plan if p["id"] != s["id"]]
    siblings = "; ".join(f"{p['id']} -> {p['files']}" for p in others) or "(none)"
    return ASTRA_HARNESS_TEMPLATE.format(owned=", ".join(s["files"]), siblings=siblings)


def _owner_for_failure(log, subtasks, failures=None):
    """Best-effort: the first subtask that owns a failing file. PREFERS the gate's
    STRUCTURED `failures` (file paths parsed from the pytest summary) — a precise signal —
    and falls back to scanning the raw `log` for whole `*.py` path tokens. Both match on
    full token / basename (never substring), so `a.py` never maps to `aa.py`."""
    if failures:
        names = set(failures)
        basenames = {f.rsplit("/", 1)[-1] for f in failures}
        for s in subtasks:
            for f in s["files"]:
                if f in names or f.rsplit("/", 1)[-1] in basenames:
                    return s
    tokens = set(re.findall(r"[\w./-]+\.py", log))
    basenames = {t.rsplit("/", 1)[-1] for t in tokens}
    for s in subtasks:
        for f in s["files"]:
            if f in tokens or f.rsplit("/", 1)[-1] in basenames:
                return s
    return None


def _extract_reflection(state, limit=300):
    """Best-effort: the worker's last assistant message (its stated reflection), trimmed.
    Never raises — a missing/odd state just yields ''."""
    try:
        messages = state.get("messages", []) if isinstance(state, dict) else []
        for m in reversed(messages):
            content = m.get("content") if isinstance(m, dict) else getattr(m, "content", None)
            if isinstance(content, list):  # some providers return content as parts
                content = " ".join(
                    str(p.get("text", p)) if isinstance(p, dict) else str(p) for p in content)
            if content and str(content).strip():
                return str(content).strip().replace("\n", " ")[:limit]
    except Exception:  # noqa: BLE001 — reflection capture must never break a run
        pass
    return ""


def _repair(owner, plan, log, cap=ASTRA_CAP_SECONDS, workspace_volume=WORKSPACE_VOLUME):
    """Spin a fresh shared worker for the owning subtask, hand back its pytest failure so
    it reflects then fixes its own file in the shared tree; the orchestrator commits.

    Runs under the same wall-clock `cap` + container-kill stall-lever as a round worker
    (via _run_with_cap), so a hung repair can NOT freeze the orchestrator. A repair that
    times out or errors has its partial changes discarded before the commit. Returns the
    worker's reflection text (best-effort, '' if unavailable / timed out)."""
    start_shared_worker(owner["worker"], workspace_volume=workspace_volume)
    captured = {"reflection": ""}
    outcomes = {}
    harness = _build_harness(owner, plan)
    msg = RED_TEST_HANDBACK_MSG.format(files=", ".join(owner["files"]), log=log[-4000:])

    def work(s, record):
        astra = make_astra(s["worker"], system_prompt=ASTRA_SHARED_SYSTEM_PROMPT, harness=harness)
        captured["reflection"] = _extract_reflection(run_astra(astra, msg))
        return True

    try:
        _, outcomes, _ = _run_with_cap([owner], cap, work)
    finally:
        if outcomes.get(owner["branch"]) != "READY":
            # timed out or errored -> drop the half-done repair so it isn't committed
            _discard_worker_changes(owner, workspace_volume=workspace_volume)
        commit_workspace(f"astraeus: repair {owner['id']}", workspace_volume=workspace_volume)
        dcmd(["rm", "-f", owner["worker"]], check=False)
    return captured["reflection"]


def _gate_with_repair(subtasks, plan, candidate="candidate", max_attempts=2,
                      cap=ASTRA_CAP_SECONDS, workspace_volume=WORKSPACE_VOLUME,
                      progress=None, on_repair=None):
    """Gate the integrated tree (already pushed as `candidate`); on a RED TEST hand it
    back to the owning worker, bounded by max_attempts. Conflicts cannot occur (one
    integrated tree), so the only failure mode is a red test — which Typhoon can
    self-repair. Returns (landed, attempts, log, gate_state) where gate_state is one
    of "landed", "retry_exhausted", "repair_no_owner", "conflict" — the explicit
    terminal state of the loop, so the transcript records WHY it stopped. `progress`,
    if given, is called (attempts, log, interim_state) after each gate run; `on_repair`,
    if given, is called (owner_id, attempt, reflection) after each handback.
    """
    r = merge_gate(candidate)
    attempts = 1
    gate_state = None
    if progress:
        progress(attempts, r.log, "landed" if r.ok else "gating")
    while (not r.ok) and (not r.conflicts) and attempts < max_attempts:
        owner = _owner_for_failure(r.log, subtasks, failures=r.failures)
        if owner is None:
            print("[astraeus] gate red but no owning subtask found in the log; stopping retry")
            gate_state = "repair_no_owner"
            break
        print(f"[astraeus] gate red -> handback to {owner['id']} "
              f"(repair {attempts}/{max_attempts - 1})")
        emit("gate", owner["id"], "handback")
        reflection = _repair(owner, plan, r.log, cap=cap, workspace_volume=workspace_volume)
        if on_repair:
            on_repair(owner["id"], attempts, reflection)
        push_candidate(candidate=candidate, workspace_volume=workspace_volume)
        r = merge_gate(candidate)
        attempts += 1
        if progress:
            progress(attempts, r.log, "landed" if r.ok else "gating")
    if gate_state is None:
        gate_state = "landed" if r.ok else ("conflict" if r.conflicts else "retry_exhausted")
    if progress:
        progress(attempts, r.log, gate_state)
    return r.ok, attempts, r.log, gate_state


def _build_result(task, plan, rounds, outcomes, timeline, t0, landed=False,
                  attempts=0, gate_log="", gate_state="running", origin_log="", repairs=None):
    """Assemble the run.json result dict from current run state. Used for the final
    transcript AND for live partial re-flushes during a run (defaults describe a run
    still in progress: gate_state='running')."""
    return {
        "task": task,
        "plan": plan,
        "rounds": [[s["id"] for s in r] for r in rounds],
        "outcomes": outcomes,
        "gate_attempts": attempts,
        "landed": landed,
        "gate_state": gate_state,
        "repairs": repairs or [],
        "gate_log": gate_log,
        "origin_log": origin_log,
        "timeline": [{"t": round(t - t0, 3), "id": b, "event": e}
                     for (t, b, e) in sorted(timeline)],
    }


def flush_transcript(result, workspace_volume=WORKSPACE_VOLUME):
    """Write run.json to the shared tree WITHOUT committing — a live progress snapshot
    a TUI can tail. The final write_transcript() commits the permanent record."""
    seed_workspace_file(".astraeus/run.json", json.dumps(result, indent=2),
                        workspace_volume=workspace_volume)


def write_transcript(result, workspace_volume=WORKSPACE_VOLUME):
    """Persist the structured run record to /workspace/.astraeus/run.json (kept on the
    volume for post-run inspection — the Phase 2 proof artifact)."""
    seed_workspace_file(".astraeus/run.json", json.dumps(result, indent=2),
                        workspace_volume=workspace_volume)
    commit_workspace("astraeus: run transcript", workspace_volume=workspace_volume)


def run_task(task, plan=None, max_attempts=2, cap=ASTRA_CAP_SECONDS,
             workspace_volume=WORKSPACE_VOLUME):
    """Phase 2 end-to-end loop: decompose -> schedule -> collaborate in ONE shared
    tree -> gate the integrated result -> land on main -> transcript. Returns a
    structured result dict. Pass `plan` to skip decompose (used by the shared-FS demo).
    No human runs git; no API key enters a container; every sandbox is --network none.
    """
    if not _docker_available():
        raise DockerError("docker daemon not available — run_task needs a live daemon")

    reset_origin_volume()
    reset_workspace_volume(workspace_volume=workspace_volume)
    print(f"[astraeus] seeded bare origin {ORIGIN_VOLUME!r} + shared workspace {workspace_volume!r}")

    plan = plan or decompose(task)
    print(f"[astraeus] plan: {len(plan)} subtask(s): "
          + ", ".join(f"{p['id']}({','.join(p['files'])})" for p in plan))

    # Map plan -> runnable subtasks (one container each; "branch" = the identifier).
    subtasks = []
    for i, p in enumerate(plan):
        subtasks.append({
            "id": p["id"], "branch": p["id"], "worker": f"astraeus_w{i + 1}",
            "files": p["files"], "instruction": p["instruction"],
        })
    for s in subtasks:
        s["harness"] = _build_harness(s, plan)

    # Seed the shared context every worker can read, then schedule into rounds.
    seed_workspace_file(".astraeus/task.md", task, workspace_volume=workspace_volume)
    seed_workspace_file(".astraeus/plan.json", json.dumps(plan, indent=2),
                        workspace_volume=workspace_volume)
    commit_workspace("astraeus: seed task + plan", workspace_volume=workspace_volume)

    rounds = schedule(subtasks)
    print("[astraeus] schedule: " + " | ".join(
        "+".join(s["id"] for s in r) for r in rounds))

    timeline_all, outcomes_all, repairs_all, t0 = [], {}, [], time.monotonic()
    try:
        for rn, rnd in enumerate(rounds):
            print(f"[astraeus] round {rn + 1}/{len(rounds)}: {[s['id'] for s in rnd]}")
            emit("round", str(rn + 1),
                 {"round": rn + 1, "total": len(rounds), "ids": [s["id"] for s in rnd]})
            timeline, outcomes, _ = run_round(rnd, cap, workspace_volume=workspace_volume)
            timeline_all.extend(timeline)
            outcomes_all.update(outcomes)
            # Only completed, COMPILING work is committed. Drop a worker's files when it
            # (a) stalled/errored (partial work), or (b) finished READY but left a file that
            # does NOT compile — a syntax error would crash pytest collection for the WHOLE
            # suite at the gate, masking every sibling. Both run BEFORE the round commit, so
            # the working-tree discard (checkout+clean) removes the bad files cleanly and
            # only importable code is ever committed toward the candidate.
            for s in rnd:
                if outcomes.get(s["branch"]) != "READY":
                    _discard_worker_changes(s, workspace_volume=workspace_volume)
                elif not _syntax_check(s["files"], workspace_volume=workspace_volume):
                    print(f"[astraeus] syntax guardrail: {s['id']} left non-compiling file(s) -> dropping")
                    outcomes[s["branch"]] = outcomes_all[s["branch"]] = "FAILED_ERROR"
                    _discard_worker_changes(s, workspace_volume=workspace_volume)
            # Code-enforce file ownership: drop any out-of-lane stray files before the commit.
            stray = _enforce_ownership(rnd, workspace_volume=workspace_volume)
            if stray:
                print(f"[astraeus] ownership guard dropped out-of-scope path(s): {stray}")
            commit_workspace(f"astraeus: round {rn + 1}", workspace_volume=workspace_volume)
            # Live snapshot for the TUI tail (written to the tree, committed with the next round).
            flush_transcript(_build_result(task, plan, rounds, outcomes_all, timeline_all, t0,
                                           repairs=repairs_all),
                             workspace_volume=workspace_volume)
            for s in rnd:
                dcmd(["rm", "-f", s["worker"]], check=False)
    except Exception:
        for s in subtasks:
            dcmd(["rm", "-f", s["worker"]], check=False)
        raise

    # Gate the integrated tree (pushed as a per-run unique candidate ref) with bounded
    # red-test repair. A unique ref means overlapping runs never collide on `candidate`.
    candidate = f"candidate-{uuid.uuid4().hex[:8]}"

    def _progress(attempts, gate_log, gate_state):
        # Live snapshot during gating so the TUI tail sees repair attempts as they happen.
        flush_transcript(_build_result(task, plan, rounds, outcomes_all, timeline_all, t0,
                                       landed=(gate_state == "landed"), attempts=attempts,
                                       gate_log=gate_log, gate_state=gate_state,
                                       repairs=repairs_all),
                         workspace_volume=workspace_volume)

    def _on_repair(owner_id, attempt, reflection):
        # Reflexion: record the worker's self-reflection for each bounded repair attempt.
        repairs_all.append({"owner_id": owner_id, "attempt": attempt, "reflection": reflection})

    try:
        push_candidate(candidate=candidate, workspace_volume=workspace_volume)
        landed, attempts, gate_log, gate_state = _gate_with_repair(
            subtasks, plan, candidate=candidate, max_attempts=max_attempts, cap=cap,
            workspace_volume=workspace_volume, progress=_progress, on_repair=_on_repair)
        origin_log = origin_main_log()
        result = _build_result(task, plan, rounds, outcomes_all, timeline_all, t0,
                               landed=landed, attempts=attempts, gate_log=gate_log,
                               gate_state=gate_state, origin_log=origin_log, repairs=repairs_all)
        write_transcript(result, workspace_volume=workspace_volume)
    except Exception as e:  # noqa: BLE001 — durability: never lose the run record on a gate/docker crash
        result = _build_result(task, plan, rounds, outcomes_all, timeline_all, t0,
                               landed=False, gate_state="error",
                               gate_log=f"{type(e).__name__}: {e}", repairs=repairs_all)
        flush_transcript(result, workspace_volume=workspace_volume)
        emit("done", "run", {"landed": False, "gate_state": "error", "attempts": 0})
        raise
    emit("done", "run", {"landed": landed, "gate_state": gate_state, "attempts": attempts})
    print(f"[astraeus] run_task done: landed={landed} gate_state={gate_state} gate_attempts={attempts}")
    print("[astraeus] origin main log:\n" + origin_log)
    return result


def step_shared_demo(cap=ASTRA_CAP_SECONDS):
    """Capstone: two workers COLLABORATE on one shared file via the central FS. featA
    creates greet.py + its test; featB (sequenced after) ADDS to the SAME files. Proof:
    both functions land on main with no conflict markers — no git merge ever happened.
    """
    plan = [
        {"id": "featA", "files": ["greet.py", "test_greet.py"],
         "instruction": (
             "Create /workspace/greet.py with a function hello() that returns the "
             "string 'hello'. Write a pytest test in /workspace/test_greet.py that does "
             "`from greet import hello` and asserts hello() == 'hello'. Make "
             "`python -m pytest -q test_greet.py` pass.")},
        {"id": "featB", "files": ["greet.py", "test_greet.py"],
         "instruction": (
             "/workspace/greet.py already contains hello(). ADD a function bye() that "
             "returns the string 'bye' to the SAME file WITHOUT removing hello(). Also "
             "ADD to /workspace/test_greet.py a test that does `from greet import bye` "
             "and asserts bye() == 'bye', keeping the existing test. Make "
             "`python -m pytest -q test_greet.py` pass.")},
    ]
    print("[astraeus] SHARED-FS DEMO: featA and featB collaborate on greet.py (sequenced)")
    result = run_task("Collaborative greet.py: hello() and bye() in one shared file",
                      plan=plan, cap=cap)

    greet = origin_show("greet.py")
    has_hello, has_bye = "def hello(" in greet, "def bye(" in greet
    markers = any(m in greet for m in ("<<<<<<<", "=======", ">>>>>>>"))
    print("\n[astraeus] final origin main:greet.py:\n" + greet)
    print(f"[astraeus] both functions present? hello={has_hello} bye={has_bye} ; "
          f"conflict markers present? {markers}")
    ok = bool(result["landed"] and has_hello and has_bye and not markers)
    print("\n[astraeus] SHARED-FS DEMO " + (
        "PASS (two sandboxes collaborated on one file; no merge needed)" if ok else "FAIL"))
    return ok


if __name__ == "__main__":
    import sys

    load_dotenv_exports()  # TYPHOON_* from .env into os.environ, before any model build
    if "--stall" in sys.argv:
        step3_stall()
    elif "--shared-demo" in sys.argv:
        step_shared_demo()
    elif "--run" in sys.argv:
        i = sys.argv.index("--run")
        task = sys.argv[i + 1] if i + 1 < len(sys.argv) else DEFAULT_TASK
        run_task(task)
    else:
        step3()
