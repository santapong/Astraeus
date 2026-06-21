"""An Astra — a worker agent that implements ONE subtask inside its own container.

Phase 1: each Astra is an independent deepagents agent whose filesystem + shell
route through a DockerSandbox into its OWN ephemeral container (one agent per
container — a deepagents SubAgent has no per-subagent backend). The repository is
already cloned and checked out on the Astra's branch at /workspace; the Astra
writes code + a pytest test and commits — nothing else. All clone/branch/push/
merge plumbing belongs to the orchestrator (deterministic Python, list-form git
in the container). The host never executes agent-written code, and the container
never holds the API key (model calls run in this host process).
"""

import os
import time

from deepagents import create_deep_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_openai import ChatOpenAI

from src.docker_backend import DockerSandbox

# Phase 1 runtime model: Typhoon, via its OpenAI-compatible API. Hardcoded on
# purpose — no config system. We build a ChatOpenAI INSTANCE (not a "openai:..."
# string) and pass it straight into create_deep_agent: the string path would apply
# deepagents' OpenAI "Responses API" provider profile, which Typhoon does not speak;
# an instance is returned unchanged by resolve_model. Needs TYPHOON_BASE_URL +
# TYPHOON_API_KEY in the host environment (see src/env.py).
def _build_typhoon_model():
    return ChatOpenAI(
        base_url=os.environ["TYPHOON_BASE_URL"],
        api_key=os.environ["TYPHOON_API_KEY"],
        model="typhoon-v2.5-30b-a3b-instruct",
        temperature=0,
        # Fail fast on a stalled connection instead of hanging on the openai
        # client's ~10-minute default; a few bounded retries cover transient blips.
        timeout=60,
        max_retries=2,
    )

ASTRA_SYSTEM_PROMPT = """You are an Astra, a worker agent in the Astraeus system.

Your git repository is already cloned and checked out on your branch at /workspace.
Do EXACTLY what the instruction asks and nothing more:

1. Create or edit the requested file(s) using absolute paths under /workspace
   (for example /workspace/a.py).
2. Write a pytest test that imports and exercises the function(s).
3. You may run `python -m pytest -q` with the execute tool to check your work.
4. When done, commit with: git add -A && git commit -m "<short message>"

Rules:
- Run NO other git command. Do NOT clone, branch, checkout, push, or merge, and do
  not touch other branches. That plumbing is the orchestrator's job, not yours.
- Work ONLY inside /workspace, using absolute /workspace/... paths.
"""

# Phase 2: the SHARED-tree variant. /workspace is a single tree that OTHER Astra
# also use, so the agent must NOT run git at all (concurrent commits would corrupt
# the shared index — the orchestrator is the sole committer) and must scope its
# self-check to its OWN test file (the tree contains everyone's tests, some of
# which may be half-written while a sibling is still working).
ASTRA_SHARED_SYSTEM_PROMPT = """You are an Astra, a worker agent in the Astraeus system.

You work inside a SHARED filesystem at /workspace that other Astra also read and
write at the same time. Do EXACTLY what the instruction asks and nothing more:

1. Create or edit ONLY the file(s) the instruction assigns to you, using absolute
   paths under /workspace (for example /workspace/a.py).
2. Write a pytest test that imports and exercises the function(s) you wrote.
3. You may run `python -m pytest -q <your own test file>` to check YOUR work
   (test only your own file — the shared tree holds other workers' tests too).

Rules:
- Run NO git command at all (no add, commit, clone, branch, checkout, push, merge).
  The orchestrator commits for you. This is critical: the tree is shared.
- Write ONLY your assigned file(s). You may READ any file under /workspace to build
  on other workers' code, but never modify a file that is not assigned to you.
"""

# Appended to ASTRA_SHARED_SYSTEM_PROMPT per worker; tells it about the wider run.
ASTRA_HARNESS_TEMPLATE = """
--- shared-workspace context ---
The overall task is in /workspace/.astraeus/task.md and the full plan (every
worker's subtask) is in /workspace/.astraeus/plan.json — read them if useful.
The file(s) ASSIGNED to you (write only these): {owned}.
Other workers: {siblings}.
If an assigned file already contains another worker's code, READ it first and ADD
your changes without removing theirs (never delete a sibling's work).
"""


def make_astra(container, model=None, system_prompt=ASTRA_SYSTEM_PROMPT, harness=""):
    """Build an Astra whose filesystem + shell run inside `container` (a running
    docker container). `model` defaults to a fresh Typhoon client (built at call
    time, so it reads the env AFTER .env is loaded).

    `system_prompt` selects the worker contract (default = the Phase 1 isolated-clone
    prompt; pass ASTRA_SHARED_SYSTEM_PROMPT for the Phase 2 shared tree). `harness`
    is an optional per-run context block appended to the prompt (empty = identical
    to Phase 1 behaviour).
    """
    model = model or _build_typhoon_model()
    backend = DockerSandbox(container)
    return create_deep_agent(
        model=model,
        system_prompt=system_prompt + harness,
        backend=backend,
    )


def run_astra(agent, instruction):
    """Dispatch one instruction to an Astra and return the final state."""
    return agent.invoke({"messages": instruction})


class SleepyModel(BaseChatModel):
    """Deterministic stall stub: every generation blocks for `sleep_seconds`.

    Used ONLY by the Step 3 timeout test to force one worker to hang, proving the
    per-Astra wall-clock cap bounds a hung model call (the Phase-0 19-minute freeze
    cannot recur). Not used in any real run.
    """

    sleep_seconds: int = 600

    @property
    def _llm_type(self):
        return "sleepy-stub"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        time.sleep(self.sleep_seconds)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=""))])

    def bind_tools(self, tools, **kwargs):
        return self  # accept tool binding, ignore — the call sleeps before any tool use
