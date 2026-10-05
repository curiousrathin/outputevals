import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { X } from 'lucide-react'
import { api } from '../api'

export function NewExperimentModal({ configurationId, onClose }: { configurationId?: string; onClose: () => void }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { data: configs = [] } = useQuery({ queryKey: ['configurations'], queryFn: api.configurations })
  const [name, setName] = useState('')
  const [configId, setConfigId] = useState(configurationId ?? '')
  const chosen = configId || configs[0]?.id || ''

  const create = useMutation({
    mutationFn: () => api.createExperiment({ name, configuration_id: chosen }),
    onSuccess: (e) => {
      queryClient.invalidateQueries({ queryKey: ['experiments'] })
      navigate(`/experiments/${e.id}`)
    },
  })

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="panel-head">
          <div className="panel-title">New experiment</div>
          <button className="icon-btn" onClick={onClose} aria-label="Close"><X size={16} /></button>
        </div>
        {configs.length === 0 ? (
          <>
            <p className="muted">You need a configuration first: a dataset plus the context you want to test.</p>
            <Link className="btn btn-primary" to="/configurations/new" onClick={onClose}>Create configuration</Link>
          </>
        ) : (
          <form
            onSubmit={(e) => {
              e.preventDefault()
              if (name.trim()) create.mutate()
            }}
          >
            <label className="label">Name</label>
            <input className="input-box" autoFocus placeholder="e.g. Invoice QA" value={name} onChange={(e) => setName(e.target.value)} />
            <label className="label">Configuration</label>
            <select className="select" style={{ width: '100%' }} value={chosen} onChange={(e) => setConfigId(e.target.value)}>
              {configs.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
            <p className="muted small">
              The baseline always uses that configuration's original CSV. Or{' '}
              <Link to="/configurations/new" onClick={onClose}>create a new configuration</Link>.
            </p>
            {create.isError && <div className="notice notice-err">{create.error.message}</div>}
            <div className="modal-actions">
              <button type="button" className="btn" onClick={onClose}>Cancel</button>
              <button className="btn btn-primary" disabled={!name.trim() || create.isPending}>Create & open arena</button>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}
