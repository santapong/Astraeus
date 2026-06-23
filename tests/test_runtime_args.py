"""Opt-in gVisor runtime wiring (offline, no docker).

`ASTRAEUS_RUNTIME` gates a `--runtime` flag on the `docker run` calls that launch the
containers executing AGENT code/tests; default behaviour is unchanged when unset.
"""

import src.docker_backend as db
import src.orchestrator as o


def test_runtime_args_empty_by_default(monkeypatch):
    monkeypatch.delenv("ASTRAEUS_RUNTIME", raising=False)
    assert db._runtime_args() == []


def test_runtime_args_set(monkeypatch):
    monkeypatch.setenv("ASTRAEUS_RUNTIME", "runsc")
    assert db._runtime_args() == ["--runtime", "runsc"]


def test_runtime_args_blank_is_empty(monkeypatch):
    monkeypatch.setenv("ASTRAEUS_RUNTIME", "   ")
    assert db._runtime_args() == []


def test_start_shared_worker_injects_runtime_when_set(monkeypatch):
    monkeypatch.setenv("ASTRAEUS_RUNTIME", "runsc")
    calls = []
    monkeypatch.setattr(o, "dcmd", lambda args, **k: calls.append(list(args)))
    o.start_shared_worker("c1")
    run = next(c for c in calls if c and c[0] == "run")
    assert run[1:3] == ["--runtime", "runsc"]    # injected right after `run`


def test_start_shared_worker_no_runtime_by_default(monkeypatch):
    monkeypatch.delenv("ASTRAEUS_RUNTIME", raising=False)
    calls = []
    monkeypatch.setattr(o, "dcmd", lambda args, **k: calls.append(list(args)))
    o.start_shared_worker("c1")
    run = next(c for c in calls if c and c[0] == "run")
    assert "--runtime" not in run                 # default unchanged
