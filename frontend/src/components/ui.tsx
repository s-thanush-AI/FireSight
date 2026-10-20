import type { ReactNode } from 'react'
import { classNames } from '../lib/format'
import type { GeometryQuality, IncidentStatus, Provenance } from '../lib/api'
import {
  geometryStyles,
  provenanceStyles,
  statusLabels,
  statusStyles,
} from '../lib/format'

export function Card({
  children,
  className,
  title,
  subtitle,
  actions,
}: {
  children?: ReactNode
  className?: string
  title?: ReactNode
  subtitle?: ReactNode
  actions?: ReactNode
}) {
  return (
    <section
      className={classNames(
        'rounded-xl border border-ink-700/70 bg-ink-900/60 shadow-lg shadow-black/20 backdrop-blur',
        className,
      )}
    >
      {(title || actions) && (
        <header className="flex items-start justify-between gap-3 border-b border-ink-700/60 px-4 py-3">
          <div>
            {title && <h2 className="text-sm font-semibold tracking-wide text-smoke-300">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-xs text-smoke-400">{subtitle}</p>}
          </div>
          {actions}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  )
}

export function Badge({
  children,
  className,
  title,
}: {
  children: ReactNode
  className?: string
  title?: string
}) {
  return (
    <span
      title={title}
      className={classNames(
        'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset',
        className ?? 'bg-ink-700/50 text-smoke-300 ring-ink-600/50',
      )}
    >
      {children}
    </span>
  )
}

export function ProvenanceBadge({ provenance }: { provenance: Provenance }) {
  return (
    <Badge className={provenanceStyles[provenance]} title={`Provenance: ${provenance}`}>
      {provenance}
    </Badge>
  )
}

export function StatusBadge({ status }: { status: IncidentStatus }) {
  return <Badge className={statusStyles[status]}>{statusLabels[status]}</Badge>
}

export function GeometryBadge({ quality }: { quality: GeometryQuality }) {
  return (
    <Badge className={geometryStyles[quality]} title={`Geometry quality: ${quality}`}>
      {quality === 'unavailable' ? 'no geometry' : quality}
    </Badge>
  )
}

export function StatCard({
  label,
  value,
  hint,
  accent,
}: {
  label: string
  value: ReactNode
  hint?: ReactNode
  accent?: string
}) {
  return (
    <div className="rounded-xl border border-ink-700/70 bg-ink-900/50 px-4 py-3">
      <div className="text-[11px] font-medium uppercase tracking-wider text-smoke-400">{label}</div>
      <div className={classNames('mt-1 text-2xl font-semibold tabular-nums', accent ?? 'text-white')}>
        {value}
      </div>
      {hint && <div className="mt-1 text-xs text-smoke-400">{hint}</div>}
    </div>
  )
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-smoke-400">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-ink-600 border-t-ember-500" />
      {label ?? 'Loading…'}
    </div>
  )
}

export function EmptyState({
  title,
  children,
  icon,
}: {
  title: string
  children?: ReactNode
  icon?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-ink-600/60 px-6 py-10 text-center">
      {icon}
      <p className="text-sm font-medium text-smoke-300">{title}</p>
      {children && <div className="max-w-md text-xs text-smoke-400">{children}</div>}
    </div>
  )
}

export function ErrorState({ error, retry }: { error: unknown; retry?: () => void }) {
  const message = error instanceof Error ? error.message : String(error)
  return (
    <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">
      <div className="font-medium">Something went wrong</div>
      <div className="mt-1 text-xs text-red-200/80">{message}</div>
      {retry && (
        <button
          onClick={retry}
          className="mt-2 rounded-md bg-red-500/20 px-3 py-1 text-xs font-medium text-red-100 hover:bg-red-500/30"
        >
          Retry
        </button>
      )}
    </div>
  )
}

export function DemoBanner({ notice, mode }: { notice?: string; mode?: string }) {
  if (mode && mode !== 'demo') {
    return (
      <div className="rounded-lg border border-sky-500/30 bg-sky-500/10 px-4 py-2 text-xs text-sky-200">
        <strong className="font-semibold">Real-data mode.</strong>{' '}
        {notice ??
          'Only user-supplied data and configured models are used. Missing data is reported as unavailable, never simulated.'}
      </div>
    )
  }
  return (
    <div className="flex items-center gap-2 rounded-lg border border-violet-500/40 bg-violet-500/10 px-4 py-2 text-xs text-violet-100">
      <span className="inline-block h-2 w-2 shrink-0 animate-pulse rounded-full bg-violet-400" />
      <span>
        <strong className="font-semibold uppercase tracking-wide">Simulated demo data.</strong>{' '}
        {notice ??
          'Every observation, bearing, incident and metric here comes from synthetic fixtures — not real fires.'}
      </span>
    </div>
  )
}
