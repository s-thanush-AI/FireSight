import { Link } from 'react-router-dom'
import {
  ArrowRight,
  Camera,
  Crosshair,
  Flame,
  Gauge,
  ShieldQuestion,
} from 'lucide-react'
import { api } from '../lib/api'
import { useAsync } from '../lib/hooks'
import { Card, EmptyState, ErrorState, GeometryBadge, Spinner, StatCard, StatusBadge } from '../components/ui'
import { formatCoord, formatDistance, formatRelative } from '../lib/format'

export function OverviewPage() {
  const incidents = useAsync(() => api.incidents({ limit: 5, sort: 'created_at:desc' }), [], {
    pollMs: 10000,
  })
  const geom = useAsync(() => api.geometry(), [])
  const models = useAsync(() => api.models(), [])

  const byStatus = incidents.data
    ? incidents.data.items.reduce<Record<string, number>>((acc, i) => {
        acc[i.status] = (acc[i.status] ?? 0) + 1
        return acc
      }, {})
    : {}

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold text-white">Overview</h1>
        <p className="text-sm text-smoke-400">
          What the pipeline is doing right now, and what it has found so far.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <StatCard
          label="Incidents"
          value={incidents.data?.total ?? '—'}
          hint="candidates + confirmed"
          accent="text-ember-400"
        />
        <StatCard
          label="Confirmed"
          value={byStatus.confirmed ?? 0}
          hint="temporal + cross-camera"
          accent="text-orange-300"
        />
        <StatCard
          label="Triangulated"
          value={geom.data?.triangulations.length ?? '—'}
          hint="ray intersections stored"
          accent="text-sky-300"
        />
        <StatCard
          label="Cameras"
          value={geom.data?.cameras.length ?? '—'}
          hint="configured"
        />
        <StatCard
          label="Detector"
          value={models.data?.detectors.find((d) => d.active)?.kind ?? '—'}
          hint={
            models.data?.detectors.find((d) => d.active)?.available
              ? 'available'
              : 'unavailable'
          }
        />
        <StatCard
          label="VLM"
          value={models.data?.vlm.configured ? 'configured' : 'simulated'}
          hint={models.data?.vlm.provider ?? '—'}
        />
      </div>

      <div className="grid gap-5 lg:grid-cols-3">
        <Card
          className="lg:col-span-2"
          title="Recent incidents"
          subtitle="Newest first"
          actions={
            <Link
              to="/incidents"
              className="inline-flex items-center gap-1 text-xs text-ember-400 hover:text-ember-500"
            >
              All incidents <ArrowRight className="h-3 w-3" />
            </Link>
          }
        >
          {incidents.loading && !incidents.data ? (
            <Spinner />
          ) : incidents.error ? (
            <ErrorState error={incidents.error} retry={incidents.reload} />
          ) : incidents.data && incidents.data.items.length ? (
            <ul className="divide-y divide-ink-800">
              {incidents.data.items.map((inc) => (
                <li key={inc.id}>
                  <Link
                    to={`/incidents/${inc.id}`}
                    className="flex items-center justify-between gap-3 py-2.5 transition-colors hover:bg-ink-800/40"
                  >
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <Flame className="h-3.5 w-3.5 shrink-0 text-ember-400" />
                        <span className="truncate text-sm text-white">{inc.title}</span>
                      </div>
                      <div className="mt-0.5 truncate text-xs text-smoke-400">
                        {formatCoord(inc.latitude, inc.longitude)}{' '}
                        {inc.location_uncertainty_m != null &&
                          `± ${formatDistance(inc.location_uncertainty_m)}`}{' '}
                        · {formatRelative(inc.created_at)}
                      </div>
                    </div>
                    <div className="flex shrink-0 items-center gap-1.5">
                      {inc.geometry_quality && <GeometryBadge quality={inc.geometry_quality} />}
                      <StatusBadge status={inc.status} />
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState
              title="No incidents yet"
              icon={<ShieldQuestion className="h-6 w-6 text-smoke-400" />}
            >
              Run the demo replay from the Detection Replay page to generate simulated incidents.
            </EmptyState>
          )}
        </Card>

        <div className="space-y-5">
          <Card title="Incident status" subtitle="Across stored incidents">
            <ul className="space-y-2 text-sm">
              {['candidate', 'confirmed', 'reviewed', 'acknowledged', 'dismissed'].map((s) => (
                <li key={s} className="flex items-center justify-between">
                  <StatusBadge status={s as never} />
                  <span className="tabular-nums text-smoke-300">{byStatus[s] ?? 0}</span>
                </li>
              ))}
            </ul>
          </Card>

          <Card title="How geolocation works" subtitle="Two rays, one least-squares intersection">
            <ul className="space-y-2 text-xs text-smoke-300">
              <li className="flex gap-2">
                <Camera className="mt-0.5 h-3.5 w-3.5 shrink-0 text-sky-300" />
                Each detection becomes a bearing (degrees clockwise from north) from a calibrated
                camera.
              </li>
              <li className="flex gap-2">
                <Crosshair className="mt-0.5 h-3.5 w-3.5 shrink-0 text-ember-400" />
                Two cameras whose rays pass close in time are intersected; quality reflects ray
                separation and fit residual.
              </li>
              <li className="flex gap-2">
                <Gauge className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-glow" />
                Uncertainty comes from assumed pixel and heading noise — an estimate, not a
                measurement.
              </li>
            </ul>
            <Link
              to="/map"
              className="mt-3 inline-flex items-center gap-1 text-xs text-ember-400 hover:text-ember-500"
            >
              Open geolocation map <ArrowRight className="h-3 w-3" />
            </Link>
          </Card>
        </div>
      </div>
    </div>
  )
}
