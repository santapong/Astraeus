# CLAUDE.md — Astraeus (Phase 0)

> **STATUS: Phase 2 IMPLEMENTED (2026-06).** Phase 0 (`v0.1.0-phase0`) and Phase 1
> (`v0.2.0-phase1`) are sealed and historical — do **NOT** re-build them; the Phase 0
> binding spec below is historical. Phase 2 (central shared `/workspace` volume across
> all sandboxes, N-worker `run_task` loop on `decompose`, orchestrator-sequenced
> same-file edits so git never merges, bounded red-test repair, harness-aware Astra,
> JSON transcript) is implemented on this branch: orchestration logic unit-tested
> (`30 passed`); docker-gated + live model runs pending a Docker+Typhoon host.
> Findings: [docs/phase0-findings.md](docs/phase0-findings.md) +
> [docs/phase1-findings.md](docs/phase1-findings.md) +
> [docs/phase2-findings.md](docs/phase2-findings.md).

## What Astraeus is
A multi-agent system where an orchestrator (**Astraeus**) plans a task, splits it among worker agents (**the Astra** — the stars), and lands their work on `main` through an automated quality gate — **with no human touching git.**

This is **Phase 0**: a walking skeleton. Build **only** what is described here. Nothing else exists yet.

## Two repos — do not confuse them
This project involves two separate git repositories:

1. **This repo (Astraeus source).** The tool you are building: orchestrator, workers, merge gate, prompts, tests. This is what lives on GitHub. **You build and version this one.**
2. **The work repo.** A *separate* repo that Astraeus operates on — where worker branches, worktrees, and merges happen. For Phase 0 this is a throwaway **local** repo created at runtime (no GitHub push yet).

Never put worktrees or agent-generated task code inside this source repo. They live in the work repo.

## Prime constraint — read before any code
**Do not over-build.** This is the most important rule in this file.
- Build **Step 1 before Step 2** (see Build Sequence). Each step must pass before the next. **Commit between steps.**
- **Stop and report after each step.** Do not start the next step until told to continue.
- **No** sandboxes, Docker, Kubernetes, or E2B (Phase 1).
- **No** config systems, plugin layers, abstractions "for later," or flexibility knobs. Hardcoded and opinionated is correct now.
- **No** frontend, dashboard, web server, or UI.
- Do **not** add any dependency not listed in the stack below without stopping to ask. Declared deps: `deepagents`, `langchain-openai`, `pytest`.
- If a requirement is ambiguous, pick the simplest reading that lets the next step run, and note the assumption in a comment.

## Tech stack — use exactly this
- **Language:** Python 3.11+
- **Agent harness:** `deepagents` (latest). Built on LangGraph; provides sub-agents (the `task` tool), shell/filesystem backends, and the runtime. Do not hand-roll an agent loop.
- **Runtime model:** **Typhoon** (`typhoon-v2.5-30b-a3b-instruct`) via its OpenAI-compatible API, built as a `langchain_openai.ChatOpenAI` instance and passed into `create_deep_agent(model=...)`. Requires `TYPHOON_BASE_URL` + `TYPHOON_API_KEY` (loaded from `.env`). This powers Astraeus and the Astra **at runtime** — separate from the Claude Code instance building this.
- **Version control:** `git`, using **git worktrees** (one per worker branch) — inside the *work repo*.
- **Shell execution:** deepagents' local shell backend (`execute`), scoped per worktree. No remote or sandboxed execution.
- **Tests:** `pytest`.
- **Env/deps:** `uv` (preferred) or `venv` + `pip`.

> deepagents moves fast. Confirm current API signatures (`create_deep_agent`, backends, sub-agent tools) at https://docs.langchain.com/oss/python/deepagents/overview before wiring. The two functions you write do not depend on that.

## This repo's layout (Astraeus source)
```
astraeus/
├── CLAUDE.md
├── src/
│   ├── orchestrator.py   # Astraeus: plan, dispatch, integrate
│   ├── worker.py         # an Astra: implement one subtask
│   └── merge_gate.py     # you implement this
├── prompts/
│   └── decompose.md      # you write this
└── tests/
```
The work repo is created and managed at runtime, elsewhere on disk — not here.

## The two pieces you implement
Everything else is deepagents + git.

### 1. `merge_gate(branch)` (~50 lines)
```python
def merge_gate(branch, test_cmd="pytest -q"):
    wt = worktree_for(branch)                      # in the WORK repo
    log(run(f"git -C {wt} diff main..{branch}"))   # sanity, log only
    tests = run(test_cmd, cwd=wt)
    if tests.exit_code != 0:
        return MergeResult(ok=False, log=tests.output)   # hand back to the Astra
    run("git checkout main")
    run(f"git merge --no-ff {branch} -m 'merge {branch}'")
    return MergeResult(ok=True)
```

### 2. `prompts/decompose.md`
Astraeus splits one task into **exactly two file-disjoint subtasks** (no shared files). Emit strict JSON:
```json
[{"branch":"featW1","files":["src/a.py","tests/test_a.py"],"instruction":"..."},
 {"branch":"featW2","files":["src/b.py","tests/test_b.py"],"instruction":"..."}]
```

## Control flow (Astraeus)
1. Decompose the task → 2 file-disjoint subtasks.
2. Dispatch A → an Astra on `featW1`; B → an Astra on `featW2`.
3. Each Astra implements in its worktree, writes its test, commits on its branch.
4. For each branch → `merge_gate(branch)`: `ok` → merge; not ok → return the log to that Astra **once** → it fixes and recommits → re-run the gate **once** → still failing → stop and report.
5. Report: clean `main`, both contributions landed, tests green.

## Build sequence — do not skip ahead
- **Step 0 (spike, throwaway):** one deep agent, shell/filesystem backend scoped to a temp dir, prompt "create hello.txt". Confirm the file lands in that dir and nowhere else. Delete it. Do not start Step 1 until this passes.
- **Step 1:** orchestrator + **one** Astra → commit on `featW1` → `merge_gate` → merge. Get green. Commit. **Report and stop.**
- **Step 2:** add a second Astra + `featW2`. Both land. Commit. Report and stop.
- **Step 3:** plant a deliberately failing test → confirm the reject/retry path fires. Commit.

## Definition of done (Step 2)
- **Input:** "Write `add(a, b)` with a test, and `mul(a, b)` with a test."
- **Output:** the work repo's `main` has both functions and both tests, `pytest` is green, and no human ran any git command.
- **Before claiming done:** run the tests yourself and confirm every criterion above. Do not report success on unverified work.

## Conventions
- Commit after each step. Message format: `phase0: <step> - <what landed>`.
- Every function ships with a pytest test.
- Keep modules small and readable. No premature abstraction.

## Hard stops (out of scope — do not build)
- Sandboxes / Docker / K8s / E2B → Phase 1
- Merge-conflict resolution → keep subtasks file-disjoint; conflicts are Phase 1
- Cognition / memory / self-improving skills → Phase 2
- Frontend / dashboard / virtual office → Phase 3
- "Flexibility" / config / plugin systems → never in Phase 0
- Building Steps 1–3 in one shot → one at a time, commit + report between
