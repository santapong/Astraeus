"""Docker-gated: two workers attached to the SAME shared volume see ONE filesystem
(the central FS all sandboxes interact with). No LLM — plain `docker exec` writes.
Skips cleanly when the docker daemon is unavailable.
"""

import subprocess
import uuid

import pytest

import src.orchestrator as o


def _docker_available():
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=15).returncode == 0
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _docker_available(), reason="docker daemon not available")


@pytest.fixture
def shared_ws():
    ws = f"astraeus_test_w_{uuid.uuid4().hex[:8]}"
    subprocess.run(["docker", "volume", "create", ws], check=True, capture_output=True)
    try:
        yield ws
    finally:
        subprocess.run(["docker", "rm", "-f", "astraeus_t1", "astraeus_t2"], capture_output=True)
        subprocess.run(["docker", "volume", "rm", "-f", ws], capture_output=True)


def test_two_workers_share_one_filesystem(shared_ws):
    o.start_shared_worker("astraeus_t1", workspace_volume=shared_ws)
    o.start_shared_worker("astraeus_t2", workspace_volume=shared_ws)

    # Disjoint writes into the SAME tree from two different containers.
    subprocess.run(["docker", "exec", "astraeus_t1", "sh", "-c", "echo A > /workspace/a.py"], check=True)
    subprocess.run(["docker", "exec", "astraeus_t2", "sh", "-c", "echo B > /workspace/b.py"], check=True)

    # Each worker can read the OTHER's file — proof it is one shared filesystem.
    a_from_2 = subprocess.run(["docker", "exec", "astraeus_t2", "cat", "/workspace/a.py"],
                              capture_output=True, text=True).stdout.strip()
    b_from_1 = subprocess.run(["docker", "exec", "astraeus_t1", "cat", "/workspace/b.py"],
                              capture_output=True, text=True).stdout.strip()
    assert a_from_2 == "A"
    assert b_from_1 == "B"

    # And the orchestrator sees both via a throwaway container.
    assert o.workspace_show("a.py", workspace_volume=shared_ws).strip() == "A"
    assert o.workspace_show("b.py", workspace_volume=shared_ws).strip() == "B"
