"""Astraeus dashboard — a read-only terminal view of a finished run (Milestone B / TUI-1).

Renders a completed `/workspace/.astraeus/run.json` transcript as panels: plan, rounds,
per-worker status, the gate verdict, the timeline, and the origin `main` log. This is a
*viewer* only — it is never imported by `orchestrator.py`/`worker.py`, so a missing
`textual` dep can never break a run. Install with `uv sync --extra tui`.

Design: the transcript -> view-model functions are plain and live at module top (no
`textual` import), so they're unit-testable without the dependency. The Textual App is
built lazily in `build_app()` / `main()`, so `import src.tui` works even when textual is
absent (only constructing/running the App needs it).

Usage:
    uv run --extra tui python -m src.tui [path/to/run.json]
With no path it opens the bundled sample at docs/examples/sample_run.json.
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


# --- Textual app (lazy import; only needed to construct/run the viewer) -------

def build_app(result):
    """Construct (do not run) the Textual viewer over `result`. Imports textual lazily."""
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
        BINDINGS = [("q", "quit", "Quit")]

        def __init__(self, result):
            super().__init__()
            self._r = result

        def compose(self) -> ComposeResult:
            yield Header()
            with Horizontal():
                yield Static("\n".join(plan_lines(self._r)) or "(no plan)",
                             classes="panel", id="plan")
                yield Static("\n".join(round_lines(self._r)) or "(no rounds)",
                             classes="panel", id="rounds")
            yield DataTable(id="workers")
            yield Static("\n".join(gate_lines(self._r)), classes="panel", id="gate")
            yield RichLog(id="timeline", markup=True)
            yield Static(summary_text(self._r), classes="panel", id="summary")
            yield Footer()

        def on_mount(self):
            self.title = "Astraeus"
            self.sub_title = self._r.get("task", "")
            table = self.query_one("#workers", DataTable)
            table.add_columns("id", "files", "status")
            for (wid, files, status) in worker_rows(self._r):
                table.add_row(wid, files, Text(status, style=status_style(status)))
            log = self.query_one("#timeline", RichLog)
            for line in timeline_lines(self._r):
                log.write(line)

    return AstraeusViewer(result)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    path = argv[0] if argv else _SAMPLE
    build_app(load_transcript(path)).run()


if __name__ == "__main__":
    main()
