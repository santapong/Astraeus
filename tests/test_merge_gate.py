"""Container/bare-origin tests for the sandboxed merge gate. No LLM — real git
inside real containers, driven by plain Python. Requires the docker daemon and
the astraeus-worker:phase1 image.

A trivial non-LLM driver seeds a bare origin on a throwaway volume and pushes a
featW1 branch carrying a passing (or failing) test; merge_gate then tests it
inside an ephemeral gate container and merges to origin's main only on green.
"""

import subprocess
import uuid

import pytest

from src.docker_backend import IMAGE
from src.merge_gate import merge_gate


def _docker(args, check=True):
    p = subprocess.run(["docker", *args], capture_output=True, text=True)
    if check and p.returncode != 0:
        raise RuntimeError(f"docker {' '.join(args)} failed ({p.returncode}):\n{p.stdout}{p.stderr}")
    return p


def _docker_available():
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=15).returncode == 0
    except Exception:
        return False


# These tests spin real containers; skip cleanly if docker isn't available.
pytestmark = pytest.mark.skipif(not _docker_available(), reason="docker daemon not available")


def _seed_origin(volume):
    _docker(["volume", "create", volume])
    seed = (
        "git init -q --bare /origin && rm -rf /tmp/seed && git clone -q /origin /tmp/seed && "
        "cd /tmp/seed && echo seed > README && git add -A && git commit -q -m init && "
        "git push -q origin HEAD:main"
    )
    _docker(["run", "--rm", "--network", "none", "-v", f"{volume}:/origin", IMAGE, "sh", "-c", seed])


def _push_branch(volume, branch, *, passing):
    """Non-LLM driver: clone origin, write add()+test, commit, push the branch."""
    expect = "5" if passing else "99"  # add(2,3)==5 passes; ==99 fails deterministically
    script = (
        "rm -rf /tmp/w && git clone -q /origin /tmp/w && cd /tmp/w && "
        f"git checkout -q -b {branch} && "
        "printf 'def add(a, b):\\n    return a + b\\n' > a.py && "
        f"printf 'from a import add\\n\\ndef test_add():\\n    assert add(2, 3) == {expect}\\n' > test_a.py && "
        f"git add -A && git commit -q -m work && git push -q origin {branch}"
    )
    _docker(["run", "--rm", "--network", "none", "-v", f"{volume}:/origin", IMAGE, "sh", "-c", script])


def _origin_main_log(volume):
    return _docker(["run", "--rm", "--network", "none", "-v", f"{volume}:/origin",
                    IMAGE, "git", "-C", "/origin", "log", "--oneline", "main"]).stdout.strip()


@pytest.fixture
def origin():
    volume = f"astraeus_test_{uuid.uuid4().hex[:8]}"
    _seed_origin(volume)
    try:
        yield volume
    finally:
        _docker(["volume", "rm", "-f", volume], check=False)


def test_passing_branch_merges_to_origin_main(origin):
    _push_branch(origin, "featW1", passing=True)
    res = merge_gate("featW1", origin)
    assert res.ok is True
    log = _origin_main_log(origin)
    assert "merge featW1" in log  # landed via --no-ff


def test_failing_branch_is_rejected_and_main_untouched(origin):
    before = _origin_main_log(origin)
    _push_branch(origin, "featW1", passing=False)
    res = merge_gate("featW1", origin)
    assert res.ok is False
    assert res.log.strip() != ""          # the pytest failure log is handed back
    after = _origin_main_log(origin)
    assert "merge featW1" not in after     # nothing merged
    assert after == before                 # origin main untouched
