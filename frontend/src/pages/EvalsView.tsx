import { Fragment, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, ChevronRight, Lock, Pencil, RefreshCw, Target } from 'lucide-react'
import { api, timeAgo, type Arm, type Experiment, type GoldenCase, type Score, type ScorecardRow, type ScorerInfo, type Trial } from '../api'
import { formatMeasure, scoreTone, scoreTooltip, sortByRegistry, useScorers } from '../evals'
import { ScoreChip } from '../components/Scores'
import { GoldenForm } from '../components/GoldenForm'

type Filter = 'all' | 'failing' | 'incorrect' | 'unsourced' | 'refused' | 'disagree' | 'no_golden'
type FormState = { mode: 'create'; trialId: string; arm: Arm } | { mode: 'edit'; golden: GoldenCase } | null

const CORRECTNESS = new Set(['expected_numbers', 'expected_text', 'abstained', 'right_columns', 'execution_accuracy'])
const find = (t: Trial, scorer: string) => t.scores.filter((s) => s.scorer === scorer)
const filters: { value: Filter; label: string; test: (t: Trial) => boolean }[] = [
  { value: 'all', label: 'All runs', test: () => true },
  { value: 'failing', label: 'Any failure', test: (t) => t.scores.some((s) => s.state === 'scored' && s.passed === false) },
  { value: 'incorrect', label: 'Incorrect', test: (t) => t.scores.some((s) => CORRECTNESS.has(s.scorer) && s.state === 'scored' && s.passed === false) },
  { value: 'no_golden', label: 'No golden answer', test: (t) => !t.golden_case_id },
  { value: 'unsourced', label: 'Unsourced numbers', test: (t) => find(t, 'unsourced_numbers').some((s) => s.passed === false) },
  { value: 'refused', label: 'Refused answers', test: (t) => find(t, 'refs_resolve').some((s) => s.passed === false) },
  { value: 'disagree', label: 'Arms disagree', test: (t) => find(t, 'arms_agree').some((s) => s.state === 'scored' && s.value === 0) },
]
const ARMS: Arm[] = ['baseline', 'configured']
const STATES = [
  { name: 'Scored', body: 'It ran. Only these count toward percentages and averages.' },
  { name: 'Locked', body: 'It applies, but needs something that doesn’t exist yet. Shown with how to unlock it.' },
  { name: 'Not applicable', body: 'It can never apply to that run, so it’s hidden from the tables.' },
  { name: 'Not computed', body: 'It should have run but couldn’t. Shown with the reason; never counted as zero.' },
]

function ScorecardCell({ row, info }: { row?: ScorecardRow; info: ScorerInfo }) {
  if (!row || row.total === 0) return <td className="muted">—</td>
  let main = '—'
  let sub = ''
  if (info.kind === 'verdict') {
    if (row.judged) {
      main = `${Math.round((100 * row.passed) / row.judged)}%`
      sub = `${row.passed} of ${row.judged} pass`
    } else sub = 'no scored runs'
  } else if (info.kind === 'measure') {
    if (row.mean !== null) {
      main = `${formatMeasure(row.mean, info.unit)} avg`
      sub = info.unit === '$' && row.sum !== null ? `${formatMeasure(row.sum, '$')} total` : `${row.scored} runs`
    }
  } else if (row.scored && row.mean !== null) {
    main = `${Math.round(row.mean * row.scored)} of ${row.scored}`
    sub = info.name === 'arms_agree' ? 'agree' : 'yes'
  }
  const extra = [
    row.not_computed ? `${row.not_computed} not computed` : '',
    row.locked ? `${row.locked} locked` : '',
    row.not_applicable ? `${row.not_applicable} not applicable` : '',
  ].filter(Boolean).join(' · ')
  return (
    <td>
      <div className="sc-main">{main}</div>
      {info.kind === 'verdict' && row.judged > 0 && (
        <div className="mini-bar"><i style={{ width: `${(100 * row.passed) / row.judged}%` }} /></div>
      )}
      {sub && <div className="sc-sub">{sub}</div>}
      {extra && <div className="sc-sub" title={row.not_computed_reasons.join('\n')}>{extra}</div>}
    </td>
  )
}

function Marks({ scores, scorers }: { scores: Score[]; scorers: ScorerInfo[] }) {
  const verdicts = scorers.filter((s) => s.kind === 'verdict' && s.level === 'response')
  const measures = scorers.filter((s) => s.kind === 'measure')
  return (
    <>
      <div className="run-marks">
        {verdicts.map((info) => {
          const s = scores.find((x) => x.scorer === info.name)
          if (!s || s.state === 'not_applicable') {
            return <span key={info.name} className="mark na" title={`${info.title}: not applicable${s ? `. ${s.reason}` : ''}`}>·</span>
          }
          const tone = scoreTone(s, info)
          return (
            <span key={info.name} className={`mark ${tone}`} title={`${info.title}\n${scoreTooltip(s, info)}`}>
              {s.state === 'locked' ? <Lock size={10} /> : tone === 'pass' ? '✓' : tone === 'fail' ? '✗' : '?'}
            </span>
          )
        })}
      </div>
      <div className="run-measures">
        {measures.map((info) => {
          const s = scores.find((x) => x.scorer === info.name)
          return s?.state === 'scored' ? formatMeasure(s.value, info.unit) : '—'
        }).join(' · ')}
      </div>
    </>
  )
}

function RunDetail({ trial, scorers, expId, golden, onForm }: {
  trial: Trial
  scorers: ScorerInfo[]
  expId: string
  golden?: GoldenCase
  onForm: (f: FormState) => void
}) {
  const byName = Object.fromEntries(scorers.map((s) => [s.name, s]))
  const trialLevel = trial.scores.filter((s) => s.arm === '')
  return (
    <div className="detail-grid">
      {ARMS.map((arm) => {
        const r = trial.responses.find((x) => x.arm === arm)
        const answer = !r ? 'No response.' : r.render_ok === false ? `Refused. Draft: ${r.output}` : r.rendered_output || r.output || r.error || 'No answer.'
        return (
          <div key={arm}>
            <h4>{arm === 'baseline' ? 'Baseline' : 'Configured'}</h4>
            <div className="detail-answer">{answer.length > 400 ? `${answer.slice(0, 400)}…` : answer}</div>
            <div className="detail-scores">
              {sortByRegistry(trial.scores.filter((s) => s.arm === arm), scorers).map((s) => (
                <div key={s.id} className="detail-score">
                  <span><ScoreChip score={s} info={byName[s.scorer]} /></span>
                  <span className="why">{s.state === 'not_applicable' ? `Not applicable: ${s.reason}` : s.reason}</span>
                </div>
              ))}
            </div>
          </div>
        )
      })}
      <div className="detail-foot">
        {trialLevel.map((s) => (
          <span key={s.id} className="detail-score">
            <ScoreChip score={s} info={byName[s.scorer]} /> <span className="why">{s.reason}</span>
          </span>
        ))}
        <span className="detail-actions">
          {golden ? (
            <button className="btn btn-sm" onClick={() => onForm({ mode: 'edit', golden })}>
              <Pencil size={13} /> Edit golden answer (v{golden.version})
            </button>
          ) : (
            ARMS.map((arm) => (
              <button key={arm} className="btn btn-sm" onClick={() => onForm({ mode: 'create', trialId: trial.id, arm })}>
                <Target size={13} /> Set correct answer from {arm}
              </button>
            ))
          )}
          <Link to={`/experiments/${expId}`} className="link-muted">Open in arena →</Link>
        </span>
      </div>
    </div>
  )
}

export function EvalsView({ exp }: { exp: Experiment }) {
  const queryClient = useQueryClient()
  const { list: scorers, byName } = useScorers()
  const evals = useQuery({ queryKey: ['evals', exp.id], queryFn: () => api.experimentEvals(exp.id) })
  const trials = useQuery({ queryKey: ['trials', exp.id], queryFn: () => api.trials(exp.id) })
  const golden = useQuery({ queryKey: ['golden', exp.dataset_id], queryFn: () => api.goldenCases(exp.dataset_id) })
  const dataset = useQuery({ queryKey: ['dataset', exp.dataset_id], queryFn: () => api.dataset(exp.dataset_id) })
  const [filter, setFilter] = useState<Filter>('all')
  const [open, setOpen] = useState<string | null>(null)
  const [form, setForm] = useState<FormState>(null)
  const rescore = useMutation({
    mutationFn: () => api.rescoreExperiment(exp.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['evals', exp.id] })
      queryClient.invalidateQueries({ queryKey: ['trials', exp.id] })
    },
  })

  const rows = evals.data?.scorecard ?? []
  const cell = (scorer: string, arm: Arm | '') => rows.find((r) => r.scorer === scorer && r.arm === arm)
  const all = trials.data ?? []
  const test = filters.find((f) => f.value === filter)!.test
  const shown = all.filter(test)
  const cases = golden.data ?? []
  const caseById = Object.fromEntries(cases.map((c) => [c.id, c]))
  const graded = all.filter((t) => t.golden_case_id).length
  const columns = dataset.data?.columns.map((c) => c.name) ?? []

  return (
    <div className="scroll">
      <div className="evals">
        <section className="evals-head">
          <div>
            <h2>Evals</h2>
            <p className="muted small">
              {evals.data ? `${evals.data.runs} run${evals.data.runs === 1 ? '' : 's'}` : 'Loading…'} · every run is scored
              the moment it's created, and older runs are scored from their saved traces. No model calls are made.
            </p>
            <div className="states">
              {STATES.map((s) => <span key={s.name} title={s.body}><b>{s.name}</b>: {s.body}</span>)}
            </div>
          </div>
          <button className="btn btn-sm" onClick={() => rescore.mutate()} disabled={rescore.isPending}>
            <RefreshCw size={14} className={rescore.isPending ? 'spin' : ''} /> Re-score all runs
          </button>
        </section>

        <section>
          <table className="scorecard">
            <thead><tr><th>Eval</th><th>Baseline</th><th>Configured</th></tr></thead>
            <tbody>
              {scorers.map((info) => (
                <tr key={info.name}>
                  <td className="sc-name" title={`${info.measures}\nHow: ${info.how}\nCaveat: ${info.caveat}`}>
                    <b>{info.title}</b><span>{info.family} · {info.kind}</span>
                  </td>
                  {info.level === 'trial' ? (
                    <ScorecardCellSpan row={cell(info.name, '')} info={info} />
                  ) : (
                    ARMS.map((arm) => <ScorecardCell key={arm} row={cell(info.name, arm)} info={info} />)
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <section>
          <div className="filter-row">
            <h2>Golden answers</h2>
            <span className="muted small">
              {graded} of {all.length} run{all.length === 1 ? '' : 's'} graded against a verified answer
            </span>
          </div>
          <p className="muted small">
            The exam: questions with checked answers, pinned to this dataset (not to a configuration), so every
            configuration is graded on the same ones. Set one from any run below or in the arena.
          </p>
          {cases.length > 0 ? (
            <table className="runs golden-table">
              <thead><tr><th>Question</th><th>Correct answer</th><th>Columns</th><th>Runs</th><th /></tr></thead>
              <tbody>
                {cases.map((c) => (
                  <tr key={c.id}>
                    <td className="run-q">
                      {c.question}
                      <div className="sc-sub">
                        {[c.category || 'uncategorized', c.held_out ? 'held out' : '', `v${c.version}`].filter(Boolean).join(' · ')}
                      </div>
                    </td>
                    <td>{c.answerable ? c.expected_values.join(' · ') : <span className="muted">Data can't answer it</span>}</td>
                    <td className="muted small">{c.expected_columns.join(', ') || '—'}</td>
                    <td>{c.linked_runs}</td>
                    <td><button className="btn btn-sm" onClick={() => setForm({ mode: 'edit', golden: c })}><Pencil size={13} /> Edit</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="muted small">None yet. Open a run below and choose "Set correct answer".</p>
          )}
        </section>

        <section>
          <div className="filter-row">
            <h2>Runs</h2>
            <div className="segmented">
              {filters.map((f) => (
                <button key={f.value} className={filter === f.value ? 'active' : ''} onClick={() => setFilter(f.value)}>
                  {f.label} <span className="muted">{all.filter(f.test).length}</span>
                </button>
              ))}
            </div>
          </div>
          <p className="muted small">
            Marks, left to right: {scorers.filter((s) => s.kind === 'verdict' && s.level === 'response').map((s) => s.title).join(', ')}.
            Hover a mark for its reason; click a row for everything.
          </p>
          <table className="runs">
            <thead><tr><th /><th>Question</th><th>Baseline</th><th>Configured</th><th>Arms</th><th>When</th></tr></thead>
            <tbody>
              {shown.map((t) => {
                const agree = t.scores.find((s) => s.scorer === 'arms_agree')
                return (
                  <Fragment key={t.id}>
                    <tr className="run-row" onClick={() => setOpen(open === t.id ? null : t.id)}>
                      <td>{open === t.id ? <ChevronDown size={14} /> : <ChevronRight size={14} />}</td>
                      <td className="run-q">
                        {t.question}
                        {t.golden_case_id && <span className="golden-badge inline" title="Graded against a verified answer"><Target size={11} /> golden</span>}
                      </td>
                      {ARMS.map((arm) => (
                        <td key={arm}><Marks scores={t.scores.filter((s) => s.arm === arm)} scorers={scorers} /></td>
                      ))}
                      <td>{agree && agree.state !== 'not_applicable' ? <ScoreChip score={agree} info={byName.arms_agree} /> : <span className="muted">—</span>}</td>
                      <td className="muted small">{timeAgo(t.created_at)}</td>
                    </tr>
                    {open === t.id && (
                      <tr className="run-detail">
                        <td colSpan={6}>
                          <RunDetail trial={t} scorers={scorers} expId={exp.id} golden={caseById[t.golden_case_id]} onForm={setForm} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                )
              })}
              {shown.length === 0 && (
                <tr><td colSpan={6} className="muted">{all.length ? 'No runs match this filter.' : 'No runs yet. Ask a question in the arena.'}</td></tr>
              )}
            </tbody>
          </table>
        </section>

        {form?.mode === 'create' && (
          <GoldenForm mode="create" trialId={form.trialId} arm={form.arm} experimentId={exp.id} onClose={() => setForm(null)} />
        )}
        {form?.mode === 'edit' && (
          <GoldenForm mode="edit" golden={form.golden} columns={columns} experimentId={exp.id} onClose={() => setForm(null)} />
        )}

        <section>
          <h2>About these evals</h2>
          <p className="muted small">What each one measures, how it decides, and when not to trust it.</p>
          <div className="about">
            {scorers.map((s) => (
              <div key={s.name} className="about-item">
                <h4>{s.title}</h4>
                <div className="meta-line">{s.family} · {s.kind} · {s.level === 'trial' ? 'per question' : 'per arm'} · v{s.version}</div>
                <p><b>Measures:</b> {s.measures}</p>
                <p><b>How:</b> {s.how}</p>
                <p><b>Caveat:</b> {s.caveat}</p>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  )
}

function ScorecardCellSpan({ row, info }: { row?: ScorecardRow; info: ScorerInfo }) {
  if (!row || row.total === 0) return <td colSpan={2} className="muted">—</td>
  const yes = row.mean !== null ? Math.round(row.mean * row.scored) : 0
  const extra = [row.not_computed ? `${row.not_computed} not computed` : '', row.not_applicable ? `${row.not_applicable} not applicable` : '']
    .filter(Boolean).join(' · ')
  return (
    <td colSpan={2}>
      <div className="sc-main">{row.scored ? `${yes} of ${row.scored}` : '—'}</div>
      <div className="sc-sub">{info.name === 'arms_agree' ? 'questions where both arms cite the same values' : 'per question'}</div>
      {extra && <div className="sc-sub" title={row.not_computed_reasons.join('\n')}>{extra}</div>}
    </td>
  )
}
