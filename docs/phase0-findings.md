# Phase 0 — Findings

What running Astraeus Phase 0 (Steps 0–3) on Typhoon actually taught us. Every item
here was learned by *running the system live*, not by reading code. This is the seed
for the Phase 1 spec.

## VALIDATED — what running it proved

- **Typhoon-30B emits clean structured tool calls.** `typhoon-v2.5-30b-a3b-instruct`
  over the OpenAI-compatible API returns well-formed `tool_calls` (verified before
  anything else was built). The whole approach depends on this, and it holds.

- **Filesystem scoping requires `virtual_mode=True`.** deepagents' filesystem tools use
  `/`-rooted *virtual* paths. With `virtual_mode=False`, those map to the **real**
  filesystem root — on Windows the model's `write_file("/hello.txt")` escaped the
  worktree to `C:\` and then `$HOME`. This surfaced only because Typhoon follows the
  tool spec literally and emits absolute `/` paths (a model that happened to use
  relative paths would have hidden the bug). `virtual_mode=True` confines `/...` to the
  worktree and blocks `..`/`~`.

- **Strict bare-array JSON decompose is reliable at `temperature=0`.** A single model
  call with a strict prompt returns exactly two file-disjoint subtasks as a JSON array,
  parsed defensively (whole-string `json.loads`, then a bracket-depth scan fallback).
  `response_format=json_object` was **rejected**: it forces a top-level *object*, but
  the spec's schema is a top-level *array*. Prompt + `temperature=0` + defensive parse
  was both reliable and faithful to the array contract.

- **Error-feedback self-repair works.** Handing the **verbatim pytest log** back to the
  same worker in a **single** handback was enough for the model to fix its own code
  (`return a - b` → `return a + b`) and re-commit to a passing, mergeable state. The
  feedback channel — not extra reasoning — is what made repair possible.

- **End-to-end, zero human git.** decompose → two Astras (each in its own worktree) →
  merge gate → reject/retry-once → land on `main`. Two contributions merged via
  `git merge --no-ff` with no human running a single git command.

## BUG FAMILIES + PHASE 1 DESIGN INPUTS — found only by running

- **Shell quoting under `cmd.exe`.** `run()` used `shell=True`; a single-quoted
  `-m 'merge featW1'` broke on Windows (`cmd.exe` treats single quotes literally), so
  git read `featW1'` as a second merge target and the merge silently failed.
  → **Phase 1: use list-form `subprocess` everywhere** (no shell string interpolation).

- **Ignored exit codes.** The gate ran `git merge` (and later `git checkout main`) and
  returned `ok=True` without checking the exit code — it reported a *successful merge*
  on a merge that never happened. → **Phase 1: every git op must check its exit code.**
  A gate that can lie is worse than no gate.

- **Unbounded timeouts.** The OpenAI client's default request timeout is ~10 minutes; a
  single stalled HTTP call froze an entire run for ~19 minutes with the endpoint itself
  answering in 0.5s. The band-aid is `timeout=60, max_retries=2` on the model.
  → **Phase 1 concurrency must ASSUME calls hang** — every model/tool call needs a
  bounded timeout and a recovery path, not a happy-path await.

- **`inherit_env=True` leaks the full environment.** The Astra's shell needs `PATH` for
  `git`/`pytest`, so it inherits the whole parent environment — **including
  `TYPHOON_API_KEY`** — into every worker shell. Acceptable for a watched local run;
  → **Phase 1: a scoped/minimal env inside real sandboxes**, never the raw host env.

- **File-disjoint subtasks were training wheels.** Phase 0 guaranteed no shared files so
  merges could never conflict. → **Phase 1 needs real merge-conflict handling** (detect,
  hand back, or rebase), because real decompositions will overlap.

- **The work repo is a throwaway `mkdtemp`.** Fine for a skeleton, but there is no
  lifecycle — no persistence, cleanup, or reuse. → **Phase 1 needs a real work-repo
  lifecycle.** (Keep the work-repo `.gitignore` seeding — it stopped workers from
  committing `__pycache__`/`*.pyc`.)
