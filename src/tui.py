"""Astraeus dashboard — a terminal view of a run (Milestones B static + D live).

Renders a `/workspace/.astraeus/run.json` transcript as panels: plan, rounds, per-worker
status, the gate verdict, the timeline, and the origin `main` log. With a *source* it
re-reads the transcript on an interval and refreshes the panels live while a run is in
progress (the orchestrator re-flushes run.json each round/gate-attempt — Milestone C).

This is a *viewer* only — never imported by `orchestrator.py`/`worker.py`, so a missing
`textual` dep can never break a run. Install with `uv sync --extra tui`.

Design: the transcript -> view-model functions are plain and live at module top (no
`textual` import, so they're unit-testable without the dep). The Textual App is built
lazily in `build_app()` / `main()`, so `import src.tui` works even when textual is absent.

Usage:
    uv run --extra tui python -m src.tui [PATH]            # static view of a saved run.json
    uv run --extra tui python -m src.tui --watch [PATH]    # live: re-read the file on an interval
    uv run --extra tui python -m src.tui --volume          # live: tail run.json in the docker volume
With no PATH it opens the bundled sample at docs/examples/sample_run.json.
"""

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SAMPLE = os.path.normpath(os.path.join(_HERE, "..", "docs", "examples", "sample_run.json"))


# --- pure transcript -> view-model (no textual; unit-tested directly) ---------

def load_transcript(path):
    """Load a run.json transcript dict from a file path."""
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def plan_lines(result):
    """One line per subtask: id, its files, and a trimmed instruction."""
    out = []
    for p in result.get("plan", []):
        files = ", ".join(p.get("files", []))
        instr = (p.get("instruction", "") or "").strip().replace("\n", " ")
        if len(instr) > 60:
            instr = instr[:57] + "..."
        out.append(f"{p.get('id', '?')}  {files} — {instr}")
    return out


def round_lines(result):
    """One line per round; ║ marks subtasks that run in parallel within the round."""
    return [f"R{i + 1}: " + " ║ ".join(rnd) for i, rnd in enumerate(result.get("rounds", []))]


def worker_rows(result):
    """(id, files, status) per subtask — status from the per-worker `outcomes` map."""
    outcomes = result.get("outcomes", {})
    rows = []
    for p in result.get("plan", []):
        wid = p.get("id", "?")
        files = ", ".join(p.get("files", []))
        rows.append((wid, files, outcomes.get(wid, "?")))
    return rows


def gate_lines(result):
    """Gate verdict: explicit terminal state, attempts used, the bool, and a log tail."""
    log = (result.get("gate_log", "") or "").strip().replace("\n", " ")
    if len(log) > 70:
        log = log[-70:]
    return [
        f"state:    {result.get('gate_state', '?')}",
        f"attempts: {result.get('gate_attempts', '?')}",
        f"landed:   {result.get('landed', '?')}",
        f"log:      {log}",
    ]


def timeline_lines(result):
    """`+  t.tts [id] event` per timeline entry (already sorted by the orchestrator)."""
    out = []
    for e in result.get("timeline", []):
        out.append(f"+{float(e.get('t', 0)):>7.2f}s [{e.get('id', '?')}] {e.get('event', '')}")
    return out


def summary_text(result):
    """The origin `main` git log captured at the end of the run."""
    return result.get("origin_log", "") or "(no origin log)"


def status_style(status):
    """Rich color for a worker outcome (READY green, FAILED_* red, else yellow)."""
    if status == "READY":
        return "green"
    if str(status).startswith("FAILED"):
        return "red"
    return "yellow"


# --- live sources: callables returning a fresh transcript dict (or None) ------

def file_source(path):
    """A source that re-reads a run.json file; returns None if it's missing/unreadable."""
    def read():
        try:
            return load_transcript(path)
        except (OSError, ValueError):
            return None
    return read


def volume_source(workspace_volume=None):
    """A source that reads run.json from the docker workspace volume (live runs). Needs a
    Docker daemon; returns None on any failure. Imports the orchestrator lazily so this
    module stays import-safe without docker."""
    def read():
        try:
            from src import orchestrator as o
            raw = o.workspace_show(".astraeus/run.json",
                                   workspace_volume=workspace_volume or o.WORKSPACE_VOLUME)
            return json.loads(raw) if raw and raw.strip() else None
        except Exception:  # noqa: BLE001 — a viewer must tolerate a not-yet-ready run
            return None
    return read


# --- Textual app (lazy import; only needed to construct/run the viewer) -------

def build_app(result, source=None, interval=1.0):
    """Construct (do not run) the Textual viewer over `result`. If `source` is given (a
    callable returning a fresh transcript dict, or None), the app re-reads it every
    `interval` seconds and refreshes the panels live. Imports textual lazily."""
    from rich.text import Text
    from textual.app import App, ComposeResult
    from textual.containers import Horizontal
    from textual.widgets import DataTable, Footer, Header, RichLog, Static

    class AstraeusViewer(App):
        CSS = """
        Static.panel { border: round $accent; padding: 0 1; margin: 0 1; }
        #workers { border: round $accent; margin: 0 1; height: auto; }
        #timeline { border: round $accent; margin: 0 1; height: 1fr; }
        """
        BINDINGS = [("q", "quit", "Quit"), ("r", "refresh", "Refresh")]

        def __init__(self, result, source=None, interval=1.0):
            super().__init__()
            self._r = result
            self._source = source
            self._interval = interval

        def compose(self) -> ComposeResult:
            yield Header()
            with Horizontal():
                yield Static(classes="panel", id="plan")
                yield Static(classes="panel", id="rounds")
            yield DataTable(id="workers")
            yield Static(classes="panel", id="gate")
            yield RichLog(id="timeline", markup=True)
            yield Static(classes="panel", id="summary")
            yield Footer()

        def on_mount(self):
            self.title = "Astraeus"
            self.query_one("#workers", DataTable).add_columns("id", "files", "status")
            self._apply(self._r)
            if self._source is not None:
                self.set_interval(self._interval, self._poll)

        def _poll(self):
            new = self._source()
            if new is not None and new != self._r:
                self._apply(new)

        def action_refresh(self):
            self._poll()

        def _apply(self, result):
            self._r = result
            self.sub_title = result.get("task", "")
            self.query_one("#plan", Static).update("\n".join(plan_lines(result)) or "(no plan)")
            self.query_one("#rounds", Static).update("\n".join(round_lines(result)) or "(no rounds)")
            self.query_one("#gate", Static).update("\n".join(gate_lines(result)))
            self.query_one("#summary", Static).update(summary_text(result))
            table = self.query_one("#workers", DataTable)
            table.clear()
            for (wid, files, status) in worker_rows(result):
                table.add_row(wid, files, Text(status, style=status_style(status)))
            log = self.query_one("#timeline", RichLog)
            log.clear()
            for line in timeline_lines(result):
                log.write(line)

    return AstraeusViewer(result, source=source, interval=interval)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    paths = [a for a in argv if not a.startswith("-")]
    if "--volume" in argv:
        source = volume_source()
        result = source() or {"task": "(waiting for run.json in the workspace volume)"}
    else:
        path = paths[0] if paths else _SAMPLE
        source = file_source(path) if "--watch" in argv else None
        result = load_transcript(path)
    build_app(result, source=source).run()


if __name__ == "__main__":
    main()
