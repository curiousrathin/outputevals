import { useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2, X } from 'lucide-react'
import { api, type Arm, type GoldenCase, type GoldenCategory, type GoldenIn } from '../api'

const NUMBER = /^[$€£]?-?\d[\d,]*(\.\d+)?%?$/

type Props =
  | { mode: 'create'; trialId: string; arm: Arm; experimentId: string; onClose: () => void }
  | { mode: 'edit'; golden: GoldenCase; columns: string[]; experimentId: string; onClose: () => void }

/** Set (or edit) the verified answer for a question. Pre-filled from a run; a person checks it. */
export function GoldenForm(props: Props) {
  const draft = useQuery({
    queryKey: ['golden-draft', props.mode === 'create' ? props.trialId : '', props.mode === 'create' ? props.arm : ''],
    queryFn: () => api.goldenDraft((props as { trialId: string }).trialId, (props as { arm: Arm }).arm),
    enabled: props.mode === 'create',
  })
  let initial: GoldenIn
  let columns: string[]
  if (props.mode === 'edit') {
    initial = props.golden
    columns = props.columns
  } else {
    if (!draft.data) {
      return (
        <Shell title="Set the correct answer" onClose={props.onClose}>
          <p className="muted">{draft.isError ? draft.error.message : 'Reading the run…'}</p>
        </Shell>
      )
    }
    const d = draft.data
    initial = {
      question: d.question, answerable: d.answerable ?? true, expected_values: d.expected_values ?? [],
      tolerance: d.tolerance ?? 0.001, expected_columns: d.expected_columns ?? [], reference_sql: d.reference_sql ?? '',
      category: d.category ?? '', held_out: false, notes: '', trial_id: props.trialId,
    }
    columns = d.dataset_columns
  }
  return <Body key={props.mode === 'edit' ? props.golden.id : props.trialId} props={props} initial={initial} columns={columns} />
}

function Shell({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal modal-wide" onClick={(e) => e.stopPropagation()}>
        <div className="panel-head">
          <div className="panel-title">{title}</div>
          <button className="icon-btn" onClick={onClose} aria-label="Close"><X size={16} /></button>
        </div>
        {children}
      </div>
    </div>
  )
}

function Body({ props, initial, columns }: { props: Props; initial: GoldenIn; columns: string[] }) {
  const queryClient = useQueryClient()
  const [question, setQuestion] = useState(initial.question)
  const [answerable, setAnswerable] = useState(initial.answerable)
  const [values, setValues] = useState<string[]>(initial.expected_values.length ? initial.expected_values : [''])
  const [tolerancePct, setTolerancePct] = useState(String(+(initial.tolerance * 100).toFixed(4)))
  const [cols, setCols] = useState<string[]>(initial.expected_columns)
  const [sql, setSql] = useState(initial.reference_sql)
  const [category, setCategory] = useState<GoldenCategory>(initial.category === 'unanswerable' ? '' : initial.category)
  const [heldOut, setHeldOut] = useState(initial.held_out)
  const [notes, setNotes] = useState(initial.notes)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const hasNumber = values.some((v) => NUMBER.test(v.trim()))

  const done = () => {
    queryClient.invalidateQueries({ queryKey: ['trials', props.experimentId] })
    queryClient.invalidateQueries({ queryKey: ['evals', props.experimentId] })
    queryClient.invalidateQueries({ queryKey: ['golden'] })
    props.onClose()
  }
  const body = (): GoldenIn => ({
    question, answerable, expected_values: values.map((v) => v.trim()).filter(Boolean),
    tolerance: Math.max(0, Number(tolerancePct) || 0) / 100, expected_columns: cols, reference_sql: sql,
    category: answerable ? category : 'unanswerable', held_out: heldOut, notes,
    ...(props.mode === 'create' ? { trial_id: props.trialId } : {}),
  })
  const save = useMutation({
    mutationFn: () => (props.mode === 'edit' ? api.updateGolden(props.golden.id, body()) : api.createGolden(body())),
    onSuccess: done,
  })
  const remove = useMutation({
    mutationFn: () => api.deleteGolden((props as { golden: GoldenCase }).golden.id),
    onSuccess: done,
  })

  return (
    <Shell title={props.mode === 'edit' ? `Golden answer · v${props.golden.version}` : 'Set the correct answer'} onClose={props.onClose}>
      <form
        className="golden-form"
        onSubmit={(e) => {
          e.preventDefault()
          save.mutate()
        }}
      >
        <div className="notice notice-info">
          {props.mode === 'create'
            ? `Pre-filled from the ${props.arm} arm's run. Check every value against the data before saving: this is the exam, and if it's wrong, every score built on it is wrong.`
            : `Saving makes this version ${props.golden.version + 1} and re-grades all ${props.golden.linked_runs} linked run(s) from their saved traces.`}
        </div>

        <label className="label" htmlFor="golden-question">Question</label>
        <input id="golden-question" className="input-box" value={question} onChange={(e) => setQuestion(e.target.value)} />
        <p className="muted small">Runs whose question matches this exactly (ignoring case and spacing) are graded against it.</p>

        <div className="segmented golden-kind">
          <button type="button" className={answerable ? 'active' : ''} onClick={() => setAnswerable(true)}>Has an answer</button>
          <button type="button" className={!answerable ? 'active' : ''} onClick={() => setAnswerable(false)}>The data can't answer this</button>
        </div>

        {answerable ? (
          <>
            <label className="label">Correct values</label>
            <div className="golden-values">
              {values.map((v, i) => (
                <div key={i} className="golden-value">
                  <input
                    id={`golden-value-${i}`}
                    className="input-box"
                    value={v}
                    placeholder="e.g. Noah Paul, or 149410.09"
                    onChange={(e) => setValues(values.map((x, j) => (j === i ? e.target.value : x)))}
                  />
                  <span className="pill">{!v.trim() ? 'empty' : NUMBER.test(v.trim()) ? 'number' : 'text'}</span>
                  <button type="button" className="icon-btn" aria-label="Remove value" onClick={() => setValues(values.filter((_, j) => j !== i))}>
                    <X size={14} />
                  </button>
                </div>
              ))}
              <button type="button" className="btn btn-sm" onClick={() => setValues([...values, ''])}><Plus size={14} /> Add value</button>
            </div>
            {hasNumber && (
              <div className="golden-row">
                <label className="label" htmlFor="golden-tolerance">Number tolerance (%)</label>
                <input id="golden-tolerance" className="input-box golden-small" value={tolerancePct} onChange={(e) => setTolerancePct(e.target.value)} />
                <span className="muted small">A number within this % of the correct one passes.</span>
              </div>
            )}

            <label className="label">Columns the right query uses</label>
            <div className="field-chips">
              {columns.map((c) => (
                <button
                  key={c}
                  type="button"
                  className={`field-chip toggle${cols.includes(c) ? ' on' : ''}`}
                  onClick={() => setCols(cols.includes(c) ? cols.filter((x) => x !== c) : [...cols, c])}
                >
                  {c}
                </button>
              ))}
            </div>

            <label className="label" htmlFor="golden-sql">Reference query (optional)</label>
            <textarea id="golden-sql" className="textarea mono" rows={3} value={sql} onChange={(e) => setSql(e.target.value)} />
            <p className="muted small">Execution accuracy runs this and checks whether the arm's query returns the same rows.</p>

            <label className="label" htmlFor="golden-category">Kind of question</label>
            <select id="golden-category" className="select" value={category} onChange={(e) => setCategory(e.target.value as GoldenCategory)}>
              <option value="">Not set</option>
              <option value="lookup">Lookup</option>
              <option value="aggregation">Aggregation</option>
              <option value="multi-hop">Multi-hop</option>
            </select>
          </>
        ) : (
          <p className="muted small">Arms pass "Abstained correctly" when they say the data doesn't contain the answer, without citing or stating any values.</p>
        )}

        <label className="check">
          <input id="golden-held-out" type="checkbox" checked={heldOut} onChange={(e) => setHeldOut(e.target.checked)} />
          Held out: never write knowledge to make this case pass
        </label>
        <label className="label" htmlFor="golden-notes">Notes</label>
        <textarea id="golden-notes" className="textarea" rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="How you checked it, edge cases…" />

        {save.isError && <div className="notice notice-err">{save.error.message}</div>}
        {remove.isError && <div className="notice notice-err">{remove.error.message}</div>}
        <div className="modal-actions">
          {props.mode === 'edit' && (
            <button
              type="button"
              className="btn btn-danger golden-delete"
              onClick={() => (confirmDelete ? remove.mutate() : setConfirmDelete(true))}
            >
              <Trash2 size={14} /> {confirmDelete ? 'Click again to delete' : 'Delete'}
            </button>
          )}
          <button type="button" className="btn" onClick={props.onClose}>Cancel</button>
          <button className="btn btn-primary" disabled={save.isPending || !question.trim()}>
            {save.isPending ? 'Saving…' : props.mode === 'edit' ? 'Save new version' : 'Save golden answer'}
          </button>
        </div>
      </form>
    </Shell>
  )
}
