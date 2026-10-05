import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, Eye, EyeOff, KeyRound, XCircle } from 'lucide-react'
import { Topbar } from '../components/Topbar'
import { api, type KeyCheckResult } from '../api'

const sourceLabel = {
  dotenv: 'From .env file',
  env: 'From ANTHROPIC_API_KEY environment variable',
  saved: 'Saved in OutputTracker',
  none: 'Not configured — add ANTHROPIC_API_KEY to .env',
}

export function SettingsPage() {
  const queryClient = useQueryClient()
  const status = useQuery({ queryKey: ['anthropic-status'], queryFn: api.anthropicStatus })
  const [key, setKey] = useState('')
  const [reveal, setReveal] = useState(false)
  const [result, setResult] = useState<KeyCheckResult | null>(null)

  const onDone = (r: KeyCheckResult) => {
    setResult(r)
    if (r.ok) setKey('')
    queryClient.invalidateQueries({ queryKey: ['anthropic-status'] })
  }
  const onError = (e: Error) =>
    setResult({ ok: false, message: e.message, model: null, model_display_name: null, context_window: null })

  const save = useMutation({ mutationFn: () => api.saveAnthropicKey(key), onSuccess: onDone, onError })
  const test = useMutation({ mutationFn: api.testAnthropicKey, onSuccess: onDone, onError })
  const remove = useMutation({
    mutationFn: api.deleteAnthropicKey,
    onSuccess: () => {
      setResult(null)
      queryClient.invalidateQueries({ queryKey: ['anthropic-status'] })
    },
  })
  const busy = save.isPending || test.isPending || remove.isPending
  const s = status.data

  return (
    <>
      <Topbar title="Settings" />
      <div style={{ overflow: 'auto' }}>
        <div className="page">
          <div className="eyebrow">Settings</div>
          <h1>Connect Claude.</h1>
          <p className="lead">
            Your key is checked against the Anthropic API before it's saved, then stored locally on this machine.
            The browser only ever sees a masked version.
          </p>

          <section className="panel">
            <div className="panel-head">
              <div className="panel-title"><KeyRound size={16} /> Anthropic API key</div>
              {s && (
                <span className={`pill ${s.configured ? 'pill-ok' : ''}`}>
                  {s.configured ? 'Connected' : 'Not connected'}
                </span>
              )}
            </div>

            <dl className="kv">
              <dt>Status</dt>
              <dd>{s ? sourceLabel[s.source] : status.isError ? "Couldn't reach the backend" : 'Loading…'}</dd>
              <dt>Key</dt>
              <dd className="mono">{s?.masked_key ?? '—'}</dd>
              <dt>Model</dt>
              <dd className="mono">{s?.model ?? '—'}</dd>
            </dl>

            <form
              className="key-form"
              onSubmit={(e) => {
                e.preventDefault()
                if (key.trim()) save.mutate()
              }}
            >
              <div className="input-wrap">
                <input
                  className="input mono"
                  type={reveal ? 'text' : 'password'}
                  placeholder={s?.configured ? 'Paste a new key to replace the current one' : 'sk-ant-…'}
                  value={key}
                  onChange={(e) => setKey(e.target.value)}
                  autoComplete="off"
                  spellCheck={false}
                />
                <button type="button" className="icon-btn" onClick={() => setReveal(!reveal)} aria-label="Toggle visibility">
                  {reveal ? <EyeOff size={15} /> : <Eye size={15} />}
                </button>
              </div>
              <button className="btn btn-primary" type="submit" disabled={busy || !key.trim()}>
                {save.isPending ? 'Verifying…' : 'Save & verify'}
              </button>
            </form>

            {result && (
              <div className={`notice ${result.ok ? 'notice-ok' : 'notice-err'}`}>
                {result.ok ? <CheckCircle2 size={15} /> : <XCircle size={15} />}
                <span>
                  {result.message}
                  {result.context_window && ` Context window: ${result.context_window.toLocaleString()} tokens.`}
                </span>
              </div>
            )}

            {s?.configured && (
              <div className="panel-actions">
                <button className="btn" onClick={() => test.mutate()} disabled={busy}>
                  {test.isPending ? 'Testing…' : 'Test connection'}
                </button>
                {s.source === 'saved' && (
                  <button className="btn btn-danger" onClick={() => remove.mutate()} disabled={busy}>
                    Remove key
                  </button>
                )}
              </div>
            )}
          </section>

          <p className="footnote">
            Get a key from <a href="https://console.anthropic.com/settings/keys" target="_blank" rel="noreferrer">console.anthropic.com</a>.
            Testing the connection uses the Models API and costs no tokens.
          </p>
        </div>
      </div>
    </>
  )
}
