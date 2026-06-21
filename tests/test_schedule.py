"""Pure tests for round scheduling — disjoint files run in parallel, shared files
are sequenced into separate rounds. No docker, no model.
"""

from src.orchestrator import schedule


def _s(id_, files):
    return {"id": id_, "files": files}


def test_all_disjoint_single_round():
    st = [_s("w1", ["a.py"]), _s("w2", ["b.py"]), _s("w3", ["c.py"])]
    rounds = schedule(st)
    assert len(rounds) == 1
    assert {s["id"] for s in rounds[0]} == {"w1", "w2", "w3"}


def test_shared_file_sequenced_into_two_rounds():
    st = [_s("w1", ["calc.py"]), _s("w2", ["calc.py"])]
    rounds = schedule(st)
    assert len(rounds) == 2
    assert [r[0]["id"] for r in rounds] == ["w1", "w2"]  # input order preserved


def test_disjoint_pair_shares_round_third_sequenced():
    # w1=[a], w2=[b] disjoint -> round 0; w3=[a] shares with w1 -> round 1.
    st = [_s("w1", ["a.py"]), _s("w2", ["b.py"]), _s("w3", ["a.py"])]
    rounds = schedule(st)
    assert len(rounds) == 2
    assert {s["id"] for s in rounds[0]} == {"w1", "w2"}
    assert [s["id"] for s in rounds[1]] == ["w3"]


def test_within_a_round_all_pairwise_disjoint():
    st = [_s("w1", ["a.py", "x.py"]), _s("w2", ["x.py"]), _s("w3", ["b.py"])]
    for rnd in schedule(st):
        seen = set()
        for s in rnd:
            fs = {f.lower() for f in s["files"]}
            assert seen.isdisjoint(fs)
            seen |= fs


def test_case_insensitive_overlap():
    st = [_s("w1", ["Calc.py"]), _s("w2", ["calc.py"])]
    assert len(schedule(st)) == 2
