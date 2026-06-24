"""Offline unit tests for the gate's pytest-summary failure parser (no docker, no model).

merge_gate._failing_files turns pytest's short-test-summary lines into the failing test
FILE paths the orchestrator uses to route a red handback to the owning worker.
"""

from src.merge_gate import MergeResult, _failing_files

# A real `pytest -q` red tail (one failing test, one passing) — confirms the summary line
# format the parser targets.
SAMPLE = """F.                                                                       [100%]
=================================== FAILURES ===================================
___________________________________ test_add ___________________________________

    def test_add():
>       assert add(2, 3) == 99
E       assert 5 == 99

test_a.py:4: AssertionError
=========================== short test summary info ============================
FAILED test_a.py::test_add - assert 5 == 99
1 failed, 1 passed in 0.05s"""


def test_failing_files_parsed_from_summary():
    assert _failing_files(SAMPLE) == ["test_a.py"]


def test_failing_files_handles_paths_params_errors_and_dedup():
    out = (
        "FAILED tests/test_a.py::test_x[1-2] - ValueError: a - b\n"  # subdir + params + ' - ' in msg
        "ERROR tests/test_b.py - collection error\n"                 # collection error: no '::'
        "FAILED tests/test_a.py::test_y - boom\n"                    # same file again -> deduped
    )
    assert _failing_files(out) == ["tests/test_a.py", "tests/test_b.py"]  # first-seen order, deduped


def test_failing_files_empty_when_green():
    assert _failing_files("2 passed in 0.01s") == []


def test_failing_files_ignores_non_summary_lines():
    # The word FAILED can appear mid-traceback; only real `FAILED <nodeid.py>` lines count.
    assert _failing_files("E   AssertionError: the call FAILED unexpectedly") == []


def test_merge_result_failures_defaults_empty():
    assert MergeResult(ok=True).failures == []
