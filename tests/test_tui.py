"""Static TUI viewer (Milestone B) — pure view-model functions, no Textual needed.

The transcript->view-model helpers are tested directly against a synthetic run.json
(the `run_task` schema). The Textual App itself is smoke-tested only when `textual` is
installed (`importorskip`), mirroring the docker-gated skip pattern elsewhere.
"""

import json

import pytest

import src.tui as tui

RESULT = {
    "task": "add + mul",
    "plan": [
        {"id": "w1", "files": ["a.py", "test_a.py"], "instruction": "implement add(a, b)"},
        {"id": "w2", "files": ["b.py", "test_b.py"], "instruction": "implement mul(a, b)"},
    ],
    "rounds": [["w1", "w2"]],
    "outcomes": {"w1": "READY", "w2": "FAILED_ERROR"},
    "gate_attempts": 2,
    "landed": True,
    "gate_state": "landed",
    "gate_log": "4 passed in 0.1s",
    "origin_log": "abc merge candidate",
    "timeline": [
        {"t": 0.0, "id": "w1", "event": "astra dispatch begin"},
        {"t": 1.5, "id": "w2", "event": "astra dispatch end"},
    ],
}


def test_load_transcript(tmp_path):
    p = tmp_path / "run.json"
    p.write_text(json.dumps(RESULT))
    assert tui.load_transcript(str(p))["task"] == "add + mul"


def test_worker_rows_pairs_files_and_outcomes():
    rows = tui.worker_rows(RESULT)
    assert ("w1", "a.py, test_a.py", "READY") in rows
    assert ("w2", "b.py, test_b.py", "FAILED_ERROR") in rows


def test_round_lines_parallel_marker():
    assert tui.round_lines(RESULT) == ["R1: w1 ║ w2"]


def test_round_lines_sequenced():
    r = {"rounds": [["w1"], ["w2"]]}
    assert tui.round_lines(r) == ["R1: w1", "R2: w2"]


def test_gate_lines_surfaces_state_and_attempts():
    text = "\n".join(tui.gate_lines(RESULT))
    assert "landed" in text     # gate_state (Milestone A) is surfaced
    assert "2" in text          # attempts used


def test_timeline_lines_format():
    lines = tui.timeline_lines(RESULT)
    assert lines[0].endswith("[w1] astra dispatch begin")
    assert any("[w2]" in line for line in lines)


def test_plan_lines_list_files_and_instruction():
    lines = tui.plan_lines(RESULT)
    assert any("w1" in line and "a.py" in line for line in lines)


def test_status_style_colors():
    assert tui.status_style("READY") == "green"
    assert tui.status_style("FAILED_TIMEOUT") == "red"
    assert tui.status_style("FAILED_ERROR") == "red"
    assert tui.status_style("?") == "yellow"


def test_summary_text_falls_back():
    assert tui.summary_text({}) == "(no origin log)"


def test_app_constructs_when_textual_present():
    pytest.importorskip("textual")
    app = tui.build_app(RESULT)   # construct (not run) — verifies the wiring imports
    assert app is not None


def test_file_source_reads_and_handles_missing(tmp_path):
    p = tmp_path / "run.json"
    p.write_text(json.dumps(RESULT))
    assert tui.file_source(str(p))()["task"] == "add + mul"
    assert tui.file_source(str(tmp_path / "nope.json"))() is None   # missing -> None, no raise


def test_live_refresh_updates_panels_on_poll(tmp_path):
    pytest.importorskip("textual")
    import asyncio

    p = tmp_path / "run.json"
    p.write_text(json.dumps(dict(RESULT, gate_state="gating", landed=False)))
    src = tui.file_source(str(p))

    async def go():
        app = tui.build_app(src(), source=src, interval=1000)  # poll manually below
        async with app.run_test() as pilot:
            await pilot.pause()
            assert "gating" in str(app.query_one("#gate").render())     # initial state
            p.write_text(json.dumps(dict(RESULT, gate_state="landed", landed=True)))
            app._poll()                                                 # run progressed
            await pilot.pause()
            assert "landed" in str(app.query_one("#gate").render())     # panel refreshed

    asyncio.run(go())
