import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Flame, Filter, Search } from 'lucide-react'
import { api } from '../lib/api'
import type { IncidentStatus } from '../lib/api'
import { useAsync } from '../lib/hooks'
import {
  Card,
  EmptyState,
  ErrorState,
  GeometryBadge,
  ProvenanceBadge,
  Spinner,
  StatusBadge,
} from '../components/ui'
import { formatCoord, formatDistance, formatRelative, severityStyles } from '../lib/format'

const STATUSES: (IncidentStatus | '')[] = [
  '',
  'candidate',
  'confirmed',
  'reviewed',
  'acknowledged',
  'dismissed',
]

export function IncidentsPage() {
  const [status, setStatus] = useState<string>('')
  const [provenance, setProvenance] = useState<string>('')
  const [search, setSearch] = useState<string>('')

  const incidents = useAsync(
    () => api.incidents({ status: status || undefined, provenance: provenance || undefined, search: search || undefined, limit: 100 }),
    [status, provenance, search],
    { pollMs: 10000 },
  )

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold text-white">Incidents</h1>
        <p className="text-sm text-smoke-400">
          Smoke candidates promoted by the temporal tracker, refined by cross-camera geometry, and
          reviewed by a human.
        </p>
      </div>

      <Card title="Filters" actions={<Filter className="h-4 w-4 text-smoke-400" />}>
        <div className="flex flex-wrap items-end gap-3">
          <label>
            <span className="mb-1 block text-xs text-smoke-400">Status</span>
            <select
              value={status}
              onChange={(e) => setStatus(e.target.value)}
              className="rounded-lg border border-ink-600 bg-ink-850 px-3 py-2 text-sm text-white outline-none focus:border-ember-500"
            >
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s === '' ? 'all' : s}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span className="mb-1 block text-xs text-smoke-400">Provenance</span>
            <select
              value={provenance}
              onChange={(e) => setProvenance(e.target.value)}
              className="rounded-lg border border-ink-600 bg-ink-850 px-3 py-2 text-sm text-white outline-none focus:border-ember-500"
            >
              {['', 'simulated', 'predicted', 'real', 'heuristic', 'manual'].map((p) => (
                <option key={p} value={p}>
                  {p === '' ? 'all' : p}
                </option>
              ))}
            </select>
          </label>
          <label className="flex-1 min-w-[200px]">
            <span className="mb-1 block text-xs text-smoke-400">Search title</span>
            <div className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-smoke-400" />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="candidate…"
                className="w-full rounded-lg border border-ink-600 bg-ink-850 py-2 pl-8 pr-3 text-sm text-white outline-none focus:border-ember-500"
              />
            </div>
          </label>
        </div>
      </Card>

      {incidents.loading && !incidents.data ? (
        <Spinner label="Loading incidents…" />
      ) : incidents.error ? (
        <ErrorState error={incidents.error} retry={incidents.reload} />
      ) : incidents.data && incidents.data.items.length ? (
        <Card
          title={`${incidents.data.total} incident(s)`}
          subtitle={`Showing ${incidents.data.items.length}`}
        >
          <ul className="divide-y divide-ink-800">
            {incidents.data.items.map((inc) => (
              <li key={inc.id}>
                <Link
                  to={`/incidents/${inc.id}`}
                  className="flex flex-wrap items-center justify-between gap-3 py-3 transition-colors hover:bg-ink-800/40"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <Flame className="h-4 w-4 shrink-0 text-ember-400" />
                      <span className="truncate text-sm font-medium text-white">{inc.title}</span>
                      <span className={`text-[11px] uppercase ${severityStyles[inc.severity_tier]}`}>
                        {inc.severity_tier}
                      </span>
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-smoke-400">
                      <span>{formatCoord(inc.latitude, inc.longitude)}</span>
                      {inc.location_uncertainty_m != null && (
                        <span>± {formatDistance(inc.location_uncertainty_m)}</span>
                      )}
                      <span>{formatRelative(inc.created_at)}</span>
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-1.5">
                    <ProvenanceBadge provenance={inc.provenance} />
                    {inc.geometry_quality && <GeometryBadge quality={inc.geometry_quality} />}
                    <StatusBadge status={inc.status} />
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        </Card>
      ) : (
        <EmptyState
          title="No incidents match"
          icon={<Flame className="h-6 w-6 text-smoke-400" />}
        >
          Incidents appear after the temporal tracker confirms a persistent smoke track. Try the
          Detection Replay page, or clear filters.
        </EmptyState>
      )}
    </div>
  )
}
