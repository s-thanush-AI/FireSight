import { Brain, Cpu, GraduationCap, ShieldAlert } from 'lucide-react'
import { api } from '../lib/api'
import { useAsync } from '../lib/hooks'
import { Badge, Card, ErrorState, ProvenanceBadge, Spinner } from '../components/ui'

export function ModelsPage() {
  const models = useAsync(() => api.models(), [])

  if (models.loading && !models.data) return <Spinner />
  if (models.error) return <ErrorState error={models.error} retry={models.reload} />
  if (!models.data) return null

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold text-white">Models &amp; VLM</h1>
        <p className="text-sm text-smoke-400">
          Which detector is active, what it can and cannot do, and how the optional
          vision-language verification is configured.
        </p>
      </div>

      <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-2 text-xs text-amber-100">
        <ShieldAlert className="mb-0.5 mr-1 inline h-3.5 w-3.5" />
        The classic detector is a computer-vision heuristic, not a trained wildfire model. No model
        weights are downloaded automatically.
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        {models.data.detectors.map((d) => (
          <Card
            key={d.name}
            title={
              <span className="flex items-center gap-2">
                <Cpu className="h-4 w-4 text-sky-300" /> {d.name}
              </span>
            }
            subtitle={d.kind}
            actions={d.active ? <Badge className="bg-ember-500/15 text-ember-300 ring-ember-500/30">active</Badge> : <Badge>available</Badge>}
          >
            <dl className="space-y-1.5 text-xs">
              <div className="flex justify-between">
                <dt className="text-smoke-400">Status</dt>
                <dd className={d.available ? 'text-emerald-300' : 'text-red-300'}>
                  {d.available ? 'available' : 'unavailable'}
                </dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-smoke-400">Version</dt>
                <dd className="font-mono text-smoke-200">{d.version}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-smoke-400">Confidence threshold</dt>
                <dd className="tabular-nums text-smoke-200">{d.confidence_threshold}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-smoke-400">IoU threshold</dt>
                <dd className="tabular-nums text-smoke-200">{d.iou_threshold}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-smoke-400">Image size</dt>
                <dd className="tabular-nums text-smoke-200">{d.image_size}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-smoke-400">Device</dt>
                <dd className="text-smoke-200">{d.device}</dd>
              </div>
              {d.provenance && (
                <div className="flex items-center justify-between">
                  <dt className="text-smoke-400">Output provenance</dt>
                  <dd>
                    <ProvenanceBadge provenance={d.provenance as never} />
                  </dd>
                </div>
              )}
              {d.weights_path && (
                <div className="flex justify-between gap-4">
                  <dt className="shrink-0 text-smoke-400">Weights</dt>
                  <dd className="truncate font-mono text-[10px] text-smoke-300">{d.weights_path}</dd>
                </div>
              )}
            </dl>
            {d.unavailable_reason && (
              <p className="mt-2 rounded-md bg-ink-800/60 px-2 py-1.5 text-[11px] text-smoke-400">
                {d.unavailable_reason}
              </p>
            )}
          </Card>
        ))}

        <Card
          title={
            <span className="flex items-center gap-2">
              <Brain className="h-4 w-4 text-violet-300" /> Vision-language verification
            </span>
          }
          subtitle="Optional, on-demand only"
        >
          <dl className="space-y-1.5 text-xs">
            <div className="flex justify-between">
              <dt className="text-smoke-400">Provider</dt>
              <dd className="text-smoke-200">{models.data.vlm.provider}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-smoke-400">Configured</dt>
              <dd className={models.data.vlm.configured ? 'text-emerald-300' : 'text-amber-300'}>
                {models.data.vlm.configured ? 'yes (environment)' : 'no — simulated in demo'}
              </dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-smoke-400">Model</dt>
              <dd className="font-mono text-smoke-200">{models.data.vlm.model ?? '—'}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-smoke-400">Base URL</dt>
              <dd className="font-mono text-[10px] text-smoke-300">
                {models.data.vlm.base_url ?? '—'}
              </dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-smoke-400">API key present</dt>
              <dd className="text-smoke-200">{models.data.vlm.api_key_present ? 'yes' : 'no'}</dd>
            </div>
          </dl>
          <p className="mt-2 rounded-md bg-ink-800/60 px-2 py-1.5 text-[11px] text-smoke-400">
            {models.data.vlm.note}
          </p>
        </Card>
      </div>

      <Card
        title={
          <span className="flex items-center gap-2">
            <GraduationCap className="h-4 w-4 text-amber-glow" /> Training
          </span>
        }
        subtitle="Never runs automatically"
      >
        <p className="text-xs text-smoke-300">{models.data.training.note}</p>
        <pre className="mt-2 overflow-x-auto rounded-md bg-black/40 px-3 py-2 font-mono text-[11px] text-emerald-300">
          {models.data.training.command}
        </pre>
      </Card>
    </div>
  )
}
