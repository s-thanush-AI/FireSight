import { useState } from 'react'
import { Bell, Check, CheckCheck, ShieldAlert } from 'lucide-react'
import { api, evidenceUrl, type AlertRecord } from '../lib/api'
import { useAsync } from '../lib/hooks'
import { Badge, Card, EmptyState, ErrorState, Spinner } from '../components/ui'
import { classNames, formatRelative, formatTimestamp } from '../lib/format'

const statusClass: Record<string, string> = {
  new: 'bg-amber-500/15 text-amber-300 ring-amber-500/30',
  acknowledged: 'bg-sky-500/15 text-sky-300 ring-sky-500/30',
  resolved: 'bg-emerald-500/15 text-emerald-300 ring-emerald-500/30',
}

export function AlertsPage() {
  const [filter, setFilter] = useState('')
  const alerts = useAsync(() => api.alerts({ status: filter || undefined, limit: 200 }), [filter], {
    pollMs: 5000,
  })
  const stats = useAsync(() => api.alertStats(), [], { pollMs: 10000 })
  const [error, setError] = useState<unknown>(null)

  const act = async (fn: () => Promise<unknown>) => {
    setError(null)
    try {
      await fn()
      alerts.reload()
      stats.reload()
    } catch (err) {
      setError(err)
    }
  }

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold text-white">Alerts</h1>
        <p className="text-sm text-smoke-400">
          Experimental detector alerts with evidence and provenance. Review before acting; this is
          not an operational warning service.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-4">
        <Stat label="New" value={stats.data?.new ?? 0} accent="text-amber-300" />
        <Stat label="Acknowledged" value={stats.data?.acknowledged ?? 0} accent="text-sky-300" />
        <Stat label="Resolved" value={stats.data?.resolved ?? 0} accent="text-emerald-300" />
        <Stat label="Total" value={stats.data?.total ?? 0} />
      </div>

      <Card
        title="Alert feed"
        subtitle="Newest first · rule-based dedupe and per-source cooldown"
        actions={
          <select
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="rounded-lg border border-ink-600 bg-ink-850 px-2 py-1 text-xs text-white outline-none focus:border-ember-500"
          >
            <option value="">All statuses</option>
            <option value="new">New</option>
            <option value="acknowledged">Acknowledged</option>
            <option value="resolved">Resolved</option>
          </select>
        }
      >
        {error != null && (
          <div className="mb-3">
            <ErrorState error={error} />
          </div>
        )}
        {alerts.loading && !alerts.data && <Spinner label="Loading alerts…" />}
        {alerts.data && !alerts.data.alerts.length && (
          <EmptyState title="No alerts" icon={<Bell className="h-6 w-6 text-smoke-400" />}>
            Run the local video analysis or a file live source with a low threshold to exercise the
            alert pipeline.
          </EmptyState>
        )}
        <div className="space-y-3">
          {alerts.data?.alerts.map((alert) => (
            <AlertRow
              key={alert.id}
              alert={alert}
              onAck={() => act(() => api.acknowledgeAlert(alert.id))}
              onResolve={() => act(() => api.resolveAlert(alert.id))}
            />
          ))}
        </div>
        {alerts.data && <p className="mt-3 text-[11px] text-smoke-500">{alerts.data.notice}</p>}
      </Card>
    </div>
  )
}

function AlertRow({
  alert,
  onAck,
  onResolve,
}: {
  alert: AlertRecord
  onAck: () => void
  onResolve: () => void
}) {
  return (
    <div className="grid gap-3 rounded-lg border border-ink-700/60 bg-ink-900/40 p-3 sm:grid-cols-[180px_1fr]">
      <div className="overflow-hidden rounded-md border border-ink-700 bg-black">
        {alert.evidence_path ? (
          <img
            src={evidenceUrl(alert.id)}
            alt={`Evidence for alert ${alert.id}`}
            className="aspect-video h-full w-full object-cover"
            loading="lazy"
          />
        ) : (
          <div className="grid aspect-video place-items-center text-[11px] text-smoke-500">
            no evidence image
          </div>
        )}
      </div>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <ShieldAlert className="h-4 w-4 text-amber-300" />
          <span className="font-mono text-xs text-smoke-300">{alert.id}</span>
          <Badge className={classNames(statusClass[alert.status])}>{alert.status}</Badge>
          <Badge>{alert.source_type}</Badge>
          <Badge>{alert.verification_status}</Badge>
          <span className="text-[11px] text-smoke-500">{formatRelative(alert.created_at)}</span>
        </div>
        <div className="mt-2 grid gap-1 text-xs text-smoke-400 sm:grid-cols-2">
          <div>detector {alert.detector_name}{alert.detector_version ? ` v${alert.detector_version}` : ''}</div>
          <div>confidence {alert.confidence != null ? alert.confidence.toFixed(2) : '—'}</div>
          <div>source {alert.source_id ?? '—'}</div>
          <div>camera {alert.camera_id ?? '—'}</div>
          <div>event {formatTimestamp(alert.event_time)}</div>
          <div>frame {alert.frame_ref ?? '—'}</div>
        </div>
        {alert.notes && <p className="mt-2 text-xs text-smoke-400">{alert.notes}</p>}
        <div className="mt-2 flex gap-2">
          {alert.status === 'new' && (
            <button
              onClick={onAck}
              className="inline-flex items-center gap-1 rounded-md border border-ink-600 px-2 py-1 text-xs text-smoke-300 hover:bg-ink-800"
            >
              <Check className="h-3.5 w-3.5" /> Acknowledge
            </button>
          )}
          {alert.status !== 'resolved' && (
            <button
              onClick={onResolve}
              className="inline-flex items-center gap-1 rounded-md border border-emerald-500/30 px-2 py-1 text-xs text-emerald-300 hover:bg-emerald-500/10"
            >
              <CheckCheck className="h-3.5 w-3.5" /> Resolve
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

function Stat({
  label,
  value,
  accent,
}: {
  label: string
  value: number
  accent?: string
}) {
  return (
    <div className="rounded-xl border border-ink-700/70 bg-ink-900/50 px-4 py-3">
      <div className="text-[11px] uppercase tracking-wider text-smoke-400">{label}</div>
      <div className={classNames('mt-1 text-2xl font-semibold tabular-nums', accent ?? 'text-white')}>
        {value}
      </div>
    </div>
  )
}
