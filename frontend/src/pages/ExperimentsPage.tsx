import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Plus, Search } from 'lucide-react'
import { Topbar } from '../components/Topbar'
import { NewExperimentModal } from '../components/NewExperimentModal'
import { api, timeAgo } from '../api'

const gettingStarted = [
  { title: 'Ingest a CSV', body: 'The original file is stored untouched. It is the baseline for every comparison.' },
  { title: 'Map fields & connections', body: 'Every column becomes a node. Describe fields and connect them in plain English.' },
  { title: 'Add context', body: 'Optionally attach Markdown with domain rules or instructions, like a Claude skill.' },
  { title: 'Compare in the arena', body: 'Ask questions and see the baseline and configured answers side by side.' },
]

export function ExperimentsPage() {
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [creating, setCreating] = useState(false)
  const { data: experiments = [], isLoading } = useQuery({ queryKey: ['experiments'], queryFn: api.experiments })
  const visible = experiments.filter((e) =>
    `${e.name} ${e.configuration_name} ${e.dataset_name}`.toLowerCase().includes(query.toLowerCase()),
  )

  if (!isLoading && experiments.length === 0) {
    return (
      <>
        <Topbar title="Experiments" />
        <div className="scroll">
          <div className="page">
            <div className="eyebrow">Get started</div>
            <h1>Does your context actually help?</h1>
            <p className="lead">
              Compare Claude on your raw CSV against Claude with your configuration (field meanings, connections and
              context), side by side.
            </p>
            <div className="page-actions">
              <Link className="btn btn-primary" to="/configurations/new">Upload a CSV</Link>
              <button className="btn" onClick={() => setCreating(true)}>New experiment</button>
            </div>
            <div className="steps">
              {gettingStarted.map((s, i) => (
                <div key={s.title} className="step">
                  <span className="step-num">0{i + 1}</span>
                  <div>
                    <div className="step-title">{s.title}</div>
                    <div className="step-body">{s.body}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
        {creating && <NewExperimentModal onClose={() => setCreating(false)} />}
      </>
    )
  }

  return (
    <>
      <Topbar title="Experiments" />
      <div className="toolbar">
        <label className="search">
          <Search size={15} />
          <input placeholder="Search experiments" value={query} onChange={(e) => setQuery(e.target.value)} />
        </label>
        <button className="btn btn-primary" onClick={() => setCreating(true)}><Plus size={15} /> New experiment</button>
      </div>
      <div className="scroll">
        <div className="card-grid">
          {visible.map((e) => (
            <div key={e.id} className="card card-click" onClick={() => navigate(`/experiments/${e.id}`)}>
              <div className="card-eyebrow">{e.dataset_name} · {e.configuration_name}</div>
              <div className="card-title">{e.name}</div>
              <div className="meta" style={{ marginTop: 22 }}>
                {e.trial_count} {e.trial_count === 1 ? 'question' : 'questions'} <span className="sep" /> {timeAgo(e.created_at)}
              </div>
            </div>
          ))}
        </div>
      </div>
      {creating && <NewExperimentModal onClose={() => setCreating(false)} />}
    </>
  )
}
