# The central shared filesystem for multi-agent systems — deep dive (10 experts)

> Deep-dive research report on the design space behind Astraeus's central shared `/workspace`:
> how many sandboxed agents can read/write one tree and coordinate without corrupting each other.
> A new topic (no sealed predecessor). Every claim is cited; web facts current as of **June 2026**.
> Reference/research notes — **not** a commitment to build; for the system itself see
> [../ARCHITECTURE.md](../ARCHITECTURE.md).
>
> **Fetch caveat (whole document):** automated `WebFetch` was blocked (HTTP 403) on many primary
> domains this session (git-scm.com, kernel.org, docker.com, 9p.io, manus.im, the Inria/ACM/USENIX
> PDFs). URLs are canonical and cross-corroborated across independent search results, but
> **byte-exact quotes should be confirmed in a browser** before publication-grade quoting. Per-expert
> confidence is noted in each caveat blockquote.

## 1. What "the central shared filesystem" means here

Astraeus mounts **one** live git working tree (`astraeus_workspace`, at `/workspace`) into every
worker container; a separate bare repo (`astraeus_origin`) holds history and `main`. Workers read
any file but, by convention, write only their assigned files and run **no git**; the orchestrator
commits each round and **sequences** any two subtasks that touch the same file into different rounds
so git never performs a three-way merge. The shared tree is also the **coordination channel**:
`/workspace/.astraeus/` carries `task.md`, `plan.json`, and the `run.json` transcript that every
agent can read.

That design touches four distinct literatures, which this panel spans:
- **Version control & consistency** — how a shared store stays coherent under many writers (Git,
  GFS).
- **Conflict-free concurrency** — letting agents edit the same thing and still converge (CRDTs, Yjs)
  vs. designing the conflict away (scheduling, append-only).
- **Per-agent views over shared backing** — isolation *with* sharing (Plan 9 namespaces, OverlayFS).
- **Filesystem as memory/coordination** — the FS as externalized context (Manus, MemGPT) and the
  classic shared-memory multi-agent pattern (blackboard).

> **Synthesis vs. fact:** the framing above is our synthesis of how these sources bear on Astraeus;
> the individual technical claims are cited per expert.

## 2. The ten experts

### 2.1 Linus Torvalds — Git makes a shared tree safe and auditable by hashing content into an immutable snapshot store; merges are the only risky step

- **Role / affiliation:** Creator of the Linux kernel and of Git; Fellow at the Linux Foundation ([profile](https://en.wikipedia.org/wiki/Linus_Torvalds)).
- **Why he matters to shared-filesystem design:** Git is the substrate Astraeus mounts as `/workspace`, designed as a content-addressable, integrity-checked snapshot store where every state is named by the hash of its contents — exactly what lets many agents read one tree while every committed state stays immutable and auditable. His three-way merge is the one operation Astraeus refuses to lean on, because conflict resolution needs judgment the worker model lacks.
- **Key ideas / contributions:**
  - Built Git in ~10 days in April 2005 (after the kernel lost BitKeeper), prioritizing speed, a fully distributed model, and strong integrity; maintainership passed to Junio Hamano in July 2005 [(GitHub Blog)](https://github.blog/open-source/git/git-turns-20-a-qa-with-linus-torvalds/).
  - Git is "a content-addressable filesystem" — insert content, get back a hash key; an object's name *is* a checksum of its bytes, making corruption/tampering detectable [(Pro Git: Git Objects)](https://git-scm.com/book/en/v2/Git-Internals-Git-Objects).
  - Three immutable object types — **blob**, **tree**, **commit** — so a commit is a full snapshot, not a diff: a shared tree is replayable and auditable at any point.
  - A DVCS gives every clone full history and lets integration happen offline against a known-good base — which Astraeus's gate exploits by cloning the bare origin fresh before promoting a candidate.
  - **Three-way merge** reconciles two tips against their common ancestor; when both change the same region it emits `<<<<<<<`/`=======`/`>>>>>>>` markers for a human (default strategy now `ort`) [(Pro Git: Advanced Merging)](https://git-scm.com/book/en/v2/Git-Tools-Advanced-Merging).
- **Artifacts:**
  - "Pro Git — Git Internals: Git Objects" — https://git-scm.com/book/en/v2/Git-Internals-Git-Objects · "Advanced Merging" — https://git-scm.com/book/en/v2/Git-Tools-Advanced-Merging
  - "Git turns 20: A Q&A with Linus Torvalds" — https://github.blog/open-source/git/git-turns-20-a-qa-with-linus-torvalds/

> *Torvalds designed three-way merge as a feature; Astraeus avoiding merges by sequencing is a property of its weak worker model, not a git defect. git-scm.com 403'd; claims confirmed via search snippets of the canonical pages. Confidence: high.*

### 2.2 Marc Shapiro — Concurrent replicas converge by design, so no coordination is ever needed

- **Role / affiliation:** Distinguished Research Scholar (Emeritus), Delys group, Sorbonne-Université–LIP6 / Inria; co-inventor of CRDTs ([profile](https://lip6.fr/Marc.Shapiro/)).
- **Why he matters to shared-filesystem design:** CRDTs are the principled inverse of Astraeus's strategy — where Astraeus *schedules* same-file subtasks apart so git never merges, CRDTs let every replica accept writes locally and still provably converge. Coordination is engineered out of the *data type*, not the workload.
- **Key ideas / contributions:**
  - **Strong Eventual Consistency:** any replica may update without synchronization, and replicas that delivered the same updates are in the same state — convergence guaranteed by the type, not a lock or scheduler [(SSS 2011)](https://inria.hal.science/inria-00609399v1).
  - **Two dual realizations:** *operation-based* CmRDTs (broadcast commutative ops) and *state-based* CvRDTs (ship state, `merge` via a join-semilattice least-upper-bound) — theoretically equivalent [(Wikipedia: CRDT)](https://en.wikipedia.org/wiki/Conflict-free_replicated_data_type).
  - **A design portfolio:** counters, registers (LWW/MV), sets (G-Set, 2P-Set, OR-Set), graphs, sequences — the catalogue that made CRDTs buildable [(RR-7506)](https://inria.hal.science/inria-00555588/en/).
  - **The trade-off, plainly:** CRDTs trade coordination for *metadata* (tombstones, version vectors) and strong for eventual consistency; convergence is set-theoretic — a deterministic merged *state*, not a *semantically correct* one for code.
- **Artifacts:**
  - "Conflict-free Replicated Data Types" — https://inria.hal.science/inria-00609399v1 (SSS 2011; Shapiro, Preguiça, Baquero, Zawirski)
  - "A comprehensive study of CRDTs" — https://inria.hal.science/inria-00555588/en/ (Inria RR-7506, 2011)

> *Convergence is not comprehension: a character-level text CRDT can merge two valid edits into a syntactically broken file. For Astraeus (workers can't resolve conflicts), "schedule to avoid collisions" sidesteps exactly that semantic-merge gap — at the cost of the parallelism a CRDT would keep. All fetches 403'd; quotes from snippets. Confidence: high.*

### 2.3 Kevin Jahns — CRDT shared types converge concurrent edits without a central arbiter, at production scale

- **Role / affiliation:** Independent OSS developer, Berlin; creator/maintainer of Yjs, co-maintainer of Yrs/y-crdt ([profile](https://github.com/dmonad)).
- **Why he matters to shared-filesystem design:** Jahns built the most widely deployed CRDT framework (22k+ stars, ~900k weekly npm downloads), proving at scale that shared mutable state across many concurrent writers can converge automatically — no locking, no single source of truth, full offline support: the closest practical analogue to what a multi-agent shared workspace needs.
- **Key ideas / contributions:**
  - **Shared types as the unit of concurrency:** `Y.Map`/`Y.Array`/`Y.Text`/`Y.XmlElement` that many writers mutate independently; the framework merges concurrent ops deterministically [(Yjs)](https://github.com/yjs/yjs).
  - **Awareness protocol:** a separate ephemeral CRDT layer for presence (cursors, "who's editing what") without polluting the durable document.
  - **Offline-then-merge:** peers diverge, accumulate local ops, and sync later; the YATA algorithm guarantees convergence without central coordination, enabling P2P topologies [(yjs.dev)](https://yjs.dev/).
  - **Performance-first design:** struct-merging, garbage collection of deleted items, binary encoding (lib0) make CRDT overhead acceptable in real editors.
  - **Cross-language portability via Yrs/y-crdt:** a Rust port binary-compatible with JS Yjs, enabling Python/Ruby/Swift/.NET/Go clients on one shared doc [(y-crdt)](https://github.com/y-crdt/y-crdt).
- **Artifacts:**
  - "Yjs" — https://github.com/yjs/yjs · homepage — https://yjs.dev/ · "Yrs / y-crdt" — https://github.com/y-crdt/y-crdt
  - "How we made Jupyter Notebooks collaborative with Yjs" — https://blog.jupyter.org/how-we-made-jupyter-notebooks-collaborative-with-yjs-b8dff6a9d8af

> *GitHub facts fetched directly; blog/docs URLs 403'd and are flagged. Yjs shows concurrent shared editing is *possible* for agents — but for source code the semantic-merge gap (§2.2) remains. Confidence: high.*

### 2.4 Rob Pike — Per-process private namespaces let every agent compose its own filesystem view over shared 9P-served resources

- **Role / affiliation:** Bell Labs CSRC (1980s–2002); co-creator of Plan 9, Inferno, and Go; since 2002 at Google ([Wikipedia](https://en.wikipedia.org/wiki/Rob_Pike)).
- **Why he matters to shared-filesystem design:** Plan 9's central insight — every process owns a *mutable private namespace* it reshapes with `bind`/`mount`, while all resources (local or remote) are uniformly served over **9P** — means many agents can share the same file servers yet each see a different, independently composed view, with no privileged global mount table.
- **Key ideas / contributions:**
  - **Three-principle architecture:** resources are files; one protocol (9P) accesses all of them; per-process namespaces join disjoint server hierarchies into one *private* view [("Plan 9 from Bell Labs", 1995)](https://www.semanticscholar.org/paper/Plan-9-from-Bell-Labs-Pike-Presotto/d84747ac8b31be455670c20fe975a2f4dcaf7f7e).
  - **Per-process namespace isolation via `bind`/`mount`:** changes are local to a process and its descendants — mounting a device in one terminal doesn't make it visible in another; a direct precedent for per-agent workspace isolation over shared backing [("Use of Name Spaces in Plan 9", 1993)](https://9p.io/sys/doc/names.html).
  - **9P as the universal resource protocol:** ~14–17 message types (attach/walk/open/read/write/create/clunk); every resource is a 9P file server, so an agent needs only a 9P connection to compose any resource into its namespace [(9P2000 RFC)](https://ericvh.github.io/9p-rfc/rfc9p2000.html).
  - **Union directories:** mount multiple servers at one path with ordering flags — an additive, layered view of a shared `/workspace` without copying files.
  - **Namespace inheritance on fork:** a child inherits the parent's namespace; later `bind`/`mount` affect only that group — maps onto an orchestrator forking workers with a common base, each customizing its subtree.
- **Artifacts:**
  - "Plan 9 from Bell Labs" — https://www.semanticscholar.org/paper/Plan-9-from-Bell-Labs-Pike-Presotto/d84747ac8b31be455670c20fe975a2f4dcaf7f7e
  - "The Use of Name Spaces in Plan 9" — https://9p.io/sys/doc/names.html · 9P2000 RFC — https://ericvh.github.io/9p-rfc/rfc9p2000.html

> *9p.io pages 403'd; quotes are paraphrase from secondary summaries; paper metadata is consistent across ACM DL/Semantic Scholar. Confidence: high.*

### 2.5 OverlayFS / union mounts — Copy-on-write layering gives each agent an isolated writable view over a shared read-only base

- **Role / affiliation:** Linux kernel union mount filesystem (mainline since 3.18, 2014); basis of Docker/OCI image layering ([kernel docs](https://docs.kernel.org/filesystems/overlayfs.html)).
- **Why it matters to shared-filesystem design:** OverlayFS gives each agent a private writable surface (`upperdir`) over a common read-only base (`lowerdir`) without copying the base; reads fall through to the shared layer while writes stay isolated until merged down — directly modeling workers consuming a shared `/workspace` snapshot while accumulating their own changes.
- **Key ideas / contributions:**
  - **Four-directory model:** `lowerdir` (read-only base, stackable up to 128 layers), `upperdir` (per-agent writable), `workdir` (kernel scratch for atomic renames), `merged` (unified view) [(kernel docs)](https://docs.kernel.org/filesystems/overlayfs.html).
  - **Copy-on-write via `copy_up`:** first write to a lower-only file copies it up, then writes go to `upperdir`; unmodified reads are zero-copy from `lowerdir`.
  - **Whiteouts for deletions:** deleting in the merged view creates a whiteout in `upperdir` to mask the lower name (opaque dirs for `rmdir`) — `lowerdir` is never touched.
  - **Docker overlay2 driver:** image layers → read-only `lowerdir`, container writable layer → `upperdir`, dedup of shared base layers across containers [(Docker Docs)](https://docs.docker.com/engine/storage/drivers/overlayfs-driver/).
  - **Per-agent overlay as coordination pattern:** launch each agent with its own `upperdir` over a shared base snapshot; afterward the `upperdir` *is* the diff, inspectable and selectively merged back — a filesystem-level `git diff` + merge.
- **Artifacts:**
  - "Overlay Filesystem" (kernel) — https://docs.kernel.org/filesystems/overlayfs.html · "OverlayFS storage driver" (Docker) — https://docs.docker.com/engine/storage/drivers/overlayfs-driver/

> *Filesystem-level isolation, not semantic merge: if two agents `copy_up` and modify the same file, collapsing the uppers silently overwrites one — file-disjoint assignment (as in Astraeus) is still required. All primary URLs 403'd; claims consistent across snippets. Confidence: medium.*

### 2.6 Yichao "Peak" Ji — The file system is the agent's unlimited, persistent, restorable context

- **Role / affiliation:** Co-founder & Chief Scientist, Manus (Butterfly Effect); MIT Tech Review Innovator Under 35 (2025); author of Manus's "Context Engineering for AI Agents" ([profile](https://x.com/peakji)).
- **Why he matters to shared-filesystem design:** Ji gave the cleanest production statement of "the file system *is* the context" — the sandbox FS as unlimited, persistent, agent-operated external memory, not mere storage. That is Astraeus's bet: `.astraeus/` (task.md, plan.json, run.json) is durable, structured context agents read/write on demand instead of stuffing a token window.
- **Key ideas / contributions:**
  - **File system as the "ultimate context":** unlimited, persistent, directly operable; the agent learns to read/write files on demand as externalized structured memory [(MarkTechPost)](https://www.marktechpost.com/2025/07/22/context-engineering-for-ai-agents-key-lessons-from-manus/).
  - **Restorable (lossless) compression:** drop a web page's body if you keep its URL; omit a document's contents while keeping its path — always re-fetchable from the pointer.
  - **Why it's needed:** even 128K+ windows are routinely insufficient for real agentic work (huge observations); offloading bulk to files sidesteps the limit [(ZenML)](https://www.zenml.io/llmops-database/context-engineering-strategies-for-production-ai-agents).
  - **Recitation via `todo.md`:** continuously rewriting a `todo.md` at the end of context steers attention to the global plan and fights goal drift — filesystem-mediated attention.
  - **Context economics:** KV-cache hit rate as the key production metric; ~100:1 input:output ratio is the cost pressure that makes filesystem offload attractive [(Lance Martin)](https://rlancemartin.github.io/2025/10/15/manus/).
- **Artifacts:**
  - "Context Engineering for AI Agents: Lessons from Building Manus" — https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus (Jul 2025) · mirror — https://medium.com/@peakji/context-engineering-for-ai-agents-lessons-from-building-manus-71883f0a67f2

> *manus.im + Medium mirror 403'd; mechanics corroborated via MarkTechPost/ZenML/Lance Martin; wording is paraphrase. For Astraeus, the open "cross-run memory" question is exactly the gap Ji's pattern fills. Confidence: high.*

### 2.7 Charles Packer — Treat the context window as virtual memory, paging info in/out of an external store

- **Role / affiliation:** Co-founder & CEO, Letta (formerly MemGPT); PhD (2024), UC Berkeley Sky Computing Lab (advised by Gonzalez & Stoica) ([profile](https://www.linkedin.com/in/charles-packer/)).
- **Why he matters to shared-filesystem design:** MemGPT established the canonical pattern for agents that must work beyond the window: external storage as "main memory," the window as a small cache, explicit paging between them. Any system using a shared filesystem as durable state — Astraeus included — is a specialized instance of this memory hierarchy.
- **Key ideas / contributions:**
  - **Virtual context management:** window = registers/L1; external tiers = RAM/disk; the agent pages data between tiers via tool calls, making total information effectively unbounded [(MemGPT)](https://arxiv.org/abs/2310.08560).
  - **Three-tier memory:** *core* (always in-context, editable), *recall* (searchable message log), *archival* (vector cold store), managed by functions like `core_memory_append` / `archival_memory_search`.
  - **Interrupt-driven control flow:** triggered by user/timer/tool-result interrupts; may run several internal memory ops before yielding — OS-scheduler-like.
  - **Shared memory blocks for multi-agent coordination:** Letta lets multiple agents share a named memory block — a coordination primitive like a shared file/segment, passing state without messages [(Letta)](https://www.letta.com/blog/memory-blocks).
  - **Agent File (.af):** serializes full agent state (config, history, prompt, memory, tools) to a portable file — a concrete answer to cross-run memory: checkpoint and restore [(agent-file)](https://github.com/letta-ai/agent-file).
- **Artifacts:**
  - "MemGPT: Towards LLMs as Operating Systems" — https://arxiv.org/abs/2310.08560 (Oct 2023) · Letta — https://github.com/letta-ai/letta · Agent File — https://github.com/letta-ai/agent-file

> *arXiv ID confirmed via multiple indices; thesis page 403'd (flagged). Confidence: high.*

### 2.8 Sanjay Ghemawat — Relaxed consistency and scheduling discipline, not locks, tame concurrent writers at scale

- **Role / affiliation:** Senior Fellow (Systems Infrastructure), Google ([profile](https://research.google/people/sanjayghemawat/)).
- **Why he matters to shared-filesystem design:** Ghemawat co-designed GFS, whose central insight — make concurrent multi-writer access tractable by deliberately *relaxing consistency* and routing all metadata through one authority — is the tradeoff Astraeus re-discovers at agent scale: assign ownership statically (one file, one writer) and let an orchestrator own integration.
- **Key ideas / contributions:**
  - **Single-master metadata + leases:** one master holds namespace/chunk metadata; a leased "primary" chunkserver serializes mutations per chunk — collapsing distributed consensus into primary-ordering, the philosophy behind Astraeus's orchestrator-owned commit sequence [(GFS, SOSP 2003)](https://research.google.com/archive/gfs-sosp2003.pdf).
  - **Deliberate relaxed consistency:** "defined" vs. "undefined but consistent" regions led workloads to be redesigned around append-only patterns — the right answer is often to *constrain the write pattern*, not solve the general race.
  - **Atomic record append:** many clients append concurrently without external sync (at-least-once; readers dedup) — Astraeus avoids even needing this by making the orchestrator sole committer.
  - **MapReduce (with Jeff Dean):** map workers write private, file-disjoint intermediates; reduce merges — structurally identical to Astraeus's disjoint-files-then-integrate rule [(MapReduce, OSDI 2004)](https://www.usenix.org/conference/osdi-04/mapreduce-simplified-data-processing-large-clusters).
  - **The single-master ceiling → Colossus:** GFS's master eventually bottlenecked at scale; the successor distributed metadata over Bigtable — a reminder that orchestrator-as-single-authority scales for task-sized work but hits throughput limits as agent counts grow.
- **Artifacts:**
  - "The Google File System" — https://research.google.com/archive/gfs-sosp2003.pdf (SOSP 2003) · "MapReduce" — https://www.usenix.org/conference/osdi-04/mapreduce-simplified-data-processing-large-clusters (OSDI 2004)

> *GFS/MapReduce/Bigtable verified via Google Research/USENIX archives; the Senior Fellow title via secondary sources (profile page 403'd). Confidence: high.*

### 2.9 Eelco Dolstra — Content-addressed, purely functional stores make filesystem state deterministic and reproducible

- **Role / affiliation:** Principal Software Engineer & co-founder, Determinate Systems; creator of Nix/NixOS; PhD, Utrecht University (2006) ([profile](https://determinate.systems/people/eelco-dolstra/)).
- **Why he matters to shared-filesystem design:** Dolstra's insight — filesystem state becomes reproducible when every build output is keyed by a hash of *all* its inputs — formalizes what Astraeus does implicitly by resetting `/workspace` to a known-good clone each run. Content-addressed derivations make that guarantee structural rather than procedural.
- **Key ideas / contributions:**
  - **Content-addressed Nix store:** outputs live at `/nix/store/<hash>-<name>` keyed over all inputs; immutable after creation, so identical inputs land at the same path — structural reproducibility [(NixOS Wiki)](https://nixos.wiki/wiki/Nix_package_manager).
  - **Purely functional deployment (PhD, 2006):** treat components as pure functions of inputs; eliminates "dependency hell" and "works on my machine" with deterministic deployment semantics [(thesis)](https://edolstra.github.io/pubs/phd-thesis.pdf).
  - **Sandboxed, isolated builds:** each derivation builds with only declared deps visible, network/host FS blocked — Astraeus's per-sandbox isolation, enforced structurally via the build graph.
  - **Transparent source→binary substitution:** outputs keyed by input hash let a cache server substitute a prebuilt binary when hashes match — a pinned Docker image is a coarse version of this.
  - **NixOS (ICFP 2008):** extends the model to whole-OS config — proof it scales to thousands of interdependent paths without mutation [(NixOS paper)](https://dl.acm.org/doi/10.1145/1411204.1411255).
- **Artifacts:**
  - "The Purely Functional Software Deployment Model" — https://edolstra.github.io/pubs/phd-thesis.pdf (2006) · NixOS reproducible builds — https://reproducible.nixos.org/

> *Thesis/ACM pages 403'd; venue/DOI confirmed via secondary citations; biographical facts corroborated. Confidence: high.*

### 2.10 Barbara Hayes-Roth — Blackboard control: structured shared-state coordination among independent agents

- **Role / affiliation:** Senior Research Scientist & Lecturer, Stanford Knowledge Systems Lab (1982–2002); creator of BB1 ([KSL profile](http://www-ksl.stanford.edu/people/bhr/)).
- **Why she matters to shared-filesystem design:** BB1 made the blackboard model a general coordination architecture: independent knowledge sources read/write a shared structured store — the blackboard — instead of messaging each other. Her 1985 paper formalized the "control problem" (who acts next given shared state), directly anticipating how Astraeus agents coordinate through `/workspace` + `.astraeus/` without exchanging messages.
- **Key ideas / contributions:**
  - **Blackboard as shared global memory** (from Hearsay-II, 1980): independent knowledge sources deposit/read/modify partial solutions; agents are decoupled — none knows another exists, each monitors the blackboard for its trigger [(Hearsay-II, Computing Surveys 1980)](https://dl.acm.org/doi/10.1145/356810.356816).
  - **Control as a first-class blackboard problem:** BB1's innovation — a separate *control* blackboard holding pending activations, with control KSs reasoning about what to do next — makes scheduling opportunistic and data-driven [(A Blackboard Architecture for Control, AI Journal 1985)](https://dl.acm.org/doi/10.1016/0004-3702(85)90063-3).
  - **Opportunistic execution:** agents act when the current state creates an opportunity (cf. Astraeus agents reading `plan.json` to decide what to do).
  - **Domain/control separation:** domain blackboard (partial solutions) vs. control blackboard (scheduling) — analogous to Astraeus's task.md/plan.json (intent) vs. run.json (execution state).
  - **Self-monitoring / meta-reasoning:** control KSs detect stalls and switch strategy — a template for Astraeus's bounded retry (hand back once, then escalate).
- **Artifacts:**
  - "A Blackboard Architecture for Control" — https://dl.acm.org/doi/10.1016/0004-3702(85)90063-3 (*Artificial Intelligence* 26(3), 1985)
  - "The Hearsay-II Speech-Understanding System" (Erman, F. Hayes-Roth, Lesser, Reddy) — https://dl.acm.org/doi/10.1145/356810.356816 (Computing Surveys 1980)

> *Authorship nuance: **Barbara** Hayes-Roth authored the 1985 control paper / BB1; **Frederick** Hayes-Roth was a Hearsay-II co-author (same lineage). 1985 paper verified via ACM DL; KSL/BB1 TR pages 403'd. Confidence: high.*

## 3. Key patterns & principles (synthesis)

1. **Content-addressing + immutability = auditable shared state (Torvalds, Dolstra).** Hash-keyed snapshots make a shared tree replayable, tamper-evident, and reproducible — the foundation under "many readers, one history."
2. **You can design coordination away, two ways (Shapiro/Jahns vs. Ghemawat/Astraeus).** Either make the data type conflict-free (CRDTs) or constrain the *workload* (append-only; one-writer-per-file scheduling). For source code, the semantic-merge gap makes the second route the safer one.
3. **Isolation *with* sharing via per-agent views (Pike, OverlayFS).** Per-process namespaces and copy-on-write overlays let each agent see/modify its own view over one shared base, then merge the diff down — structural enforcement of "touch only your part."
4. **A single authority tames concurrency — until it doesn't (Ghemawat).** One master/orchestrator serializing mutations is simple and correct at modest scale, with a known throughput ceiling (GFS→Colossus) as agent counts grow.
5. **The filesystem is externalized memory/context (Ji, Packer).** Files are unlimited, persistent, restorable context the agent pages in/out — and the natural substrate for cross-run memory (Agent File `.af`).
6. **Agents coordinate through shared structured state, not messages (Hayes-Roth).** The blackboard is the 40-year-old root of `/workspace` + a transcript: decoupled workers + opportunistic, data-driven control.

## 4. Implications for Astraeus

(Code refs are to this repo.)

**What the experts validate in the current design:**
- **Git as the coordination substrate** (`src/docker_backend.py`: `ORIGIN_VOLUME`, `WORKSPACE_VOLUME`; `src/orchestrator.py`: `commit_workspace`, `push_candidate`) is Torvalds's content-addressable, auditable snapshot model used exactly as intended.
- **Sequencing same-file edits instead of merging** (`src/orchestrator.py::schedule`, the round commit loop) is endorsed from two directions: Shapiro's caveat (CRDT convergence ≠ semantic correctness for code) and Ghemawat's GFS lesson (constrain the write pattern — one-writer-per-file — rather than solve the general race). Astraeus's "git never three-way-merges" is the right call for a weak worker model.
- **Orchestrator as sole committer** mirrors GFS's single-master mutation ordering — simple and correct at N≤`MAX_WORKERS`.
- **`/workspace/.astraeus/` as shared structured memory** (`seed_workspace_file` writing task.md/plan.json/run.json) is precisely Hayes-Roth's blackboard (domain vs. control: plan.json = intent, run.json = execution state) and Ji/Packer's "filesystem as context."
- **Per-run workspace reset for reproducibility** (`reset_workspace_volume`) is a procedural approximation of Dolstra's content-addressed determinism.
- **Gate clones origin fresh, never mounts the shared workspace** (`src/merge_gate.py`) keeps the verifier's state defined/clean — a GFS-style "defined region" discipline.

**Concrete upgrade paths (tie to documented open questions):**
- **Make "write only your files" structural, not prompt-enforced.** ARCHITECTURE flags this as a convention. **OverlayFS per-agent `upperdir`** over a shared read-only base (§2.5), or **Plan 9-style per-agent namespaces/bind mounts** (§2.4), would let each worker physically write only its own layer; the orchestrator merges the diff down. This is the shared-FS counterpart to the harness doc's hooks/enforcement point.
- **Don't adopt CRDTs for the tree (and say why).** §2.2–2.3 confirm CRDTs converge *state* but not *meaning* for code, so concurrent same-file editing would risk silently-broken merges. Astraeus's sequencing is the better fit; record this as a deliberate rejection, not an omission.
- **Cross-run memory is the next real frontier (Ji, Packer).** The per-run reset deliberately forgoes memory; a **persistent, content-addressed store** (Manus's restorable files; Letta's `.af` agent checkpoints) is the path if/when cognition/memory becomes a goal (Phase 3) — without sacrificing the per-run reproducibility the reset currently buys.
- **Unique candidate branch per run.** The gate pushes `origin/candidate`; concurrent runs could collide. A `candidate-<run_id>` ref (GFS lease/ownership thinking) makes multi-run safe.
- **Know the single-authority ceiling (Ghemawat).** Orchestrator-as-sole-committer is fine at `MAX_WORKERS=4`; document that scaling agent counts will eventually need the GFS→Colossus move (distributed metadata / parallel integration).

## 5. Sources

**Version control & distributed storage**
- https://git-scm.com/book/en/v2/Git-Internals-Git-Objects · https://git-scm.com/book/en/v2/Git-Tools-Advanced-Merging · https://github.blog/open-source/git/git-turns-20-a-qa-with-linus-torvalds/
- https://research.google.com/archive/gfs-sosp2003.pdf · https://www.usenix.org/conference/osdi-04/mapreduce-simplified-data-processing-large-clusters · https://research.google.com/archive/bigtable-osdi06.pdf

**Conflict-free concurrency**
- https://inria.hal.science/inria-00609399v1 · https://inria.hal.science/inria-00555588/en/ · https://en.wikipedia.org/wiki/Conflict-free_replicated_data_type
- https://github.com/yjs/yjs · https://yjs.dev/ · https://github.com/y-crdt/y-crdt

**Per-agent views over shared backing**
- https://9p.io/sys/doc/names.html · https://ericvh.github.io/9p-rfc/rfc9p2000.html · https://www.semanticscholar.org/paper/Plan-9-from-Bell-Labs-Pike-Presotto/d84747ac8b31be455670c20fe975a2f4dcaf7f7e
- https://docs.kernel.org/filesystems/overlayfs.html · https://docs.docker.com/engine/storage/drivers/overlayfs-driver/

**Filesystem as memory / coordination**
- https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus · https://rlancemartin.github.io/2025/10/15/manus/
- https://arxiv.org/abs/2310.08560 · https://github.com/letta-ai/agent-file · https://www.letta.com/blog/memory-blocks
- https://dl.acm.org/doi/10.1016/0004-3702(85)90063-3 · https://dl.acm.org/doi/10.1145/356810.356816

**Reproducibility**
- https://edolstra.github.io/pubs/phd-thesis.pdf · https://reproducible.nixos.org/ · https://nixos.wiki/wiki/Nix_package_manager

## 6. Verification caveats

1. **Automated fetch was widely blocked (HTTP 403)** this session on git-scm.com, kernel.org, docker.com, 9p.io, manus.im, lip6.fr, and most of the arXiv/Inria/ACM/USENIX PDFs. URLs are canonical and facts cross-corroborated across independent search results, but **byte-exact quotes were not read from the primary pages** — confirm in a browser before publication-grade quoting.
2. **Authorship nuance (blackboard):** Barbara Hayes-Roth authored the 1985 "A Blackboard Architecture for Control" (and BB1); Frederick Hayes-Roth was a *Hearsay-II* co-author. They are distinct people in the same lineage.
3. **Paper metadata** (CRDT RR-7506/SSS 2011, GFS SOSP 2003, MemGPT arXiv:2310.08560, Plan 9 venues, NixOS ICFP 2008) was confirmed via multiple indices where the PDF 403'd; treat exact page numbers/DOIs as "corroborated, not byte-read."
4. **Product facts** (Yjs stars/downloads, Letta `.af`, Manus metrics) come from GitHub (often fetchable) plus secondary coverage; figures are approximate where flagged.
5. **No fabricated citations.** Unverifiable claims are flagged "(unverified this session)" rather than given a fake source; no spam-range arXiv IDs were used.
