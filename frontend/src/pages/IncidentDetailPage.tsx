import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  ArrowLeft,
  CheckCircle2,
  Download,
  Eye,
  Sparkles,
  Undo2,
  XCircle,
} from 'lucide-react'
import { api } from '../lib/api'
import { useAsync } from '../lib/hooks'
import {
  Badge,
  Card,
  ErrorState,
  GeometryBadge,
  ProvenanceBadge,
  Spinner,
  StatusBadge,
} from '../components/ui'
import { formatCoord, formatDistance, formatPercent, formatTimestamp } from '../lib/format'

export function IncidentDetailPage() {
  const { id = '' } = useParams()
  const detail = useAsync(() => api.incident(id), [id])
  const [actionError, setActionError] = useState<unknown>(null)
  const [verifying, setVerifying] = useState(false)

  const act = async (action: string) => {
    setActionError(null)
    try {
      await api.patchIncident(id, action, `operator action via dashboard (${action})`)
      detail.reload()
    } catch (err) {
      setActionError(err)
    }
  }

  const verify = async () => {
    setVerifying(true)
    setActionError(null)
    try {
      await api.verifyIncident(id)
      detail.reload()
    } catch (err) {
      setActionError(err)
    } finally {
      setVerifying(false)
    }
  }

  if (detail.loading && !detail.data) return <Spinner label="Loading incident…" />
  if (detail.error)
    return (
      <div className="space-y-4">
        <Link to="/incidents" className="inline-flex items-center gap-1 text-xs text-ember-400">
          <ArrowLeft className="h-3 w-3" /> Back to incidents
        </Link>
        <ErrorState error={detail.error} retry={detail.reload} />
      </div>
    )
  if (!detail.data) return null

  const { incident, observations, triangulations, history, vlm_verifications } = detail.data

  return (
    <div className="space-y-5">
      <Link to="/incidents" className="inline-flex items-center gap-1 text-xs text-ember-400 hover:text-ember-500">
        <ArrowLeft className="h-3 w-3" /> Back to incidents
      </Link>

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-white">{incident.title}</h1>
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <StatusBadge status={incident.status} />
            <ProvenanceBadge provenance={incident.provenance} />
            {incident.geometry_quality && <GeometryBadge quality={incident.geometry_quality} />}
            <Badge>{incident.mode} mode</Badge>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => act('acknowledge')}
            className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-1.5 text-xs text-emerald-200 hover:bg-emerald-500/20"
          >
            <CheckCircle2 className="h-3.5 w-3.5" /> Acknowledge
          </button>
          <button
            onClick={() => act('mark_reviewed')}
            className="inline-flex items-center gap-1.5 rounded-lg border border-sky-500/40 bg-sky-500/10 px-3 py-1.5 text-xs text-sky-200 hover:bg-sky-500/20"
          >
            <Eye className="h-3.5 w-3.5" /> Mark reviewed
          </button>
          <button
            onClick={() => act('dismiss')}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-500/40 bg-slate-500/10 px-3 py-1.5 text-xs text-slate-200 hover:bg-slate-500/20"
          >
            <XCircle className="h-3.5 w-3.5" /> Dismiss
          </button>
          <button
            onClick={() => act('reopen')}
            className="inline-flex items-center gap-1.5 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-1.5 text-xs text-amber-200 hover:bg-amber-500/20"
          >
            <Undo2 className="h-3.5 w-3.5" /> Reopen
          </button>
          <a
            href={`/api/v1/reports/${encodeURIComponent(incident.id)}/download?format=json`}
            className="inline-flex items-center gap-1.5 rounded-lg border border-ink-600 px-3 py-1.5 text-xs text-smoke-300 hover:bg-ink-800"
          >
            <Download className="h-3.5 w-3.5" /> Export JSON
          </a>
        </div>
      </div>

      {actionError != null && <ErrorState error={actionError} />}

      <div className="grid gap-5 lg:grid-cols-3">
        <Card className="lg:col-span-2" title="Summary">
          <p className="text-sm text-smoke-300">{incident.summary ?? 'No summary recorded.'}</p>
          <dl className="mt-4 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
            <div>
              <dt className="text-xs text-smoke-400">Estimate</dt>
              <dd className="text-smoke-200">{formatCoord(incident.latitude, incident.longitude)}</dd>
            </div>
            <div>
              <dt className="text-xs text-smoke-400">Uncertainty</dt>
              <dd className="text-smoke-200">
                {incident.location_uncertainty_m != null
                  ? `± ${formatDistance(incident.location_uncertainty_m)}`
                  : 'unavailable'}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-smoke-400">First seen</dt>
              <dd className="text-smoke-200">{formatTimestamp(incident.first_seen_ts)}</dd>
            </div>
            <div>
              <dt className="text-xs text-smoke-400">Source dataset</dt>
              <dd className="text-smoke-200">{incident.source_dataset ?? '—'}</dd>
            </div>
          </dl>
        </Card>

        <Card
          title="VLM verification"
          subtitle="Model opinion — never ground truth"
          actions={
            <button
              onClick={verify}
              disabled={verifying}
              className="inline-flex items-center gap-1.5 rounded-lg bg-ember-500/90 px-3 py-1.5 text-xs font-medium text-ink-950 hover:bg-ember-400 disabled:opacity-50"
            >
              <Sparkles className="h-3.5 w-3.5" /> {verifying ? 'Running…' : 'Run verification'}
            </button>
          }
        >
          {vlm_verifications.length ? (
            <ul className="space-y-2 text-xs">
              {vlm_verifications
                .slice()
                .reverse()
                .map((v) => (
                  <li key={v.id} className="rounded-md bg-ink-800/50 px-3 py-2">
                    <div className="flex items-center justify-between">
                      <span className="font-medium text-smoke-200">{v.provider}</span>
                      <ProvenanceBadge provenance={v.provenance} />
                    </div>
                    <div className="mt-1 text-smoke-300">
                      assessment: {v.assessment ?? 'none'} · status {v.status}
                      {v.model_confidence != null && ` · conf ${formatPercent(v.model_confidence)}`}
                    </div>
                    {v.visual_evidence && (
                      <p className="mt-1 text-smoke-400">{v.visual_evidence}</p>
                    )}
                    {v.limitations && (
                      <p className="mt-1 text-smoke-400/80">Limitations: {v.limitations}</p>
                    )}
                  </li>
                ))}
            </ul>
          ) : (
            <p className="text-xs text-smoke-400">
              No verification yet. Demo mode returns a clearly-labelled simulated opinion; real mode
              needs VLM credentials configured in the environment.
            </p>
          )}
        </Card>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="Bearing observations" subtitle={`${observations.length} recorded`}>
          {observations.length ? (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="text-left text-smoke-400">
                  <tr>
                    <th className="pb-2">Camera</th>
                    <th className="pb-2">Bearing</th>
                    <th className="pb-2">Confidence</th>
                    <th className="pb-2">Provenance</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-ink-800">
                  {observations.map((o) => (
                    <tr key={o.id}>
                      <td className="py-1.5 font-mono text-[11px] text-smoke-300">{o.camera_id}</td>
                      <td className="py-1.5 tabular-nums text-smoke-200">
                        {o.bearing_deg.toFixed(1)}°
                      </td>
                      <td className="py-1.5 tabular-nums text-sky-300">
                        {o.confidence != null ? formatPercent(o.confidence) : '—'}
                      </td>
                      <td className="py-1.5">
                        <ProvenanceBadge provenance={o.provenance} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-xs text-smoke-400">No observations recorded.</p>
          )}
        </Card>

        <Card title="Triangulation" subtitle={`${triangulations.length} result(s)`}>
          {triangulations.length ? (
            <ul className="space-y-2 text-xs">
              {triangulations.map((t) => (
                <li key={t.id} className="rounded-md bg-ink-800/50 px-3 py-2">
                  <div className="flex items-center justify-between">
                    <span className="text-smoke-200">{formatCoord(t.latitude, t.longitude)}</span>
                    <GeometryBadge quality={t.quality} />
                  </div>
                  <div className="mt-1 flex flex-wrap gap-x-3 text-smoke-400">
                    <span>± {formatDistance(t.uncertainty_m)}</span>
                    <span>separation {t.ray_separation_deg?.toFixed(1)}°</span>
                    <span>residual {t.fit_residual_m?.toFixed(0)} m</span>
                    <span>method {t.method}</span>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-smoke-400">
              No triangulation — a second camera did not observe this event within the association
              window.
            </p>
          )}
        </Card>
      </div>

      <Card title="Status history" subtitle="Every transition is audited">
        {history.length ? (
          <ol className="space-y-2 text-xs">
            {history
              .slice()
              .reverse()
              .map((h) => (
                <li key={h.id} className="flex flex-wrap items-center gap-2">
                  <span className="text-smoke-400">{formatTimestamp(h.created_at)}</span>
                  <Badge>{h.action}</Badge>
                  <span className="text-smoke-300">
                    {h.from_status ?? '∅'} → {h.to_status}
                  </span>
                  <span className="text-smoke-400">by {h.actor}</span>
                  {h.reason && <span className="text-smoke-400/80">“{h.reason}”</span>}
                </li>
              ))}
          </ol>
        ) : (
          <p className="text-xs text-smoke-400">No history.</p>
        )}
      </Card>
    </div>
  )
}
