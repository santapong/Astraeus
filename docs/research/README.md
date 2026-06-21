# Astraeus — Research notes

Background research informing Astraeus's design. Every claim is cited; web facts current as of
June 2026. These are reference/research docs, **not** a commitment to build — for the system itself
see [../ARCHITECTURE.md](../ARCHITECTURE.md).

- **[harness-engineering.md](harness-engineering.md)** — what "harness engineering" is, profiles of
  5 practitioners (Barry Zhang · Ofir Press / SWE-agent · Thorsten Ball · Dexter Horthy ·
  Simon Willison), synthesized principles, and implications for Astraeus.
- **[loop-engineering.md](loop-engineering.md)** — agentic loop design, profiles of 5 experts
  (Shunyu Yao / ReAct · Noah Shinn / Reflexion · Lilian Weng · Harrison Chase / LangGraph ·
  Andrew Ng), and how they map onto `run_task`'s bounded red-test repair.
- **[terminal-ui.md](terminal-ui.md)** — TUI framework survey (Textual, Rich, prompt_toolkit,
  urwid, curses; Go Bubble Tea; Rust ratatui; JS Ink) plus a concrete Textual dashboard design for
  watching an Astraeus orchestration run live.
