import { useEffect, useState } from 'react'
import { CircleStop, Play, Plus, Radio, Trash2, Video } from 'lucide-react'
import { api, liveFrameUrl, type Camera, type LiveSource } from '../lib/api'
import { useAsync } from '../lib/hooks'
import { Badge, Card, EmptyState, ErrorState, Spinner } from '../components/ui'
import { classNames, formatTimestamp } from '../lib/format'

const statusStyle: Record<string, string> = {
  running: 'bg-emerald-500/15 text-emerald-300 ring-emerald-500/30',
  starting: 'bg-sky-500/15 text-sky-300 ring-sky-500/30',
  reconnecting: 'bg-amber-500/15 text-amber-300 ring-amber-500/30',
  stalled: 'bg-orange-500/15 text-orange-300 ring-orange-500/30',
  finished: 'bg-slate-500/15 text-slate-300 ring-slate-500/30',
  stopped: 'bg-slate-500/15 text-slate-300 ring-slate-500/30',
  error: 'bg-red-500/15 text-red-300 ring-red-500/30',
  idle: 'bg-ink-700/50 text-smoke-300 ring-ink-600/50',
}

export function LiveSourcesPage() {
  const sources = useAsync(() => api.liveSources(), [], { pollMs: 2000 })
  const cameras = useAsync(() => api.cameras(), [])
  const [name, setName] = useState('Local wildfire flames test clip')
  const [nameTouched, setNameTouched] = useState(false)
  const [kind, setKind] = useState<'file' | 'rtsp'>('file')
  const [path, setPath] = useState('videos/wildfire-flames-test.mp4')
  const [url, setUrl] = useState('')
  const [cameraId, setCameraId] = useState('')
  const [sampleFps, setSampleFps] = useState(1)
  const [threshold, setThreshold] = useState(0.25)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)

  const changeKind = (next: 'file' | 'rtsp') => {
    setKind(next)
    setError(null)
    if (!nameTouched) {
      setName(next === 'rtsp' ? 'RTSP camera' : 'Local Ranch2 test clip')
    }
    if (next === 'rtsp') setUrl('')
  }

  const create = async () => {
    const target = kind === 'file' ? path.trim() : url.trim()
    if (!target) {
      setError(
        new Error(
          kind === 'rtsp'
            ? 'Enter an rtsp:// or rtsps:// URL. RTSP mode never falls back to a local clip.'
            : 'Enter a video path relative to the data root.',
        ),
      )
      return
    }
    if (kind === 'rtsp' && !/^rtsps?:\/\//i.test(target)) {
      setError(new Error('RTSP URL must start with rtsp:// or rtsps://'))
      return
    }
    setBusy(true)
    setError(null)
    try {
      await api.createLiveSource({
        name,
        kind,
        ...(kind === 'file' ? { path } : { url }),
        camera_id: cameraId || undefined,
        sample_fps: sampleFps,
        threshold,
        loop: true,
      })
      sources.reload()
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  const act = async (fn: () => Promise<unknown>) => {
    setError(null)
    try {
      await fn()
      sources.reload()
    } catch (err) {
      setError(err)
    }
  }

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold text-white">Live Sources</h1>
        <p className="text-sm text-smoke-400">
          Connect an RTSP camera, or explicitly start a local-file test source. These are separate
          modes: RTSP never falls back to a bundled clip. Credentials are never returned by the API;
          previews and alerts are experimental.
        </p>
      </div>

      <div className="grid gap-5 xl:grid-cols-[420px_1fr]">
        <Card title="Add source" subtitle="RTSP or a video under backend/data/videos">
          <div className="space-y-3 text-sm">
            <label className="block">
              <span className="mb-1 block text-xs text-smoke-400">Name</span>
              <input
                value={name}
                onChange={(e) => {
                  setName(e.target.value)
                  setNameTouched(true)
                }}
                maxLength={80}
                className="w-full rounded-lg border border-ink-600 bg-ink-850 px-3 py-2 text-white outline-none focus:border-ember-500"
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs text-smoke-400">Kind</span>
              <select
                value={kind}
                onChange={(e) => changeKind(e.target.value as 'file' | 'rtsp')}
                className="w-full rounded-lg border border-ink-600 bg-ink-850 px-3 py-2 text-white outline-none focus:border-ember-500"
              >
                <option value="file">Local test video (file)</option>
                <option value="rtsp">RTSP camera</option>
              </select>
            </label>
            {kind === 'file' ? (
              <label className="block">
                <span className="mb-1 block text-xs text-smoke-400">
                  Path relative to the data root
                </span>
                <input
                  value={path}
                  onChange={(e) => setPath(e.target.value)}
                  placeholder="videos/ranch2-sjh.mp4"
                  className="w-full rounded-lg border border-ink-600 bg-ink-850 px-3 py-2 font-mono text-xs text-white outline-none focus:border-ember-500"
                />
              </label>
            ) : (
              <label className="block">
                <span className="mb-1 block text-xs text-smoke-400">
                  RTSP URL (userinfo is redacted in every response)
                </span>
                <input
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  placeholder="rtsp://host:8554/stream"
                  className="w-full rounded-lg border border-ink-600 bg-ink-850 px-3 py-2 font-mono text-xs text-white outline-none focus:border-ember-500"
                />
              </label>
            )}
            <label className="block">
              <span className="mb-1 block text-xs text-smoke-400">Camera (optional, for bearings)</span>
              <select
                value={cameraId}
                onChange={(e) => setCameraId(e.target.value)}
                className="w-full rounded-lg border border-ink-600 bg-ink-850 px-3 py-2 text-white outline-none focus:border-ember-500"
              >
                <option value="">No camera</option>
                {cameras.data?.items.map((c: Camera) => (
                  <option key={c.id} value={c.id}>
                    {c.id} ({c.calibration_status})
                  </option>
                ))}
              </select>
            </label>
            <div className="grid grid-cols-2 gap-3">
              <label className="block">
                <span className="mb-1 block text-xs text-smoke-400">Samples / second</span>
                <input
                  type="number"
                  min={0.1}
                  max={10}
                  step={0.1}
                  value={sampleFps}
                  onChange={(e) => setSampleFps(Number(e.target.value))}
                  className="w-full rounded-lg border border-ink-600 bg-ink-850 px-3 py-2 text-white outline-none focus:border-ember-500"
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-xs text-smoke-400">Confidence threshold</span>
                <input
                  type="number"
                  min={0}
                  max={1}
                  step={0.05}
                  value={threshold}
                  onChange={(e) => setThreshold(Number(e.target.value))}
                  className="w-full rounded-lg border border-ink-600 bg-ink-850 px-3 py-2 text-white outline-none focus:border-ember-500"
                />
              </label>
            </div>
            <button
              onClick={create}
              disabled={busy || !name.trim()}
              className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-ember-500 px-4 py-2 text-sm font-medium text-ink-950 hover:bg-ember-400 disabled:opacity-50"
            >
              <Plus className="h-4 w-4" /> {busy ? 'Starting…' : 'Start source'}
            </button>
            {kind === 'rtsp' && (
              <p className="text-[11px] text-amber-300/90">
                RTSP mode connects only to the URL above. It never opens the Ranch2 test clip and
                never reports a failed connection as success. RTSP has not been verified against a
                real camera in this environment.
              </p>
            )}
          </div>
        </Card>

        <div className="space-y-4">
          {error != null && <ErrorState error={error} />}
          {sources.loading && !sources.data && <Spinner label="Loading sources…" />}
          {sources.data && !sources.data.sources.length && (
            <EmptyState title="No live sources" icon={<Radio className="h-6 w-6 text-smoke-400" />}>
              Choose “Local test video” for the Ranch2 clip, or choose “RTSP camera” and enter a
              reachable stream URL. A stopped/removed source disappears from this list.
            </EmptyState>
          )}
          {sources.data?.sources.map((source) => (
            <SourceCard
              key={source.id}
              source={source}
              onStop={() => act(() => api.stopLiveSource(source.id))}
              onDelete={() => act(() => api.deleteLiveSource(source.id))}
            />
          ))}
          {sources.data && (
            <p className="text-[11px] text-smoke-500">{sources.data.notice}</p>
          )}
        </div>
      </div>
    </div>
  )
}

function SourceCard({
  source,
  onStop,
  onDelete,
}: {
  source: LiveSource
  onStop: () => void
  onDelete: () => void
}) {
  return (
    <div className="overflow-hidden rounded-xl border border-ink-700/70 bg-ink-900/60">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-ink-700/60 px-4 py-3">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold text-white">
            <Video className="h-4 w-4 text-smoke-400" /> {source.name}
            <Badge className={statusStyle[source.status] ?? statusStyle.idle}>{source.status}</Badge>
            <Badge>{source.kind}</Badge>
          </div>
          <div className="mt-1 font-mono text-[11px] text-smoke-400">{source.target}</div>
        </div>
        <div className="flex gap-2">
          <button
            onClick={onStop}
            disabled={source.status === 'stopped' || source.status === 'finished'}
            className="inline-flex items-center gap-1 rounded-md border border-ink-600 px-2 py-1 text-xs text-smoke-300 hover:bg-ink-800 disabled:opacity-40"
          >
            <CircleStop className="h-3.5 w-3.5" /> Stop
          </button>
          <button
            onClick={onDelete}
            className="inline-flex items-center gap-1 rounded-md border border-red-500/30 px-2 py-1 text-xs text-red-300 hover:bg-red-500/10"
          >
            <Trash2 className="h-3.5 w-3.5" /> Remove
          </button>
        </div>
      </div>
      <div className="grid gap-4 p-4 md:grid-cols-[320px_1fr]">
        <Preview source={source} />
        <div className="grid grid-cols-2 gap-3 text-xs">
          <Metric label="Read" value={source.frames_read} />
          <Metric label="Processed" value={source.frames_processed} />
          <Metric label="Detections" value={source.detections_total} />
          <Metric label="Sample rate" value={`${source.sample_fps}/s`} />
          <Metric label="Camera" value={source.camera_id ?? 'none'} />
          <Metric label="Last frame" value={formatTimestamp(source.last_frame_at)} />
          {source.error && (
            <div className="col-span-2 rounded-md border border-red-500/30 bg-red-500/10 px-2 py-1.5 text-red-200">
              {source.error}
            </div>
          )}
          {source.status === 'reconnecting' && (
            <div className="col-span-2 flex items-center gap-1 text-amber-300">
              <Play className="h-3 w-3" /> reconnecting with backoff
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function Preview({ source }: { source: LiveSource }) {
  const [tick, setTick] = useState(() => Date.now())
  useEffect(() => {
    const t = window.setInterval(() => setTick(Date.now()), 1200)
    return () => window.clearInterval(t)
  }, [])
  return (
    <div className="relative grid aspect-video place-items-center overflow-hidden rounded-lg border border-ink-700 bg-black">
      {source.has_frame ? (
        <img
          src={`${liveFrameUrl(source.id)}?t=${tick}`}
          alt={`Latest preview from ${source.name}`}
          className="h-full w-full object-contain"
        />
      ) : (
        <span className="text-xs text-smoke-400">Waiting for a decoded frame…</span>
      )}
      <span
        className={classNames(
          'absolute left-2 top-2 rounded px-2 py-1 text-[10px] uppercase tracking-wider ring-1',
          source.kind === 'rtsp'
            ? 'bg-black/60 text-sky-200 ring-sky-400/30'
            : 'bg-black/60 text-amber-200 ring-amber-400/30',
        )}
      >
        {source.kind === 'rtsp' ? 'RTSP · experimental' : 'LOCAL FILE TEST · NOT LIVE'}
      </span>
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-smoke-500">{label}</div>
      <div className="truncate font-medium text-smoke-200">{value}</div>
    </div>
  )
}
