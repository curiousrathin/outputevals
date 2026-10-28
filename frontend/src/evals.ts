import { useQuery } from '@tanstack/react-query'
import { api, type Score, type ScorerInfo } from './api'

/** The eval registry, in display order, fetched once. */
export function useScorers() {
  const q = useQuery({ queryKey: ['scorers'], queryFn: api.scorers, staleTime: Infinity })
  const list = q.data?.scorers ?? []
  const byName: Record<string, ScorerInfo> = Object.fromEntries(list.map((s) => [s.name, s]))
  return { list, byName }
}

export function formatMeasure(value: number | null, unit: string): string {
  if (value === null) return '—'
  if (unit === '$') return value >= 0.01 ? `$${value.toFixed(3)}` : `$${value.toFixed(4)}`
  if (unit === 's') return `${value.toFixed(1)} s`
  return Number.isInteger(value) ? String(value) : value.toFixed(2)
}

// Signals are neither good nor bad, so they get words instead of ✓/✗.
const SIGNAL_WORDS: Record<string, [string, string]> = { arms_agree: ['Arms differ', 'Arms agree'] }

export function scoreLabel(score: Score, info?: ScorerInfo): string {
  const title = info?.title ?? score.scorer
  if (score.state !== 'scored' || !info) return title
  if (info.kind === 'measure') return formatMeasure(score.value, info.unit)
  if (info.kind === 'signal') {
    const [no, yes] = SIGNAL_WORDS[info.name] ?? [`${title}: no`, `${title}: yes`]
    return score.value === 1 ? yes : no
  }
  if (info.name === 'unsourced_numbers' && score.passed === false) return `${score.value} unsourced`
  return title
}

export function scoreTooltip(score: Score, info?: ScorerInfo): string {
  const state = { scored: '', locked: 'Locked. ', not_applicable: 'Not applicable. ', not_computed: 'Not computed. ' }[score.state]
  const lines = [`${state}${score.reason}`.trim()]
  if (info) lines.push('', `Measures: ${info.measures}`, `How: ${info.how}`, `Caveat: ${info.caveat}`)
  return lines.join('\n')
}

export type Tone = 'pass' | 'fail' | 'warn' | 'neutral' | 'muted'

export function scoreTone(score: Score, info?: ScorerInfo): Tone {
  if (score.state === 'not_computed') return 'warn'
  if (score.state !== 'scored') return 'muted'
  if (info?.kind === 'verdict') return score.passed ? 'pass' : 'fail'
  return 'neutral'
}

export function sortByRegistry(scores: Score[], list: ScorerInfo[]): Score[] {
  const order = new Map(list.map((s, i) => [s.name, i]))
  return [...scores].sort((a, b) => (order.get(a.scorer) ?? 99) - (order.get(b.scorer) ?? 99))
}
