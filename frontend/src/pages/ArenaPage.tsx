import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { AlertTriangle, ArrowUp, ChevronDown, ChevronRight, Loader2 } from 'lucide-react'
import { Topbar } from '../components/Topbar'
import { api, timeAgo, type Arm, type ArmResponse, type Experiment, type Preference, type Trial } from '../api'

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

function ArmPane({ response, exp, question }: { response: ArmResponse; exp: Experiment; question: string }) {
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
        {response.output && (
          <div className="markdown"><Markdown remarkPlugins={[remarkGfm]}>{response.output}</Markdown></div>
        )}
      </div>
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
            </span>
          ))}
          {'\n\n'}<span className="prompt-role">TRACE</span>{'\n'}{response.model} · content hash {response.content_hash.slice(0, 16)}…
        </pre>
      )}
    </div>
  )
}

function TrialCard({ trial, exp }: { trial: Trial; exp: Experiment }) {
  const queryClient = useQueryClient()
  const [note, setNote] = useState(trial.note)
  const update = useMutation({
    mutationFn: (body: { preference?: Preference | null; note?: string }) => api.updateTrial(trial.id, body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['trials', exp.id] }),
  })

  return (
    <article className="trial">
      <div className="trial-q">
        <span className="trial-question">{trial.question}</span>
        <span className="muted small">{timeAgo(trial.created_at)}</span>
      </div>
      <div className="arena-grid">
        {trial.responses.map((r) => <ArmPane key={r.id} response={r} exp={exp} question={trial.question} />)}
      </div>
      <div className="verdict">
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

export function ArenaPage() {
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

      <div className="scroll">
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
              gets your field descriptions, connections and context.
            </div>
          )}
        </div>
      </div>
    </>
  )
}
