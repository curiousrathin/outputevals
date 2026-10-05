import { Topbar } from '../components/Topbar'

interface Props {
  title: string
  eyebrow: string
  headline: string
  lead: string
  primary: string
  steps: { title: string; body: string }[]
}

export function PlaceholderPage({ title, eyebrow, headline, lead, primary, steps }: Props) {
  return (
    <>
      <Topbar title={title} />
      <div style={{ overflow: 'auto' }}>
        <div className="page">
          <div className="eyebrow">{eyebrow}</div>
          <h1>{headline}</h1>
          <p className="lead">{lead}</p>
          <div className="page-actions">
            <button className="btn btn-primary">{primary}</button>
            <button className="btn">Read the docs</button>
          </div>
          <div className="steps">
            {steps.map((s, i) => (
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
    </>
  )
}
