# Phase 2 — Design & Status

Phase 2 turns Astraeus from "two isolated workers integrated through git" into a
**central collaborative workspace**: one shared filesystem every sandbox mounts, an
N-worker loop driven by `decompose`, orchestrator-sequenced edits so the workers can
share files, bounded self-repair, and a persisted run transcript. Companion to
[phase0-findings.md](phase0-findings.md) + [phase1-findings.md](phase1-findings.md).

> **Honesty note.** Unlike Phase 0/1 (every item learned by running live), the items
> below split into **VERIFIED** (unit/logic tests that ran green in this build) and
> **PENDING LIVE** (docker-gated tests + the model-driven `run_task`/`--shared-demo`
> runs), which require a host with the Docker daemon **and** Typhoon credentials —
> neither was available in the environment that wrote this code. The design holds the
> Phase 1 honesty rules; the live numbers are not claimed until a run produces them.

## What Phase 2 adds

- **A central shared workspace.** A new docker volume `astraeus_workspace` is a live
  git checkout of `main`, mounted at `/workspace` in **every** worker. All Astra read
  and write the one tree, so a worker can build on another's code — the "central file
  system all sandboxes interact with". The bare `astraeus_origin` volume is kept for
  history and as the published `main`.

- **The conflict class is designed out, not handed to the model.** Phase 1 proved
  (FINAL) that `typhoon-v2.5-30b-a3b` cannot resolve a git merge conflict. Phase 2
  therefore never produces one: `schedule()` groups subtasks into **rounds** by file
  overlap — file-disjoint subtasks run in parallel; any two that share a file are put
  in **different rounds and run one-after-another** on the live tree, the orchestrator
  committing between rounds, so a later writer does read-modify-write on the earlier
  one's committed code. There are no divergent branches to 3-way-merge. The gate's
  only failure mode is a **red test**, which Phase 0 proved the model *can* self-repair.

- **Orchestrator owns ALL git (strengthened).** In one shared `.git`, concurrent agent
  commits would corrupt the index, so workers run **no git at all** — they only write
  their assigned files; the orchestrator commits after each round (`commit_workspace`).
  This sharpens the Phase 1 role split (agent = semantics, orchestrator = plumbing).

- **The gate stays reproducible.** `merge_gate` is reused unchanged: the integrated
  tree is pushed to origin as a single `candidate` branch, and the gate clones origin
  into a **fresh** container and runs the **full** suite there. It never mounts
  `astraeus_workspace`, so shared scratch (`/workspace/.astraeus/`) and any half-written
  intermediate state cannot influence the verdict (closes phase1 GAP #1/#6 — the gate
  now naturally runs the UNION of every worker's tests).

- **Real end-to-end loop.** `run_task(task)` = `decompose` → `schedule` → collaborate
  in the shared tree (rounds) → push `candidate` → gate with bounded red-test repair →
  land on `main` → write transcript. `decompose` is generalized from "exactly two,
  file-disjoint" to **2..MAX_WORKERS** subtasks that **may** share files.

- **Harness-aware Astra + transcript.** Each worker's prompt gains a context block
  naming the file(s) it owns, its siblings, and the read-only `/workspace/.astraeus/`
  (the task + plan). Every run persists `/workspace/.astraeus/run.json` (plan, rounds,
  per-worker outcomes, gate attempts, timeline) for post-run inspection.

## VERIFIED (unit/logic tests, ran green: `34 passed, 6 skipped`)

- **decompose contract** (`tests/test_decompose.py`): accepts 2–4 subtasks, unique ids,
  shared files allowed; rejects <2, >MAX_WORKERS, duplicate ids, missing/empty fields;
  tolerant JSON extraction (fences, surrounding prose, `]` inside strings).
- **scheduling** (`tests/test_schedule.py`): all-disjoint → one round; shared file →
  two sequenced rounds; within any round all file-sets are pairwise disjoint;
  case-insensitive overlap.
- **cap / stall lever** (`tests/test_run_with_cap.py`): fast workers → READY; a worker
  exceeding the wall-clock cap → FAILED_TIMEOUT with its container `rm -f`'d; a raising
  worker → FAILED_ERROR (never crashes the run). Runs in-process, no docker.
- **bounded repair** (`tests/test_gate_repair.py`): green lands with zero handbacks;
  one red → exactly one handback then green; persistent red → FAILED after the cap; a
  **conflict is NEVER handed back** (honours the Phase 1 FINAL finding).
- **run_task wiring + transcript + harness** (`tests/test_run_task.py`): decompose is
  called with the task; disjoint → one round, shared → two sequenced rounds; task/plan
  seeded; transcript persisted with the timeline; the shared system prompt carries the
  harness block.

## PENDING LIVE (written, needs Docker + Typhoon to execute)

- **docker-gated plumbing** (`tests/test_workspace_fs.py`, `tests/test_shared_dispatch.py`):
  seed/show/commit/push on the shared volume; two workers reading each other's files in
  the one shared tree. Skip cleanly without a daemon.
- **`python -m src.orchestrator --run "<task>"`**: the full model-driven loop landing
  both functions on `main` with a `run.json` transcript.
- **`python -m src.orchestrator --shared-demo`**: the capstone — featA writes
  `greet.py:hello()`, featB (sequenced) adds `bye()` to the **same** file; expected
  result is both functions on `main` with **no conflict markers** and no merge.

## DESIGN INPUTS FOR PHASE 3 (anticipated, to confirm by running)

1. **Sequencing reliability on a weak model.** Read-modify-write on a shared file is
   reinforced in the harness; if a sequenced worker still drops prior work, the gate's
   full-suite run should catch it (the earlier round's test fails) and bounded repair
   hands the log back. Whether one repair is enough is an empirical question.
2. **Owner mapping for repair is heuristic** (first subtask whose filename appears in
   the red log). Good enough for flat layouts; a structured pytest report would be
   sharper.
3. **`astraeus_workspace` is reset per run** (like the origin) for reproducibility;
   cross-run memory/persistence remains a Phase 2/3 "cognition" question, deliberately
   not built here.
