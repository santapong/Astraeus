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

from deepagents import create_deep_agent
from deepagents.backends import LocalShellBackend

# A current frontier Claude model (matches deepagents' own default). Needs
# ANTHROPIC_API_KEY at runtime. Hardcoded on purpose — no config system in Phase 0.
DEFAULT_MODEL = "anthropic:claude-sonnet-4-6"

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


def make_astra(worktree_path, model=DEFAULT_MODEL):
    """Build an Astra agent whose filesystem + shell are scoped to `worktree_path`."""
    backend = LocalShellBackend(root_dir=str(worktree_path), virtual_mode=False)
    return create_deep_agent(
        model=model,
        system_prompt=ASTRA_SYSTEM_PROMPT,
        backend=backend,
    )


def run_astra(agent, instruction):
    """Dispatch one instruction to an Astra and return the final state."""
    return agent.invoke({"messages": instruction})
