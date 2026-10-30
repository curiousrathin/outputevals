import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, Play, Square, Trash2 } from 'lucide-react'
import { api, timeAgo, type Arm, type ArmSummary, type Batch, type BatchQuestion, type BatchReport, type Count, type Experiment, type GoldenCase, type Rate, type ScorerInfo } from '../api'
import { formatMeasure } from '../evals'

const ARMS: Arm[] = ['baseline', 'configured']
const ARM_LABEL: Record<Arm, string> = { baseline: 'Baseline', configured: 'Configured' }
const STATUS: Record<Batch['status'], string> = {
  running: 'Running', done: 'Done', cancelled: 'Cancelled', failed: 'Failed', interrupted: 'Interrupted',
}
const pct = (x: number) => `${Math.round(100 * x)}%`
const pts = (x: number) => `${x > 0 ? '+' : x < 0 ? '−' : '±'}${Math.abs(Math.round(100 * x))} pts`

/** A 95% interval on a 0–1 scale (or −1…+1 when `signed`): a bar for the interval, a dot for the estimate. */
function IntervalStrip({ rate, arm, signed = false, label }: { rate: Rate; arm?: Arm; signed?: boolean; label: string }) {
  const min = signed ? -1 : 0
  const x = (v: number) => `${(100 * (v - min)) / (1 - min)}%`
  const ci = rate.lo !== null && rate.hi !== null
  const tip = `${label}: ${signed ? pts(rate.mean) : pct(rate.mean)}` +
    (ci ? `\n95% interval: ${signed ? pts(rate.lo!) : pct(rate.lo!)} to ${signed ? pts(rate.hi!) : pct(rate.hi!)}` : '\nToo few runs for an interval') +
    `\n${rate.questions} question${rate.questions === 1 ? '' : 's'}${rate.runs ? ` · ${rate.runs} runs` : ''}`
  return (
    <svg className={`interval ${arm ?? 'diff'}`} role="img" aria-label={tip} viewBox="0 0 100 14" preserveAspectRatio="none">
      <title>{tip}</title>
      <line className="track" x1="0" x2="100" y1="7" y2="7" />
      {signed && <line className="zero" x1="50" x2="50" y1="1" y2="13" />}
      {ci && <line className="ci" x1={x(rate.lo!)} x2={x(rate.hi!)} y1="7" y2="7" />}
      <circle className="est" cx={x(rate.mean)} cy="7" r="4" />
    </svg>
  )
}

function Tile({ label, main, sub, children }: { label: string; main: string; sub?: string; children?: ReactNode }) {
  return (
    <div className="tile">
      <div className="tile-label">{label}</div>
      <div className="tile-main">{main}</div>
      {children}
      {sub && <div className="sc-sub">{sub}</div>}
    </div>
  )
}

const count = (c: Count) => (c.of ? `${c.count} of ${c.of}` : '—')

function ArmTiles({ arm, s, repeats }: { arm: Arm; s: ArmSummary; repeats: number }) {
  const a = s.accuracy
  return (
    <div className={`arm-tiles arm-${arm}`}>
      <h4><span className={`arm-dot ${arm}`} />{ARM_LABEL[arm]}</h4>
      <div className="tiles">
        <Tile
          label="Accuracy"
          main={a ? pct(a.mean) : '—'}
          sub={a ? (a.lo !== null ? `95% interval ${pct(a.lo)}–${pct(a.hi!)}` : 'too few runs for an interval') : 'no graded runs yet'}
        >
          {a && <IntervalStrip rate={a} arm={arm} label={`${ARM_LABEL[arm]} accuracy`} />}
        </Tile>
        <Tile label={`Right every time (pass^${repeats})`} main={count(s.pass_all)} sub="questions" />
        <Tile label={`Right at least once (pass@${repeats})`} main={count(s.pass_any)} sub="questions" />
        <Tile label="Same answer every time" main={count(s.consistent)} sub="questions asked 2+ times" />
        <Tile
          label="Cost"
          main={s.cost ? formatMeasure(s.cost.total, '$') : '—'}
          sub={s.cost ? `${formatMeasure(s.cost.per_run, '$')} per run` : undefined}
        />
        <Tile
          label="Latency (median)"
          main={s.latency ? formatMeasure(s.latency.p50, 's') : '—'}
          sub={s.latency ? `p95 ${formatMeasure(s.latency.p95, 's')}${s.errors ? ` · ${s.errors} errors` : ''}` : undefined}
        />
      </div>
    </div>
  )
}

function Difference({ d }: { d: Rate | null }) {
  if (!d) return null
  const ci = d.lo !== null && d.hi !== null
  const clear = ci && (d.lo! > 0 || d.hi! < 0)
  const verdict = !ci
    ? 'Too few runs to tell whether this is more than noise.'
    : clear
      ? `${d.mean > 0 ? 'Configured' : 'Baseline'} is ahead by more than the noise in these runs.`
      : 'The interval includes zero: these runs can’t tell the arms apart yet.'
  return (
    <div className="difference">
      <div>
        <div className="tile-label">Configured − baseline, accuracy</div>
        <div className="tile-main">{pts(d.mean)}</div>
        <div className="sc-sub">
          {ci ? `95% interval ${pts(d.lo!)} to ${pts(d.hi!)} · ` : ''}paired by question, {d.questions} question{d.questions === 1 ? '' : 's'}
        </div>
      </div>
      <div className="difference-plot">
        <IntervalStrip rate={d} signed label="Configured − baseline" />
        <div className="axis"><span>−100</span><span>0</span><span>+100</span></div>
      </div>
      <p className="small">
        {verdict}
        {d.questions < 5 && ' With fewer than 5 questions, the interval mostly reflects these particular questions; add golden answers to make it meaningful.'}
      </p>
    </div>
  )
}

function RunDots({ q, arm }: { q: BatchQuestion; arm: Arm }) {
  const a = q.arms[arm]
  return (
    <div className="run-dots">
      <div className="run-marks">
        {a.runs.map((r) => (
          <span
            key={r.trial_id}
            className={`mark ${r.correct === null ? 'muted' : r.correct ? 'pass' : 'fail'}`}
            title={`Run ${r.repeat + 1}: ${r.correct === null ? 'not graded' : r.correct ? 'correct' : 'incorrect'}\n${r.reason}\nCited: ${r.answer}`}
          >
            {r.correct === null ? '·' : r.correct ? '✓' : '✗'}
          </span>
        ))}
      </div>
      <div className="sc-sub">
        {a.judged ? `${a.passed}/${a.judged} correct` : 'not graded'}
        {a.runs.length > 1 && ` · ${a.distinct_answers === 1 ? 'same answer' : `${a.distinct_answers} different answers`}`}
      </div>
    </div>
  )
}

function Report({ report, scorers, onShowRuns }: { report: BatchReport; scorers: ScorerInfo[]; onShowRuns: () => void }) {
  const verdicts = scorers.filter((s) => s.kind === 'verdict' && s.level === 'response')
  const evalRow = (name: string, arm: Arm) => report.evals.find((e) => e.scorer === name && e.arm === arm)
  return (
    <div className="batch-report">
      <div className="arm-tiles-grid">
        {ARMS.map((arm) => <ArmTiles key={arm} arm={arm} s={report.arms[arm]} repeats={report.repeats} />)}
      </div>
      <Difference d={report.difference} />

      <div className="filter-row">
        <h3>By question</h3>
        <button className="link-muted" onClick={onShowRuns}>Show these runs in the table below →</button>
      </div>
      <table className="runs">
        <thead><tr><th>Question</th><th>Baseline</th><th>Configured</th></tr></thead>
        <tbody>
          {report.questions.map((q) => (
            <tr key={q.golden_case_id}>
              <td className="run-q">
                {q.question}
                <div className="sc-sub">{[q.category || 'uncategorized', q.held_out ? 'held out' : ''].filter(Boolean).join(' · ')}</div>
              </td>
              {ARMS.map((arm) => <td key={arm}><RunDots q={q} arm={arm} /></td>)}
            </tr>
          ))}
        </tbody>
      </table>

      <h3>Every pass/fail eval, with 95% intervals</h3>
      <table className="scorecard">
        <thead><tr><th>Eval</th><th>Baseline</th><th>Configured</th></tr></thead>
        <tbody>
          {verdicts.map((info) => (
            <tr key={info.name}>
              <td className="sc-name" title={`${info.measures}\nHow: ${info.how}\nCaveat: ${info.caveat}`}>
                <b>{info.title}</b><span>{info.family}</span>
              </td>
              {ARMS.map((arm) => {
                const r = evalRow(info.name, arm)
                return (
                  <td key={arm}>
                    {r ? (
                      <>
                        <div className="sc-main">{pct(r.mean)}</div>
                        <IntervalStrip rate={r} arm={arm} label={`${info.title}, ${ARM_LABEL[arm]}`} />
                        <div className="sc-sub">{r.lo !== null ? `${pct(r.lo)}–${pct(r.hi!)}` : 'no interval'} · {r.runs} runs</div>
                      </>
                    ) : <span className="muted">—</span>}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted small">
        Intervals come from a two-level bootstrap: resample the questions, then the runs within each question.
        Each question counts once, however many times it was asked. Accuracy, pass^k and pass@k use the Correct eval.
      </p>
    </div>
  )
}

function StartBatch({ exp, cases }: { exp: Experiment; cases: GoldenCase[] }) {
  const queryClient = useQueryClient()
  const [repeats, setRepeats] = useState(5)
  const [chosen, setChosen] = useState<string[] | null>(null) // null: all
  const [picking, setPicking] = useState(false)
  const ids = chosen ?? cases.map((c) => c.id)
  const estimate = useQuery({
    queryKey: ['batch-estimate', exp.id, repeats, ids.join(',')],
    queryFn: () => api.batchEstimate(exp.id, repeats, ids),
    enabled: ids.length > 0 && repeats >= 1,
  })
  const start = useMutation({
    mutationFn: () => api.startBatch(exp.id, repeats, ids),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['batches', exp.id] }),
  })
  const e = estimate.data
  const tooBig = e ? e.runs > e.max_runs : false

  if (!cases.length) {
    return <p className="muted small">A batch runs the golden questions. Set a correct answer on at least one run first.</p>
  }
  return (
    <div className="batch-start">
      <div className="batch-start-row">
        <label>
          Ask
          <button className="link-muted" onClick={() => setPicking(!picking)}>
            {ids.length === cases.length ? `all ${cases.length}` : `${ids.length} of ${cases.length}`} golden question{cases.length === 1 ? '' : 's'}
          </button>
        </label>
        <label>
          <input
            type="number" min={1} max={e?.max_repeats ?? 20} value={repeats}
            onChange={(ev) => setRepeats(Math.max(1, Math.min(20, Number(ev.target.value) || 1)))}
          /> times each, on both arms
        </label>
        <button className="btn btn-primary btn-sm" disabled={!ids.length || tooBig || start.isPending} onClick={() => start.mutate()}>
          {start.isPending ? <Loader2 size={14} className="spin" /> : <Play size={14} />} Run batch
        </button>
      </div>
      {picking && (
        <div className="batch-pick">
          {cases.map((c) => (
            <label key={c.id}>
              <input
                type="checkbox"
                checked={ids.includes(c.id)}
                onChange={(ev) => setChosen(ev.target.checked ? [...ids, c.id] : ids.filter((i) => i !== c.id))}
              />
              {c.question} {c.held_out && <span className="muted small">(held out)</span>}
            </label>
          ))}
        </div>
      )}
      {e && (
        <p className={`small ${tooBig ? 'error-text' : 'muted'}`}>
          {e.runs} runs · at least {e.model_calls_at_least} model calls
          {e.est_cost_usd !== null ? ` · about ${formatMeasure(e.est_cost_usd, '$')}` : ' · cost unknown until a question has been asked'}
          {e.est_minutes !== null && ` · about ${Math.max(1, Math.round(e.est_minutes))} min`}
          {e.based_on_runs > 0 && ` (estimated from ${e.based_on_runs} earlier run${e.based_on_runs === 1 ? '' : 's'})`}
          {tooBig && ` · over the ${e.max_runs}-run limit`}
          . The configuration is frozen when the batch starts.
        </p>
      )}
      {start.isError && <div className="notice notice-err">{start.error.message}</div>}
    </div>
  )
}

export function Batches({ exp, cases, scorers, onShowRuns }: {
  exp: Experiment
  cases: GoldenCase[]
  scorers: ScorerInfo[]
  onShowRuns: (batchId: string) => void
}) {
  const queryClient = useQueryClient()
  const list = useQuery({
    queryKey: ['batches', exp.id],
    queryFn: () => api.batches(exp.id),
    refetchInterval: (q) => (q.state.data?.some((b) => b.status === 'running') ? 2000 : false),
  })
  const batches = list.data ?? []
  const [openId, setOpenId] = useState<string | null>(null)
  const selected = openId ?? batches[0]?.id ?? null
  const running = batches.some((b) => b.status === 'running')
  const detail = useQuery({
    queryKey: ['batch', selected],
    queryFn: () => api.batch(selected!),
    enabled: !!selected,
    refetchInterval: (q) => (q.state.data?.batch.status === 'running' ? 3000 : false),
  })

  // When a batch finishes, refresh everything that counts its runs.
  const wasRunning = useRef(false)
  useEffect(() => {
    if (wasRunning.current && !running) {
      for (const key of ['trials', 'evals', 'batch', 'experiment', 'experiments']) queryClient.invalidateQueries({ queryKey: [key] })
    }
    wasRunning.current = running
  }, [running, queryClient])

  const cancel = useMutation({
    mutationFn: (id: string) => api.cancelBatch(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['batches', exp.id] }),
  })
  const remove = useMutation({
    mutationFn: (id: string) => api.deleteBatch(id),
    onSuccess: () => {
      setOpenId(null)
      for (const key of ['batches', 'trials', 'evals']) queryClient.invalidateQueries({ queryKey: [key, exp.id] })
    },
  })

  return (
    <section>
      <div className="filter-row"><h2>Batches</h2></div>
      <p className="muted small">
        One run can be lucky. A batch asks every golden question several times on both arms, then reports accuracy with
        error bars, how often each arm is right every time, and whether it gives the same answer twice.
      </p>
      {!running && <StartBatch exp={exp} cases={cases} />}

      {batches.length > 0 && (
        <div className="batch-list">
          {batches.map((b, i) => (
            <div
              key={b.id}
              className={`batch-item ${b.id === selected ? 'active' : ''}`}
              onClick={() => setOpenId(b.id)}
              role="button"
              tabIndex={0}
              onKeyDown={(ev) => ev.key === 'Enter' && setOpenId(b.id)}
            >
              <div className="batch-item-head">
                <b>Batch {batches.length - i}</b>
                <span className={`status-chip ${b.status}`}>{b.status === 'running' && <Loader2 size={11} className="spin" />}{STATUS[b.status]}</span>
              </div>
              <div className="sc-sub">
                {b.golden_case_ids.length} question{b.golden_case_ids.length === 1 ? '' : 's'} × {b.repeats} · {timeAgo(b.created_at)}
              </div>
              <div className="mini-bar progress"><i style={{ width: `${(100 * b.done) / Math.max(1, b.total)}%` }} /></div>
              <div className="sc-sub" title={`Configuration version ${b.config_version} · ${b.model}`}>
                {b.done} of {b.total} runs · config {b.config_version.slice(0, 7)}
              </div>
              {b.error && <div className="sc-sub error-text">{b.error}</div>}
              {b.status === 'interrupted' && <div className="sc-sub">The server stopped before it finished.</div>}
              <div className="batch-actions" onClick={(ev) => ev.stopPropagation()}>
                {b.status === 'running' ? (
                  <button className="link-muted" onClick={() => cancel.mutate(b.id)} disabled={cancel.isPending}>
                    <Square size={11} /> Cancel
                  </button>
                ) : (
                  <button
                    className="link-muted"
                    onClick={() => {
                      if (confirm(`Delete this batch and its ${b.done} runs?`)) remove.mutate(b.id)
                    }}
                  >
                    <Trash2 size={11} /> Delete
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {detail.data && detail.data.report.runs_done > 0 && (
        <Report report={detail.data.report} scorers={scorers} onShowRuns={() => onShowRuns(detail.data!.batch.id)} />
      )}
      {detail.data && detail.data.report.runs_done === 0 && detail.data.batch.status === 'running' && (
        <p className="muted small"><Loader2 size={13} className="spin" /> Waiting for the first runs…</p>
      )}
    </section>
  )
}
