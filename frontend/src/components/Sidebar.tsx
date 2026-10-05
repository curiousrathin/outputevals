import { useState } from 'react'
import { NavLink } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Activity, Bookmark, Database, FlaskConical, Plus, Settings, Workflow } from 'lucide-react'
import { api } from '../api'
import { NewExperimentModal } from './NewExperimentModal'

const nav = [
  { to: '/experiments', label: 'Experiments', icon: FlaskConical, end: true },
  { to: '/datasets', label: 'Datasets', icon: Database },
  { to: '/configurations', label: 'Configurations', icon: Workflow },
  { to: '/observability', label: 'Observability', icon: Activity },
  { to: '/saved', label: 'Saved attempts', icon: Bookmark },
]

const navClass = ({ isActive }: { isActive: boolean }) => `nav-item${isActive ? ' active' : ''}`

export function Sidebar() {
  const [creating, setCreating] = useState(false)
  const { data: experiments = [] } = useQuery({ queryKey: ['experiments'], queryFn: api.experiments })

  return (
    <aside className="sidebar">
      <div className="brand">
        <span className="brand-mark">O</span>
        OutputTracker
      </div>

      <button className="nav-item" onClick={() => setCreating(true)}>
        <Plus size={16} /> New experiment
      </button>
      {nav.map(({ to, label, icon: Icon, end }) => (
        <NavLink key={to} to={to} end={end} className={navClass}>
          <Icon size={16} /> {label}
        </NavLink>
      ))}

      <div className="section-head">
        Experiments
        <button className="icon-btn" aria-label="New experiment" onClick={() => setCreating(true)}><Plus size={15} /></button>
      </div>
      {experiments.map((e) => (
        <NavLink key={e.id} to={`/experiments/${e.id}`} className={({ isActive }) => `side-run${isActive ? ' active' : ''}`}>
          <div className="side-run-title">{e.name}</div>
          <div className="meta">
            {e.configuration_name} <span className="sep" /> {e.trial_count}
          </div>
        </NavLink>
      ))}
      {experiments.length === 0 && <div className="muted small side-empty">No experiments yet.</div>}

      <div className="sidebar-footer">
        <NavLink to="/settings" className={navClass}>
          <Settings size={16} /> Settings
        </NavLink>
      </div>
      {creating && <NewExperimentModal onClose={() => setCreating(false)} />}
    </aside>
  )
}
