# Astraeus — Usage

How to install, configure, and run Astraeus. For how it works internally, see
[ARCHITECTURE.md](ARCHITECTURE.md).

## Prerequisites

- **Python 3.11+**
- **[`uv`](https://docs.astral.sh/uv/)** (preferred) — or `venv` + `pip`
- **A running Docker daemon** — every worker and the merge gate run in containers; the
  orchestrator drives them with the `docker` CLI. Astraeus checks the daemon is up before
  a run and fails loudly (`DockerError`) if not.
- **Typhoon credentials** — an OpenAI-compatible API key for
  [`typhoon-v2.5-30b-a3b-instruct`](https://opentyphoon.ai).

## Setup

### 1. Credentials

Create a `.env` in the repo root. It is **gitignored** and never committed; the API key
stays on the host and is never passed into a container.

```bash
export TYPHOON_BASE_URL="https://api.opentyphoon.ai/v1"
export TYPHOON_API_KEY="<your-key>"
```

(`src/env.py` loads this `export KEY="val"` format into `os.environ` at startup — no
`python-dotenv` dependency.)

### 2. Dependencies

```bash
uv sync --extra dev          # installs deepagents, langchain-openai, pytest
```

### 3. Worker/gate image

All agent code and tests run inside this image (`python:3.11-slim` + `git` + `pytest`):

```bash
docker build -t astraeus-worker:phase1 .
```

The tag `astraeus-worker:phase1` is hardcoded (`src/docker_backend.py:IMAGE`) and reused
across phases — keep the name as-is unless you also change that constant.

## Running

All entrypoints go through `python -m src.orchestrator`:

| Command | What it does |
| --- | --- |
| `uv run --extra dev python -m src.orchestrator --run "<task>"` | **Phase 2 loop.** Decompose any task → collaborate in the shared workspace → gate → land on `main`. |
| `uv run --extra dev python -m src.orchestrator --shared-demo` | **Collaboration demo.** Two workers edit ONE shared file (`greet.py`), sequenced; both land with no conflict markers. |
| `uv run --extra dev python -m src.orchestrator` | **Default (`step3`).** Phase 1 parallel happy-path demo: two file-disjoint Astra in isolated clones land both branches. |
| `uv run --extra dev python -m src.orchestrator --stall` | **Bounded-hang demo (`step3_stall`).** One worker stalls; the wall-clock cap bounds it and the other branch still lands. |

Example:

```bash
uv run --extra dev python -m src.orchestrator --run \
  "Write add(a,b) returning a+b with a pytest test, and mul(a,b) returning a*b with a pytest test."
```

## Inspecting results

The bare origin's `main` and the per-run transcript both live on Docker volumes:

```bash
# origin main history (proof the work landed)
docker run --rm -v astraeus_origin:/origin astraeus-worker:phase1 \
  git -C /origin log --oneline main

# a landed file on main
docker run --rm -v astraeus_origin:/origin astraeus-worker:phase1 \
  git -C /origin show main:greet.py

# the structured run transcript (plan, rounds, outcomes, gate attempts, timeline)
docker run --rm -v astraeus_workspace:/workspace astraeus-worker:phase1 \
  cat /workspace/.astraeus/run.json
```

The orchestrator also prints the plan, the round schedule, per-thread timeline, gate
verdicts, and the final origin `main` log to stdout.

## Running the tests

```bash
uv run --extra dev pytest -q
```

- **Logic/orchestration tests** (decompose, schedule, the wall-clock cap, bounded repair,
  `run_task` wiring, the gate timeout guard) run with **no Docker and no model**.
- **Docker-gated tests** (`test_workspace_fs.py`, `test_shared_dispatch.py`,
  `test_merge_gate.py`) **skip cleanly** when the daemon is unavailable, and exercise real
  containers + git when it is.

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| `DockerError: docker daemon not available` | Start Docker; `run_task` requires a live daemon (precondition check). |
| `KeyError: 'TYPHOON_API_KEY'` / auth errors | Missing or malformed `.env`; confirm `TYPHOON_BASE_URL` + `TYPHOON_API_KEY`. |
| `docker: ... Unable to find image 'astraeus-worker:phase1'` | Build the image (Setup step 3). |
| A run reports a branch/task **FAILED** | A worker's tests stayed red after the bounded repair, a worker stalled (capped), or a worker errored — the transcript and gate log say which. `main` stays clean. |
| Many `astraeus_*` containers/volumes linger | Containers are torn down per run; volumes (`astraeus_origin`, `astraeus_workspace`) persist for inspection and are recreated fresh each run. Remove with `docker volume rm -f astraeus_origin astraeus_workspace`. |

## Verified vs. pending

The orchestration logic is unit-tested (`34 passed`). The docker-gated plumbing tests and
the live model-driven runs (`--run`, `--shared-demo`) require a host with **both** a Docker
daemon and Typhoon credentials; see [phase2-findings.md](phase2-findings.md) for the exact
verification status.
