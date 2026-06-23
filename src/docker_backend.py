"""DockerSandbox — a deepagents BaseSandbox whose every file + shell operation
runs INSIDE an ephemeral Docker container, via the docker CLI.

Why this exists (Phase 1): the host must NEVER execute agent-written code. By
subclassing deepagents' BaseSandbox and implementing only execute() / upload_files()
/ download_files() / id, ALL of the agent's file tools (read/write/edit/ls/grep/glob)
and its shell tool route through `docker exec`/stdin into the container
(BaseSandbox derives every file op from execute()+upload_files() — see
deepagents/backends/sandbox.py).

Every host subprocess here is list-form (never shell=True); the `sh -c` lives
INSIDE the container, which is the intended sandboxed execution surface. Model
calls happen in the orchestrator process on the host, so the container needs no
API key.
"""

import os
import subprocess

from deepagents.backends.protocol import (
    ExecuteResponse,
    FileDownloadResponse,
    FileUploadResponse,
)
from deepagents.backends.sandbox import BaseSandbox

WORKDIR = "/workspace"
DEFAULT_TIMEOUT = 120  # seconds, per docker-exec command

# Hardcoded, opinionated (Phase 1: no config layer).
IMAGE = "astraeus-worker:phase1"
ORIGIN_VOLUME = "astraeus_origin"

# Phase 2: the central shared working tree every sandbox mounts at /workspace.
# Unlike the bare ORIGIN_VOLUME (history, reachable only through git), this is a
# live checkout all Astra read/write directly — "the central file system all
# sandboxes interact with". MAX_WORKERS caps N for the N-worker loop.
WORKSPACE_VOLUME = "astraeus_workspace"
MAX_WORKERS = 4


class DockerError(RuntimeError):
    """A docker CLI command exited non-zero (surfaced, never swallowed)."""


def dcmd(args, check=True, timeout=120):
    """Run a docker CLI command list-form (no host shell), text mode.

    Every git/docker plumbing op goes through here so exit codes are always
    checked (raises DockerError on failure) — the Phase-0 ignored-exit-code bug
    family cannot recur. Returns the CompletedProcess.
    """
    p = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)
    if check and p.returncode != 0:
        joined = " ".join(str(a) for a in args)
        raise DockerError(f"`docker {joined}` exit {p.returncode}:\n{p.stdout}{p.stderr}")
    return p


def _runtime_args():
    """Opt-in container runtime for the sandboxes that execute AGENT code/tests.

    `ASTRAEUS_RUNTIME=runsc` runs those containers under gVisor — a one-line `docker run`
    flag, no image/orchestration change — to harden against container escape (the cheapest
    mitigation for the documented Docker-escape risk; see docs/research/harness-sandbox-deep.md).
    Empty by default, so behaviour is unchanged unless the env var is set. Trusted git
    plumbing keeps the default runtime.
    """
    rt = os.environ.get("ASTRAEUS_RUNTIME", "").strip()
    return ["--runtime", rt] if rt else []


def _docker(args, input_bytes=None, timeout=None):
    """Run a docker CLI command, list-form (no host shell). Returns CompletedProcess.

    Bytes-mode variant used by DockerSandbox for stdin uploads / binary output.
    """
    return subprocess.run(
        ["docker", *args],
        input=input_bytes,
        capture_output=True,
        timeout=timeout,
    )


class DockerSandbox(BaseSandbox):
    """Routes deepagents file + shell ops into a running container via `docker exec`.

    The container must already be running (the orchestrator owns its lifecycle).
    `workdir` is the cwd for `execute()` — the Astra's git clone.
    """

    def __init__(self, container, workdir=WORKDIR, default_timeout=DEFAULT_TIMEOUT):
        self._container = container
        self._workdir = workdir
        self._default_timeout = default_timeout

    @property
    def id(self):
        return self._container

    def execute(self, command, *, timeout=None):
        """Run `command` via `sh -c` inside the container, cwd=workdir."""
        eff = timeout if timeout is not None else self._default_timeout
        try:
            p = _docker(
                ["exec", "-w", self._workdir, self._container, "sh", "-c", command],
                timeout=(eff if eff and eff > 0 else None),
            )
        except subprocess.TimeoutExpired:
            return ExecuteResponse(
                output=f"Error: command timed out after {eff}s", exit_code=124, truncated=False
            )
        out = (p.stdout or b"").decode("utf-8", "replace")
        err = (p.stderr or b"").decode("utf-8", "replace")
        if out and err:
            output = out + "\n" + err
        else:
            output = out or err
        return ExecuteResponse(output=output, exit_code=p.returncode, truncated=False)

    def upload_files(self, files):
        """Write each (path, bytes) into the container via stdin (binary-safe, no ARG_MAX)."""
        responses = []
        for path, content in files:
            try:
                p = _docker(
                    [
                        "exec", "-i", self._container, "sh", "-c",
                        'mkdir -p "$(dirname "$1")" && cat > "$1"', "_", path,
                    ],
                    input_bytes=content,
                    timeout=self._default_timeout,
                )
                if p.returncode != 0:
                    err = (p.stderr or b"").decode("utf-8", "replace").strip() or "upload_failed"
                    responses.append(FileUploadResponse(path=path, error=err))
                else:
                    responses.append(FileUploadResponse(path=path, error=None))
            except Exception as e:  # noqa: BLE001 — per-file partial success, never raise
                responses.append(FileUploadResponse(path=path, error=f"{type(e).__name__}: {e}"))
        return responses

    def download_files(self, paths):
        """Read each path out of the container as bytes."""
        responses = []
        for path in paths:
            try:
                p = _docker(["exec", self._container, "cat", path], timeout=self._default_timeout)
                if p.returncode != 0:
                    responses.append(FileDownloadResponse(path=path, content=None, error="file_not_found"))
                else:
                    responses.append(FileDownloadResponse(path=path, content=p.stdout, error=None))
            except Exception as e:  # noqa: BLE001 — per-file partial success, never raise
                responses.append(FileDownloadResponse(path=path, content=None, error=f"{type(e).__name__}: {e}"))
        return responses
