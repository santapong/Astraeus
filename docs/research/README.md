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

## Deep dives (10-expert panels, June 2026)

Three standalone reports from a 30-agent research fan-out (10 experts each), extending the notes
above with a larger bench and dedicated tracks. Same format (definition → 10 experts → synthesis →
implications for Astraeus → sources → verification caveats); every claim cited, fetch-blocked
sources flagged, no fabricated citations.

- **[harness-sandbox-deep.md](harness-sandbox-deep.md)** — harness engineering + **per-agent
  sandbox isolation** (7 harness / 3 sandbox): John Yang · Erik Schluntz · Boris Cherny ·
  Carlos Jiménez · swyx · Hamel Husain · Paul Gauthier (harness/ACI) + E2B · gVisor · Firecracker
  (Docker → gVisor → microVM isolation spectrum).
- **[central-filesystem.md](central-filesystem.md)** — the central shared filesystem many agents
  read/write: Linus Torvalds (Git) · Marc Shapiro (CRDTs) · Kevin Jahns (Yjs) · Rob Pike (Plan 9) ·
  OverlayFS · Peak Ji (Manus) · Charles Packer (MemGPT) · Sanjay Ghemawat (GFS) · Eelco Dolstra
  (Nix) · Barbara Hayes-Roth (blackboard).
- **[loop-engineering-deep.md](loop-engineering-deep.md)** — the outer orchestration loop +
  multi-agent patterns: Yohei Nakajima (BabyAGI) · Geoffrey Huntley (Ralph) · Joon Sung Park
  (Generative Agents) · Toran Bruce Richards (AutoGPT) · Chi Wang (AutoGen) · João Moura (CrewAI) ·
  Aman Madaan (Self-Refine) · Guanzhi Wang (Voyager) · Nuno Campos (LangGraph) · Walden Yan
  (Cognition — the "don't build multi-agents" counterpoint).
