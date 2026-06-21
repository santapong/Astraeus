"""The gate turns a pytest that overruns the cap into a clean RED verdict, not an
uncaught crash. No docker — `dcmd` is stubbed to raise TimeoutExpired on the pytest call.
"""

import subprocess

import src.merge_gate as mg
from src.merge_gate import merge_gate


def test_gate_pytest_timeout_is_clean_red(monkeypatch):
    def fake_dcmd(args, check=True, timeout=120):
        if "pytest" in args:
            raise subprocess.TimeoutExpired(cmd="pytest", timeout=timeout)

        class _P:
            returncode = 0
            stdout = ""
            stderr = ""

        return _P()

    monkeypatch.setattr(mg, "dcmd", fake_dcmd)
    res = merge_gate("candidate")
    assert res.ok is False
    assert "timed out" in res.log.lower()
