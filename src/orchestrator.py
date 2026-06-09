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

from src.docker_backend import IMAGE, ORIGIN_VOLUME, dcmd
from src.env import load_dotenv_exports
from src.merge_gate import merge_gate
from src.worker import make_astra, run_astra

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
        "printf '__pycache__/\\n*.pyc\\n' > .gitignore && "
        "git add -A && git commit -q -m init && git push -q origin HEAD:main"
    )
    dcmd(["run", "--rm", "--network", "none", "-v", f"{ORIGIN_VOLUME}:/origin", IMAGE, "sh", "-c", seed])


def start_worker(name, branch):
    """Run a fresh worker container (no network) and clone+branch it for the Astra."""
    dcmd(["rm", "-f", name], check=False)
    dcmd(["run", "-d", "--name", name, "--network", "none",
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
    "Do not touch any other file."
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


if __name__ == "__main__":
    load_dotenv_exports()  # TYPHOON_* from .env into os.environ, before any model build
    step2()
