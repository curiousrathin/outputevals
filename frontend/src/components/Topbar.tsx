import { ArrowLeft, ArrowRight } from 'lucide-react'
import { useNavigate } from 'react-router-dom'

export function Topbar({ title }: { title: string }) {
  const navigate = useNavigate()
  return (
    <header className="topbar">
      <div className="topbar-nav">
        <button className="icon-btn" aria-label="Back" onClick={() => navigate(-1)}><ArrowLeft size={16} /></button>
        <button className="icon-btn" aria-label="Forward" onClick={() => navigate(1)}><ArrowRight size={16} /></button>
      </div>
      <span className="topbar-title">{title}</span>
    </header>
  )
}
