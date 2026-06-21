"""In-process tests for the wall-clock cap / stall lever (_run_with_cap) — no docker,
no model. dcmd is stubbed so the timeout branch's container-kill is a no-op.
"""

import time

import src.orchestrator as o


def _subtasks(ids):
    return [{"branch": i, "worker": f"c_{i}"} for i in ids]


def test_all_fast_are_ready(monkeypatch):
    monkeypatch.setattr(o, "dcmd", lambda *a, **k: None)

    def work(s, record):
        record(s["branch"], "did work")
        return True

    _, outcomes, _ = o._run_with_cap(_subtasks(["w1", "w2"]), cap=5, work=work)
    assert outcomes == {"w1": "READY", "w2": "READY"}


def test_stalled_worker_times_out_and_container_killed(monkeypatch):
    killed = []
    monkeypatch.setattr(o, "dcmd", lambda args, **k: killed.append(args))

    def work(s, record):
        if s["branch"] == "slow":
            time.sleep(10)  # exceeds the cap; thread is a daemon, harmless after test
        return True

    _, outcomes, _ = o._run_with_cap(_subtasks(["fast", "slow"]), cap=1, work=work)
    assert outcomes["fast"] == "READY"
    assert outcomes["slow"] == "FAILED_TIMEOUT"
    assert any("c_slow" in a for a in killed)  # the stalled container was rm -f'd


def test_worker_error_is_failed_error(monkeypatch):
    monkeypatch.setattr(o, "dcmd", lambda *a, **k: None)

    def work(s, record):
        if s["branch"] == "boom":
            raise RuntimeError("kaboom")
        return True

    _, outcomes, _ = o._run_with_cap(_subtasks(["boom", "ok"]), cap=5, work=work)
    assert outcomes["boom"] == "FAILED_ERROR"
    assert outcomes["ok"] == "READY"
