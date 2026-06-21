"""run_task wiring + transcript + harness — no docker, no model (all I/O stubbed).

Verifies the loop calls decompose with the task, schedules disjoint vs shared files
into the right rounds, dispatches each round, lands via the gate, and persists a
structured transcript. Also checks the harness block and the shared system prompt.
"""

import json

import src.orchestrator as o
import src.worker as w
from src.merge_gate import MergeResult

PLAN = [
    {"id": "w1", "files": ["a.py", "test_a.py"], "instruction": "do a"},
    {"id": "w2", "files": ["b.py", "test_b.py"], "instruction": "do b"},
]


def _patch_common(monkeypatch, seeded, rounds_seen):
    monkeypatch.setattr(o, "_docker_available", lambda: True)
    monkeypatch.setattr(o, "reset_origin_volume", lambda *a, **k: None)
    monkeypatch.setattr(o, "reset_workspace_volume", lambda *a, **k: None)
    monkeypatch.setattr(o, "commit_workspace", lambda *a, **k: None)
    monkeypatch.setattr(o, "push_candidate", lambda *a, **k: None)
    monkeypatch.setattr(o, "dcmd", lambda *a, **k: None)
    monkeypatch.setattr(o, "origin_main_log", lambda *a, **k: "abc merge candidate")
    monkeypatch.setattr(o, "merge_gate", lambda *a, **k: MergeResult(ok=True, log="passed"))
    monkeypatch.setattr(o, "seed_workspace_file",
                        lambda rel, content, **k: seeded.__setitem__(rel, content))

    def run_round(subtasks, cap, **k):
        rounds_seen.append([s["branch"] for s in subtasks])
        tl = [(0.0, s["branch"], "astra dispatch begin") for s in subtasks]
        oc = {s["branch"]: "READY" for s in subtasks}
        return tl, oc, 0.0

    monkeypatch.setattr(o, "run_round", run_round)


def test_run_task_decomposes_and_wires(monkeypatch):
    seeded, rounds_seen, dcalls = {}, [], []
    _patch_common(monkeypatch, seeded, rounds_seen)
    monkeypatch.setattr(o, "decompose", lambda task: dcalls.append(task) or PLAN)

    result = o.run_task("my task")
    assert dcalls == ["my task"]                 # decompose called with the task
    assert result["landed"] is True
    assert result["plan"] == PLAN
    assert set(result["outcomes"]) == {"w1", "w2"}
    assert result["rounds"] == [["w1", "w2"]]    # disjoint -> one round

    assert ".astraeus/run.json" in seeded        # transcript persisted
    tr = json.loads(seeded[".astraeus/run.json"])
    assert tr["task"] == "my task"
    assert tr["landed"] is True
    assert any(e["id"] in ("w1", "w2") for e in tr["timeline"])


def test_run_task_seeds_task_and_plan(monkeypatch):
    seeded, rounds_seen = {}, []
    _patch_common(monkeypatch, seeded, rounds_seen)
    monkeypatch.setattr(o, "decompose", lambda task: PLAN)

    o.run_task("the task text")
    assert seeded[".astraeus/task.md"] == "the task text"
    assert json.loads(seeded[".astraeus/plan.json"]) == PLAN


def test_run_task_shared_files_two_rounds(monkeypatch):
    shared = [
        {"id": "w1", "files": ["calc.py"], "instruction": "x"},
        {"id": "w2", "files": ["calc.py"], "instruction": "y"},
    ]
    seeded, rounds_seen = {}, []
    _patch_common(monkeypatch, seeded, rounds_seen)
    monkeypatch.setattr(o, "decompose", lambda task: shared)

    result = o.run_task("collab")
    assert result["rounds"] == [["w1"], ["w2"]]  # sequenced
    assert rounds_seen == [["w1"], ["w2"]]       # one worker dispatched per round


def test_run_task_plan_override_skips_decompose(monkeypatch):
    seeded, rounds_seen, dcalls = {}, [], []
    _patch_common(monkeypatch, seeded, rounds_seen)
    monkeypatch.setattr(o, "decompose", lambda task: dcalls.append(task) or PLAN)

    o.run_task("ignored", plan=PLAN)
    assert dcalls == []                          # decompose NOT called when plan supplied


def test_run_task_discards_failed_worker_changes(monkeypatch):
    seeded, rounds_seen = {}, []
    _patch_common(monkeypatch, seeded, rounds_seen)
    monkeypatch.setattr(o, "decompose", lambda task: PLAN)

    # one worker READY, the other FAILED_ERROR (partial/garbage work to drop).
    def run_round(subtasks, cap, **k):
        tl = [(0.0, s["branch"], "astra dispatch begin") for s in subtasks]
        oc = {s["branch"]: ("READY" if i == 0 else "FAILED_ERROR")
              for i, s in enumerate(subtasks)}
        return tl, oc, 0.0
    monkeypatch.setattr(o, "run_round", run_round)

    discarded = []
    monkeypatch.setattr(o, "_discard_worker_changes",
                        lambda s, **k: discarded.append(s["branch"]))

    o.run_task("t")
    assert discarded == ["w2"]  # only the non-READY worker's changes are dropped


def test_build_harness_lists_owned_and_siblings():
    h = o._build_harness({"id": "w1", "files": ["a.py", "test_a.py"]}, PLAN)
    assert "a.py, test_a.py" in h   # what it owns
    assert "w2" in h                # its sibling is named


def test_make_astra_shared_prompt_includes_harness(monkeypatch):
    captured = {}
    monkeypatch.setattr(w, "create_deep_agent",
                        lambda model=None, system_prompt=None, backend=None, **k:
                        captured.__setitem__("sp", system_prompt))
    monkeypatch.setattr(w, "DockerSandbox", lambda c: object())

    w.make_astra("c1", model=object(),
                 system_prompt=w.ASTRA_SHARED_SYSTEM_PROMPT, harness="HARNESS_BLOCK")
    assert "shared filesystem" in captured["sp"].lower()  # base shared contract
    assert "HARNESS_BLOCK" in captured["sp"]              # harness appended
