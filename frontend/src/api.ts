async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const isForm = init?.body instanceof FormData
  const res = await fetch(path, {
    ...init,
    headers: isForm ? init?.headers : { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (res.status === 204) return undefined as T
  const body = await res.json().catch(() => ({}))
  if (!res.ok) {
    const detail = typeof body.detail === 'string' ? body.detail : body.detail?.[0]?.msg
    throw new Error(detail ?? `Request failed (${res.status})`)
  }
  return body as T
}

const json = (method: string, data: unknown): RequestInit => ({ method, body: JSON.stringify(data) })

// ---------- Settings ----------
export interface AnthropicStatus {
  configured: boolean
  source: 'dotenv' | 'env' | 'saved' | 'none'
  masked_key: string | null
  model: string
}

export interface KeyCheckResult {
  ok: boolean
  message: string
  model: string | null
  model_display_name: string | null
  context_window: number | null
}

// ---------- Datasets ----------
export interface Column {
  name: string
  dtype: 'number' | 'text' | 'date' | 'boolean'
  non_null: number
  unique: number
  samples: string[]
}

export interface Dataset {
  id: string
  name: string
  filename: string
  sha256: string
  size_bytes: number
  row_count: number
  est_tokens: number
  columns: Column[]
  created_at: string
}

export interface Preview {
  columns: string[]
  rows: (string | number | boolean | null)[][]
}

// ---------- Configurations ----------
export interface ConfigNode {
  id: string
  description: string
  x: number
  y: number
}

export interface ConfigEdge {
  id?: string
  source: string
  target: string
  description: string
}

export interface ConfigurationIn {
  name: string
  dataset_id: string
  nodes: ConfigNode[]
  edges: ConfigEdge[]
  attachments: string[] // library folders or files
  context_markdown: string
}

export interface Configuration extends ConfigurationIn {
  id: string
  prompt_preview: string
  attachment_error: string | null
}

// ---------- Library ----------
export interface LibraryNode {
  path: string
  name: string
  type: 'folder' | 'file'
  size?: number
  children?: LibraryNode[]
}

// ---------- Experiments ----------
export interface Experiment {
  id: string
  name: string
  description: string
  configuration_id: string
  configuration_name: string
  dataset_id: string
  dataset_name: string
  trial_count: number
  created_at: string
}

export type Arm = 'baseline' | 'configured'
export type Preference = Arm | 'tie' | 'both_bad'

export interface CitedValue {
  ev_id: string
  value: string
  label: string
}

export interface ToolCall {
  sql: string
  error: string | null
  row_count: number
  result: string
  evidence?: CitedValue[] // missing on trials recorded before evidence existed
}

export interface ArmResponse {
  id: string
  arm: Arm
  model: string
  mode: 'inline' | 'query'
  tool_calls: ToolCall[]
  output: string // raw draft with {{ev:…}} references
  render_ok: boolean | null // null: nothing to render (error, or recorded before rendering existed)
  rendered_output: string
  missing_refs: string[]
  system_prompt: string
  stop_reason: string | null
  error: string | null
  input_tokens: number
  output_tokens: number
  cache_creation_tokens: number
  cache_read_tokens: number
  latency_ms: number
  fingerprint: string
  content_hash: string
}

export interface Trial {
  id: string
  experiment_id: string
  question: string
  config_version: string
  library_files: { path: string; sha256: string }[] // what the configured arm saw
  golden_case_id: string // '' until the question has a golden case
  batch_id: string // '' for questions asked in the arena
  repeat: number
  preference: Preference | null
  note: string
  created_at: string
  responses: ArmResponse[]
  scores: Score[] // current-version evals for both arms and the trial
}

// ---------- Evals ----------
// scored: it ran · locked: needs something that doesn't exist yet · not_applicable: can't apply · not_computed: failed to run
export type ScoreState = 'scored' | 'locked' | 'not_applicable' | 'not_computed'

export interface Score {
  id: string
  trial_id: string
  response_id: string // '' for trial-level evals
  arm: Arm | ''
  scorer: string
  scorer_version: number
  state: ScoreState
  value: number | null
  passed: boolean | null // null when the eval measures instead of judging
  reason: string
  details: Record<string, unknown>
  created_at: string
}

export interface ScorerInfo {
  name: string
  title: string
  family: string
  level: 'response' | 'trial'
  kind: 'verdict' | 'measure' | 'signal'
  version: number
  measures: string
  how: string
  caveat: string
  unit: string
  requires: string[]
}

export interface ScorecardRow {
  scorer: string
  arm: Arm | ''
  total: number
  scored: number
  locked: number
  not_applicable: number
  not_computed: number
  judged: number
  passed: number
  mean: number | null
  sum: number | null
  not_computed_reasons: string[]
}

export interface ExperimentEvals {
  runs: number
  scorecard: ScorecardRow[]
}

// ---------- Golden cases ----------
export type GoldenCategory = '' | 'lookup' | 'aggregation' | 'multi-hop' | 'unanswerable'

export interface GoldenIn {
  question: string
  answerable: boolean
  expected_values: string[]
  tolerance: number // relative, 0.001 = 0.1%
  expected_columns: string[]
  reference_sql: string
  category: GoldenCategory
  held_out: boolean
  notes: string
  trial_id?: string
  dataset_id?: string
}

export interface GoldenCase extends GoldenIn {
  id: string
  dataset_id: string
  dataset_sha: string
  version: number
  created_from_trial_id: string
  linked_runs: number
  created_at: string
  updated_at: string
}

export interface GoldenDraft extends Partial<GoldenIn> {
  question: string
  source_arm?: Arm
  dataset_columns: string[]
}

// ---------- Batches ----------
export type BatchStatus = 'running' | 'done' | 'cancelled' | 'failed' | 'interrupted'

export interface Batch {
  id: string
  experiment_id: string
  golden_case_ids: string[]
  repeats: number
  total: number
  done: number
  status: BatchStatus
  error: string
  config_version: string
  model: string
  settings: Record<string, unknown>
  created_at: string
  finished_at: string | null
}

export interface BatchEstimate {
  questions: number
  repeats: number
  runs: number
  model_calls_at_least: number
  est_cost_usd: number | null
  est_minutes: number | null
  based_on_runs: number
  max_runs: number
  max_repeats: number
  concurrency: number
}

/** A pass rate averaged over questions, with a 95% interval (null with too few runs). */
export interface Rate {
  mean: number
  lo: number | null
  hi: number | null
  questions: number
  runs?: number
}

export interface Count { count: number; of: number }

export interface ArmSummary {
  accuracy: Rate | null
  pass_all: Count
  pass_any: Count
  consistent: Count
  errors: number
  latency: { p50: number; p95: number } | null
  cost: { total: number; per_run: number } | null
}

export interface BatchRun {
  trial_id: string
  repeat: number
  correct: boolean | null
  reason: string
  answer: string
}

export interface BatchQuestion {
  golden_case_id: string
  question: string
  category: string
  held_out: boolean
  arms: Record<Arm, { runs: BatchRun[]; judged: number; passed: number; distinct_answers: number; same_answer_share: number | null }>
}

export interface BatchReport {
  repeats: number
  runs_done: number
  arms: Record<Arm, ArmSummary>
  difference: Rate | null
  questions: BatchQuestion[]
  evals: (Rate & { scorer: string; arm: Arm })[]
}

export const api = {
  anthropicStatus: () => request<AnthropicStatus>('/api/settings/anthropic'),
  saveAnthropicKey: (api_key: string) => request<KeyCheckResult>('/api/settings/anthropic', json('PUT', { api_key })),
  testAnthropicKey: () => request<KeyCheckResult>('/api/settings/anthropic/test', { method: 'POST' }),
  deleteAnthropicKey: () => request<AnthropicStatus>('/api/settings/anthropic', { method: 'DELETE' }),

  datasets: () => request<Dataset[]>('/api/datasets'),
  dataset: (id: string) => request<Dataset>(`/api/datasets/${id}`),
  preview: (id: string) => request<Preview>(`/api/datasets/${id}/preview`),
  uploadDataset: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<Dataset>('/api/datasets', { method: 'POST', body: form })
  },
  deleteDataset: (id: string) => request<void>(`/api/datasets/${id}`, { method: 'DELETE' }),

  configurations: () => request<Configuration[]>('/api/configurations'),
  configuration: (id: string) => request<Configuration>(`/api/configurations/${id}`),
  createConfiguration: (body: ConfigurationIn) => request<Configuration>('/api/configurations', json('POST', body)),
  updateConfiguration: (id: string, body: ConfigurationIn) =>
    request<Configuration>(`/api/configurations/${id}`, json('PUT', body)),
  deleteConfiguration: (id: string) => request<void>(`/api/configurations/${id}`, { method: 'DELETE' }),

  libraryTree: () => request<LibraryNode[]>('/api/library/tree'),
  libraryFile: (path: string) =>
    request<{ path: string; content: string }>(`/api/library/file?path=${encodeURIComponent(path)}`),
  saveLibraryFile: (path: string, content: string) =>
    request<{ path: string; content: string }>('/api/library/file', json('PUT', { path, content })),
  createLibraryFolder: (path: string) => request<void>('/api/library/folder', json('POST', { path })),
  deleteLibraryItem: (path: string) =>
    request<void>(`/api/library/item?path=${encodeURIComponent(path)}`, { method: 'DELETE' }),

  scorers: () => request<{ scorers: ScorerInfo[]; unlock_hints: Record<string, string> }>('/api/evals/scorers'),
  experimentEvals: (id: string, scope = 'all') => request<ExperimentEvals>(`/api/experiments/${id}/evals?scope=${encodeURIComponent(scope)}`),
  rescoreExperiment: (id: string) => request<ExperimentEvals>(`/api/experiments/${id}/evals/rescore`, { method: 'POST' }),

  goldenCases: (datasetId: string) => request<GoldenCase[]>(`/api/datasets/${datasetId}/golden`),
  goldenDraft: (trialId: string, arm: Arm) => request<GoldenDraft>(`/api/trials/${trialId}/golden-draft?arm=${arm}`),
  createGolden: (body: GoldenIn) => request<GoldenCase>('/api/golden', json('POST', body)),
  updateGolden: (id: string, body: GoldenIn) => request<GoldenCase>(`/api/golden/${id}`, json('PUT', body)),
  deleteGolden: (id: string) => request<void>(`/api/golden/${id}`, { method: 'DELETE' }),

  experiments: () => request<Experiment[]>('/api/experiments'),
  experiment: (id: string) => request<Experiment>(`/api/experiments/${id}`),
  createExperiment: (body: { name: string; configuration_id: string }) =>
    request<Experiment>('/api/experiments', json('POST', body)),
  deleteExperiment: (id: string) => request<void>(`/api/experiments/${id}`, { method: 'DELETE' }),

  trials: (experimentId: string, scope = 'all') =>
    request<Trial[]>(`/api/experiments/${experimentId}/trials?scope=${encodeURIComponent(scope)}`),

  batches: (experimentId: string) => request<Batch[]>(`/api/experiments/${experimentId}/batches`),
  batchEstimate: (experimentId: string, repeats: number, cases: string[]) =>
    request<BatchEstimate>(`/api/experiments/${experimentId}/batches/estimate?repeats=${repeats}&cases=${cases.join(',')}`),
  startBatch: (experimentId: string, repeats: number, golden_case_ids: string[]) =>
    request<Batch>(`/api/experiments/${experimentId}/batches`, json('POST', { repeats, golden_case_ids })),
  batch: (id: string) => request<{ batch: Batch; report: BatchReport }>(`/api/batches/${id}`),
  cancelBatch: (id: string) => request<Batch>(`/api/batches/${id}/cancel`, { method: 'POST' }),
  deleteBatch: (id: string) => request<void>(`/api/batches/${id}`, { method: 'DELETE' }),
  runTrial: (experimentId: string, question: string) =>
    request<Trial>(`/api/experiments/${experimentId}/trials`, json('POST', { question })),
  updateTrial: (id: string, body: { preference?: Preference | null; note?: string }) =>
    request<Trial>(`/api/trials/${id}`, json('PATCH', body)),
}

export function timeAgo(iso: string): string {
  const s = (Date.now() - new Date(iso.endsWith('Z') || iso.includes('+') ? iso : `${iso}Z`).getTime()) / 1000
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return `${Math.floor(s / 86400)}d ago`
}
