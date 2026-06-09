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


def make_astra(container, model=None):
    """Build an Astra whose filesystem + shell run inside `container` (a running
    docker container). `model` defaults to a fresh Typhoon client (built at call
    time, so it reads the env AFTER .env is loaded).
    """
    model = model or _build_typhoon_model()
    backend = DockerSandbox(container)
    return create_deep_agent(
        model=model,
        system_prompt=ASTRA_SYSTEM_PROMPT,
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
