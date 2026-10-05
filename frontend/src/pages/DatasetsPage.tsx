import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowRight } from 'lucide-react'
import { Topbar } from '../components/Topbar'
import { DatasetList, PreviewTable, UploadZone } from '../components/DatasetPicker'
import { api, MAX_INLINE_TOKENS } from '../api'

export function DatasetsPage() {
  const navigate = useNavigate()
  const [selected, setSelected] = useState<string>()
  const { data: datasets = [] } = useQuery({ queryKey: ['datasets'], queryFn: api.datasets })
  const current = datasets.find((d) => d.id === selected) ?? datasets[0]

  return (
    <>
      <Topbar title="Datasets" />
      <div className="scroll">
        <div className="page page-wide">
          <div className="eyebrow">Datasets</div>
          <h1>Bring your data.</h1>
          <p className="lead">Upload a CSV. The original file is kept byte-for-byte and used as the baseline in every experiment.</p>

          <div className="two-col">
            <div>
              <UploadZone onUploaded={(d) => setSelected(d.id)} />
              <DatasetList selected={current?.id} onSelect={(d) => setSelected(d.id)} />
            </div>

            {current && (
              <section className="panel">
                <div className="panel-head">
                  <div>
                    <div className="panel-title">{current.name}</div>
                    <div className="muted small">
                      {current.filename} · {current.row_count.toLocaleString()} rows · ~{current.est_tokens.toLocaleString()} tokens
                    </div>
                  </div>
                  <button className="btn btn-primary" onClick={() => navigate(`/configurations/new?dataset=${current.id}`)}>
                    Configure <ArrowRight size={15} />
                  </button>
                </div>
                {current.est_tokens > MAX_INLINE_TOKENS && (
                  <div className="notice notice-info">
                    Too large to paste into a prompt whole, so both arms get every row as a SQL table and Claude queries
                    it. Every query is logged under "What the model saw".
                  </div>
                )}
                <div className="field-chips">
                  {current.columns.map((c) => (
                    <span key={c.name} className="field-chip">
                      {c.name} <span className="dtype">{c.dtype}</span>
                    </span>
                  ))}
                </div>
                <PreviewTable datasetId={current.id} />
              </section>
            )}
          </div>
        </div>
      </div>
    </>
  )
}
