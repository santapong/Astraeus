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


if __name__ == "__main__":
    load_dotenv_exports()  # TYPHOON_* from .env into os.environ, before any model build
    step1()
