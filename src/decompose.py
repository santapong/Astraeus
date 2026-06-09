"""Decompose ONE task into EXACTLY TWO file-disjoint subtasks.

This is a SINGLE structured model call on the Typhoon runtime — NOT a deep agent.
Only the Astra workers need the agent machinery; planning is one LLM call whose
JSON output is parsed and hard-validated here. On any failure we print the raw
model output and raise (no retry — that is Step 3).
"""

import json
from pathlib import Path

from src.worker import _build_typhoon_model

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "decompose.md"


class DecomposeError(Exception):
    """Raised when the model output is not valid, schema-conforming JSON."""


def _extract_json_array(text):
    """Return the JSON array parsed from `text`, tolerant of stray wrapping.

    Try the whole (fence-stripped) string first; only if that fails, scan from
    the first '[' to its true matching ']' with a depth counter (a naive
    first-'['/last-']' slice would break on a ']' inside an instruction string).
    """
    s = text.strip()
    if s.startswith("```"):
        # drop a leading ```json / ``` fence and any trailing fence
        s = s.split("```", 2)[1] if s.count("```") >= 2 else s.strip("`")
        if s.lower().startswith("json"):
            s = s[4:]
        s = s.strip()

    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass

    start = s.find("[")
    if start == -1:
        raise DecomposeError("no JSON array found in model output")
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(s)):
        c = s[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                return json.loads(s[start:i + 1])
    raise DecomposeError("unterminated JSON array in model output")


def _validate(subtasks):
    """Enforce the Step-2 contract; raise DecomposeError on any violation."""
    if not isinstance(subtasks, list) or len(subtasks) != 2:
        raise DecomposeError(f"expected a list of exactly 2 subtasks, got {subtasks!r}")

    branches = []
    file_sets = []
    for item in subtasks:
        if not isinstance(item, dict):
            raise DecomposeError(f"subtask is not an object: {item!r}")
        for key in ("branch", "files", "instruction"):
            if key not in item:
                raise DecomposeError(f"subtask missing '{key}': {item!r}")
        files = item["files"]
        if not isinstance(files, list) or not files or not all(isinstance(f, str) for f in files):
            raise DecomposeError(f"'files' must be a non-empty list of strings: {item!r}")
        if not isinstance(item["instruction"], str) or not item["instruction"].strip():
            raise DecomposeError(f"'instruction' must be a non-empty string: {item!r}")
        branches.append(item["branch"])
        file_sets.append({f.lower() for f in files})  # lowercase: Windows is case-insensitive

    if set(branches) != {"featW1", "featW2"} or len(branches) != 2:
        raise DecomposeError(f"branches must be exactly featW1 and featW2, got {branches!r}")
    shared = file_sets[0] & file_sets[1]
    if shared:
        raise DecomposeError(f"files must be disjoint across subtasks; shared: {sorted(shared)}")
    return subtasks


def decompose(task, model=None):
    """Split `task` into exactly two file-disjoint subtasks (validated)."""
    model = model or _build_typhoon_model()
    prompt = _PROMPT_PATH.read_text().replace("{task}", task)

    raw = model.invoke(prompt).content
    text = raw if isinstance(raw, str) else str(raw)
    try:
        subtasks = _extract_json_array(text)
        return _validate(subtasks)
    except DecomposeError:
        print("[decompose] RAW MODEL OUTPUT >>>\n" + text + "\n<<< END RAW OUTPUT")
        raise
