import { useState } from 'react'
import { Link, NavLink, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { AlertTriangle, ArrowUp, ChevronDown, ChevronRight, Loader2, Target } from 'lucide-react'
import { Topbar } from '../components/Topbar'
import { ScoreChip, ScoreStrip } from '../components/Scores'
import { GoldenForm } from '../components/GoldenForm'
import { useScorers } from '../evals'
import { EvalsView } from './EvalsView'
import { api, timeAgo, type Arm, type ArmResponse, type Experiment, type Preference, type Score, type ScorerInfo, type Trial } from '../api'

const prefLabels: { value: Preference; label: string }[] = [
  { value: 'baseline', label: 'Baseline better' },
  { value: 'configured', label: 'Configured better' },
  { value: 'tie', label: 'Tie' },
  { value: 'both_bad', label: 'Both wrong' },
]

function armTitle(arm: Arm, exp: Experiment) {
  return arm === 'baseline'
    ? { label: 'Baseline', sub: `${exp.dataset_name} · original CSV` }
    : { label: 'Configured', sub: exp.configuration_name }
}

function ArmPane({ response, exp, question, scores, scorers, onSetAnswer }: {
  response: ArmResponse
  exp: Experiment
  question: string
  scores: Score[]
  scorers: ScorerInfo[]
  onSetAnswer?: () => void // shown only while the question has no golden answer
}) {
  const [showPrompt, setShowPrompt] = useState(false)
  const t = armTitle(response.arm, exp)
  return (
    <div className={`arm arm-${response.arm}`}>
      <div className="arm-head">
        <span className="arm-label">{t.label}</span>
        <span className="muted small">{t.sub}</span>
      </div>
      <div className="arm-body">
        {response.error && (
          <div className="notice notice-err"><AlertTriangle size={15} /> <span>{response.error}</span></div>
        )}
        {response.render_ok === false && (
          <div className="notice notice-err">
            <AlertTriangle size={15} />
            <span>
              Answer refused. It cites {response.missing_refs.length === 1 ? 'a reference' : 'references'} that no
              query produced ({response.missing_refs.join(', ')}), so none of it is shown. The draft is under
              "What the model saw".
            </span>
          </div>
        )}
        {response.render_ok === true && (
          <div className="markdown"><Markdown remarkPlugins={[remarkGfm]}>{response.rendered_output}</Markdown></div>
        )}
        {response.render_ok === null && response.output && (
          <div className="markdown"><Markdown remarkPlugins={[remarkGfm]}>{response.output}</Markdown></div>
        )}
      </div>
      <ScoreStrip scores={scores} scorers={scorers} />
      <div className="arm-foot">
        {response.mode === 'query' && (
          <>
            <span>SQL · {response.tool_calls.length} {response.tool_calls.length === 1 ? 'query' : 'queries'}</span>
            <span className="sep" />
          </>
        )}
        <span>{(response.latency_ms / 1000).toFixed(1)}s</span>
        <span className="sep" />
        <span>{response.input_tokens + response.cache_read_tokens + response.cache_creation_tokens} in · {response.output_tokens} out</span>
        {response.cache_read_tokens > 0 && (
          <>
            <span className="sep" />
            <span>{response.cache_read_tokens} cached</span>
          </>
        )}
        {onSetAnswer && (
          <button className="link-muted set-answer" onClick={onSetAnswer} title="Use this run to set the verified answer for this question">
            <Target size={13} /> Set as correct answer
          </button>
        )}
        <button className="link-muted see-prompt" onClick={() => setShowPrompt(!showPrompt)}>
          {showPrompt ? <ChevronDown size={14} /> : <ChevronRight size={14} />} What the model saw
        </button>
      </div>
      {showPrompt && (
        <pre className="prompt-view">
          <span className="prompt-role">SYSTEM</span>{'\n'}{response.system_prompt}{'\n\n'}
          <span className="prompt-role">USER</span>{'\n'}{question}
          {response.tool_calls.map((call, i) => (
            <span key={i}>
              {'\n\n'}<span className="prompt-role">QUERY {i + 1}</span>{'\n'}{call.sql}{'\n'}
              <span className="prompt-role">RESULT</span>{' '}
              {call.error ? `Error: ${call.error}` : `(${call.row_count} rows)\n${call.result}`}
              {call.evidence && call.evidence.length > 0 && (
                <>
                  {'\n'}<span className="prompt-role">EVIDENCE</span>
                  {call.evidence.map((c) => `\n${c.ev_id}  ${c.label} = ${c.value}`).join('')}
                </>
              )}
            </span>
          ))}
          {response.output && (
            <>
              {'\n\n'}<span className="prompt-role">DRAFT</span>{'\n'}{response.output}
            </>
          )}
          {'\n\n'}<span className="prompt-role">TRACE</span>{'\n'}{response.model} · content hash {response.content_hash.slice(0, 16)}…
        </pre>
      )}
    </div>
  )
}

function TrialCard({ trial, exp }: { trial: Trial; exp: Experiment }) {
  const queryClient = useQueryClient()
  const { list: scorers, byName } = useScorers()
  const trialScores = trial.scores.filter((s) => s.arm === '' && s.state !== 'not_applicable')
  const [goldenFrom, setGoldenFrom] = useState<Arm | null>(null)
  const [note, setNote] = useState(trial.note)
  const update = useMutation({
    mutationFn: (body: { preference?: Preference | null; note?: string }) => api.updateTrial(trial.id, body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['trials', exp.id] }),
  })

  return (
    <article className="trial">
      <div className="trial-q">
        <span className="trial-question">{trial.question}</span>
        <span className="trial-meta">
          {trial.golden_case_id && (
            <Link to={`/experiments/${exp.id}/evals`} className="golden-badge" title="This question is graded against a verified answer. Edit it on the Evals tab.">
              <Target size={12} /> Golden answer set
            </Link>
          )}
          <span className="muted small">{timeAgo(trial.created_at)}</span>
        </span>
      </div>
      {goldenFrom && (
        <GoldenForm mode="create" trialId={trial.id} arm={goldenFrom} experimentId={exp.id} onClose={() => setGoldenFrom(null)} />
      )}
      {trial.library_files?.length > 0 && (
        <div className="trial-files">
          <span className="muted small">Library seen by configured arm:</span>
          {trial.library_files.map((f) => (
            <span key={f.path} className="field-chip" title={`content hash ${f.sha256}`}>
              {f.path} <span className="dtype">{f.sha256.slice(0, 7)}</span>
            </span>
          ))}
        </div>
      )}
      <div className="arena-grid">
        {trial.responses.map((r) => (
          <ArmPane
            key={r.id}
            response={r}
            exp={exp}
            question={trial.question}
            scores={trial.scores.filter((s) => s.response_id === r.id)}
            scorers={scorers}
            onSetAnswer={trial.golden_case_id ? undefined : () => setGoldenFrom(r.arm)}
          />
        ))}
      </div>
      <div className="verdict">
        {trialScores.map((s) => <ScoreChip key={s.id} score={s} info={byName[s.scorer]} />)}
        <div className="segmented">
          {prefLabels.map((p) => (
            <button
              key={p.value}
              className={trial.preference === p.value ? 'active' : ''}
              onClick={() => update.mutate({ preference: trial.preference === p.value ? null : p.value })}
            >
              {p.label}
            </button>
          ))}
        </div>
        <input
          className="note-input"
          placeholder="Note what went wrong first (open coding)…"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          onBlur={() => note !== trial.note && update.mutate({ note })}
        />
      </div>
    </article>
  )
}

function PendingTrial({ question, exp }: { question: string; exp: Experiment }) {
  return (
    <article className="trial">
      <div className="trial-q"><span className="trial-question">{question}</span></div>
      <div className="arena-grid">
        {(['baseline', 'configured'] as Arm[]).map((arm) => {
          const t = armTitle(arm, exp)
          return (
            <div key={arm} className={`arm arm-${arm}`}>
              <div className="arm-head"><span className="arm-label">{t.label}</span><span className="muted small">{t.sub}</span></div>
              <div className="arm-body thinking"><Loader2 size={15} className="spin" /> Claude is thinking…</div>
            </div>
          )
        })}
      </div>
    </article>
  )
}

export function ArenaPage({ tab = 'arena' }: { tab?: 'arena' | 'evals' }) {
  const { id } = useParams()
  const queryClient = useQueryClient()
  const [question, setQuestion] = useState('')
  const exp = useQuery({ queryKey: ['experiment', id], queryFn: () => api.experiment(id!) })
  const trials = useQuery({ queryKey: ['trials', id], queryFn: () => api.trials(id!) })

  const run = useMutation({
    mutationFn: (q: string) => api.runTrial(id!, q),
    onSuccess: () => {
      setQuestion('')
      queryClient.invalidateQueries({ queryKey: ['trials', id] })
      queryClient.invalidateQueries({ queryKey: ['experiments'] })
    },
  })
  const submit = () => question.trim() && !run.isPending && run.mutate(question.trim())

  if (exp.isError) return <><Topbar title="Arena" /><div className="page"><p className="lead">{exp.error.message}</p></div></>
  if (!exp.data) return <Topbar title="Arena" />
  const e = exp.data
  const list = trials.data ?? []
  const tally = Object.fromEntries(prefLabels.map((p) => [p.value, list.filter((t) => t.preference === p.value).length]))

  return (
    <>
      <Topbar title={e.name} />
      <div className="arena-header">
        <div className="arena-arms">
          <span><span className="arm-dot baseline" /> Baseline: <b>{e.dataset_name}</b> (original CSV)</span>
          <span>vs</span>
          <span><span className="arm-dot configured" /> Configured: <Link to={`/configurations/${e.configuration_id}`}><b>{e.configuration_name}</b></Link></span>
        </div>
        {list.length > 0 && (
          <div className="tally">
            Configured {tally.configured} · Baseline {tally.baseline} · Tie {tally.tie} · Both wrong {tally.both_bad}
          </div>
        )}
      </div>
      <nav className="tabs" aria-label="Experiment views">
        <NavLink to={`/experiments/${e.id}`} end>Arena</NavLink>
        <NavLink to={`/experiments/${e.id}/evals`}>Evals</NavLink>
      </nav>

      {tab === 'evals' ? <EvalsView exp={e} /> : <div className="scroll">
        <div className="arena">
          <form
            className="composer"
            onSubmit={(ev) => {
              ev.preventDefault()
              submit()
            }}
          >
            <textarea
              placeholder="Ask a question about your data…"
              rows={2}
              value={question}
              onChange={(ev) => setQuestion(ev.target.value)}
              onKeyDown={(ev) => {
                if (ev.key === 'Enter' && !ev.shiftKey) {
                  ev.preventDefault()
                  submit()
                }
              }}
            />
            <button className="send" disabled={!question.trim() || run.isPending} aria-label="Ask">
              {run.isPending ? <Loader2 size={16} className="spin" /> : <ArrowUp size={16} />}
            </button>
          </form>
          {run.isError && <div className="notice notice-err">{run.error.message}</div>}

          {run.isPending && <PendingTrial question={run.variables} exp={e} />}
          {list.map((t) => <TrialCard key={t.id} trial={t} exp={e} />)}
          {!run.isPending && list.length === 0 && (
            <div className="empty-arena muted">
              Ask your first question. Both arms get the same question and the same CSV; only the configured arm also
              gets your field descriptions, connections, attached library files and notes.
            </div>
          )}
        </div>
      </div>}
    </>
  )
}
