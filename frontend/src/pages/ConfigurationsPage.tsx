import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Plus } from 'lucide-react'
import { Topbar } from '../components/Topbar'
import { NewExperimentModal } from '../components/NewExperimentModal'
import { api } from '../api'

export function ConfigurationsPage() {
  const navigate = useNavigate()
  const { data: configs = [] } = useQuery({ queryKey: ['configurations'], queryFn: api.configurations })
  const { data: datasets = [] } = useQuery({ queryKey: ['datasets'], queryFn: api.datasets })
  const [useIn, setUseIn] = useState<string>()
  const datasetName = (id: string) => datasets.find((d) => d.id === id)?.name ?? '…'

  return (
    <>
      <Topbar title="Configurations" />
      <div className="toolbar">
        <span className="muted">Reusable setups: a dataset, its field graph, and extra context.</span>
        <Link className="btn btn-primary" to="/configurations/new"><Plus size={15} /> New configuration</Link>
      </div>
      <div className="scroll">
        {configs.length === 0 ? (
          <div className="page">
            <div className="eyebrow">Configurations</div>
            <h1>Nothing configured yet.</h1>
            <p className="lead">Upload a CSV, describe its fields and how they connect, and add any extra context.</p>
            <Link className="btn btn-primary" to="/configurations/new">Create your first configuration</Link>
          </div>
        ) : (
          <div className="card-grid">
            {configs.map((c) => (
              <div key={c.id} className="card card-click" onClick={() => navigate(`/configurations/${c.id}`)}>
                <div className="card-eyebrow">{datasetName(c.dataset_id)}</div>
                <div className="card-title">{c.name}</div>
                <div className="meta" style={{ marginTop: 14 }}>
                  {c.nodes.filter((n) => n.description.trim()).length}/{c.nodes.length} fields described
                  <span className="sep" /> {c.edges.length} connections
                  <span className="sep" /> {c.context_markdown.trim() ? 'context' : 'no context'}
                </div>
                <div className="card-actions">
                  <button
                    className="btn btn-sm"
                    onClick={(e) => {
                      e.stopPropagation()
                      setUseIn(c.id)
                    }}
                  >
                    Use in experiment
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
      {useIn && <NewExperimentModal configurationId={useIn} onClose={() => setUseIn(undefined)} />}
    </>
  )
}
