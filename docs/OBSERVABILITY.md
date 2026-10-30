# Observability

*Everything outputevals records about a run, what each record looks like, and which technology produces it. As of 2026-10-28.*

The goal: for any answer, be able to say **what was asked, what the model saw, what it did, where each value came from, how it was graded, and what it cost.** Everything is stored locally in one SQLite file (`data/outputtracker.db`); nothing is sent to an external tracing service.

> **About the examples.** They are real records, in their exact stored shape, from a synthetic demo database: a generated invoices CSV and a fake model used by the test suite. That's why latency is a few milliseconds and token counts are round. Real runs have the same fields.

---

## 1. At a glance

| Layer | What's recorded | Stored in | Provided by |
|---|---|---|---|
| **Dataset identity** | SHA-256 of the uploaded file, row count, column profile | `dataset` | Python `hashlib` (native) · **pandas** (profile) |
| **Knowledge identity** | Configuration version hash; content hash of every library file the configured arm saw | `trial` | Python `hashlib` (native) |
| **What the model saw** | The full system prompt, the question | `armresponse`, `trial` | Our prompt builder (native) |
| **What the model did** | Every SQL query, its result, its error, the evidence ids minted from it | `armresponse.tool_calls` | Tool loop (native) · **DuckDB** (execution) |
| **Where values came from** | Content-addressed, append-only evidence records | `evidence` | Native, keyed with `hashlib` |
| **The answer** | Raw draft with `{{ev:…}}` references, rendered answer, whether it rendered, missing references | `armresponse` | Fail-closed resolver (native) |
| **Model API usage** | Model id, input / output / cache-read / cache-write tokens, stop reason, error | `armresponse` | **Anthropic API** via the `anthropic` Python SDK |
| **Timing** | Wall-clock milliseconds per arm | `armresponse.latency_ms` | Python `time.perf_counter` (native) |
| **Run identity** | Fingerprint (inputs) and content hash (everything) | `armresponse` | **Briefcase** (`briefcase-ai` 4.4) |
| **Grading** | One result per eval per arm: state, value, pass/fail, reason, details | `score` | Eval registry (native) |
| **Ground truth** | Golden answers pinned to a dataset hash | `goldencase` | Native |
| **Human judgement** | Preference label and a free-text note per question | `trial` | You, through the UI |
| **Server requests** | Method, path, status of each HTTP request | **Terminal only; not saved** | **Uvicorn** access log |

"Native" means code in this repo (`backend/app/`), not a third-party library.

---

## 2. Layer by layer

### 2.1 Dataset identity

Every uploaded CSV is stored byte-for-byte and identified by the SHA-256 of its contents. That hash feeds every evidence id, so a value computed from one version of a file can never be mistaken for one from another.

```json
{
  "id": "cd9d0587ca08",
  "name": "invoices",
  "filename": "invoices.csv",
  "sha256": "adfc730da7b84e7fdc1a5fe573a67af0dac9c2f0c396f715c83a69356e1115f9",
  "size_bytes": 39807,
  "row_count": 2000,
  "est_tokens": 13269
}
```

- **Provided by:** `hashlib.sha256` (Python standard library); column types, counts and samples by **pandas** (`core/datasets.py`).
- **See it:** Datasets page; `GET /api/datasets/{id}`.

### 2.2 Knowledge identity

Each question records exactly which knowledge the configured arm had:

```json
{
  "config_version": "e3b0c44298fc1c14",
  "library_files": [
    { "path": "sales-semantics/definitions.md", "sha256": "1a2b3c4d5e6f" }
  ]
}
```

- `config_version` is the first 16 hex characters of the SHA-256 of the configuration text: field descriptions, relationships, attached file contents and notes. Change any of them and the version changes. (In the demo it's `e3b0c442…`, the hash of an empty text: that configuration added nothing.)
- `library_files` lists every attached file with a hash of its contents, so a run can be reproduced even after the files change.
- **Provided by:** `hashlib` (native); `core/prompts.py`, `core/library.py`.
- **See it:** the chips under each question in the arena ("Library seen by configured arm").

### 2.3 What the model saw

The exact system prompt each arm received is stored in full, after templating. Excerpt:

```text
You are a data analyst answering questions about a CSV dataset.
Answer using only the data. If the data does not contain the answer, say so plainly instead of guessing.

The dataset is loaded as a DuckDB table named `data` with every row of the original file. …
Every query result lists evidence ids for its values. In your answer, write each value that
comes from the data as its reference, for example "The top customer was {{ev:7f3a91c2d0e4}} …"

<dataset filename="invoices.csv" rows="2000" table="data">
<columns> … </columns>
<first_rows> … 20 lines of the original CSV … </first_rows>
</dataset>
```

The configured arm's prompt adds a `<data_dictionary>`, a `<library>` block with each attached file, and `<additional_context>` (notes). Baseline and configured share a byte-identical first block, which is also the prompt-cache prefix.

- **Provided by:** native (`core/prompts.py`).
- **See it:** "What the model saw" under each arm, which shows the system prompt, question, queries, evidence and draft.

### 2.4 What the model did

Every tool call is recorded in order, with the SQL, the result as the model saw it, any error, and the evidence minted from it:

```json
[
  {
    "sql": "SELECT customer, SUM(amount) AS total FROM data GROUP BY 1 ORDER BY 2 DESC LIMIT 1",
    "error": null,
    "row_count": 1,
    "result": "customer,total\r\nCustomer 4,400600\r\n",
    "evidence": [
      { "ev_id": "ev:f20a020b38e1", "value": "Customer 4", "label": "row 0 · \"customer\"" },
      { "ev_id": "ev:cba84df985c5", "value": "400600",     "label": "row 0 · \"total\"" }
    ]
  }
]
```

A failed query keeps the database's error message (`"error": "Binder Error: Referenced column \"amout\" not found…"`), which the model also saw and could correct.

- **Provided by:** the tool loop (`core/arena.py`, native); execution by **DuckDB** (in memory, external file access off, configuration locked); result caps and number formatting in `core/sqltool.py`.
- **See it:** "What the model saw" → QUERY / RESULT / EVIDENCE.

### 2.5 Where values came from: evidence

Each cell of a small query result becomes an append-only evidence record. Its id is a hash of the dataset hash, the normalized SQL and the cell's position, so the same data, query and cell always give the same id.

```json
{
  "ev_id": "ev:cba84df985c5",
  "value": "400600",
  "label": "row 0 · \"total\"",
  "query": "SELECT customer, SUM(amount) AS total FROM data GROUP BY 1 ORDER BY 2 DESC LIMIT 1",
  "source": "adfc730da7b84e7fdc1a5fe573a67af0dac9c2f0c396f715c83a69356e1115f9",
  "dataset_id": "cd9d0587ca08",
  "superseded_by": null,
  "history": ["400600"]
}
```

- A correction appends a new row and marks the old one `superseded_by`; `history` lists every value ever recorded.
- "Row 0" is a row of the **query result**. For an aggregate like this, it isn't a row of the original CSV.
- **Provided by:** native (`core/evidence.py`), ids from `hashlib`.
- **See it:** `GET /api/evidence/{ev_id}`; the EVIDENCE lines under "What the model saw".

### 2.6 The answer

Both the draft the model wrote and the answer a reader sees are kept:

```json
{
  "output":          "Top customer: {{ev:f20a020b38e1}} with {{ev:cba84df985c5}}.",
  "render_ok":       true,
  "rendered_output": "Top customer: Customer 4 with 400600.",
  "missing_refs":    []
}
```

When a draft cites an id that doesn't exist, nothing is shown:

```json
{
  "output":          "Top customer: {{ev:f20a020b38e1}} with {{ev:000000000000}}.",
  "render_ok":       false,
  "rendered_output": "",
  "missing_refs":    ["ev:000000000000"]
}
```

- **Provided by:** the fail-closed resolver (`core/resolver.py`, native).
- **See it:** the arena (rendered answer, or a red "Answer refused" notice); the raw draft under "What the model saw".

### 2.7 Model API usage and timing

```json
{
  "model": "claude-opus-5-5",
  "stop_reason": "end_turn",
  "error": null,
  "input_tokens": 100,
  "output_tokens": 20,
  "cache_creation_tokens": 0,
  "cache_read_tokens": 0,
  "latency_ms": 7
}
```

- Token counts are **summed across every model call in the arm's tool loop**. One arm usually makes several calls: one per query round, plus the final answer.
- `stop_reason` is from the **last** call. A refusal records `error: "Model declined to answer (<category>)."` from the API's `stop_details`; hitting the token limit records `"Answer was cut off at the token limit."`; API and connection failures record their message.
- `latency_ms` is one number for the whole arm, measured around the entire loop.
- **Provided by:** token counts, stop reason and refusal category come from the **Anthropic API** response (`response.usage`, `response.stop_reason`, `response.stop_details`) through the **`anthropic` Python SDK**; timing from Python's `time.perf_counter` (native).
- **See it:** the footer of each arm ("SQL · 1 query · 0.0s · 100 in · 20 out"); the Cost and Latency evals.

### 2.8 Run identity: fingerprint and content hash

```json
{
  "fingerprint":  "3c1490d7bf9babec508779fbf533b7102c7858612ce00298214f5e73bd120a44",
  "content_hash": "4483c91494931349ba6556aa27d2574097834b0023a7a7217203e83166b4c8f9"
}
```

| Hash | Covers | Same value means |
|---|---|---|
| **Fingerprint** | Which arm ran, system prompt, question, settings (effort, max tokens, mode), model | The same thing was asked the same way |
| **Content hash** | All of the above plus the draft, every tool call, any error, the experiment and dataset ids | The run is identical, output included |

Latency is in neither. Same fingerprint with different content hashes means the model answered the same input differently: drift, or plain non-determinism.

- **Provided by:** **Briefcase** (`briefcase-ai` 4.4). `core/arena.py` builds a Briefcase `DecisionSnapshot` at the end of each arm, keeps these two hashes, and discards the snapshot. That is Briefcase's whole role today; its replay, drift, cost, hash-chain and audit-bundle features are not used. All Briefcase calls go through `core/ledger.py`.
- **See it:** the TRACE line at the bottom of "What the model saw".

### 2.9 Grading: eval scores

Every arm is scored by every registered eval the moment the run is saved. Older runs are scored from their saved traces when first viewed. Each result is one row:

```json
{ "arm": "configured", "scorer": "refs_resolve",      "scorer_version": 1, "state": "scored",
  "value": 1.0, "passed": true,  "reason": "All 2 reference(s) resolved.", "details": { "references": 2 } }

{ "arm": "configured", "scorer": "cost",              "scorer_version": 1, "state": "scored",
  "value": 0.0008, "passed": null, "reason": "$0.0008 · 100 in (0 cached) · 20 out",
  "details": { "tokens": { "input": 100, "output": 20, "cache_read": 0, "cache_write": 0 },
               "usd": { "total": 0.0008, "input": 0.0004, "output": 0.0004, "cache_read": 0.0, "cache_write": 0.0 } } }

{ "arm": "configured", "scorer": "execution_accuracy", "scorer_version": 1, "state": "scored",
  "value": 1.0, "passed": true,  "reason": "Query 1 returns the same 1 row(s) as the reference query.",
  "details": { "query": 1, "golden_version": 1 } }

{ "arm": "configured", "scorer": "abstained",         "scorer_version": 1, "state": "not_applicable",
  "value": null, "passed": null, "reason": "This question has an answer in the data." }

{ "arm": "",           "scorer": "arms_agree",        "scorer_version": 1, "state": "scored",
  "value": 1.0, "passed": null, "reason": "Both arms cite the same values.",
  "details": { "baseline": ["400600", "customer 4"], "configured": ["400600", "customer 4"] } }
```

- **States:** `scored` · `locked` (needs something that doesn't exist yet, e.g. a golden answer) · `not_applicable` · `not_computed` (should have run but couldn't, with the reason). Only `scored` results count toward rates and averages.
- **`passed` is null** for measurements (cost, latency) and signals (arms agree). They aren't pass/fail.
- **Versioned:** results are stored per eval version. `golden_version` in `details` records which version of the golden answer a result was graded against.
- **Provided by:** the eval registry and its 12 evals (`app/evals/`, native). Cost uses list prices in `evals/pricing.py`; execution accuracy re-runs queries on **DuckDB**.
- **See it:** score chips under each arm (hover for the reason); the **Evals** tab (scorecard, runs table, About these evals).

### 2.10 Ground truth: golden answers

```json
{
  "id": "7037bc0a332c",
  "dataset_id": "cd9d0587ca08",
  "dataset_sha": "adfc730da7b84e7fdc1a5fe573a67af0dac9c2f0c396f715c83a69356e1115f9",
  "question": "Who is the top customer by total amount?",
  "question_key": "who is the top customer by total amount",
  "answerable": true,
  "expected_values": ["Customer 4", "400601"],
  "tolerance": 0.001,
  "expected_columns": ["customer", "amount"],
  "reference_sql": "SELECT customer, SUM(amount) AS total FROM data GROUP BY 1 ORDER BY 2 DESC LIMIT 1",
  "category": "aggregation",
  "held_out": false,
  "version": 1,
  "created_from_trial_id": "e5a8518f1a08"
}
```

- Pinned to the exact data (`dataset_sha`), never to a configuration. Runs link to it by an exact match on `question_key`, recorded as `trial.golden_case_id`.
- (400601 is deliberately one off; it still passes because it's within the 0.1% tolerance.)
- **Provided by:** native (`core/golden.py`, `api/golden.py`).
- **See it:** "Golden answer set" badge in the arena; Golden answers section on the Evals tab.

### 2.11 Human judgement

```json
{ "preference": "configured", "note": "Baseline used the tax-inclusive total." }
```

Values: `baseline`, `configured`, `tie`, `both_bad`, or null. The note is for open coding: naming what went wrong in your own words.

- **Provided by:** you, through the arena.

### 2.12 Server requests

Uvicorn prints one line per HTTP request to the terminal running the server:

```text
INFO:     127.0.0.1:52344 - "POST /api/experiments/60c54db21a32/trials HTTP/1.1" 200 OK
```

These lines are **not saved anywhere**, and the app writes no logs of its own.

---

## 3. How one run fits together

```
dataset (sha256) ─────────────┐
                              ▼
experiment ──▶ trial ──────────────────────────────▶ goldencase
               (question, config_version,           (expected values,
                library_files, preference, note)      pinned to dataset sha)
                  │
                  ├─▶ armresponse: baseline      ├─▶ score × 12 per arm
                  └─▶ armresponse: configured    └─▶ score × 1 per question (arms agree)
                        system_prompt
                        tool_calls ──────▶ evidence (ev_id = hash of dataset sha + SQL + cell)
                        output ──resolver──▶ rendered_output
                        tokens, stop_reason, error, latency_ms
                        fingerprint, content_hash   (Briefcase)
```

## 4. Ways to look at it

| Where | What you get |
|---|---|
| **Arena** | Rendered answers, score chips with reasons, token/latency footer, "What the model saw" (prompt, queries, results, evidence, draft, content hash) |
| **Evals tab** | Scorecard per arm, filterable runs with every score and reason, golden answers and coverage |
| **API** | `GET /api/experiments/{id}/trials` (everything per question, including scores) · `GET /api/evidence/{ev_id}` · `GET /api/experiments/{id}/evals` · `GET /api/evals/scorers` |
| **SQLite directly** | `sqlite3 data/outputtracker.db` then e.g. `SELECT scorer, state, reason FROM score WHERE trial_id = '…';` |

---

## 5. What is not recorded

| Not recorded | Why it matters | How to add it |
|---|---|---|
| **Each model call separately.** Tokens are summed and timing merged per arm | Can't see which round of a long tool loop was slow or expensive | Store one record ("span") per call |
| **The API request id** (`response._request_id`) | It's what Anthropic support asks for when a call misbehaves | Save it on each span |
| **Per-query timing in DuckDB** | Slow data loading (e.g. reloading a large CSV) is invisible | Time each `DataQuery.run` |
| **SDK retries.** The SDK silently retries rate limits and server errors up to twice | A slow run might be a retry, and nothing shows it | Count retries (SDK hooks or `max_retries=0` plus our own loop) |
| **Code version.** No git commit on runs | A score change can't be traced to a prompt or eval code change | Record the commit on each trial |
| **Thinking content** | Not returned by default on Opus 5.5 (`display: "omitted"`); billed in output tokens either way | Request summarized thinking if it's ever needed |
| **Server logs** | Uvicorn's request log isn't saved; the app logs nothing | Add structured logging, or OpenTelemetry once anything runs in production |
| **HTTP, network and host metrics.** DNS, TLS, retries on the wire, CPU, memory | Abstracted by Anthropic and DuckDB; rarely explains answer quality | Only via OpenTelemetry in production |

The lowest level recorded today is the **Anthropic API response** (token counts, stop reasons, refusal categories, errors) plus per-arm wall-clock time. The hashes sit *above* that layer: they're summaries of what was recorded, used for identity and drift, not a view closer to the network or hardware.

---

## 6. Privacy and storage notes

- Everything lives in `data/` (gitignored): the database, uploaded CSVs, the library, and a saved API key if one was entered in Settings.
- Stored system prompts include the **first 20 lines of the CSV**, and query results include data values. Treat the database as containing client data.
- The API key is never stored in the database or returned by the API; it's shown masked.
- Nothing is sent anywhere except the model calls themselves, to the Anthropic API.
