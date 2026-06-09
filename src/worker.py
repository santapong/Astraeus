"""An Astra — a worker agent that implements ONE subtask in its own worktree.

Each Astra is an independent deepagents agent scoped to a single worktree via a
LocalShellBackend(root_dir=...). We use one agent per worktree (rather than the
nested `task` tool) because a deepagents SubAgent has no per-subagent backend —
the backend is set at the agent level, and each Astra needs its OWN worktree.
This is the simplest reading that gives clean per-worktree isolation.

The Astra writes code + a pytest test and commits INSIDE its worktree. It runs
no other git command — all branch/worktree/merge plumbing belongs to the
orchestrator (deterministic Python; no LLM touches git plumbing).
"""

import os

from deepagents import create_deep_agent
from deepagents.backends import LocalShellBackend
from langchain_openai import ChatOpenAI

# Phase 0 runtime model: Typhoon, via its OpenAI-compatible API. Hardcoded on
# purpose — no config system in Phase 0. We build a ChatOpenAI INSTANCE (not a
# "openai:..." string) and pass it straight into create_deep_agent: the string
# path would apply deepagents' OpenAI "Responses API" provider profile, which
# Typhoon does not speak; an instance is returned unchanged by resolve_model.
# Needs TYPHOON_BASE_URL + TYPHOON_API_KEY in the environment (see src/env.py).
def _build_typhoon_model():
    return ChatOpenAI(
        base_url=os.environ["TYPHOON_BASE_URL"],
        api_key=os.environ["TYPHOON_API_KEY"],
        model="typhoon-v2.5-30b-a3b-instruct",
        temperature=0,
    )

ASTRA_SYSTEM_PROMPT = """You are an Astra, a worker agent in the Astraeus system.

You work entirely inside your current working directory (your git worktree).
Do EXACTLY what the instruction asks and nothing more:

1. Write the requested function(s) in the requested file(s).
2. Write a pytest test that imports and exercises the function(s).
3. Run the tests yourself with `execute` (e.g. `pytest -q`) and make them pass.
4. When green, commit with: git add -A && git commit -m "<short message>"

Rules:
- Run NO other git command. Do not create branches or worktrees, do not
  checkout or merge, do not touch `main`. Branch/merge plumbing is not your job.
- Stay within your current directory. Do not write outside it.
- Make the test importable: keep the function file and its test in the same
  directory (or ensure the import path resolves) so `pytest -q` passes.
"""


def make_astra(worktree_path, model=None):
    """Build an Astra agent whose filesystem + shell are scoped to `worktree_path`.

    `model` defaults to a fresh Typhoon client (built at call time, so it reads the
    env AFTER .env is loaded).

    `virtual_mode=True`: deepagents' filesystem tools use `/`-rooted virtual paths.
    With virtual_mode=False those map to the REAL fs root (e.g. `/a.py` -> `C:\a.py`),
    so the agent escapes the worktree. virtual_mode=True confines `/...` to the
    worktree and blocks `..`/`~`. (Shell `execute` still runs with cwd=worktree.)
    `inherit_env=True` is required: without it the `execute` shell runs with an empty
    environment and the Astra's git/pytest calls fail with no PATH.
    """
    model = model or _build_typhoon_model()
    backend = LocalShellBackend(
        root_dir=str(worktree_path), virtual_mode=True, inherit_env=True
    )
    return create_deep_agent(
        model=model,
        system_prompt=ASTRA_SYSTEM_PROMPT,
        backend=backend,
    )


def run_astra(agent, instruction):
    """Dispatch one instruction to an Astra and return the final state."""
    return agent.invoke({"messages": instruction})
