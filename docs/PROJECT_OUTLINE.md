# Project Outline — Information Workbench & Eval Playground

*Working name: OutputTracker. Drafted 2026-10-13 from the "POSTS" vision notes, the OutputTracker / outputevals comparison, and the Braintrust review ([braintrust-ideas.pdf](braintrust-ideas.pdf)).*

---

## 1. Vision

**A workbench where anyone can shape how AI understands their information — and see exactly why it answers the way it does.**

Non-technical people build the outputs they want visually, without SQL. Technical people get the full trace of what the model saw. Underneath sits an information architecture (context in Markdown, relationships in a graph, the database as system of record) and an eval playground that proves which setup works before anything reaches production.

> The goal is always test time. Everything here exists to know — before production — the right context, prompt, data setup and model.

## 2. Thesis

1. **The bottleneck is semantics, not models.** Applied AI fails on meaning — which column is revenue, what "customer" means to this team — not on model capability.
2. **Information architecture is the product.** Structured, versioned, sourced knowledge about the data is the durable asset; the model is one component.
3. **Every turn should compound.** Failures expose missing knowledge; proven fixes are kept; the next question starts better grounded (the information flywheel).
4. **Traces are the source of truth.** With agents, logic lives in the model, so you understand behavior by reading what it saw and did — not the code.

## 3. Principles

| Principle | What it means in practice |
|---|---|
| **Two audiences, one product** | Hide the mechanics (SQL, infra) from non-technical users; never hide the *meaning*. Every view has a "show me what the model saw" drill-down. |
| **Augment, don't replace** | The human ideates, evaluates and steers. Proposals are approved, never auto-written. |
| **Manual friction first** | No automating a workflow before it has been done by hand. Saved attempts and traces come before agents. |
| **Numbers are never invented** | Every figure resolves to a stored, content-addressed query result, or the answer is refused (fail-closed resolver). |
| **Meaning is local** | Knowledge is scoped — to a person, team, or workflow — not one global truth. |
| **Lean, agnostic core** | Nothing dataset- or client-specific in the core; it lives in skills and knowledge units at the edges. |
| **Craft over volume** | Beautiful, intuitive, elegant. Ask "does it fit in the product?" before adding anything. |

## 4. Architecture

```
 ┌───────────────────────────── UI ─────────────────────────────┐
 │  Visual builder (non-technical)   │   Trace explorer (technical) │
 └───────────────────────────────────┴──────────────────────────────┘
                 │                                   ▲
                 ▼                                   │ every step logged
 ┌──────────────── Harness (per run) ──────────────────────────────┐
 │  skill selection → retrieval → SQL tool loop → draft → resolver │
 └─────────────────────────────────────────────────────────────────┘
        │                    │                     │
        ▼                    ▼                     ▼
 ┌─ Context (Markdown) ─┐ ┌─ Relationships ─┐ ┌─ System of record ─┐
 │ skills, rules,       │ │ context graph:  │ │ raw tables (SQL),   │
 │ definitions          │ │ fields + edges  │ │ evidence store      │
 │ (vector-searchable)  │ │ (multi-hop)     │ │ (append-only)       │
 └──────────────────────┘ └─────────────────┘ └─────────────────────┘
                 ▲
                 │ golden sets, scorers, experiments, results
 ┌──────────────── Eval playground ────────────────────────────────┐
```

**Which layer answers what**

- **Markdown context** — meaning, rules, conventions, procedures and style. Retrieved by similarity (vectors are fine here).
- **Context graph** — how fields and entities relate; multi-hop retrieval.
- **System of record** — facts and numbers. Only reachable through SQL; results become evidence rows. **Vectors never produce a number.**

**One home per kind of knowledge** (so the layers never contradict each other)

| Kind of knowledge | Home | Example |
|---|---|---|
| Facts and numbers | Database, via SQL evidence | Noah Paul's July revenue |
| Structure: fields, entities, relationships | Graph | Customer → located_in → Province |
| One-line field label | Graph node description | "Untaxed Total: invoice amount before tax" |
| Meaning, rules, policies | Markdown | "Revenue always excludes tax." |
| Procedures (how to do a task) | Skill Markdown | Step-by-step for a deck in company style |
| Style and format | Skill Markdown + attached files | Brand colors, tone, a slide template |

If a node's description outgrows one line, the node links to a Markdown section instead of repeating it. The graph then works as an index into the Markdown: traversal pulls in exactly the sections that apply to the fields a question touches.

**The library.** Skills are folders of Markdown (a `SKILL.md` plus supporting files and assets) stored as real files on disk, so they can be edited anywhere and versioned with git. Configurations attach skills or files; every trace records the content hash of each file the model saw. Start with `.md` and `.txt` only; other formats come later as an import-to-Markdown step.

**Scoped attachments.** Each configuration has an allowlist of what it can see, so file selection is itself an experimental variable (A with one file vs. B with two, same golden set).

| Attach | Example | Behavior |
|---|---|---|
| Skill folder | `sales-semantics/` | All files inside, resolved when each run starts |
| Single file | `sales-semantics/definitions.md` | Just that file |
| Section *(later)* | `definitions.md#revenue` | One heading: the start of knowledge units |

Two modes: **include** (in the prompt every run; build this first) and **available** (listed by name and description, read on demand through a `read_doc` tool; progressive disclosure, built with retrieval later).

Rules: folder attachments resolve at run time and the trace records the resolved file list and hashes; a missing or renamed file fails the run instead of being skipped; paths must stay inside the library; the configuration version hash covers attached file contents, so editing a file creates a new version of every configuration that uses it.

## 5. Core objects

| Object | Description |
|---|---|
| **Dataset** | An ingested source, stored untouched as the baseline; loaded once into a queryable table. |
| **Knowledge unit** | One atomic piece of knowledge: a definition, relationship, rule, correction, or verified query. Carries type, scope, provenance (which failure prompted it), approver, measured impact, and a staleness policy. Append-only. |
| **Skill** | A selectable, shareable package of knowledge units for one domain or task — like an app on a phone. Versioned. What the old "configuration" becomes. |
| **Evidence** | A content-addressed query result. The only place a number can come from. |
| **Trace** | The full record of one run: prompt, skill version, retrieval steps, SQL calls, evidence, raw output, rendered output, tokens, cost, latency, fingerprint/content hash. |
| **Golden set** | Questions with expected answers, source refs, category, difficulty, and a held-out flag. Grows by promoting real questions. |
| **Scorer** | A pluggable function: (question, answer, trace, expected) → score 0–1 + reason. Has metadata (see §7). |
| **Experiment** | Golden set × arms (skill version × model × settings) × scorers × N trials. Produces a scorecard and row-level diffs. |

## 6. User journeys

**Non-technical user (analyst, ops, manager)**
1. Upload or connect data → see fields in plain language.
2. Pick a skill, or start one: describe fields and connect them visually.
3. Ask a question → see the answer with every number clickable back to its source.
4. Mark it right or wrong → a fix is proposed → approve it after the playground shows it helps.

**Technical user (engineer, data person, auditor)**
1. Open any answer's trace: exactly what the model saw, each SQL call, each evidence row.
2. Run experiments across skills, models (frontier and open source) and settings.
3. Compare scorers, read the scorecard and diffs, export the skill to where it will run in production.

## 7. Eval playground

The playground has two jobs: **run as many evals as possible**, and **find out which ones are trustworthy and useful for this use case.** The second job is the one most tools skip — and the one that turns breadth into understanding.

### 7.1 Scorer registry

Every eval is a scorer plugin with metadata, so they can be added cheaply and compared fairly:

| Field | Example |
|---|---|
| `family` | correctness / honesty / grounding / retrieval / SQL / robustness / reliability / comparative / operational / memory / human |
| `format` | pointwise, pairwise, checklist, trajectory… (see §7.3) |
| `requires` | what must exist for it to run, e.g. `reference_answer`, `gold_sql`, `trials>=5` (see §7.4) |
| `needs_reference` | yes (golden answer) or no |
| `method` | code, embedding, LLM judge, human |
| `granularity` | per answer, per run, per trace step |
| `cost` | free / cents per call |
| `source` | built here, or wrapped from a library (Braintrust autoevals, RAGAS, DeepEval, promptfoo, Inspect) |

Build the simple code scorers yourself (that's where the learning is); wrap libraries for the complex ones and compare them with your own.

### 7.2 The catalog

**A. Output correctness — reference-based**
- Exact match · Contains · Regex
- Numeric tolerance (absolute and relative)
- List/set match with precision, recall, F1 (e.g. "top 5 customers")
- Embedding similarity to the expected answer
- LLM judge: answer correct
- Factuality classification: the answer is a subset, superset, match, or contradiction of the reference

**B. Output quality — reference-free**
- Rubric judge (completeness, clarity, relevance to the question)
- Conciseness / length
- Format and schema validity (Pydantic)
- Refusal detection

**C. Honesty**
- Abstained correctly (unanswerable questions)
- Hallucination rate (confident answer to an unanswerable question)
- Over-refusal rate (refusing an answerable question)
- Calibration: stated confidence vs. actual accuracy

**D. Grounding & attribution** *(the differentiator)*
- Every number sourced (resolver passed)
- Stray-number check (raw figures that bypass `{{ev:*}}`)
- Claim-level faithfulness: each claim supported by retrieved evidence
- Citation precision and recall

**E. Retrieval & context**
- Context precision: how much retrieved context was relevant
- Context recall: was everything needed retrieved (fields, edges, rules)
- Context utilization: did the answer actually use the provided definition
- Long-context recall (needle-in-a-haystack over large context)

**F. SQL & tool use**
- SQL validity (parses and executes)
- Execution accuracy: result set matches the gold query's result (the text-to-SQL standard, as in Spider/BIRD)
- Column and filter correctness against `source_refs`
- Tool-call efficiency (number of calls, wasted calls)
- Error recovery rate (fixed its own failed query)
- Trajectory match against a reference path

**G. Robustness**
- Paraphrase invariance (same question, three wordings, same answer)
- Perturbations: renamed columns, noise rows, shuffled order, distractor fields
- Position sensitivity (does moving context around change the answer)
- Prompt injection through data (a cell containing instructions)

**H. Reliability**
- pass@k (right at least once in k)
- pass^k / consistency (right every time in k)
- Self-consistency agreement across runs
- Evidence-id stability across near-duplicate questions

**I. Comparative**
- Pairwise win rate, with position swapping
- Elo / Bradley–Terry ratings across many skills and models (the model testing ground)

**J. Operational**
- Latency (p50 / p95), tokens, cost, cache hit rate
- Quality per dollar
- Error and timeout rate

**K. Memory** *(for the separate memory project, §10; this playground is where they run)*
- Recall of facts stated in earlier sessions
- Update correctness: a corrected fact supersedes the old one
- Staleness detection: knowledge that no longer matches the data
- Conflict resolution between scoped knowledge units

**L. Human**
- Thumbs and preference labels
- Inter-annotator agreement (Cohen's kappa)
- Judge–human agreement

**M. Statistics & experiment hygiene** *(applied to every run, not scorers themselves)*
- Confidence intervals; paired significance (McNemar, paired bootstrap)
- Held-out gap (tuning set vs. held-out set)
- Ablation: contribution of each knowledge unit
- Slicing by category, difficulty and error type

**N. Regression & change detection** *(a way of running every scorer above against a saved baseline)*
- **Pinned baseline:** a named earlier run that later runs are compared against.
- **Row-level regressions:** questions that passed before and fail now (and fixes, the reverse). Reported as fixed / broke / same.
- **Flip rate:** share of rows whose verdict changed, in either direction. High flip rate with an unchanged average means instability hidden under a stable headline.
- **Quality gates:** thresholds a change must pass, e.g. "no drop in execution accuracy, zero new grounding failures, no golden row that passed 5/5 now below 4/5."
- **Significance of the change:** paired test (McNemar / paired bootstrap) on baseline vs. new, so noise isn't read as a regression.
- **Output drift:** same fingerprint (same inputs), different content hash (different output) between runs.
- **Triggers:** model release, data re-ingest, skill/knowledge change, prompt-template change, scorer change.
- **Re-score vs. re-run:** when a scorer or judge changes, re-score the stored outputs (no model calls) before re-running the model. That separates "the answers changed" from "the grading changed."

### 7.3 Eval formats — the second axis

Families (§7.2) say *what* is measured. Formats say *how* the judgment is made. The same family can be tried in several formats, and comparing them is part of the research.

| Format | How it works | Example |
|---|---|---|
| **Pointwise, reference-based** | Score one answer against a known answer | Numeric tolerance, execution accuracy |
| **Pointwise, reference-free** | Score one answer on its own merits | Rubric judge, schema validity |
| **Checklist rubric** | Break "good" into yes/no items, score each, average | "Names the customer? Gives the amount? States the period?" |
| **Pairwise** | Pick the better of two answers, positions swapped | Baseline vs. skill win rate |
| **Listwise / ranking** | Rank several answers (skills, models) at once | Best of 4 model outputs |
| **Judge panel** | Several judges (different models or prompts) vote | Majority of 3 judges |
| **Trajectory** | Score the path, not the output | SQL calls, tool order, error recovery |
| **Multi-turn / simulated user** | A simulated user asks follow-ups; score the whole conversation | "And for August?" after a July question |
| **Metamorphic** | No answer known; check relations between outputs | Paraphrase gives same answer; doubled data doubles the sum |
| **Adversarial / red team** | Generated inputs designed to break it | Injected instructions in a CSV cell |
| **Statistical** | Applied across runs, not to one answer | pass^k, McNemar, held-out gap |
| **Human** | A person grades or picks | Labels, preferences |

### 7.4 Eligibility — run every eval the workflow allows

The playground doesn't ask you to choose evals. **Each scorer declares what it requires; each workflow, golden row and trace declares what it provides; every eligible scorer runs.**

**Requirement vocabulary (examples)**

| Requirement | Provided by |
|---|---|
| `reference_answer` | Golden row has an expected answer |
| `numeric_expected` / `expected_list` | Expected answer is a number / a list |
| `unanswerable_label` | Golden row marked NOT_IN_DATA |
| `gold_sql` / `source_refs` | Golden row has a reference query / expected columns |
| `trace.sql_calls` / `trace.retrieval_steps` | The workflow uses SQL / retrieval |
| `evidence_refs` | The answer went through the resolver |
| `trials>=k` | The experiment runs each row k times |
| `two_arms` / `many_arms` | The experiment compares 2+ skills or models |
| `baseline_run` | A pinned earlier run exists |
| `human_labels` | Someone has graded these outputs |
| `paraphrase_set` / `perturbations` | Variants exist or can be generated |
| `multi_turn` | The workflow is a conversation |
| `output_schema` | The workflow expects structured output |

**Eligibility is per row, not per workflow.** Numeric tolerance runs only on rows with a numeric answer; abstention only on unanswerable rows.

**Show what's locked, and why.** Every scorecard lists ineligible scorers with what would unlock them: *"Add gold SQL to this row → unlocks execution accuracy, column correctness, trajectory match."* That makes the golden set richer over time, and it teaches what each eval needs.

### 7.5 Research: which evals work for which workflows

The research question is a matrix: **workflows × scorers**, each cell filled with report-card results (§7.6). The table below is the *starting hypothesis* for which families apply. The research replaces it with measured results.

● applies directly · ◐ applies with extra labels or setup · – doesn't apply

| Workflow | Correct | Quality | Honesty | Grounding | Retrieval | SQL/tools | Robust | Reliab. | Compar. | Ops | Human |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **Data Q&A** (first) | ● | ● | ● | ● | ● | ● | ● | ● | ● | ● | ● |
| **Report drafting** (long text with numbers) | ◐ | ● | ◐ | ● | ● | ◐ | ● | ● | ● | ● | ● |
| **Extraction / classification** | ● | ◐ | ◐ | ◐ | – | – | ● | ● | ◐ | ● | ● |
| **Document summarization** | ◐ | ● | ◐ | ● | ◐ | – | ● | ● | ● | ● | ● |
| **Agentic multi-step task** | ◐ | ◐ | ◐ | ◐ | ● | ● | ● | ● | ● | ● | ● |
| **Conversation / assistant** | ◐ | ● | ● | ◐ | ◐ | – | ● | ● | ● | ● | ● |

**What the research produces**
- A per-workflow scorer leaderboard: which evals agree with humans, discriminate, and stay stable *for that workflow*.
- Format comparisons: e.g. "checklist rubric beats a single 1–10 judge score on report drafting."
- A findings log: each conclusion with the experiment that supports it. This is the raw material for posts and interviews.

**Research mode vs. decision mode**
- **Research mode:** run every eligible scorer on a sample. The goal is learning about the evals.
- **Decision mode:** run only scorers the report card trusts, with named north-star metrics. The goal is deciding about the system.

### 7.6 Evaluating the evaluators — the scorer report card

To learn which evals work for this use case, score the scorers against a small human-labeled set (start with ~50 answers you grade yourself):

| Metric | Question it answers |
|---|---|
| **Agreement with humans** (kappa) | Does it judge like I do? |
| **Discrimination** (separates known-good from known-bad; AUC) | Can it tell good from bad at all? |
| **Stability** (same verdict on reruns) | Is it flaky? |
| **Sensitivity** (moves when quality moves) | Does it notice real changes? |
| **Cost and latency** | Can I afford to run it every time? |
| **Redundancy** (correlation with other scorers) | Is it telling me anything new? |

The report card is the playground's most valuable output: over time it says *"for business-data Q&A, these 6 scorers are reliable, these 3 are noise, and this judge disagrees with humans on aggregation questions."* That's a finding worth writing about.

### 7.7 Guardrails against metric soup

- Each experiment names **one or two north-star metrics** up front (e.g. execution accuracy + consistency); everything else is diagnostic.
- LLM-judge scorers × many rows × N trials gets expensive; every experiment shows its estimated cost before running, with a budget cap.
- Research mode runs expensive judges on a stratified sample (every category and difficulty), not the full set.
- **Cache every score** by (scorer version, output hash). Re-scoring stored outputs then costs nothing, so adding a new scorer to old experiments is free for code scorers.
- A scorer isn't trusted for decisions until its report card says so.

### 7.8 Adopted from Braintrust

Decisions on the ideas in [braintrust-ideas.pdf](braintrust-ideas.pdf). All eight are adopted, each adjusted to this design.

| # | Idea | Decision | How we adapt it | Phase |
|---|---|---|---|---|
| 01 | Golden-set experiments | **Adopt** | Experiment = golden set × arms × eligible scorers × N trials | 1 |
| 02 | Pluggable scorers | **Adopt, extended** | Registry adds `requires` and per-row eligibility (§7.4), which Braintrust doesn't do | 1 |
| 03 | Row-by-row diffs | **Adopt, extended** | Fixed / broke / same, plus flip rate | 2 |
| 04 | Promote to golden | **Adopt, extended** | Promoting a question shows which evals each added field unlocks | 2 |
| 05 | Version everything | **Adopt, with a fix** | Append-only skills; Briefcase fingerprint includes model *settings* so a settings change isn't mistaken for drift | 0–1 |
| 06 | Playground gate | **Adopt** | A knowledge proposal is approved only if decision-mode scorers show it helps without regressions | 4 |
| 07 | Repeated trials | **Adopt** | Consistency (pass^k) is the default north-star metric for data Q&A | 2 |
| 08 | Regression reruns | **Adopt, extended** | Triggers in §7.2 N; re-score stored outputs before re-running the model | 4 |
| – | Production tracing / online scoring | **Skip for now** | Per-run traces yes; scoring live traffic only once something is deployed | – |
| – | Prompt hosting / deployment | **Skip** | Export skills to where they run instead | – |
| – | General-purpose SDK | **Skip** | Stays a focused product, not a generic eval tool | – |

### 7.9 When each metric activates

Activation depends on three inputs: **the workflow** (does it use SQL or the resolver?), **the prompt** (is there a golden row, and what kind of answer does it expect?) and **the data** (is there evidence, a baseline run, multiple trials?). Nothing is switched on by hand.

| Metric (PDF page) | Activates when | Phase |
|---|---|---|
| Exact match / contains (p. 7) | Golden row's expected answer is short text | 1 |
| Numeric tolerance (p. 7) | Expected answer parses as a number (detected automatically) | 1 |
| LLM judge: answer correct (p. 8) | Golden row has any expected answer | 1 |
| Abstained correctly (p. 8) | Golden row is marked NOT_IN_DATA | 1 |
| Every number sourced (p. 9) | The answer went through the resolver (every data workflow) | 1 |
| Stray-number check | Same as above | 1 |
| Right sources used (p. 9) | Golden row has `source_refs` **and** the trace has SQL calls | 1 |
| Accuracy (p. 10) | At least one reference-based scorer ran across the run | 1 |
| Row-by-row diff (p. 10) | The experiment has 2+ arms, or a pinned baseline exists | 2 |
| Pairwise win rate (p. 10) | 2+ arms, with a human or judge grader | 3 |
| pass@k and consistency (p. 11) | Trials ≥ 2 (k = number of trials) | 2 |
| Held-out gap (p. 11) | The golden set has held-out rows | 2 |
| Grader agreement (p. 11) | 2+ graders (human or judge) scored the same outputs | 3 |

**Ad-hoc questions** (asked in the arena, no golden row) still get every eval that doesn't need a known answer: every number sourced, stray-number check, SQL validity, rubric judge, refusal detection, and cost/latency. Promoting the question to the golden set unlocks the rest.

## 8. Phased build

Each phase stands on its own.

| Phase | Build | You get |
|---|---|---|
| **0. Merge foundations** | Experiment structure, SQL tool loop and UI from outputevals; evidence store, resolver and append-only rules from OutputTracker; Briefcase fingerprints with params on every trace | One codebase with the guarantee intact |
| **1. Prove it** | Golden set (start with 4–5 rows, grow to 30+), scorer registry with requirements and per-row eligibility, families A, C, D, F; score cache; experiments with versioning | A defensible baseline-vs-skill score |
| **2. Explain it** | Trace explorer, row-level diffs, promote-to-golden, repeated trials (H), statistics (M), error taxonomy | Which questions moved, how reliably, and why |
| **2v. Visual traces** | Read-only field graph per answer where used columns glow (columns parsed from SQL); edges glow when both fields were used together; file chips outlined when in context; hover a number to light its column, query and evidence cell; replay of tool calls; baseline vs. configured graphs side by side. Three states everywhere: dim (available), outlined (given), glowing (demonstrably used). Glows come only from trace data | Seeing why an answer came out the way it did |
| **3. Trust the evals** | Human labeling UI, families L and B, scorer report card, research mode, "locked evals" hints, more formats (checklist, judge panel, pairwise) | Knowing which evals to believe |
| **3b. Second workflow** | Add one more workflow (report drafting is closest) so the workflow × scorer matrix has two rows to compare | The first cross-workflow finding |
| **3c. Workflows** | Engineers stamp 5–10 published, versioned workflows: a prompt template with typed inputs (picked from real values), a configuration, model settings, golden cases (inputs + verified answer), and the evals that must pass. Editing creates a draft that publishes only if its golden cases still pass. Free chat runs are tracked and scored too; recurring chat questions become the next workflows | The engine (for AI engineers) behind a simple app (for the team) |
| **4. Compound it** | Knowledge units with provenance, playground gate for proposals, ablation, regression reruns, robustness (G) | The flywheel |
| **5. Two audiences** | Visual builder for non-technical users; skills as installable, scoped packages; export to semantic-model formats / MCP | The product |
| **6. Model ground** | Multi-model routing (frontier + open source), comparative ratings (I), quality per dollar (J), distillation datasets from traces | The testing ground |
| **7. Memory seams** | Retrieval behind one interface; selection *within* large skills; automatic skill activation; proposals accepted from any source, not only humans | Ready for the separate memory project (§10) |

## 9. Open decisions

1. **Base codebase.** Decided: outputevals, with OutputTracker's evidence store and resolver ported in (done in phase 0). The old OutputTracker repo is an archive.
2. **Scope of "any workflow".** Recommendation: business-data Q&A first; add exactly one more (report drafting) in Phase 3b so the eval research has something to compare. Generalize further only after both are proven.
3. **Data sources.** Single CSV today; multi-table and database connectors are needed before real client use.
4. **Data handling.** Local-only mode, retention, and what's sent to model APIs — needed before client data.
5. **Naming.** OutputTracker vs. outputevals vs. something that says "information workbench".

## 10. Memory — where it fits, and where it stops

**This project is curated memory.** Skills and knowledge units are semantic and procedural memory; traces are episodic memory. Everything is explicit: a human approves what's stored, and activating a skill decides what's recalled.

| Memory type | Here | Who decides |
|---|---|---|
| Working | The context window of one run | Harness |
| Semantic | Knowledge units (definitions, rules) | Human, approved and scoped |
| Procedural | Verified queries, skills | Human |
| Episodic | Traces | Logged; used for evals, not recalled into prompts |

**Long-term memory is a separate project.** It changes two things: the system decides what to *write*, and the system decides what's relevant to *recall*. That's a fundamental architecture change and stays out of this codebase.

**Seams kept here so it can plug in later:**
1. **Memory writes are proposals.** A memory system is just another proposer into the knowledge store, through the same playground gate. Autonomy = automating the proposal step, then auto-approving what passes the gate.
2. **One retrieval interface.** "What knowledge applies to this question?" Today: the activated skill. Later: a memory system behind the same call.
3. **Complete, append-only traces** — the episodic raw material from day one.

**This project is the memory project's test bench.** Its headline experiment: *curated knowledge vs. autonomous memory vs. both, on the same golden set*, scored with the same report card.
