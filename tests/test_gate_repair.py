"""Bounded red-test repair loop (_gate_with_repair) — no docker, no model.

merge_gate / _repair / push_candidate are stubbed so we test only the loop logic:
green lands with no repair; one red triggers exactly one handback; persistent red
fails after the cap; a CONFLICT is never handed back (Phase 1 FINAL finding — the
model cannot resolve merges); and every exit records an explicit `gate_state`.
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

    landed, attempts, _, gate_state = o._gate_with_repair(_subtasks(), [], max_attempts=2)
    assert landed is True
    assert attempts == 1
    assert counter["n"] == 0
    assert gate_state == "landed"


def test_red_then_green_one_repair(monkeypatch):
    counter = {"n": 0}
    _count_repairs(monkeypatch, counter)
    seq = [MergeResult(ok=False, log="E   test_a.py::test_add assert 4 == 5"),
           MergeResult(ok=True, log="ok")]
    monkeypatch.setattr(o, "merge_gate", lambda *a, **k: seq.pop(0))

    landed, attempts, _, gate_state = o._gate_with_repair(_subtasks(), [], max_attempts=2)
    assert landed is True
    assert attempts == 2
    assert counter["n"] == 1
    assert gate_state == "landed"


def test_red_twice_fails_after_cap(monkeypatch):
    counter, gates = {"n": 0}, {"n": 0}
    _count_repairs(monkeypatch, counter)

    def gate(*a, **k):
        gates["n"] += 1
        return MergeResult(ok=False, log="E   test_a.py failed")

    monkeypatch.setattr(o, "merge_gate", gate)
    landed, attempts, _, gate_state = o._gate_with_repair(_subtasks(), [], max_attempts=2)
    assert landed is False
    assert gates["n"] == 2     # initial + one re-gate
    assert counter["n"] == 1   # bounded: exactly one repair
    assert gate_state == "retry_exhausted"


def test_conflict_never_triggers_handback(monkeypatch):
    counter = {"n": 0}
    _count_repairs(monkeypatch, counter)
    monkeypatch.setattr(o, "merge_gate",
                        lambda *a, **k: MergeResult(ok=False, log="conflict", conflicts=["a.py"]))

    landed, attempts, _, gate_state = o._gate_with_repair(_subtasks(), [], max_attempts=3)
    assert landed is False
    assert attempts == 1
    assert counter["n"] == 0   # conflicts are NEVER handed back to the model
    assert gate_state == "conflict"


def test_repair_no_owner_stops_with_state(monkeypatch):
    # Red, but the log names no file owned by any subtask -> no owner -> stop, no repair.
    counter = {"n": 0}
    _count_repairs(monkeypatch, counter)
    monkeypatch.setattr(o, "merge_gate",
                        lambda *a, **k: MergeResult(ok=False, log="E   zzz.py::t failed"))

    landed, attempts, _, gate_state = o._gate_with_repair(_subtasks(), [], max_attempts=3)
    assert landed is False
    assert attempts == 1
    assert counter["n"] == 0
    assert gate_state == "repair_no_owner"


def test_owner_for_failure_maps_by_filename():
    subs = _subtasks()
    assert o._owner_for_failure("E test_b.py::test_mul failed", subs)["id"] == "w2"
    assert o._owner_for_failure("nothing matches", subs) is None


def test_owner_for_failure_no_substring_false_match():
    # w1 owns a.py; w2 owns aa.py. A log mentioning ONLY aa.py must map to w2 — the
    # old substring check ("a.py" in "aa.py") would have wrongly picked w1.
    subs = [{"id": "w1", "branch": "w1", "worker": "c1", "files": ["a.py", "test_a.py"]},
            {"id": "w2", "branch": "w2", "worker": "c2", "files": ["aa.py", "test_aa.py"]}]
    assert o._owner_for_failure("E   test_aa.py::t failed in aa.py", subs)["id"] == "w2"
    assert o._owner_for_failure("E   test_a.py::t failed", subs)["id"] == "w1"
    assert o._owner_for_failure("no python files mentioned", subs) is None


def test_handback_asks_for_reflection():
    # Reflexion: the worker must reflect before fixing, not blindly re-run.
    assert "reflect" in o.RED_TEST_HANDBACK_MSG.lower()


def test_extract_reflection_from_state():
    state = {"messages": [
        {"role": "user", "content": "fix it"},
        {"role": "assistant", "content": "Expected 5 but got 4; I will fix add()."}]}
    assert "Expected 5" in o._extract_reflection(state)
    assert o._extract_reflection({}) == ""              # missing/odd state -> '' (no raise)
    assert o._extract_reflection({"messages": []}) == ""


def test_on_repair_receives_reflection(monkeypatch):
    monkeypatch.setattr(o, "_repair", lambda *a, **k: "expected 5 got 4; will fix add")
    monkeypatch.setattr(o, "push_candidate", lambda *a, **k: None)
    seq = [MergeResult(ok=False, log="E   test_a.py::t failed"), MergeResult(ok=True, log="ok")]
    monkeypatch.setattr(o, "merge_gate", lambda *a, **k: seq.pop(0))

    repairs = []
    landed, attempts, _, gate_state = o._gate_with_repair(
        _subtasks(), [], max_attempts=2,
        on_repair=lambda oid, att, refl: repairs.append((oid, att, refl)))
    assert landed is True and gate_state == "landed"
    assert repairs == [("w1", 1, "expected 5 got 4; will fix add")]   # owner, attempt, reflection
