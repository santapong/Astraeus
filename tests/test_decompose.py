"""Pure tests for the Phase 2 N-worker decompose contract — no model, no docker.

Exercises _validate (2..MAX_WORKERS subtasks, unique ids, shared files allowed) and
_extract_json_array (tolerant JSON parsing) directly.
"""

import pytest

from src.decompose import DecomposeError, _extract_json_array, _validate, decompose
from src.docker_backend import MAX_WORKERS


class _FakeModel:
    """Minimal stand-in for the Typhoon ChatOpenAI: .invoke(prompt).content from a queue."""

    def __init__(self, outputs):
        self._outputs = list(outputs)
        self.prompts = []

    def invoke(self, prompt):
        self.prompts.append(prompt)
        return type("R", (), {"content": self._outputs.pop(0)})()


_VALID = ('[{"id":"w1","files":["a.py"],"instruction":"do a"},'
          '{"id":"w2","files":["b.py"],"instruction":"do b"}]')


def _subtask(i, files):
    return {"id": f"w{i}", "files": files,
            "instruction": f"create {files[0]} and write a pytest test asserting a value"}


def test_validate_accepts_two_disjoint():
    st = [_subtask(1, ["a.py", "test_a.py"]), _subtask(2, ["b.py", "test_b.py"])]
    assert _validate(st) == st


def test_validate_accepts_three_and_four():
    for n in (3, 4):
        st = [_subtask(i, [f"m{i}.py", f"test_m{i}.py"]) for i in range(1, n + 1)]
        assert len(_validate(st)) == n


def test_validate_allows_shared_files_phase2():
    # Phase 2 relaxation: files MAY overlap (the orchestrator sequences them).
    st = [_subtask(1, ["calc.py", "test_calc.py"]), _subtask(2, ["calc.py", "test_calc.py"])]
    assert _validate(st) == st


def test_validate_rejects_fewer_than_two():
    with pytest.raises(DecomposeError):
        _validate([_subtask(1, ["a.py"])])


def test_validate_rejects_more_than_max():
    st = [_subtask(i, [f"m{i}.py"]) for i in range(1, MAX_WORKERS + 2)]
    with pytest.raises(DecomposeError):
        _validate(st)


def test_validate_rejects_duplicate_ids():
    st = [_subtask(1, ["a.py"]), {"id": "w1", "files": ["b.py"], "instruction": "x"}]
    with pytest.raises(DecomposeError):
        _validate(st)


def test_validate_rejects_missing_instruction():
    with pytest.raises(DecomposeError):
        _validate([{"id": "w1", "files": ["a.py"]}, _subtask(2, ["b.py"])])


def test_validate_rejects_empty_files():
    empty = {"id": "w1", "files": [], "instruction": "write a pytest test"}
    with pytest.raises(DecomposeError):
        _validate([empty, _subtask(2, ["b.py"])])


def test_extract_json_array_plain_and_fenced():
    raw = '[{"id":"w1","files":["a.py"],"instruction":"x"}]'
    assert _extract_json_array(raw)[0]["id"] == "w1"
    fenced = "```json\n" + raw + "\n```"
    assert _extract_json_array(fenced)[0]["files"] == ["a.py"]


def test_extract_json_array_with_surrounding_prose_and_bracket_in_string():
    raw = 'Sure! Here:\n[{"id":"w1","files":["a.py"],"instruction":"do [x] then stop"}]\nDone.'
    out = _extract_json_array(raw)
    assert out[0]["instruction"] == "do [x] then stop"  # ']' inside a string handled


def test_extract_json_array_raises_when_absent():
    with pytest.raises(DecomposeError):
        _extract_json_array("no array anywhere here")


def test_decompose_happy_path_is_single_call():
    m = _FakeModel([_VALID])
    out = decompose("t", model=m)
    assert [s["id"] for s in out] == ["w1", "w2"]
    assert len(m.prompts) == 1                       # valid first try -> no retry


def test_decompose_retries_on_invalid_then_succeeds():
    m = _FakeModel(["not json at all", _VALID])
    out = decompose("t", model=m)
    assert len(out) == 2
    assert len(m.prompts) == 2                       # one retry
    assert "REJECTED" in m.prompts[1]                # validation error fed back into the retry


def test_decompose_raises_after_max_attempts():
    m = _FakeModel(["nope", "still nope", "and again"])
    with pytest.raises(DecomposeError):
        decompose("t", model=m, max_attempts=2)
    assert len(m.prompts) == 2                        # bounded: stops at max_attempts
