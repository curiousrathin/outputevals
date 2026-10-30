# Current Build

*What exists in `outputevals` today, as of 2026-10-29. Use it to decide what to keep, trim or add next. The plan for where it's going lives in [PROJECT_OUTLINE.md](PROJECT_OUTLINE.md).*

---

## 1. In one paragraph

A local web app that asks the same question of a dataset twice: a **baseline** arm that sees only the raw data, and a **configured** arm that also gets your field descriptions, relationships and attached skill files. Both arms read the data only through read-only SQL. Every value they get back becomes a content-addressed **evidence** record, the answers must cite those records as `{{ev:…}}` references, and a **fail-closed resolver** renders an answer only if every reference exists. Each run saves what the model saw: the prompt, every query, the cited evidence, the library files with their hashes, tokens, latency and two Briefcase hashes. A **library** of Markdown skill files lives on disk, and each configuration attaches only the folders or files it needs.

| | |
|---|---|
| **Repo / branch** | `~/dev/outputevals`, branch `phase-0-merge` |
| **Committed?** | Up to eval step 2 (`cf08bf1`). Step 3 (batches) is uncommitted |
| **Size** | Backend ~2,400 lines of Python · frontend ~2,700 lines of TypeScript/CSS |
| **Tests** | 108 backend tests, all passing · frontend checked by type-check and build only |
| **Run it** | `cd ~/dev/outputevals/backend && .venv/bin/uvicorn app.main:app --port 8000` → http://localhost:8000 |
| **UI edits** | Rebuild with `npm run build` in `frontend/` (needs Node 22.12+), or `npm run dev` for hot reload on port 5173 |

---

## 2. What happens when you ask a question

```
Question
  │
  ├─ resolve the configuration's library attachments  (missing file → run fails with a clear message)
  ├─ build two system prompts that share a byte-identical, cached prefix:
  │     instructions + citation rules + column schema + first 20 CSV lines
  │     configured arm only: + data dictionary + <library> files + notes
  │
  ├─ both arms run in parallel threads, each a tool loop (max 25 rounds):
  │     Claude ──query_data(sql)──▶ DuckDB (in memory, read-only)
  │        ▲                          │
  │        └── result + evidence ids ─┘   ids minted in-thread, no database access
  │
  ├─ save every cited value as append-only evidence
  ├─ fail-closed resolver renders each draft, or refuses it whole
  └─ save the trial: config version, library file hashes, both responses
        (prompt, queries, evidence, draft, rendered answer, tokens, latency, fingerprint, content hash)
```

**Key files:** `core/arena.py` (tool loop), `core/prompts.py` (prompt building), `core/sqltool.py` (DuckDB), `core/evidence.py` (store + citing), `core/resolver.py` (fail-closed render), `api/experiments.py` (orchestration).

---

## 3. Feature inventory

Status key: **Working** (built and tested) · **Manual** (works, no automated test) · **Partial** · **Placeholder** · **Unused**

### Datasets
| Feature | Status | Notes |
|---|---|---|
| Upload a CSV | Working | `.csv` only; stored byte-for-byte as the baseline (`data/datasets/{id}.csv`) |
| Profile columns | Working | pandas: type, non-null count, distinct count, 3 sample values |
| Preview rows | Working | First 50 rows (max 500) |
| Delete | Working | Blocked (409) while a configuration uses it |
| Token estimate | Unused | `est_tokens` is still computed and shown, but nothing depends on it since inline mode was removed |

### Configurations
| Feature | Status | Notes |
|---|---|---|
| 4-step wizard | Manual | Dataset → Fields & connections → Context → Save (optionally creates an experiment) |
| Field graph editor | Manual | Every column is a node; add a one-line description per field; draw labeled edges (React Flow) |
| Graph validation | Working | Edges must join real columns, can't self-loop, need a description |
| Library attachments | Working | Checkbox tree; attaching a folder covers its files; validated on save |
| Notes for this configuration | Working | The old free-text Markdown box, now secondary to the library |
| Prompt preview | Working | Shows exactly what the configured arm adds, including attached files |
| Missing-file warning | Working | Shown on the configuration if an attached file disappears |
| Versioning | Partial | Edited in place. History survives through each trial's `config_version` hash, stored prompt and file hashes |
| Delete | Working | Blocked (409) while an experiment uses it |

### Library
| Feature | Status | Notes |
|---|---|---|
| Files on disk | Working | `data/library/` by default (gitignored); `OT_LIBRARY_DIR` to point elsewhere, e.g. its own git repo |
| Tree, editor, preview | Manual | Folders first, then `SKILL.md`, then files; Edit/Preview; Ctrl/Cmd+S saves |
| New file / folder | Manual | New files start as `SKILL.md` with a title; existing names are rejected |
| Path safety | Working | No `..`, absolute paths, hidden files or symlinks; `.md`/`.txt` only; 200 KB per file |
| Delete | Working | Files, and empty folders only; blocked (409) while attached to a configuration |
| Rename / move | Not built | Delete and recreate for now |

### Experiments and the arena
| Feature | Status | Notes |
|---|---|---|
| Two arms per question | Working | Same cached prefix; only the configuration block differs |
| SQL tool loop | Working | Up to 25 rounds; errors go back to the model so it can fix its query |
| Evidence minting | Working | Every non-null cell of a result with ≤ 60 cells gets an id; larger or truncated results tell the model to aggregate further |
| Fail-closed rendering | Working | One unknown reference refuses the whole answer; the UI shows "Answer refused" with the missing ids |
| What the model saw | Manual | System prompt, question, each query with result and evidence, raw draft, model, content hash |
| Library files per trial | Working | Chips with short content hashes under each question |
| Preference label + note | Working | Baseline better / Configured better / Tie / Both wrong, plus a free-text note |
| Token, cache and latency counts | Working | Shown per arm; cache reads show when the shared prefix hit |
| Delete experiment | Working | Removes its trials and responses |

### Traces and provenance
| Feature | Status | Notes |
|---|---|---|
| Append-only evidence | Working | Corrections append and supersede; unchanged re-records are no-ops |
| Evidence lookup | Working | `GET /api/evidence/{id}`: value, query, label, source hash, history |
| Fingerprint + content hash | Working | Briefcase; settings are now part of the fingerprint, so a settings change isn't mistaken for drift |
| Config version | Working | Hash of the full configuration text, including attached file contents |

### Evals (steps 0–3)
| Feature | Status | Notes |
|---|---|---|
| Scored on every run | Working | Each new trial is scored the moment it's saved; older trials are scored from their stored traces the first time they're viewed. No model calls |
| Four states | Working | Scored · locked (shown, with how to unlock) · not applicable (hidden, counted) · not computed (shown, with the reason). Only scored results count toward rates and averages |
| Scorer registry | Working | Each eval declares what it measures, how it decides, its caveat, its kind (verdict / measure / signal) and what it requires. `app/evals/` |
| Versioned results | Working | Scores are stored per scorer version; bumping a version adds rows instead of overwriting |
| Always-on evals | Working | Completed · References resolve · Unsourced numbers · SQL health · Arms agree · Latency · Cost |
| Arena score strips | Manual | Chips under each arm, hover for the reason and the eval's description; "Arms agree" on each question |
| Evals tab | Manual | Scorecard per arm, runs table with filters (any failure, unsourced numbers, refused, arms disagree) and expandable rows, "About these evals" guide, re-score button |
| Cost | Working | List prices from the Claude API reference (cached 2026-10-06); unknown models show "not computed", never $0; override with `OT_MODEL_PRICES` |
| Reference evals | Working | Expected numbers (within a tolerance) · Expected text · Abstained correctly · Right columns used · Execution accuracy. Locked until the question has a golden answer |
| Golden answers | Working | "Set as correct answer" on any arm, pre-filled from that run (values it cited, columns its SQL used, its last query, a category); checked and edited by a person before saving. Pinned to the dataset and its hash, never to a configuration. Editing bumps the version and re-grades linked runs from their traces |
| Matching runs to golden answers | Working | Exact question match after normalizing case, spacing and trailing punctuation, or an explicit link. Similar questions are never graded against each other |
| Correct | Working | One verdict per run against the golden answer: expected numbers and text both pass (or, for unanswerable questions, it abstained). Errors and refused answers are incorrect. Batches build on it |
| Batches | Working | Ask chosen golden questions N times (1–20) on both arms in the background; 3 runs at a time (`OT_BATCH_CONCURRENCY`), at most 200 runs (`OT_BATCH_MAX_RUNS`). Runs go in rounds so a cancelled batch still covers each question evenly. Configuration, model and settings frozen at start. Cancel keeps finished runs; 3 runs in a row that can't reach the API stop it; batches left running by a restart are marked interrupted |
| Batch estimate | Working | Runs, model calls, cost and minutes, from this experiment's earlier runs; shown before starting |
| Batch report | Manual | Per arm: accuracy with a 95% interval, right every time (pass^k), right at least once (pass@k), same answer every time, cost, median/p95 latency. Configured − baseline difference with an interval and a plain verdict. Per question: ✓/✗ for each run, with how many different answers. Every pass/fail eval with an interval |
| Error bars | Working | Two-level bootstrap (resample questions, then runs within each), seeded per batch, 2,000 draws. Each question counts once. `app/evals/stats.py` |
| Run scope | Manual | Evals tab scorecard and runs table can show everywhere, the arena only, or one batch. The arena shows only questions asked by hand, with a pointer to batch runs |
| Golden answers on the Evals tab | Manual | List with linked-run counts and edit; coverage ("2 of 4 runs graded"); filters for incorrect answers and runs without a golden answer |

### Settings and serving
| Feature | Status | Notes |
|---|---|---|
| API key | Working | Read from `.env`, then the environment, then a key saved in Settings (`data/secrets.json`, mode 600); validated via the Models API at no token cost; only ever shown masked |
| Model settings | Working | `claude-opus-5-5`, effort `medium`, 16,000 max tokens, adaptive thinking; override with `OT_LLM_MODEL` / `OT_LLM_EFFORT` |
| One-process serving | Working | FastAPI serves the built frontend; deep links fall back to the app; unknown `/api` paths still 404 |
| Observability page | Placeholder | "Coming next" page in the sidebar |
| Saved attempts page | Placeholder | "Coming next" page in the sidebar |

---

## 4. Data model (SQLite, `data/outputtracker.db`)

| Table | Holds | Notable fields |
|---|---|---|
| `dataset` | One uploaded CSV | `sha256` (feeds evidence ids), `columns` profile, `est_tokens` |
| `configuration` | Graph + attachments + notes | `nodes`, `edges`, `attachments`, `context_markdown` |
| `experiment` | A named pairing of one configuration with its dataset | `configuration_id` |
| `trial` | One question | `config_version`, `library_files` [{path, sha256}], `golden_case_id`, `batch_id` + `repeat` ("" for arena questions), `preference`, `note` |
| `batch` | The golden set asked N times | `golden_case_ids`, `repeats`, `total`, `done`, `status` (running / done / cancelled / failed / interrupted), `error`, `config_version`, `model`, `settings` |
| `armresponse` | One arm's answer + trace | `tool_calls` (with evidence), `output` (draft), `render_ok`, `rendered_output`, `missing_refs`, `system_prompt`, tokens, `latency_ms`, `fingerprint`, `content_hash`, `mode` |
| `evidence` | Append-only facts | `ev_id`, `value`, `source`, `query`, `label`, `superseded_by` |
| `golden_case` | A question with a verified answer | `dataset_id` + `dataset_sha` it was checked against, `question_key`, `answerable`, `expected_values`, `tolerance`, `expected_columns`, `reference_sql`, `category`, `held_out`, `version`; `workflow_id` and `params` reserved for workflows |
| `score` | One eval result per arm (or per question) | `scorer`, `scorer_version`, `state`, `value`, `passed`, `reason`, `details`; unique per trial, response, eval and version |

New columns are added automatically on startup (`db.py`); there are no other migrations.

---

## 5. API (42 endpoints)

| Area | Endpoints |
|---|---|
| Settings | `GET/PUT/DELETE /api/settings/anthropic`, `POST /api/settings/anthropic/test` |
| Datasets | `GET/POST /api/datasets`, `GET/DELETE /api/datasets/{id}`, `GET /api/datasets/{id}/preview` |
| Configurations | `GET/POST /api/configurations`, `GET/PUT/DELETE /api/configurations/{id}` |
| Experiments | `GET/POST /api/experiments`, `GET/DELETE /api/experiments/{id}`, `GET/POST /api/experiments/{id}/trials`, `PATCH /api/trials/{id}` |
| Evidence | `GET /api/evidence/{ev_id}` |
| Library | `GET /api/library/tree`, `GET/PUT /api/library/file`, `POST /api/library/folder`, `DELETE /api/library/item` |
| Evals | `GET /api/evals/scorers`, `GET /api/experiments/{id}/evals`, `POST /api/experiments/{id}/evals/rescore`; trials also carry their scores |
| Golden answers | `GET /api/datasets/{id}/golden`, `GET /api/trials/{id}/golden-draft`, `POST /api/golden`, `PUT/DELETE /api/golden/{id}` |
| Batches | `GET/POST /api/experiments/{id}/batches`, `GET /api/experiments/{id}/batches/estimate`, `GET/DELETE /api/batches/{id}` (with report), `POST /api/batches/{id}/cancel`; trials and evals take `?scope=all\|arena\|<batch id>` |
| Health | `GET /api/health` |

---

## 6. Guarantees, and how they're enforced

| Guarantee | Enforced by | Tested |
|---|---|---|
| A number shown in an answer came from a query result | Resolver refuses any draft with an unknown `{{ev:…}}` | Yes, including "nothing leaks through on a partial failure" |
| The model can't change or escape the data | DuckDB with external access off and configuration locked; one statement; `SELECT`/`WITH`/`DESCRIBE`/`SUMMARIZE` only; 200-row / 20,000-character result cap | Yes (writes, multiple statements, `COPY`, `SET`, reading `/etc/passwd`) |
| The only difference between arms is the configuration | Shared, byte-identical cached prefix | Yes |
| Evidence history is never lost | Append-only rows; corrections supersede | Yes |
| An experiment never silently loses context | Missing attachments fail the run with a clear message | Yes |
| Library files can't reach the rest of the disk | Path normalization and resolution checks | Yes |
| You can tell which version of each file a run saw | Content hashes on every trial; edits change the config version | Yes |

---

## 7. Known gaps and limitations

| # | Gap | Impact | Effort to fix |
|---|---|---|---|
| 1 | **Unsourced numbers are detected, not blocked.** The Unsourced numbers eval flags them on every run, but the answer still renders | The guarantee is measured, not enforced, for typed numbers | Small: optionally refuse answers that fail it, once the eval's false positives are known |
| 2 | **First 20 CSV rows are in the prompt.** The model can read values from the preview and type them without querying | Makes gap 1 more likely | Small: show schema only, or rely on the gap-1 check |
| 3 | **Citation behaviour is measured on fake runs only.** The evals now count it on every run; real-model runs haven't been reviewed yet | Unknown real-world rate | Look at the Evals tab after a few real questions |
| 4 | **Resolution is store-wide.** A draft could cite an id minted in a different run or dataset | Low risk today | Small: only accept ids minted in this run |
| 5 | **DuckDB reloads the CSV 3 times per question** (schema + each arm) | Slow on large files (e.g. the 940 MB FrankieDS.csv) | Medium: build a DuckDB file once at upload |
| 6 | **Evidence ids depend on exact SQL text.** Reworded queries mint new ids for the same value | Duplicate evidence; weaker drift detection | Medium |
| 7 | **No arithmetic in answers.** Derived figures (a % change) have to be computed in SQL | Correct by design; may cause refusals or awkward phrasing | Watch it in evals |
| 8 | **Configurations are edited in place** | History is reconstructable but not first-class | Medium: append-only versions |
| 9 | **The whole graph and every attached file go into the prompt** | Fine while small; no selection yet | Later: graph as index, `read_doc` tool (Phase 7) |
| 10 | **One CSV per dataset.** No joins, database connectors, or cleaning/transform steps | Limits real client use | Large |
| 11 | **No significance tests, pinned baselines or judges yet.** Batches give error bars and pass^k, but no McNemar test, row-level diffs between batches, or LLM judge | Can show noise, can't yet compare two batches row by row | Steps 4–6 |
| 17 | **Batches run in the server process.** Restarting the server interrupts a running batch (it's marked interrupted; finished runs are kept) | Long batches need the server left running | Medium: a job queue, later |
| 18 | **Consistency compares cited values only.** Two prose answers with no citations count as the same answer | Over-states consistency for answers that don't cite | Small: compare rendered numbers too |
| 16 | **Golden answers are edited in place** (version number + re-grade), not stored as separate rows; "Abstained correctly" is a keyword heuristic | History of old answers isn't kept; honesty grading is rough | Append-only versions later; LLM judge in step 5 |
| 12 | **Local, single user.** No auth; secrets in `.env` | Fine for now | Later |
| 13 | **No frontend tests** | UI regressions are caught only by hand | Medium |
| 14 | **Rendered numbers use raw query formatting** (e.g. `149410.09`, no thousands separators) | Cosmetic | Small: format numbers when minting |
| 15 | **Nothing is committed** | Work exists only on this machine | Commit (two commits suggested: evidence/resolver merge, then library) |

---

## 8. Candidates to trim

Things that exist but don't earn their place yet. Tick what to remove.

- [ ] **`faiss-cpu` and `fastembed` dependencies.** Listed in `pyproject.toml`, imported nowhere; heavy to install. Re-add when vector search over the library is built.
- [ ] **`judge_model` and `embedding_model` settings.** Unused (`embedding_model` only appears in `/api/health`). Re-add with Phase 1 judges / Phase 7 retrieval.
- [ ] **Observability and Saved attempts placeholder pages.** Nav items that lead to "Coming next". Remove until there's something behind them, or keep as a roadmap signal.
- [ ] **`ArmResponse.mode`.** Always `"query"` now that inline mode is gone; kept only for old rows.
- [ ] **`Dataset.est_tokens`.** Only displayed; it used to decide inline vs. query mode.
- [ ] **"Notes for this configuration" box.** A second home for knowledge beside the library, against the one-home rule. Could become read-only for old configurations, or go away.
- [x] **Planning docs moved here** from the old `OutputTracker` repo (outline and Braintrust PDF are now in `docs/`).
- [ ] **The old `OutputTracker` repo.** Its store/resolver ideas now live here. It still holds the vanilla-JS UI, `as_of` checkpoints, the Briefcase JSONL trail and an uncommitted `SqlPlan` change. Decide: archive it, or delete it.
- [ ] **Empty `README.md`.** Replace with a short "what it is / how to run" (this document could seed it).

---

## 9. Candidates to add next

In the order the outline suggests. Tick what to build.

**Close the guarantee (small, high value)**
- [x] Stray-number check (gap 1), as the first eval scorer (detects; doesn't block yet)
- [ ] Accept only evidence minted in this run (gap 4)
- [ ] Decide on the 20-row preview (gap 2)

**Phase 1: prove it**
- [x] Eval steps 0 and 1: score storage, registry with requirements, four states, always-on evals, Evals tab
- [x] Step 2: golden answers ("Set as correct answer") and reference evals: expected numbers, expected text, abstained correctly, right columns used, execution accuracy
- [x] Step 3: batches (run the golden set N times), consistency, error bars
- [ ] Append-only configuration versions (gap 8)
- [ ] Build each dataset's DuckDB file once (gap 5)

**Phase 2: explain it**
- [ ] Promote an arena question to the golden set (with a "fields that unlock evals" hint)
- [x] Repeated trials and consistency (pass^k), in step 3
- [ ] Row-level diffs and flip rate between runs
- [ ] Visual trace view: the read-only graph with used columns glowing (Phase 2v)
- [ ] A state-driven "next step" guide (the game-like prompts)

**Later**
- [ ] Human labeling and the scorer report card (Phase 3)
- [ ] Second workflow: report drafting (Phase 3b)
- [ ] Data cleaning and correction steps; multi-table datasets
- [ ] Export skills and runs

---

## 10. File map

```
outputevals/
├── backend/
│   ├── app/
│   │   ├── main.py            app, routers, serves the built frontend
│   │   ├── config.py          OT_* settings (model, effort, data and library dirs)
│   │   ├── db.py              SQLite engine, add-missing-columns migration
│   │   ├── models.py          the nine tables
│   │   ├── api/               HTTP layer: settings, datasets, configurations,
│   │   │                      experiments, evidence, library, evals, golden, batches
│   │   ├── evals/
│   │   │   ├── registry.py    eval metadata, the four states, requirements → locked
│   │   │   ├── builtin.py     the seven always-on evals
│   │   │   ├── reference.py   the five evals graded against a golden answer
│   │   │   ├── service.py     score on create, backfill, re-score, scorecard
│   │   │   ├── stats.py       batch report: accuracy intervals, pass^k, pass@k, consistency
│   │   │   ├── numbers.py     finds numbers typed outside references
│   │   │   └── pricing.py     list prices for the cost eval
│   │   └── core/
│   │       ├── arena.py       two-arm tool loop, Briefcase hashes
│   │       ├── prompts.py     shared prefix, configuration text, citation rules
│   │       ├── sqltool.py     read-only DuckDB, result caps, number display
│   │       ├── evidence.py    content-addressed, append-only evidence + citing
│   │       ├── resolver.py    fail-closed render
│   │       ├── golden.py      matching runs to golden answers, drafting one from a run
│   │       ├── runner.py      one question through both arms, saved and scored (arena + batches)
│   │       ├── batches.py     background batch runs, cancel, interrupted-on-restart
│   │       ├── library.py     skill files on disk, path safety, attachments
│   │       ├── datasets.py    CSV profiling and storage
│   │       ├── ledger.py      thin Briefcase wrapper
│   │       ├── llm.py         Anthropic client, key check
│   │       └── secrets.py     key lookup and storage
│   └── tests/                 108 tests: evidence 19, batches 17, golden 16, evals 16, library 14,
│                              sqltool 10, workflow 7, settings 5, smoke 4
├── frontend/src/
│   ├── pages/                 Experiments, Arena, Datasets, Library,
│   │                          Configurations, ConfigWizard, Settings, Placeholder
│   ├── components/            Sidebar, GraphEditor, LibraryTree, DatasetPicker,
│   │                          NewExperimentModal, Topbar
│   ├── api.ts                 types and API calls
│   └── styles.css
├── data/                      (gitignored) database, uploaded CSVs, library, saved key
└── .env                       (gitignored) ANTHROPIC_API_KEY
```

---

## 11. Related material

| What | Where |
|---|---|
| Project outline (vision, architecture, eval playground, phases) | [PROJECT_OUTLINE.md](PROJECT_OUTLINE.md) |
| Braintrust ideas + eval metrics by example (PDF) | [braintrust-ideas.pdf](braintrust-ideas.pdf) |
| Observability: everything recorded about a run | [OBSERVABILITY.md](OBSERVABILITY.md) |
| Blueprint (interactive overview of the planned system) | https://claude.ai/artifact/78DVorHQgb4FZmhY9E6a36 |
| Primer (16-module course on the concepts and choices) | https://claude.ai/artifact/UTwdeLf9o86JdEKqnWivCB |
| Walkthrough (animated: one question through the graph to an answer) | https://claude.ai/artifact/PRhiWQ9Ek6osyZWUmLfTiY |
