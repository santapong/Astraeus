# Loop Engineering for LLM Agents: A Field Guide and Expert Profiles

> Research report for the Astraeus project. Profiles 5 named experts on agentic
> loop design, synthesizes the patterns, and maps them to Astraeus's `run_task`
> loop + bounded red-test repair. Every factual claim is cited; web facts current
> as of June 2026.

## 1. What "loop engineering" is

*Loop engineering* (a.k.a. agentic loop design) is the practice of designing the **control loop**
an LLM agent runs in — the repeated cycle of *reason → act → observe → revise* — together with
its **stopping conditions, retry/repair logic, memory, and control flow**. Rather than asking a
model to emit a final answer in one shot, an agentic workflow has the model iterate: take an
action, observe the result, and update its plan, looping until a goal or a guardrail (success
check, retry budget, or wall-clock cap) is met ([Lilian Weng, "LLM Powered Autonomous Agents,"
2023](https://lilianweng.github.io/posts/2023-06-23-agent/); [Andrew Ng, four agentic design
patterns, 2024](https://x.com/AndrewYNg/status/1773393357022298617)). The engineering discipline
is in *the loop itself*: what each iteration does, how feedback re-enters the next iteration, and
when the loop is allowed (or forced) to stop ([Harrison Chase / LangGraph](https://www.langchain.com/langgraph)).

---

## 2. The five experts

### 2.1 Shunyu Yao — the reason↔act interleaving loop (ReAct)

- **Role / affiliation:** Researcher; lead author of ReAct, done in the Princeton NLP group with
  Google collaborators (published at ICLR 2023).
- **Why he matters to loop design:** ReAct defined the canonical inner loop of a tool-using
  agent — **interleave a reasoning trace with a task action, then feed the environment
  observation back in** — the structural template most modern agent loops still follow.
- **Key ideas / contributions:** Generating *reasoning traces* and *task-specific actions* in an
  interleaved manner so the two reinforce each other: reasoning helps induce, track, and update
  plans and handle exceptions, while actions query external sources/environments to gather
  information.
- **Artifacts:**
  - *ReAct: Synergizing Reasoning and Acting in Language Models*, arXiv:2210.03629 — https://arxiv.org/abs/2210.03629
  - Project page: https://react-lm.github.io/
  - Code: https://github.com/ysymyth/ReAct

### 2.2 Noah Shinn — verbal self-reflection + bounded retries (Reflexion)

- **Role / affiliation:** Lead author of Reflexion (NeurIPS 2023); co-authors include Shunyu Yao
  and Karthik Narasimhan.
- **Why he matters to loop design:** Reflexion is the reference design for a **bounded retry loop
  with a self-critique step** — exactly the shape of Astraeus's bounded red-test repair. The agent
  does not silently retry; it *reflects in words on why it failed*, stores that reflection, and
  uses it to do better on the next bounded trial.
- **Key ideas / contributions:** Reinforce a language agent through *linguistic* feedback rather
  than weight updates — convert binary/scalar feedback (e.g., a failing test) into a textual
  self-reflection, keep it in episodic memory, and condition the next attempt on it (a "semantic
  gradient" across a small number of trials).
- **Artifacts:**
  - *Reflexion: Language Agents with Verbal Reinforcement Learning*, arXiv:2303.11366 — https://arxiv.org/abs/2303.11366
  - Code: https://github.com/noahshinn/reflexion

### 2.3 Lilian Weng — the synthesis: planning, reflection, memory, tools

- **Role / affiliation:** AI researcher; author of the widely cited *Lil'Log* essay on LLM agents
  (written while at OpenAI), published June 23, 2023.
- **Why she matters to loop design:** Her essay is the standard **conceptual map** of an LLM-agent
  loop, framing the LLM as the "brain/controller" surrounded by *planning* (incl. subgoal
  decomposition and self-reflection), *memory*, and *tool use* — the vocabulary most teams now use
  to reason about loop architecture.
- **Key ideas / contributions:** Decomposes autonomous agents into planning (task decomposition +
  reflection/refinement such as ReAct, Reflexion, Chain-of-Hindsight), memory (short-term context
  vs. long-term vector store), and tool use; surveys early systems (AutoGPT, GPT-Engineer,
  BabyAGI).
- **Artifacts:**
  - *LLM Powered Autonomous Agents*, Lil'Log, 2023-06-23 — https://lilianweng.github.io/posts/2023-06-23-agent/

### 2.4 Harrison Chase — graph-based control flow and explicit stopping (LangGraph)

- **Role / affiliation:** Co-founder & CEO of LangChain; creator of LangGraph.
- **Why he matters to loop design:** LangGraph operationalizes loop engineering as **explicit,
  inspectable control flow**. Instead of hoping the model loops correctly, you model the agent as
  a stateful directed graph — nodes (LLM calls, tool calls, validators, routers), edges, and a
  shared state — that supports *cycles*, conditional routing, and explicit stopping conditions.
- **Key ideas / contributions:** Controllability over implicit agent loops (you own the execution
  graph); a production runtime with streaming, persistence/statefulness, human-in-the-loop, and
  durable execution; cyclic graphs as the primitive that distinguishes an "agent" from a linear
  "chain."
- **Artifacts:**
  - LangGraph overview: https://www.langchain.com/langgraph
  - Course: *AI Agents in LangGraph* (DeepLearning.AI) — https://www.deeplearning.ai/courses/ai-agents-in-langgraph

### 2.5 Andrew Ng — agentic design patterns (reflection, tool use, planning, multi-agent)

- **Role / affiliation:** Founder of DeepLearning.AI; the patterns were popularized via *The
  Batch* / DeepLearning.AI and his public posts in 2024.
- **Why he matters to loop design:** Ng gave the field its shared, accessible **pattern language**
  for iterative agentic workflows, explicitly arguing that *iterating* (an agentic workflow) beats
  single-shot generation — the core thesis behind loop engineering.
- **Key ideas / contributions:** Four design patterns — **Reflection** (the model critiques and
  revises its own output across iterations), **Tool Use**, **Planning** (flagged as less mature /
  less predictable), and **Multi-Agent Collaboration** (specialized agents with their own
  prompts/tools coordinating). The strongest systems combine several patterns.
- **Artifacts:**
  - Post summarizing the four patterns: https://x.com/AndrewYNg/status/1773393357022298617
  - *The Batch* / DeepLearning.AI: https://www.deeplearning.ai/the-batch/

---

## 3. Key patterns & principles (synthesis)

- **ReAct loop (reason → act → observe):** the base inner cycle — interleave a thought, a tool
  action, and an observation, then repeat ([arXiv:2210.03629](https://arxiv.org/abs/2210.03629)).
- **Reflection / Reflexion (evaluator–critic loop):** after an attempt, produce a *verbal*
  critique of what went wrong and condition the next attempt on it; generalizes to any "generate →
  critique → revise" loop ([arXiv:2303.11366](https://arxiv.org/abs/2303.11366); [Andrew Ng,
  2024](https://x.com/AndrewYNg/status/1773393357022298617)).
- **Plan-and-execute / decomposition:** break a goal into subtasks, optionally (re)prioritize,
  then execute ([Lil'Log, 2023](https://lilianweng.github.io/posts/2023-06-23-agent/); [Andrew Ng,
  2024](https://x.com/AndrewYNg/status/1773393357022298617)).
- **Bounded loops & stopping criteria:** real agents need a budget — a fixed number of trials and/
  or explicit terminal conditions — so a failing loop halts and reports instead of spinning
  ([arXiv:2303.11366](https://arxiv.org/abs/2303.11366); [LangGraph](https://www.langchain.com/langgraph)).
- **Graph-based control flow:** make the loop *explicit and inspectable* — nodes, edges, cycles,
  conditional routing, shared state — rather than emergent from a prompt ([LangGraph](https://www.langchain.com/langgraph)).
- **Multi-agent decomposition:** split work across specialized agents that coordinate ([Andrew Ng,
  2024](https://x.com/AndrewYNg/status/1773393357022298617)).
- **Memory across iterations:** carry short-term context and long-term memory so each iteration
  benefits from prior ones ([Lil'Log, 2023](https://lilianweng.github.io/posts/2023-06-23-agent/)).

---

## 4. Implications for Astraeus's `run_task` loop + bounded repair

Astraeus's pipeline — **decompose → schedule subtasks into rounds → dispatch worker agents →
automated test gate with bounded red-test repair → JSON transcript**, with per-agent wall-clock
caps — is a multi-pattern composition of the loops above. The `decompose` step is the
*plan-and-execute / decomposition* pattern (Weng's planning component; Ng's Planning + Multi-Agent
Collaboration), and dispatching disjoint subtasks to workers is multi-agent role specialization
with coordination handled by the orchestrator ([Lil'Log, 2023](https://lilianweng.github.io/posts/2023-06-23-agent/);
[Andrew Ng, 2024](https://x.com/AndrewYNg/status/1773393357022298617)). The most direct mapping is
the **bounded red-test repair**: a Reflexion-style evaluator–critic loop where the *test gate* is
the environment's feedback signal, and the worker should turn a failing test into a *verbal
reflection* ("the test expected X, my output did Y, so I will change Z") that conditions the single
retry — not a blind re-run ([arXiv:2303.11366](https://arxiv.org/abs/2303.11366)). The literature
strongly endorses *bounding* this repair: Reflexion operates over a small fixed number of trials,
and robust runtimes pair loops with explicit stopping conditions — exactly what the retry budget
plus per-agent wall-clock cap provide ([arXiv:2303.11366](https://arxiv.org/abs/2303.11366);
[LangGraph](https://www.langchain.com/langgraph)).

Two concrete takeaways. First, **make the gate's feedback first-class in the retry prompt**:
passing the failing test log back verbatim is good, but adding a short structured self-reflection
step before the repair attempt is what the Reflexion result predicts will most improve the bounded
retry's success rate ([arXiv:2303.11366](https://arxiv.org/abs/2303.11366)). Second, **treat the
run loop as explicit control flow with logged terminal states** — success, retry-exhausted, and
timeout should each be distinct, recorded outcomes in the JSON transcript, mirroring LangGraph's
principle that an agent's loop, cycles, and stopping conditions should be inspectable rather than
implicit; that makes the per-agent wall-clock cap a real terminal edge rather than an ad-hoc abort
([LangGraph](https://www.langchain.com/langgraph)). The JSON transcript itself doubles as the
episodic memory/audit trail Weng's taxonomy calls for ([Lil'Log, 2023](https://lilianweng.github.io/posts/2023-06-23-agent/)).

---

## 5. Alternates considered

- **Geoffrey Huntley — the "Ralph" persistent-loop technique.** A deliberately brute-force loop: a
  shell loop that re-runs an agent, **starting each iteration with a fresh context window** and
  feeding prior output/errors back in, until the task converges. Relevant to Astraeus as a contrast
  point — it manages "context rot" by *resetting* context per iteration rather than accumulating
  it. Not in the main five because it is a practitioner technique/blog body of work rather than a
  primary research contribution. https://ghuntley.com/ralph/ , https://ghuntley.com/loop/
- **Yohei Nakajima — BabyAGI task loop.** An ~100-line agent (April 3, 2023) running a **task
  creation → prioritization → execution** loop over an LLM plus a vector memory store; many later
  frameworks start from this decomposition idea. An influential demo/system rather than the
  canonical scholarly statement (Weng and Ng cover the pattern more authoritatively).
  https://yoheinakajima.com/birth-of-babyagi/

---

## 6. Sources

- https://arxiv.org/abs/2210.03629 (ReAct paper)
- https://react-lm.github.io/ (ReAct project page)
- https://github.com/ysymyth/ReAct (ReAct code)
- https://arxiv.org/abs/2303.11366 (Reflexion paper)
- https://github.com/noahshinn/reflexion (Reflexion code)
- https://lilianweng.github.io/posts/2023-06-23-agent/ (Lilian Weng, LLM Powered Autonomous Agents)
- https://www.langchain.com/langgraph (LangGraph)
- https://www.deeplearning.ai/courses/ai-agents-in-langgraph (AI Agents in LangGraph course)
- https://x.com/AndrewYNg/status/1773393357022298617 (Andrew Ng, four agentic design patterns)
- https://www.deeplearning.ai/the-batch/ (The Batch / DeepLearning.AI)
- https://ghuntley.com/ralph/ , https://ghuntley.com/loop/ (Geoffrey Huntley, "Ralph" loop)
- https://yoheinakajima.com/birth-of-babyagi/ (Yohei Nakajima, Birth of BabyAGI)

## 7. Uncertainty notes

Affiliations are stated at the time of each artifact (e.g., Lilian Weng's essay was written while
at OpenAI; ReAct reflects Princeton/Google at publication) and current employers may differ. Andrew
Ng's four-patterns content was released as a *series* across *The Batch* in 2024; the consolidated
public post and *The Batch* hub are cited rather than each individual letter. The Huntley "Ralph"
material is self-published blog content. LangGraph launch/start timing comes from secondary
summaries rather than a single official changelog.
