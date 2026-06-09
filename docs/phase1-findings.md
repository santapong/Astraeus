# Phase 1 — Findings

What running Astraeus Phase 1 (Steps 0–3 + the pre-registered handback trial) on
Typhoon taught us. Every item was learned by *running the system live*. This is the
seed for the Phase 2 spec. Companion to [phase0-findings.md](phase0-findings.md).

## VALIDATED — what running it proved

- **`BaseSandbox` → `docker exec` mapping works exactly as the source predicted.** A
  container backend needs only four abstract members (`execute`, `upload_files`,
  `download_files`, `id`); `BaseSandbox` derives every file tool (`read`/`write`/
  `edit`/`ls`/`grep`/`glob`) from them. One `DockerSandbox` instance routes all of
  the agent's file + shell ops into its container.

- **Prompt steering held Typhoon to `/workspace`.** `BaseSandbox` has no
  `virtual_mode`; paths are literal in the container. A one-line system-prompt rule
  ("use absolute paths under /workspace") was enough across every step — the
  pre-authorized path-normalization fallback **never had to fire**.

- **The host never executed agent-written code.** Worker code runs in the worker
  container; the gate runs `pytest` in a *separate* ephemeral gate container. Proven
  by the gate's in-container pytest output.

- **`--network none` throughout at zero cost.** Workers and gate ran with no network;
  git talks to the local `/origin` volume and model calls happen on the host, so
  nothing needed the network.

- **No container ever held the API key (asserted).** Model calls run in the host
  process; containers are started without `-e TYPHOON_API_KEY`. `docker exec … env`
  → `NO_TYPHOON_KEY_IN_CONTAINER`. The Phase-0 `inherit_env` leak is dead by
  construction.

- **Bare origin on a named volume retired worktrees.** A bare repo on the
  `astraeus_origin` volume (mounted `/origin`) removed all host↔container path
  translation. Concurrent pushes are safe — after a parallel run both `featW1` and
  `featW2` refs were present on origin.

- **Orchestrator-owns-plumbing / agent-owns-semantics split.** The orchestrator does
  every git plumbing op (clone, branch, push, fetch, the merge that *materializes*
  conflict markers, the gate's merge-to-main) via list-form `docker exec`; the agent
  does only the semantic work (write/edit + commit; resolve markers + commit). Keeps
  the model's surface to what Phase 0 proved it can do.

- **Hangs are bounded by construction.** Each Astra runs in its own daemon thread
  under a wall-clock cap; a stalled worker is FAILED at the cap and its container
  `docker rm -f`'d (the lever — a Python thread can't be force-killed). Live: a
  `SleepyModel(600s)` stall was capped at **75s**, total wall **92.6s**, the other
  branch still landed, and the process exited cleanly. The Phase-0 19-minute freeze
  is impossible by construction, not by assertion.

## ROLE BOUNDARY — the headline

**`typhoon-v2.5-30b-a3b` cannot resolve a merge conflict — not even add/add, not even
with an explicit worked example.** Tested live across **three independent attempts,
three distinct failure modes**:

1. **Lossy resolution** — kept only origin/main's side and silently dropped its own
   contribution *and that contribution's test* (so the now-incomplete test suite
   stayed green and a lossy merge landed).
2. **Markers left uncommitted** — never completed the merge; the re-gate hit the same
   conflict and correctly refused to merge.
3. **Edit-loop crash (pre-registered trial, WITH the worked example)** — switched to
   targeted `edit_file` marker removals, kept building `old_string` with the wrong
   whitespace (`String not found in file`), looped re-reading/retrying the same
   broken pattern, and the agent error-ed out before producing a resolution.

The pre-registered trial (one attempt, fixed bar, honesty rules held) was a **FAIL**:
origin `main` ended with `def add(` only, `def mul(` absent, zero markers — featW2
honestly did not land. **The worked example did not help; the finding is FINAL for
this model.**

**Capability map (this model):** tool calls ✅ · scoped writes ✅ · JSON decompose ✅
· self-repair from its own test logs ✅ · **conflict resolution ❌ (even add/add, even
with a worked example)**. Conflict resolution is a distinct ROLE that this worker
model cannot fill; the handback worked-example stays in the message permanently for a
stronger model later.

## GAPS + PHASE 2 DESIGN INPUTS — found only by running

1. **A test-only gate passes lossy resolutions.** Deleting a contribution *together
   with its test* stays green. Fix: the gate should run the **UNION of both branches'
   tests**. Interim cover (already in place): the orchestrator content-checks that
   both `def add(` and `def mul(` survive on main.

2. **Pure add/add conflicts are mechanically resolvable** (git union-merge / keep-both)
   — no model is needed for that class. A deterministic resolver should handle them;
   reserve the model only for conflicts that require real judgment.

3. **Conflict-resolver is a distinct ROLE** for a stronger model when one is available.
   Until then, conflicts → FAILED honestly (the gate refuses; main stays consistent).

4. **MSYS path mangling is the 4th member of the "shell lies to you" family** (after
   cmd.exe single-quotes, ignored exit codes, unbounded timeouts). Git-bash rewrote
   `/origin` → `C:/Program Files/Git/origin` in a *manual* proof command. Production is
   immune (list-form `subprocess`, no shell); manual commands are not — use
   `MSYS_NO_PATHCONV=1`.

5. **Docker Desktop fragility.** The daemon exited **three times** mid-session (the
   Docker Desktop process fully quit), each a hard prerequisite failure. A mid-run
   daemon death is — by design — a loud, unhandled failure (list-form `dcmd` raises
   `DockerError` on the first failed call) rather than a silent corruption. Phase 2
   should treat daemon liveness as an explicit precondition.

6. **Content-level assertions beat test-green assertions.** The Step-2 false positive
   (merge commits present + pytest green, yet `mul` silently dropped) is the lesson:
   verify the *artifact* (both functions on main), not just that some tests passed.
