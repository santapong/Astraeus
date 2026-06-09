"""Tiny no-dependency loader for a bash-style `.env` (KEY="val" / export KEY="val").

The repo's `.env` uses `export KEY="val"` syntax and the platform shell is
PowerShell, so nothing loads it automatically — and python-dotenv is not an
allowed dependency in Phase 0. This parses the file into os.environ once, in the
orchestrator process. Subprocesses (merge_gate's pytest, orchestrator git) inherit
os.environ, so loading here covers them too. setdefault means a real shell export
still wins over the file.
"""

import os
from pathlib import Path


def load_dotenv_exports(path=".env"):
    """Parse `export KEY="val"` / `KEY=val` lines from `path` into os.environ."""
    p = Path(path)
    if not p.exists():
        return
    for raw in p.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        # strip an inline comment after the value, then surrounding quotes
        value = value.split("#", 1)[0].strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)
