import type { GeometryQuality, IncidentStatus, Provenance, SeverityTier } from './api'

export function classNames(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(' ')
}

export function formatTimestamp(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

export function formatRelative(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso).getTime()
  if (Number.isNaN(d)) return '—'
  const diff = Date.now() - d
  const s = Math.round(diff / 1000)
  if (s < 60) return `${s}s ago`
  const m = Math.round(s / 60)
  if (m < 60) return `${m}m ago`
  const h = Math.round(m / 60)
  if (h < 24) return `${h}h ago`
  return `${Math.round(h / 24)}d ago`
}

export function formatCoord(lat: number | null, lon: number | null, digits = 5): string {
  if (lat == null || lon == null) return 'unavailable'
  return `${lat.toFixed(digits)}, ${lon.toFixed(digits)}`
}

export function formatDistance(m: number | null | undefined): string {
  if (m == null) return '—'
  if (m >= 1000) return `${(m / 1000).toFixed(2)} km`
  return `${m.toFixed(0)} m`
}

export function formatPercent(x: number | null | undefined, digits = 0): string {
  if (x == null) return '—'
  return `${(x * 100).toFixed(digits)}%`
}

export const provenanceStyles: Record<Provenance, string> = {
  real: 'bg-emerald-500/15 text-emerald-300 ring-emerald-500/30',
  predicted: 'bg-sky-500/15 text-sky-300 ring-sky-500/30',
  simulated: 'bg-violet-500/15 text-violet-300 ring-violet-500/30',
  heuristic: 'bg-amber-500/15 text-amber-300 ring-amber-500/30',
  manual: 'bg-slate-500/15 text-slate-300 ring-slate-500/30',
}

export const statusStyles: Record<IncidentStatus, string> = {
  candidate: 'bg-amber-500/15 text-amber-300 ring-amber-500/30',
  confirmed: 'bg-orange-500/15 text-orange-300 ring-orange-500/30',
  reviewed: 'bg-sky-500/15 text-sky-300 ring-sky-500/30',
  acknowledged: 'bg-emerald-500/15 text-emerald-300 ring-emerald-500/30',
  dismissed: 'bg-slate-500/15 text-slate-400 ring-slate-500/30',
}

export const severityStyles: Record<SeverityTier, string> = {
  info: 'text-slate-300',
  low: 'text-emerald-300',
  medium: 'text-amber-300',
  high: 'text-orange-300',
  critical: 'text-red-400',
}

export const geometryStyles: Record<GeometryQuality, string> = {
  strong: 'bg-emerald-500/15 text-emerald-300 ring-emerald-500/30',
  moderate: 'bg-amber-500/15 text-amber-300 ring-amber-500/30',
  weak: 'bg-orange-500/15 text-orange-300 ring-orange-500/30',
  unavailable: 'bg-slate-500/15 text-slate-400 ring-slate-500/30',
}

export const statusLabels: Record<IncidentStatus, string> = {
  candidate: 'Candidate',
  confirmed: 'Confirmed',
  reviewed: 'Reviewed',
  acknowledged: 'Acknowledged',
  dismissed: 'Dismissed',
}
