# Harness Engineering for LLM Agents — Field Survey & 5 Practitioner Profiles

> Research report for the Astraeus project. Every factual claim carries a source URL.
> "Verified" = corroborated across multiple independent sources. Several primary domains
> blocked automated fetching this session, so a few exact quotes/dates are
> search-snippet-sourced, not byte-confirmed (see the verification caveats at the end).
> Compiled 2026-06-21.

---

## 1. What "harness engineering" means

The **harness** is the scaffolding and runtime wrapped *around* a raw language model that turns it
into an agent: system-prompt construction, tool definition and exposure, the tool-calling loop, the
execution environment/sandbox, context and memory management, permissions, and observability. The
model is the "brain"; the harness is the loop and plumbing. The most authoritative primary anchors
are Anthropic's engineering posts, which frame the distinction between **workflows** ("systems where
LLMs and tools are orchestrated through predefined code paths") and **agents** ("systems where LLMs
dynamically direct their own processes and tool usage") ([Anthropic, "Building Effective Agents",
2024-12-19](https://www.anthropic.com/research/building-effective-agents)), and which later
decompose a long-running agent explicitly into session / harness / sandbox layers ([Anthropic,
"Effective harnesses for long-running agents",
2025-11-26](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)).
LangChain has since proposed a working taxonomy that names the layer directly: *"LangChain is the
abstraction. LangGraph is the runtime. Deep Agents are the harness."* ([LangChain, "Agent
Frameworks, Runtimes, and Harnesses — oh my!",
2025-10-25](https://www.langchain.com/blog/agent-frameworks-runtimes-and-harnesses-oh-my)).

> **Synthesis vs. fact:** "Harness engineering" is not yet a single canonical term with one coiner;
> it is an emerging label for a real and converging body of practice (tool/ACI design, context
> engineering, loop + sandbox design). The definition above is a synthesis of how the cited sources
> use the constituent ideas.

---

## 2. Five influential people

### 1. Barry Zhang — Anthropic (Applied AI)
- **Role/affiliation:** Member of Technical Staff on Anthropic's Applied AI team ([speaker bio](https://thefocus.ai/reports/aiecode-2025-11/speakers/barry-zhang/)).
- **Why he matters:** Co-author (with **Erik Schluntz**, MTS at Anthropic — [profile](https://theorg.com/org/anthropic/org-chart/erik-schluntz)) of **"Building Effective Agents,"** the single most-cited practitioner framework for agent construction, and its public-facing voice via conference talks. It argues the most successful implementations use **simple, composable patterns**, not heavy frameworks ([Building Effective Agents](https://www.anthropic.com/research/building-effective-agents)).
- **Key ideas:** The **workflows vs. agents** distinction and five workflow patterns — prompt chaining, routing, parallelization, **orchestrator–workers**, and evaluator–optimizer; the **agent–computer interface (ACI)** appendix, which argues teams should invest as much in tool design as in prompts; and his talk distillation: *don't use agents for everything; keep it simple; think from the agent's perspective.* A later talk pushes "build skills, not agents."
- **Artifacts:**
  - "Building Effective Agents" — https://www.anthropic.com/research/building-effective-agents (with Erik Schluntz; 2024-12-19)
  - Talk: "How We Build Effective Agents," AI Engineer Summit 2025 — https://www.youtube.com/watch?v=D7_ipDqhtwk
  - Talk: "Don't Build Agents, Build Skills Instead" — https://www.youtube.com/watch?v=CEvIs9y1uog

> *The orchestrator–workers pattern is the one most directly mirrored by Astraeus. The ACI
> appendix's exact wording could not be byte-verified (anthropic.com blocked automated fetch).*

### 2. Ofir Press — Princeton (with John Yang & Carlos E. Jiménez)
- **Role/affiliation:** Postdoc at Princeton Language & Intelligence ([Q&A](https://ai.princeton.edu/news/2025/meet-postdoc-qa-ofir-press); [site](https://ofir.io/about/)). Senior author on work led by **John Yang** ([site](https://john-b-yang.github.io/)) and **Carlos E. Jiménez** ([site](https://www.carlosejimenez.com/)).
- **Why they matter:** The academic origin of the **Agent-Computer Interface (ACI)** thesis — agent performance is driven by the *interface between the model and the computer*, not the model alone. **SWE-bench** ([arXiv 2310.06770](https://arxiv.org/abs/2310.06770), ICLR 2024) established a hard, realistic eval (2,294 real GitHub issues across 12 Python repos); **SWE-agent** then closed much of the gap purely by engineering the interface ([arXiv 2405.15793](https://arxiv.org/abs/2405.15793), NeurIPS 2024).
- **Key ideas:** An ACI "specifies the commands available to the LM and how the environment state after the execution of each command will be communicated back to the LM" ([SWE-agent docs](https://swe-agent.com/1.0/background/aci/)). Four design principles: actions simple/easy for the agent; actions compact/efficient; environment feedback informative but concise; **guardrails** (e.g., a syntax checker) to halt and recover from error propagation. A *~100-line* "mini" agent later scored >74% on SWE-bench Verified ([mini-swe-agent](https://mini-swe-agent.com)) — the interface, not harness bulk, carries the weight.
- **Artifacts:**
  - SWE-agent paper — https://arxiv.org/abs/2405.15793 · SWE-bench paper — https://arxiv.org/abs/2310.06770
  - Repo — https://github.com/SWE-agent/SWE-agent · ACI docs — https://swe-agent.com/1.0/background/aci/

> *A report that Carlos Jiménez is "now at Anthropic" appeared in search synthesis but could not be
> confirmed against a primary page — treat as unverified. Exact paper quotes are snippet-sourced.*

### 3. Thorsten Ball — Sourcegraph (Amp)
- **Role/affiliation:** Engineer at Sourcegraph working on **Amp**; author of *Writing An Interpreter In Go* ([interpreterbook.com](https://interpreterbook.com/)); writes the *Register Spill* newsletter.
- **Why he matters:** His post **"How to Build an Agent"** is the canonical demonstration that a capable code-editing agent is *not* mysterious — it is "an LLM, a loop, and enough tokens," buildable in well under ~400 lines, most of it boilerplate. It deflated the mystique around agent harnesses and triggered ports in many languages.
- **Key ideas:** The minimal viable harness = model + loop + a few tools (`read_file`, `list_files`, `edit_file`); the genuine complexity lives in the *model*, not the scaffolding (subtitle: *"or: The Emperor Has No Clothes"*).
- **Artifacts:**
  - "How to Build an Agent" — https://ampcode.com/notes/how-to-build-an-agent (≈2025-04-15)
  - Podcast: Changelog #648, "Agent, take the wheel" — https://changelog.com/podcast/648

> *ampcode.com blocked automated fetch; the thesis is reconstructed from corroborated extracts and
> secondary ports. The three tool names are confirmed via ports rather than the locked primary page.*

### 4. Dexter Horthy — HumanLayer
- **Role/affiliation:** Founder & CEO of HumanLayer (YC F24) ([YC](https://www.ycombinator.com/companies/humanlayer); [GitHub](https://github.com/dexhorthy)).
- **Why he matters:** Author of **"12-Factor Agents,"** a widely cited manifesto arguing reliable agents are *mostly well-engineered deterministic software with LLM calls at key points*, not autonomous loops — drawn from conversations with 100+ builders ([repo](https://github.com/humanlayer/12-factor-agents)).
- **Key ideas — the 12 factors (verbatim from the README):** 1. Natural Language to Tool Calls; 2. Own your prompts; 3. Own your context window; 4. Tools are just structured outputs; 5. Unify execution state and business state; 6. Launch/Pause/Resume with simple APIs; 7. Contact humans with tool calls; 8. Own your control flow; 9. Compact Errors into Context Window; 10. Small, Focused Agents; 11. Trigger from anywhere; 12. Make your agent a stateless reducer (+ bonus 13: pre-fetch context). Later talks push **"Advanced Context Engineering"** and a spec-first Research/Plan/Implement workflow.
- **Artifacts:**
  - Repo — https://github.com/humanlayer/12-factor-agents
  - Talk: "12-Factor Agents," AI Engineer World's Fair 2025 — https://www.youtube.com/watch?v=8kMaTybvDUw
  - Talk: "Advanced Context Engineering for Agents" — https://www.youtube.com/watch?v=IS_y40zY-hc

> *The 12 factor names are byte-verified from the repo README.*

### 5. Simon Willison — independent
- **Role/affiliation:** Independent developer/researcher; creator of Datasette and the `llm` CLI; co-creator of Django; coined "prompt injection" ([about](https://simonwillison.net/about/)).
- **Why he matters:** Supplies the field's *definitional clarity* and *security framing*. His crowdsourced definition of an agent and his security model for what a harness must constrain are widely adopted (swyx defers to him on "Defining Agents").
- **Key ideas:** An agent as a model **running tools in a loop** toward a goal ([2025-09-18](https://simonwillison.net/2025/Sep/18/agents/); ["tools in a loop", 2025-05-22](https://simonwillison.net/2025/May/22/tools-in-a-loop/)). The **"lethal trifecta"** — (a) access to private data, (b) exposure to untrusted content, and (c) the ability to externally communicate — that makes a tool-equipped agent exfiltration-vulnerable ([2025-06-16](https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/)). Practical loop/tool design via the `llm` CLI ([2025-05-27](https://simonwillison.net/2025/May/27/llm-tools/)) and ["Designing agentic loops", 2025-09-30](https://simonwillison.net/2025/Sep/30/designing-agentic-loops/).
- **Artifacts:** the posts linked above, plus his agent-definitions tag — https://simonwillison.net/tags/agent-definitions/

> *simonwillison.net blocked automated fetch; exact quote strings/dates are cross-corroborated via
> search snippets. The concept "tools in a loop" is solid; precise wording varies by post.*

### Honorable mentions (strong, but cut to keep exactly 5)
- **Harrison Chase** (co-founder/CEO, LangChain) — ships the harness layer itself: **LangGraph** ([repo](https://github.com/langchain-ai/langgraph)) and **`deepagents`**, described literally as *"The batteries-included agent harness"* ([repo](https://github.com/langchain-ai/deepagents)). **Directly relevant — this is the harness Astraeus runs on.** Cut only because his influence is as a *builder/vendor*; see Implications.
- **Geoffrey Huntley** (Sourcegraph/Amp) — the "Ralph" loop-until-done pattern and aggressive **context-budget discipline** (over-installing MCP tools wastes the token budget) ([ghuntley.com/agent](https://ghuntley.com/agent/), [ghuntley.com/ralph](https://ghuntley.com/ralph/)).
- **swyx (Shawn Wang)** — coined "AI Engineer" and convenes the discourse (Latent Space), but by his own deference to Willison is a *namer/convener* more than a harness-technique innovator ([latent.space/p/agent](https://www.latent.space/p/agent)).

---

## 3. Key techniques & principles (synthesis)

- **The harness is small; the model carries the load.** Ball (~300–400 lines), the Princeton team (~100-line mini-agent >74% on SWE-bench Verified), and Zhang/Schluntz ("keep it simple") all argue against heavy scaffolding. *(The strongest cross-cutting claim.)*
- **Design the agent–computer interface, not just the prompt.** The ACI thesis (Press/Yang/Jiménez) and Anthropic's tool-writing guidance agree: build a *few high-impact, consolidated* tools; tool descriptions are prompts; return high-signal, token-efficient output ([Anthropic, "Writing effective tools for AI agents", 2025-09-11](https://www.anthropic.com/engineering/writing-tools-for-agents)).
- **Context engineering — curate the working set.** Find "the smallest possible set of high-signal tokens" ([Anthropic, "Effective context engineering", 2025-09-29](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)); own your context window (Horthy, factors 3 & 9); compaction, structured note-taking, sub-agents that return summaries. *(Attribution caveat: "context engineering" was popularized June 2025 by Tobi Lütke, amplified by Andrej Karpathy — who endorsed, not coined it — with an early definition from Cognition's Walden Yan; no single coiner is established.)*
- **Own your control flow and keep agents small + focused.** Horthy (factors 8, 10, 12: stateless reducer); Zhang ("small, focused"); Anthropic's orchestrator–workers pattern.
- **Verification and guardrails as first-class harness components.** SWE-agent's syntax-checker guardrail; Anthropic's "give the agent a way to verify its work… show evidence rather than asserting success" ([Claude Code best practices](https://www.anthropic.com/engineering/claude-code-best-practices)); evaluator–optimizer loops.
- **Constrain permissions against the lethal trifecta.** Willison: private data + untrusted content + external communication = exfiltration risk; a sandbox/permissions design should break at least one leg.
- **Observability/evals drive iteration.** LangSmith (Chase); Anthropic's prototype→evaluate→collaborate tool-refinement loop.

---

## 4. Implications for a multi-agent orchestrator like Astraeus

Astraeus is, in the Anthropic taxonomy, an **orchestrator–workers workflow** ([Building Effective
Agents](https://www.anthropic.com/research/building-effective-agents)) — the exact pattern
Zhang/Schluntz describe — and it runs on the harness Harrison Chase ships: **`deepagents`, "the
batteries-included agent harness,"** on LangGraph ([repo](https://github.com/langchain-ai/deepagents)).
Field lessons that map onto the project:

- **Keep each Astra's harness minimal and its tool surface small.** Ball and the SWE-agent mini-agent results say a worker needs little more than a scoped shell + file tools; resist adding tools that burn the context budget (Huntley). Astraeus's per-container `DockerSandbox` (a handful of file/shell ops) is the right instinct.
- **Treat the worker's tools/feedback as a deliberate ACI.** Concise, informative test/error feedback plus a guardrail that catches broken edits before they propagate (SWE-agent principle 4) maps directly onto the bounded red-test repair loop — the "return the gate log to the Astra" design is an ACI feedback-formatting decision, not just plumbing.
- **Own context and control flow at the orchestrator.** Horthy's "stateless reducer" + "compact errors into context" argue for the orchestrator sequencing same-file edits and handing each worker a fresh, high-signal context rather than an accumulating transcript — consistent with the Phase 2 orchestrator-sequenced edits and JSON transcript.
- **Make verification a harness component, not an afterthought.** The merge gate *is* Astraeus's evaluator; Anthropic's "show evidence, don't assert success" supports gating on real `pytest` exit codes over model self-report.
- **Mind the lethal trifecta in the Docker sandboxes.** Once workers run untrusted task code with repo access and any network egress, Willison's trifecta applies; Astraeus's `--network none` + sandbox boundary already breaks the "externally communicate" leg.

---

## Sources

**Definition / Anthropic**
- https://www.anthropic.com/research/building-effective-agents
- https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents
- https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- https://www.anthropic.com/engineering/writing-tools-for-agents
- https://www.anthropic.com/engineering/claude-code-best-practices
- https://www.youtube.com/watch?v=D7_ipDqhtwk · https://www.youtube.com/watch?v=CEvIs9y1uog
- https://theorg.com/org/anthropic/org-chart/erik-schluntz · https://thefocus.ai/reports/aiecode-2025-11/speakers/barry-zhang/

**SWE-agent / ACI (Princeton)**
- https://arxiv.org/abs/2405.15793 · https://arxiv.org/abs/2310.06770
- https://github.com/SWE-agent/SWE-agent · https://swe-agent.com/1.0/background/aci/ · https://mini-swe-agent.com
- https://john-b-yang.github.io/ · https://www.carlosejimenez.com/ · https://ofir.io/about/ · https://ai.princeton.edu/news/2025/meet-postdoc-qa-ofir-press

**Thorsten Ball / Geoffrey Huntley**
- https://ampcode.com/notes/how-to-build-an-agent · https://changelog.com/podcast/648 · https://interpreterbook.com/
- https://ghuntley.com/agent/ · https://ghuntley.com/ralph/

**Dexter Horthy / 12-Factor Agents**
- https://github.com/humanlayer/12-factor-agents · https://github.com/humanlayer/12-factor-agents/blob/main/README.md
- https://www.youtube.com/watch?v=8kMaTybvDUw · https://www.youtube.com/watch?v=IS_y40zY-hc · https://www.ycombinator.com/companies/humanlayer

**Simon Willison**
- https://simonwillison.net/2025/Sep/18/agents/ · https://simonwillison.net/2025/May/22/tools-in-a-loop/ · https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/ · https://simonwillison.net/2025/Sep/30/designing-agentic-loops/ · https://simonwillison.net/about/

**Honorable mentions / context-engineering attribution**
- https://github.com/langchain-ai/langgraph · https://github.com/langchain-ai/deepagents · https://www.langchain.com/blog/agent-frameworks-runtimes-and-harnesses-oh-my · https://blog.langchain.com/the-rise-of-context-engineering/
- https://www.latent.space/p/agent · https://cognition.ai/blog/dont-build-multi-agents

---

## Verification caveats (read before publishing exact quotes)

1. **Several primary domains blocked automated fetching this session** (anthropic.com,
   simonwillison.net, ampcode.com, ghuntley.com, latent.space, x.com, blog.langchain.com). URLs,
   authorship, dates, and core ideas are cross-corroborated, but **byte-exact quotes/dates from
   those domains should be confirmed in a browser** before publication-grade quoting. **Byte-verified:**
   the 12-Factor Agents factor names, SWE-agent paper metadata + author list, and the GitHub
   descriptions for LangGraph/deepagents.
2. **"Context engineering" has no established single coiner.** Earliest exact-phrase use found ≈Apr
   2025; popularized by Tobi Lütke (~Jun 19, 2025) and amplified by Andrej Karpathy (~Jun 25, 2025,
   who *endorsed* not coined it); early definition from Walden Yan/Cognition. Do not attribute
   coinage to Karpathy, Willison, or Chase.
3. **Unconfirmed personal facts (excluded or flagged):** Carlos Jiménez "now at Anthropic"; Huntley's
   exact Sourcegraph title; exact publication days of several blog posts.
4. **Data-quality flag:** the search surfaced likely AI-generated spam — fabricated arXiv IDs in the
   `2606.*` range and a ResearchGate item recasting a Willison blog post as a paper. These were
   **excluded** and should not be cited.
5. **The "exactly 5" selection is an editorial judgment.** Chase, Huntley, and swyx are well-sourced
   and were cut only to honor the count; all three appear in honorable mentions.
