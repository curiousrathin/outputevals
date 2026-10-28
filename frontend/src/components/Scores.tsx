import { Lock } from 'lucide-react'
import type { Score, ScorerInfo } from '../api'
import { scoreLabel, scoreTone, scoreTooltip, sortByRegistry } from '../evals'

export function ScoreChip({ score, info }: { score: Score; info?: ScorerInfo }) {
  const tone = scoreTone(score, info)
  const mark = tone === 'pass' ? '✓' : tone === 'fail' ? '✗' : null
  return (
    <span className={`score-chip ${tone}`} title={scoreTooltip(score, info)}>
      {score.state === 'locked' && <Lock size={11} />}
      {mark && <b>{mark}</b>}
      {scoreLabel(score, info)}
      {score.state === 'not_computed' && <span className="score-na">· not computed</span>}
    </span>
  )
}

/** One arm's (or one trial's) evals. Locked ones fold into one chip; not-applicable ones into a count. */
export function ScoreStrip({ scores, scorers }: { scores: Score[]; scorers: ScorerInfo[] }) {
  if (!scores.length) return null
  const byName = Object.fromEntries(scorers.map((s) => [s.name, s]))
  const shown = sortByRegistry(scores.filter((s) => s.state !== 'not_applicable' && s.state !== 'locked'), scorers)
  const locked = sortByRegistry(scores.filter((s) => s.state === 'locked'), scorers)
  const hidden = scores.filter((s) => s.state === 'not_applicable')
  const unlock = [...new Set(locked.map((s) => s.reason))].join(' · ')
  return (
    <div className="score-strip">
      {shown.map((s) => <ScoreChip key={s.id} score={s} info={byName[s.scorer]} />)}
      {locked.length > 0 && (
        <span className="score-chip muted" title={`${locked.map((s) => byName[s.scorer]?.title ?? s.scorer).join(', ')}\n\nTo unlock: ${unlock}`}>
          <Lock size={11} /> {locked.length} locked
        </span>
      )}
      {hidden.length > 0 && (
        <span className="score-hidden" title={hidden.map((h) => `${byName[h.scorer]?.title ?? h.scorer}: ${h.reason}`).join('\n')}>
          +{hidden.length} not applicable
        </span>
      )}
    </div>
  )
}
