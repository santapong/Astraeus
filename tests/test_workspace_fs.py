"""Docker-gated: the central shared workspace volume is one tree the orchestrator
seeds, reads, commits, and pushes. No LLM — real git in real containers. Skips
cleanly when the docker daemon is unavailable.
"""

import subprocess
import uuid

import pytest

import src.orchestrator as o
from src.docker_backend import IMAGE


def _docker_available():
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=15).returncode == 0
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _docker_available(), reason="docker daemon not available")


def _seed_origin(volume):
    subprocess.run(["docker", "volume", "create", volume], check=True, capture_output=True)
    seed = ("git init -q --bare /origin && rm -rf /tmp/s && git clone -q /origin /tmp/s && "
            "cd /tmp/s && echo seed > README && git add -A && git commit -q -m init && "
            "git push -q origin HEAD:main")
    subprocess.run(["docker", "run", "--rm", "--network", "none", "-v", f"{volume}:/origin",
                    IMAGE, "sh", "-c", seed], check=True, capture_output=True)


@pytest.fixture
def volumes():
    origin = f"astraeus_test_o_{uuid.uuid4().hex[:8]}"
    ws = f"astraeus_test_w_{uuid.uuid4().hex[:8]}"
    _seed_origin(origin)
    o.reset_workspace_volume(origin_volume=origin, workspace_volume=ws)
    try:
        yield origin, ws
    finally:
        subprocess.run(["docker", "volume", "rm", "-f", origin], capture_output=True)
        subprocess.run(["docker", "volume", "rm", "-f", ws], capture_output=True)


def test_seed_show_round_trip(volumes):
    _, ws = volumes
    o.seed_workspace_file(".astraeus/task.md", "hello task", workspace_volume=ws)
    assert o.workspace_show(".astraeus/task.md", workspace_volume=ws) == "hello task"


def test_commit_appears_in_log(volumes):
    origin, ws = volumes
    o.seed_workspace_file("note.txt", "x\n", workspace_volume=ws)
    o.commit_workspace("astraeus: test commit", origin_volume=origin, workspace_volume=ws)
    log = o.workspace_git(["log", "--oneline"], origin_volume=origin, workspace_volume=ws).stdout
    assert "astraeus: test commit" in log


def test_push_candidate_creates_branch_on_origin(volumes):
    origin, ws = volumes
    o.seed_workspace_file("a.py", "x = 1\n", workspace_volume=ws)
    o.commit_workspace("astraeus: a", origin_volume=origin, workspace_volume=ws)
    o.push_candidate(origin_volume=origin, workspace_volume=ws)
    branches = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "-v", f"{origin}:/origin",
         IMAGE, "git", "-C", "/origin", "branch"], capture_output=True, text=True).stdout
    assert "candidate" in branches
