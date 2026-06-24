# Harness engineering & per-agent sandboxing — deep dive (10 experts)

> Deep-dive research report extending [harness-engineering.md](harness-engineering.md) with a
> larger bench (10 profiles) and a dedicated **per-agent sandbox/isolation** track. Every claim
> is cited; web facts current as of **June 2026**. Reference/research notes — **not** a commitment
> to build; for the system itself see [../ARCHITECTURE.md](../ARCHITECTURE.md).
>
> **Fetch caveat (whole document):** automated `WebFetch` was blocked (HTTP 403) on many primary
> domains this session (anthropic.com, latent.space, aider.chat, e2b.dev, hamel.dev, gvisor.dev
> pages, the arXiv/USENIX PDFs). URLs are canonical and cross-corroborated across independent
> search results, but **byte-exact quotes/dates should be confirmed in a browser** before
> publication-grade quoting. Per-expert confidence is noted in each caveat blockquote.

## 1. What "harness engineering + per-agent sandboxing" means

A **harness** is everything around the model that turns a raw LLM into a working agent: the tool
set and how tools report results (the **agent–computer interface, ACI**), the context it is given,
the loop that drives it, and the **sandbox** its actions execute in. "Harness engineering" is the
discipline of designing that scaffold; the recurring empirical finding across the people below is
that **the harness often moves task success as much as the model does** — the same model can swing
tens of points under different scaffolds.

This document splits into two tracks the user requested as one topic (7 harness / 3 sandbox):
- **Harness / ACI (§2.1–2.7):** tool design, context, edit formats, evals, and the practitioner
  vocabulary that has grown up around shipping coding agents.
- **Per-agent sandbox isolation (§2.8–2.10):** how each agent gets its own disposable execution
  environment, and the isolation-strength spectrum (Docker → gVisor → Firecracker microVM).

> **Synthesis vs. fact:** "harness engineering" is an emerging label, not a single canonical term
> with one coiner; the definition above synthesizes how the cited sources use the constituent ideas
> (ACI, context engineering, loop design, sandboxing). It crystallized as practitioner vocabulary
> through 2025–2026 (swyx, Cherny, LangChain).

## 2. The ten experts

### 2.1 John Yang — Agent performance is gated by the Agent–Computer Interface, not just the model

- **Role / affiliation:** CS PhD student at Stanford (advised by Diyi Yang); previously master's at Princeton NLP (advised by Karthik Narasimhan); creator/lead of SWE-bench, SWE-agent, and mini-SWE-agent ([profile](https://john-b-yang.github.io/)).
- **Why he matters to harness design:** Yang's SWE-agent work reframes the central question of coding agents from "which model?" to "what interface does the model act through?" — showing that a small set of deliberately engineered tools and feedback formats (the ACI) can multiply a fixed model's task-solving rate. This is the conceptual backbone for Astraeus's few-tool worker harness and its structured pytest→owner feedback loop.
- **Key ideas / contributions:**
  - **The Agent–Computer Interface (ACI) thesis:** like humans, LM agents need interfaces purpose-built for them. SWE-agent's ACI "offers a small set of simple actions for viewing, searching through and editing files, uses guardrails to prevent common mistakes, and provides agents with specific, concise feedback about command effects at every turn" [(SWE-agent)](https://arxiv.org/abs/2405.15793).
  - **High-signal feedback beats raw capability:** a custom file editor that runs a **linter at edit time** — showing errors plus a before/after snippet — curbs compounding mistakes from a single bad edit. Directly analogous to Astraeus handing a worker its own red-pytest log for one bounded reflect-then-fix.
  - **Empirical payoff:** with GPT-4 Turbo, SWE-agent solved ~12.5% of full SWE-bench and 18.0% of SWE-bench Lite vs. a prior RAG best of 3.8% — the interface, not the model, drove the jump [(SWE-agent)](https://arxiv.org/abs/2405.15793).
  - **Radical minimalism (mini-SWE-agent):** a ~100-line agent with **bash as its only tool**, no LM tool-calling, a linear history, and `subprocess.run` per action (stateless → easy sandboxing) that still scores >74% on SWE-bench Verified — putting "the language model rather than the agent scaffold in the middle of attention" [(mini-swe-agent)](https://github.com/SWE-agent/mini-swe-agent).
  - **Design lesson for Astraeus:** the mini-SWE-agent stance validates Astraeus's thin worker with few tools inside an ephemeral, network-isolated container rather than an elaborate framework.
- **Artifacts:**
  - "SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering" — https://arxiv.org/abs/2405.15793 (NeurIPS 2024)
  - mini-SWE-agent (~100 lines, >74% SWE-bench Verified) — https://github.com/SWE-agent/mini-swe-agent
  - SWE-agent project / docs — https://swe-agent.com · profile — https://john-b-yang.github.io/

> *Solid via multiple independent search sources: paper title/ID, full author list, NeurIPS 2024 venue, the ACI principles, solve rates, and mini-SWE-agent's design. Not byte-verified: arxiv.org and the project pages 403'd the fetcher, so exact abstract wording was corroborated via snippets. Confidence: high.*

### 2.2 Erik Schluntz — Harnesses, not frameworks: orchestrator–workers + an evaluator loop, kept deliberately simple

- **Role / affiliation:** Member of Technical Staff at Anthropic (tool use, computer use, agentic coding); previously co-founder & CTO of Cobalt Robotics ([profile](https://theorg.com/org/anthropic/org-chart/erik-schluntz)). Co-author of Anthropic's foundational agent-engineering guidance.
- **Why he matters to harness design:** Schluntz co-wrote the piece that most directly names Astraeus's exact shape — **orchestrator–workers** — and the harness philosophy Astraeus follows: prefer simple, composable, transparent patterns over heavyweight frameworks, and invest in the ACI as much as a human UI. His later Anthropic work on long-running agents maps almost one-to-one onto Astraeus's commit-per-round + sandboxed gate + bounded-repair loop.
- **Key ideas / contributions:**
  - **Workflows vs. agents.** "Building Effective Agents" separates *workflows* (LLMs orchestrated through predefined code paths) from *agents* (dynamically self-directing). Astraeus is squarely a *workflow*: the Python orchestrator owns control flow (decompose → dispatch → gate → merge) and workers have a narrow tool surface [(Building Effective Agents)](https://www.anthropic.com/research/building-effective-agents).
  - **Orchestrator–workers.** A central LLM "dynamically breaks down tasks, delegates them to worker LLMs, and synthesizes their results" — the literal template for Astraeus's host decomposing one task into 2–4 file-disjoint subtasks and dispatching one Astra per subtask.
  - **Evaluator–optimizer.** A generate→critique→revise loop. Astraeus's merge gate is a *deterministic* (pytest, not LLM) instantiation, with the red-test output handed back for ONE bounded repair.
  - **Simplicity, transparency, ACI.** Three stated principles: keep design simple, surface planning steps, and "invest just as much effort in agent-computer interfaces (ACI) as in human-computer interfaces (HCI)."
  - **Harnesses for long-running agents.** Anthropic's follow-up uses an *initializer agent*, a persistent handoff artifact (`PROGRESS.md`) + git history so a fresh context recovers state, and a **fresh-context evaluator subagent** (no write tools) that grades work it never built — mirroring Astraeus's per-round commits as durable state and its isolated gate [(harnesses)](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents) [(repo)](https://github.com/anthropics/cwc-long-running-agents).
  - **Default-FAIL / evidence-gated verification.** Every feature starts failing and flips only after the agent reads real evidence — the sibling of Astraeus merging only on a green sandboxed run.
- **Artifacts:**
  - "Building Effective Agents" — https://www.anthropic.com/research/building-effective-agents (Schluntz & Zhang, Dec 2024)
  - "Effective harnesses for long-running agents" — https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents
  - anthropics/cwc-long-running-agents — https://github.com/anthropics/cwc-long-running-agents

> *Caveat: anthropic.com/theorg.com/latent.space all 403'd; wording/dates corroborated via snippets + the fetchable cwc repo. Treat the harness-piece date (~Nov 2025) as approximate. Confidence: high.*

### 2.3 Boris Cherny — CLAUDE.md, hooks, and "loop engineering" as the definitive practitioner harness

- **Role / affiliation:** Creator and Head of Claude Code, Anthropic (previously Principal Engineer, Meta; author of O'Reilly's *Programming TypeScript*) ([LinkedIn](https://www.linkedin.com/in/bcherny/) · [GitHub](https://github.com/bcherny)).
- **Why he matters to harness design:** Cherny conceived and dog-foods the most widely deployed coding-agent harness in production; his 2025–2026 public discourse crystallized "loop/harness engineering" as practitioner vocabulary for the layer Astraeus occupies.
- **Key ideas / contributions:**
  - **CLAUDE.md as durable, session-persistent context** read at every session start — accumulated conventions, templates, design rules. Maps directly to Astraeus's per-worker context seeding via `/workspace/.astraeus/` [(coverage)](https://www.theneuron.ai/explainer-articles/claude-code-creators-boris-cherny-and-cat-wu-explain-how-to-use-agent-loops/).
  - **Hooks as architecturally enforced policy:** `PreToolUse`/`PostToolUse`/etc. fire deterministic commands at lifecycle events; an exit-code-2 hook *blocks* a tool call unconditionally — non-negotiable boundaries enforced in code, not English [(Hooks)](https://code.claude.com/docs/en/hooks). (Personal design credit unverified this session.)
  - **Subagents as isolated context windows with owned system prompts;** `isolation: worktree` spawns a subagent in a temporary git worktree so many can edit in parallel without conflicts — mirroring Astraeus's per-worker Docker-isolated `/workspace` tree [(Sub-agents)](https://code.claude.com/docs/en/sub-agents).
  - **Skills as demand-loaded instruction bundles** (`SKILL.md`) that load only when invoked, keeping base context lean — parallel to delivering task-specific worker instructions at invocation time [(Skills)](https://code.claude.com/docs/en/skills).
  - **"Loop engineering":** Cherny's June 2026 framing — "I don't prompt Claude anymore… My job is to write loops" — reframes the role from prompt engineering to designing orchestration systems; exactly the layer Astraeus's orchestrator occupies [(loop-engineering)](https://thenewstack.io/loop-engineering/).
  - **"Give the agent a way to verify its work"** as the primary quality multiplier — materialized in Astraeus as the sandboxed pytest gate driving bounded repair.
- **Artifacts:**
  - Claude Code docs — Sub-agents https://code.claude.com/docs/en/sub-agents · Hooks https://code.claude.com/docs/en/hooks · Skills https://code.claude.com/docs/en/skills
  - "Steering Claude Code: skills, hooks, subagents and more" — https://claude.com/blog/steering-claude-code-skills-hooks-rules-subagents-and-more

> *Most primary interviews + the Anthropic blog 403'd; claims corroborated via official Claude Code docs + secondary press. Cherny's role is high-confidence; specific personal design-attributions are medium. Confidence: medium.*

### 2.4 Carlos E. Jiménez — The interface between agent and computer is as decisive as the model itself

- **Role / affiliation:** PhD candidate, Princeton NLP (advised by Karthik Narasimhan) ([profile](https://www.carlosejimenez.com/)).
- **Why he matters to harness design:** Co-creator of SWE-bench — the first benchmark to judge models on *real* GitHub issues using test execution as the sole arbiter — and co-author of SWE-agent, which proved harness design contributes as much as the model. He makes "the test suite is the gate" empirical.
- **Key ideas / contributions:**
  - **Execution-grounded evaluation:** SWE-bench collects 2,294 real GitHub issues from 12 Python repos; a patch must turn failing tests to passing ("fail-to-pass") in a Docker-isolated env — no rubric, only tests decide [(SWE-bench, ICLR 2024)](https://arxiv.org/abs/2310.06770). The best non-interactive LLM resolved only ~1.96%.
  - **ACI as a first-class concern:** SWE-agent's windowed viewer, capped `search_file`/`search_dir`, lint-before-commit edit, and structured feedback lifted GPT-4 Turbo to 12.47% vs. 3.8% prior — a >3× lift from the interface [(SWE-agent)](https://arxiv.org/abs/2405.15793).
  - **Four ACI design principles:** simplicity, efficiency (compact actions), informative-but-concise feedback, and guardrails (linting + hard limits) — directly actionable for any harness builder.
  - **SWE-bench Verified:** a human-validated 500-instance subset (93 developers confirmed solvability/fairness), fixing contamination/noise in the original [(Verified)](https://www.swebench.com/verified.html).
  - **SWE-ReX:** extracted the sandboxed, massively-parallel execution backend into a standalone library — reproducible isolated execution is *infrastructure*, not scaffolding.
- **Artifacts:**
  - "SWE-bench" — https://arxiv.org/abs/2310.06770 (ICLR 2024) · "SWE-agent" — https://arxiv.org/abs/2405.15793 (NeurIPS 2024)
  - SWE-bench Verified — https://www.swebench.com/verified.html · SWE-agent — https://github.com/SWE-agent/SWE-agent

> *arXiv IDs confirmed via HuggingFace/NeurIPS indices; exact pass-rates drawn from secondary sources (PDF 403'd). Current post-PhD position unconfirmed. Confidence: high.*

### 2.5 Shawn "swyx" Wang — The harness is the product surface where AI engineers live

- **Role / affiliation:** Co-founder & CEO of AI Engineer (conference + community); Latent Space podcast; founder of Smol AI ([profile](https://swyx.io/about)).
- **Why he matters to harness design:** Coined/popularized "AI Engineer" — the engineer who wraps foundation models with tooling and orchestration — which defines the *harness* as the primary engineering surface of the role, and has since tracked the framework → runtime → harness evolution for practitioners.
- **Key ideas / contributions:**
  - **"The Rise of the AI Engineer" (June 2023):** a once-multi-year ML project now needs "API docs and a spare afternoon," catalyzing a profession that orchestrates model APIs; Karpathy endorsed it, noting "a lot of glue code/infra around it" [(Karpathy)](https://x.com/karpathy/status/1674873002314563584) [(essay)](https://www.latent.space/p/ai-engineer).
  - **AI Engineer Summit / World's Fair:** institutionalized harness/agent-runtime as the central engineering discourse [(ai.engineer)](https://www.ai.engineer/about).
  - **Harness-in-the-box vs. out-of-the-box:** whether the harness is co-located with the agent brain or separated — affecting isolation, security, deployment [(Latent Space)](https://www.latent.space/p/cognition).
  - **"Is Harness Engineering Real?" (2026):** framed "Big Model vs. Big Harness" with practitioner evidence (Princeton CORE-Bench: same model 42% vs. 78% under different scaffolds; Vercel cutting 80% of tools to lift success) and counter-evidence — "both effects are real; they dominate in different regimes" [(AINews)](https://www.latent.space/p/ainews-is-harness-engineering-real).
  - **"Extreme Harness Engineering":** framing the harness as a disciplined production artifact, successor to "context engineering" [(Latent Space)](https://www.latent.space/p/harness-eng).
- **Artifacts:**
  - "The Rise of the AI Engineer" — https://www.latent.space/p/ai-engineer
  - "[AINews] Is Harness Engineering Real?" — https://www.latent.space/p/ainews-is-harness-engineering-real
  - LangChain "Agent Frameworks, Runtimes, and Harnesses" — https://www.langchain.com/blog/agent-frameworks-runtimes-and-harnesses-oh-my

> *Swyx is an ecosystem cartographer/convener; his contribution is taxonomic/definitional, not empirical. Latent Space pages 403'd, so texts were reconstructed from snippets. Confidence: medium.*

### 2.6 Hamel Husain — You can't improve a harness you haven't instrumented to measure

- **Role / affiliation:** Independent ML/LLM consultant; founder, Parlance Labs; formerly ML at GitHub & Airbnb; co-author (with Shreya Shankar) of *Evals for AI Engineers* (O'Reilly) ([profile](https://www.linkedin.com/in/hamelhusain)).
- **Why he matters to harness design:** Across 35+ AI products, his central finding is that failing products share one root cause — no robust evaluation infrastructure built *before* features. For a harness like Astraeus, that frames the `run.json` transcript as foundational substrate, not convenience.
- **Key ideas / contributions:**
  - **Eval-first development:** build evaluation infrastructure before feature commitments; measure experiments run, not features shipped [(Your AI Product Needs Evals)](https://hamel.dev/blog/posts/evals/) — an argument for treating `run.json` as the primary dev artifact.
  - **Look at your data:** read 30–50 raw traces ("open coding"), build a failure taxonomy ("axial coding") *before* building an LLM judge. In Astraeus: read 30 runs' `run.json` before deciding what to capture.
  - **Domain-specific trace rendering** reduces the friction that makes engineers skip looking at data — directly the role of an Astraeus TUI over `run.json`.
  - **Eval skills for coding agents:** a six-area diagnostic (error analysis, evaluator design, judge validation, human review, labeled data, pipeline hygiene); coding agents can now instrument themselves via MCP, closing the loop on harness quality [(post)](https://hamel.dev/blog/posts/evals-skills/).
  - **Infrastructure > model improvement:** cites Codex harness work as evidence that improving the harness/sandbox/trace collection beats tuning the model — validating Astraeus's "invest in the loop first" priority.
- **Artifacts:**
  - "Your AI Product Needs Evals" — https://hamel.dev/blog/posts/evals/ · "Evals Skills for Coding Agents" — https://hamel.dev/blog/posts/evals-skills/
  - "LLM Evals FAQ" (w/ Shreya Shankar) — https://hamel.dev/blog/posts/evals-faq/ · *Evals for AI Engineers* — https://www.oreilly.com/library/view/evals-for-ai/9798341660717/

> *hamel.dev 403'd; body text reconstructed from summaries (Lenny's, O'Reilly, Maven). Book/course/affiliation high-confidence; exact blog phrasing is paraphrase. Confidence: high.*

### 2.7 Paul Gauthier — Edit format and repo-aware context are the decisive variables in coding-agent ACI

- **Role / affiliation:** Creator of Aider, the terminal AI pair-programmer; independent OSS developer ([GitHub](https://github.com/paul-gauthier)).
- **Why he matters to harness design:** Gauthier has measured, in controlled benchmarks, exactly how edit representation and repo-context presentation change whether an LLM's edits apply cleanly — the two levers Astraeus workers must get right (how much repo they see; how they express mutations).
- **Key ideas / contributions:**
  - **Repository map via tree-sitter + PageRank:** parse every file (130+ languages), rank symbols by reference, serialize a token-budgeted (~1k-token) skeleton into each prompt — a navigable map of the whole codebase without flooding context [(repo-map)](https://aider.chat/2023/10/22/repomap.html).
  - **Edit-format benchmarks swing success dramatically:** on the laziness benchmark, GPT-4 Turbo went 20%→61% switching from search/replace blocks to unified diffs; asking for diff *data* rather than prose yields more complete code [(unified diffs)](https://aider.chat/docs/unified-diffs.html).
  - **Three edit-format tiers:** *whole* (stable, expensive), *diff* (token-efficient, brittle), *udiff* (strong middle ground). For Astraeus workers owning a bounded file subset, diff/udiff keep inter-turn tokens low.
  - **Architect/Editor mode:** split planning (Architect) from edit-emission (Editor); o1-preview + DeepSeek reached 85% polyglot — reasoning about *what* and serializing *how* are different tasks [(architect)](https://aider.chat/2024/09/26/architect.html).
  - **Aider Polyglot leaderboard:** 225 Exercism exercises, 6 languages, two attempts (second gets test-failure feedback) — isolates the generation + diff-apply + test loop, directly analogous to Astraeus's pytest gate [(leaderboards)](https://aider.chat/docs/leaderboards/).
- **Artifacts:**
  - "Building a better repository map with tree sitter" — https://aider.chat/2023/10/22/repomap.html
  - "Unified diffs make GPT-4 Turbo 3X less lazy" — https://aider.chat/docs/unified-diffs.html · "Architect mode" — https://aider.chat/2024/09/26/architect.html
  - Aider leaderboards — https://aider.chat/docs/leaderboards/ · Polyglot — https://github.com/Aider-AI/polyglot-benchmark

> *aider.chat 403'd; benchmark numbers (20%→61%, 85% architect/editor) corroborated via secondary sources but re-verify against primary docs. GitHub profile/org verified directly. Confidence: medium.*

### 2.8 Vasek Mlejnsky (E2B) — Every agent should get its own disposable computer, isolated at the microVM layer

- **Role / affiliation:** Co-founder & CEO of E2B (e2b.dev), an open-source cloud-runtime for isolated, disposable agent sandboxes; founded 2023 with Tomas Valenta ([LinkedIn](https://www.linkedin.com/in/mlejva/)).
- **Why this matters to sandbox design:** E2B is the reference implementation of Astraeus's premise — agent code runs in a per-agent, ephemeral environment the host never trusts — and the strongest argument on the "is plain Docker enough?" question: E2B deliberately chose **Firecracker microVMs** (own kernel per sandbox) over shared-kernel containers, because container escape on a shared host kernel is exactly the threat purpose-built sandboxes defeat.
- **Key ideas / contributions:**
  - **One sandbox per agent/session, from an SDK:** `Sandbox.create()` returns an isolated env with file/shell ops routed in — structurally identical to Astraeus's `DockerSandbox` routing every op through `docker exec` [(E2B)](https://github.com/e2b-dev/E2B).
  - **Firecracker microVMs, not bare containers:** each sandbox runs its own kernel under KVM, so a kernel exploit can't escape to the host — the gap vs. Astraeus's shared-kernel container model [(infra)](https://github.com/e2b-dev/infra).
  - **Fast startup makes disposability practical:** ~150 ms start (snapshot-restore lower) makes "fresh VM per agent, then discard" affordable — the disposability Astraeus gets cheaply from short-lived containers *(exact ms unverified this session)*.
  - **Open-source, framework/model-agnostic (Apache-2.0):** works with LangChain/AutoGen/CrewAI — the sandbox is a substrate any harness plugs into.
  - **Category validation:** $21M Series A (July 2025, Insight Partners), reporting broad Fortune-100 adoption — per-agent isolated execution is a real infra primitive *(exact figures unverified this session)*.
- **Artifacts:**
  - E2B (source + SDKs) — https://github.com/e2b-dev/E2B · infra (Firecracker) — https://github.com/e2b-dev/infra
  - "Firecracker vs QEMU" — https://e2b.dev/blog/firecracker-vs-qemu · docs — https://e2b.dev/docs

> *For Astraeus's `--network none`, no-key-inside threat model (untrusted but not actively multi-tenant-hostile), containers are a defensible Phase-2 choice; E2B's microVM design is the upgrade path if the trust assumption tightens. Role + Firecracker basis + Series A confirmed via GitHub + multiple sources; ms/% figures 403'd. Confidence: high.*

### 2.9 gVisor — A user-space application kernel that shrinks the host attack surface, making container escapes structurally harder

- **Role / affiliation:** Open-source sandboxed container runtime (application kernel) in Go, maintained by Google; OCI-compatible via `runsc`, a drop-in replacement for `runc` in Docker/Kubernetes ([gVisor](https://gvisor.dev/)).
- **Why it matters to sandbox design:** gVisor interposes a userspace kernel (the **Sentry**) between workloads and the host kernel, so agent code never issues syscalls directly to the host — the dominant container-escape mechanism. For Astraeus, swapping `runc`→`runsc` adds a second, independent containment layer protecting the mounted `/origin` and `/workspace` volumes.
- **Key ideas / contributions:**
  - **Sentry (userspace kernel):** intercepts and services syscalls internally; being Go (memory-safe), whole vuln classes vanish — e.g. CVE-2020-14386 (a kernel container-escape) couldn't trigger inside gVisor because the vulnerable C networking code doesn't exist there [(Google Cloud)](https://cloud.google.com/blog/products/containers-kubernetes/how-gvisor-protects-google-cloud-services-from-cve-2020-14386).
  - **Gofer (filesystem proxy):** file ops route through a separate process over 9P — a second boundary between agent code and the `/workspace` volume [(docs)](https://gvisor.dev/docs/).
  - **Drop-in `runsc`:** a one-line `daemon.json` change + `--runtime=runsc`; no image, orchestration, or `--network none` changes — hardening is incremental and reversible [(Docker runtimes)](https://docs.docker.com/engine/daemon/alternative-runtimes/).
  - **Reduced host-kernel surface:** the app's syscalls don't reach the host directly; only the small set the Sentry itself issues do.
  - **Performance trade-off is workload-specific:** CPU-bound ≈ minimal overhead; syscall/IO-heavy can see 10–30% (improved by Directfs). Astraeus's git+file workloads are moderately syscall-intensive.
- **Artifacts:**
  - gVisor — https://github.com/google/gvisor · docs — https://gvisor.dev/docs/ · security model — https://gvisor.dev/docs/architecture_guide/security/
  - CVE-2020-14386 case study — https://cloud.google.com/blog/products/containers-kubernetes/how-gvisor-protects-google-cloud-services-from-cve-2020-14386

> *Not a silver bullet: the Sentry runs as a host userspace process, so a Sentry + host-kernel chain could still escape; syscall coverage is incomplete (may break some workloads). Production-adopter list (Anthropic/OpenAI/Cloudflare) from secondary sources only. Confidence: high (architecture/CVE).*

### 2.10 Firecracker / microVMs — KVM microVMs deliver hardware-grade isolation at near-container startup, setting the hardening ceiling

- **Role / affiliation:** Open-source VMM by AWS for serverless/multi-tenant workloads; Apache 2.0 (2018); powers AWS Lambda & Fargate ([project](https://firecracker-microvm.github.io/) · [GitHub](https://github.com/firecracker-microvm/firecracker)).
- **Why it matters to sandbox design:** Firecracker is the "hardware isolation" end of the spectrum — each workload gets its own KVM-backed kernel/memory, eliminating the shared-kernel surface of plain Docker while keeping cold-start under ~125 ms. It defines Astraeus's hardening ceiling short of confidential computing.
- **Key ideas / contributions:**
  - **Minimal device model:** ~6 emulated devices (vs. hundreds in QEMU), ~50K lines of Rust; a `jailer` adds cgroup/namespace isolation + privilege drop [(FAQ)](https://github.com/firecracker-microvm/firecracker/blob/main/FAQ.md).
  - **125 ms cold start, <5 MiB overhead,** up to ~150 microVMs/s/host — documented in the NSDI '20 paper and FAQ.
  - **The isolation spectrum:** Docker (shared kernel — one CVE affects all) < gVisor (userspace syscall interposition, no hardware boundary) < Firecracker (hardware-enforced memory boundary, native-speed guest syscalls) < confidential VMs — the key decision axis for untrusted code [(comparison)](https://northflank.com/blog/kata-containers-vs-firecracker-vs-gvisor).
  - **AI-sandbox adoption:** E2B runs every agent sandbox in a Firecracker microVM; Fly.io Machines/Sprites use Firecracker; Modal chose gVisor — showing the middle ground stays valid when VMM ops cost is a constraint.
  - **When to harden (Astraeus):** plain `--network none` Docker is reasonable for a controlled research harness with trusted LLM workers; Firecracker becomes warranted when agent code is fully untrusted, workers share a cloud host, or audit demands a documented hardware boundary.
- **Artifacts:**
  - "Firecracker: Lightweight Virtualization for Serverless Applications" — https://www.usenix.org/conference/nsdi20/presentation/agache (NSDI 2020)
  - project — https://firecracker-microvm.github.io/ · GitHub — https://github.com/firecracker-microvm/firecracker

> *Core specs verified via GitHub FAQ; NSDI '20 PDF 403'd (URL canonical). Adopter claims (E2B, Fly.io, Modal/gVisor) from press/blogs. Confidence: high.*

## 3. Key patterns & principles (synthesis)

1. **The ACI is a force multiplier (Yang, Jiménez, Gauthier).** A few high-signal tools with concise, corrective feedback (linters, capped search, structured diffs) beat a sprawling toolset. The harness, not just the model, sets the ceiling.
2. **Prefer simple workflows over autonomous agents where you can (Schluntz, Yang/mini-SWE-agent).** Deterministic, orchestrator-owned control flow + a thin worker is lower-risk and more debuggable than a self-directing mega-agent.
3. **Verification is the quality gate (Schluntz, Cherny, Jiménez).** Evidence-gated, "no self-grading" verification — ideally a fresh-context or deterministic evaluator — is what makes autonomy safe. Tests-as-arbiter is the strongest cheap version.
4. **Context is engineered and file-resident (Cherny, Husain).** Durable, structured context (CLAUDE.md, demand-loaded skills, `.astraeus/`) and instrumented traces are first-class harness components.
5. **You can't improve what you don't measure (Husain, swyx).** The transcript/eval substrate must exist before tuning; harness effects are real but regime-dependent — measure your own.
6. **Sandbox isolation is a spectrum, chosen by threat model (E2B, gVisor, Firecracker).** Docker namespaces → gVisor (userspace kernel) → Firecracker (microVM) trade increasing escape-resistance against startup/ops cost. Pick the weakest boundary that covers your actual adversary, and know your upgrade path.
7. **Disposability + statelessness ease sandboxing (Yang, E2B).** Stateless per-action execution and fresh-per-task environments make isolation cheap and reproducible.

## 4. Implications for Astraeus

Astraeus already embodies much of the consensus above; the gaps it documents map cleanly onto the experts' upgrade paths. (Code refs are to this repo.)

**What the experts validate in the current design:**
- **Few-tool, harness-aware worker** (`src/worker.py`: `ASTRA_SHARED_SYSTEM_PROMPT`, `ASTRA_HARNESS_TEMPLATE`; `make_astra`) is exactly the ACI minimalism of Yang/mini-SWE-agent and Schluntz's "invest in the ACI, keep it simple."
- **Orchestrator–workers as a *workflow*** (`src/orchestrator.py::run_task`) is the literal Schluntz pattern; the deterministic **pytest gate** (`src/merge_gate.py`) is his evaluator–optimizer with a non-LLM critic, and matches Jiménez's "tests are the arbiter" and Cherny's "give the agent a way to verify."
- **Structured feedback routing** (`merge_gate._failing_files` → `orchestrator._owner_for_failure` → `RED_TEST_HANDBACK_MSG`) is the high-signal, concise-feedback principle (Yang's lint-at-edit; SWE-agent's structured env feedback) applied to multi-agent repair.
- **The `_syntax_check` pre-gate guardrail** (`src/orchestrator.py`) is an ACI guardrail in Yang/Jiménez's sense — catch a collection-crashing error before it masks siblings.
- **File-resident shared context** (`/workspace/.astraeus/task.md`, `plan.json`, `run.json`) is Cherny's CLAUDE.md idea and Husain's "trace as primary artifact."
- **Per-agent ephemeral, `--network none`, no-key-inside container** (`src/docker_backend.py::DockerSandbox`; `start_shared_worker`) is the E2B "one disposable sandbox per agent" shape, one isolation layer below microVMs.

**Concrete upgrade paths (tie to documented open questions):**
- **Harden the sandbox by threat model.** Astraeus's docs flag the Docker-escape risk (a breakout reaches the mounted `/origin` + `/workspace`). The cheapest mitigation is **`runsc` (gVisor)** as a drop-in runtime — a one-line `daemon.json` change, no image/orchestration edits (§2.9). If workers ever run fully untrusted code or share a multi-tenant host, move to **Firecracker microVMs / E2B-style per-agent VMs** (§2.8, §2.10). Decision axis: weakest boundary that covers the real adversary.
- **Make discipline code-enforced, not just prompt-enforced.** ARCHITECTURE flags "write only your files / run no git" as prompt-enforced. Cherny's **hooks** and a read-only-except-owned-files mount (overlay/bind) are the architectural enforcement analog — the gate stays the backstop, but violations can be *blocked*, not just caught.
- **Treat `run.json` as the eval substrate (Husain).** Before tuning prompts, read many runs' transcripts and build a failure taxonomy; the existing transcript + TUI are the right foundation.
- **Edit-format awareness (Gauthier).** As tasks grow beyond toy files, how workers express edits (whole-file vs. diff) will affect apply-success; worth measuring on the real worker model.

## 5. Sources

**Harness / ACI (SWE-agent family)**
- https://arxiv.org/abs/2405.15793 · https://arxiv.org/abs/2310.06770 · https://www.swebench.com/verified.html
- https://github.com/SWE-agent/SWE-agent · https://github.com/SWE-agent/mini-swe-agent · https://swe-agent.com · https://john-b-yang.github.io/ · https://www.carlosejimenez.com/

**Anthropic harnesses / Claude Code**
- https://www.anthropic.com/research/building-effective-agents · https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents · https://github.com/anthropics/cwc-long-running-agents
- https://code.claude.com/docs/en/sub-agents · https://code.claude.com/docs/en/hooks · https://code.claude.com/docs/en/skills · https://thenewstack.io/loop-engineering/

**AI Engineer / evals / Aider**
- https://www.latent.space/p/ai-engineer · https://www.latent.space/p/ainews-is-harness-engineering-real · https://www.langchain.com/blog/agent-frameworks-runtimes-and-harnesses-oh-my
- https://hamel.dev/blog/posts/evals/ · https://hamel.dev/blog/posts/evals-skills/ · https://www.oreilly.com/library/view/evals-for-ai/9798341660717/
- https://aider.chat/2023/10/22/repomap.html · https://aider.chat/docs/unified-diffs.html · https://aider.chat/2024/09/26/architect.html · https://aider.chat/docs/leaderboards/

**Per-agent sandboxing**
- https://github.com/e2b-dev/E2B · https://github.com/e2b-dev/infra · https://e2b.dev/blog/firecracker-vs-qemu
- https://github.com/google/gvisor · https://gvisor.dev/docs/ · https://cloud.google.com/blog/products/containers-kubernetes/how-gvisor-protects-google-cloud-services-from-cve-2020-14386 · https://docs.docker.com/engine/daemon/alternative-runtimes/
- https://www.usenix.org/conference/nsdi20/presentation/agache · https://github.com/firecracker-microvm/firecracker · https://northflank.com/blog/kata-containers-vs-firecracker-vs-gvisor

## 6. Verification caveats

1. **Automated fetch was widely blocked (HTTP 403)** this session on anthropic.com, latent.space, aider.chat, e2b.dev, hamel.dev, several gvisor.dev pages, and the arXiv/USENIX/NeurIPS PDFs. URLs are canonical and facts cross-corroborated across independent search results, but **byte-exact quotes/dates were not read from the primary pages** — confirm in a browser before publication-grade quoting.
2. **Dates approximate where flagged:** Anthropic's long-running-agents harness piece (~Nov 2025) and follow-ups were not byte-verified.
3. **Personal attribution caveats:** specific Claude Code design credits to Boris Cherny (hooks/subagent isolation) are attributed to "Claude Code (Anthropic)" where individual authorship couldn't be confirmed; gVisor's production-adopter list (Anthropic/OpenAI/Cloudflare) is from secondary sources only.
4. **Benchmark numbers** (Aider edit-format swings; SWE-bench pass rates; Firecracker 125 ms/<5 MiB; E2B startup/adoption) were corroborated via secondary sources where the primary PDF/page 403'd — treat precise figures as "approximately verified."
5. **No fabricated citations.** Where a fact could not be verified, it is flagged "(unverified this session)" rather than given a fake source; no arXiv IDs in the spam range were used.
