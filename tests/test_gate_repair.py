"""Bounded red-test repair loop (_gate_with_repair) — no docker, no model.

merge_gate / _repair / push_candidate are stubbed so we test only the loop logic:
green lands with no repair; one red triggers exactly one handback; persistent red
fails after the cap; and a CONFLICT is never handed back (Phase 1 FINAL finding —
the model cannot resolve merges).
"""

import src.orchestrator as o
from src.merge_gate import MergeResult


def _subtasks():
    return [{"id": "w1", "branch": "w1", "worker": "c1", "files": ["a.py", "test_a.py"]},
            {"id": "w2", "branch": "w2", "worker": "c2", "files": ["b.py", "test_b.py"]}]


def _count_repairs(monkeypatch, counter):
    monkeypatch.setattr(o, "_repair", lambda *a, **k: counter.__setitem__("n", counter["n"] + 1))
    monkeypatch.setattr(o, "push_candidate", lambda *a, **k: None)


def test_green_first_try_no_repair(monkeypatch):
    counter = {"n": 0}
    _count_repairs(monkeypatch, counter)
    monkeypatch.setattr(o, "merge_gate", lambda *a, **k: MergeResult(ok=True, log="passed"))

    landed, attempts, _ = o._gate_with_repair(_subtasks(), [], max_attempts=2)
    assert landed is True
    assert attempts == 1
    assert counter["n"] == 0


def test_red_then_green_one_repair(monkeypatch):
    counter = {"n": 0}
    _count_repairs(monkeypatch, counter)
    seq = [MergeResult(ok=False, log="E   test_a.py::test_add assert 4 == 5"),
           MergeResult(ok=True, log="ok")]
    monkeypatch.setattr(o, "merge_gate", lambda *a, **k: seq.pop(0))

    landed, attempts, _ = o._gate_with_repair(_subtasks(), [], max_attempts=2)
    assert landed is True
    assert attempts == 2
    assert counter["n"] == 1


def test_red_twice_fails_after_cap(monkeypatch):
    counter, gates = {"n": 0}, {"n": 0}
    _count_repairs(monkeypatch, counter)

    def gate(*a, **k):
        gates["n"] += 1
        return MergeResult(ok=False, log="E   test_a.py failed")

    monkeypatch.setattr(o, "merge_gate", gate)
    landed, attempts, _ = o._gate_with_repair(_subtasks(), [], max_attempts=2)
    assert landed is False
    assert gates["n"] == 2     # initial + one re-gate
    assert counter["n"] == 1   # bounded: exactly one repair


def test_conflict_never_triggers_handback(monkeypatch):
    counter = {"n": 0}
    _count_repairs(monkeypatch, counter)
    monkeypatch.setattr(o, "merge_gate",
                        lambda *a, **k: MergeResult(ok=False, log="conflict", conflicts=["a.py"]))

    landed, attempts, _ = o._gate_with_repair(_subtasks(), [], max_attempts=3)
    assert landed is False
    assert attempts == 1
    assert counter["n"] == 0   # conflicts are NEVER handed back to the model


def test_owner_for_failure_maps_by_filename():
    subs = _subtasks()
    assert o._owner_for_failure("E test_b.py::test_mul failed", subs)["id"] == "w2"
    assert o._owner_for_failure("nothing matches", subs) is None
