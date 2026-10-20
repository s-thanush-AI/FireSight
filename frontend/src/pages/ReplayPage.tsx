import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  AlertTriangle,
  Film,
  Layers,
  Pause,
  Play,
  Radio,
  RotateCcw,
  ScanLine,
  StepForward,
  Video as VideoIcon,
  Zap,
} from 'lucide-react'
import {
  api,
  ApiError,
  assetUrl,
  videoStreamUrl,
  wsUrl,
  type ReplayEvent,
  type ReplayStatusResponse,
  type SequenceInfo,
  type VideoAnalysis,
  type VideoInfo,
} from '../lib/api'
import { useAsync } from '../lib/hooks'
import { Badge, Card, EmptyState, ErrorState, ProvenanceBadge, Spinner } from '../components/ui'
import { classNames, formatTimestamp } from '../lib/format'

interface LiveFrame {
  replay_id: string
  frame: {
    index: number
    filename: string
    timestamp: string
    camera_id: string | null
    provenance?: string
    detector_name?: string
    detector_version?: string
    detector_caveat?: string | null
    detector_provenance?: string
  } | null
  image_jpeg_base64: string | null
  detections: Record<string, unknown>[]
}

export function ReplayPage() {
  const sequences = useAsync(() => api.sequences(), [])
  const videos = useAsync(() => api.videos(), [])
  const [mode, setMode] = useState<'images' | 'video'>('images')
  const [chosenSequence, setChosenSequence] = useState<string>('')
  const [chosenVideo, setChosenVideo] = useState<string>('')
  const [session, setSession] = useState<ReplayStatusResponse | null>(null)
  const [live, setLive] = useState<LiveFrame | null>(null)
  const [originalJpeg, setOriginalJpeg] = useState<string | null>(null)
  const [showOriginal, setShowOriginal] = useState(false)
  const [events, setEvents] = useState<ReplayEvent[]>([])
  const [connected, setConnected] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [videoError, setVideoError] = useState<string | null>(null)
  const [analysis, setAnalysis] = useState<VideoAnalysis | null>(null)
  const [analyzing, setAnalyzing] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)

  const { reload: reloadSequences } = sequences

  useEffect(() => {
    const onChange = () => reloadSequences()
    window.addEventListener('firesight:sequences-changed', onChange)
    return () => window.removeEventListener('firesight:sequences-changed', onChange)
  }, [reloadSequences])

  const sequenceId = chosenSequence || sequences.data?.items[0]?.id || ''
  const videoId = chosenVideo || videos.data?.videos[0]?.id || ''
  const replayId = session?.id

  const selectedSequence: SequenceInfo | undefined = useMemo(
    () => sequences.data?.items.find((s) => s.id === sequenceId),
    [sequences.data, sequenceId],
  )
  const selectedVideo: VideoInfo | undefined = useMemo(
    () => videos.data?.videos.find((v) => v.id === videoId),
    [videos.data, videoId],
  )

  const closeSocket = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.onclose = null
      wsRef.current.close()
      wsRef.current = null
    }
    setConnected(false)
  }, [])

  useEffect(() => () => closeSocket(), [closeSocket])

  const connectSocket = useCallback(
    (replayId: string) => {
      closeSocket()
      const ws = new WebSocket(wsUrl(`/ws/replays/${replayId}`))
      wsRef.current = ws
      ws.onopen = () => setConnected(true)
      ws.onclose = () => setConnected(false)
      ws.onerror = () => setConnected(false)
      ws.onmessage = (msg) => {
        try {
          const payload = JSON.parse(msg.data)
          if (payload.type === 'frame' || payload.type === 'status') {
            const data = payload.data
            if (payload.type === 'status') {
              setSession((prev) => ({ ...(prev ?? ({} as ReplayStatusResponse)), ...data }))
            } else {
              setLive(data as LiveFrame)
              setSession((prev) =>
                prev
                  ? {
                      ...prev,
                      frame_index: data.frame?.index ?? prev.frame_index,
                      frames_emitted: Math.max(prev.frames_emitted ?? 0, data.frame?.index ?? 0),
                    }
                  : prev,
              )
            }
          } else if (payload.type === 'error') {
            setError(new ApiError(0, payload.detail ?? dataError(payload)))
          } else if (typeof payload.type === 'string') {
            setEvents((prev) => [...prev.slice(-199), payload as ReplayEvent])
          }
        } catch {
          /* ignore malformed frames */
        }
      }
    },
    [closeSocket],
  )

  // The websocket is the primary stream, but a polled fallback guarantees the
  // first frame (and any missed frame) is rendered. This was the blank-replay bug.
  useEffect(() => {
    if (!replayId) return
    let cancelled = false
    const tick = async () => {
      try {
        const frame = await api.replayFrame(replayId)
        if (cancelled || !frame.frame) return
        setLive((prev) => ({
          replay_id: replayId,
          frame: frame.frame,
          image_jpeg_base64: frame.image_jpeg_base64 ?? prev?.image_jpeg_base64 ?? null,
          detections: frame.detections,
        }))
        setOriginalJpeg(frame.original_jpeg_base64)
        setSession((prev) =>
          prev ? { ...prev, frame_index: frame.frame?.index ?? prev.frame_index } : prev,
        )
      } catch {
        /* keep the websocket/error state authoritative */
      }
    }
    void tick()
    const timer = window.setInterval(() => void tick(), 1500)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [replayId])

  const start = async () => {
    if (!sequenceId) return
    setBusy(true)
    setError(null)
    setEvents([])
    setLive(null)
    setOriginalJpeg(null)
    try {
      const created = await api.createReplay(sequenceId, undefined, 1)
      setSession(created)
      connectSocket(created.id)
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  const control = async (fn: () => Promise<ReplayStatusResponse>) => {
    try {
      const s = await fn()
      setSession((prev) => ({ ...(prev ?? ({} as ReplayStatusResponse)), ...s }))
    } catch (err) {
      setError(err)
    }
  }

  const step = async (n: number) => {
    if (!session) return
    try {
      const res = await api.stepReplay(session.id, n)
      setSession(res.status)
      const frame = await api.replayFrame(session.id)
      setLive({
        replay_id: session.id,
        frame: frame.frame,
        image_jpeg_base64: frame.image_jpeg_base64,
        detections: frame.detections,
      })
      setOriginalJpeg(frame.original_jpeg_base64)
    } catch (err) {
      setError(err)
    }
  }

  const runAnalysis = async () => {
    if (!videoId) return
    setAnalyzing(true)
    setError(null)
    try {
      const result = await api.analyzeVideo(videoId, {
        sample_every_s: 5,
        max_samples: 120,
        camera_id: selectedVideo?.camera_id ?? undefined,
      })
      setAnalysis(result)
    } catch (err) {
      setError(err)
    } finally {
      setAnalyzing(false)
    }
  }

  const confirmEvents = events.filter(
    (e) => e.type === 'temporal_alert' || e.type === 'incident_created',
  )
  const alerts = session?.alerts_total ?? 0
  const provenance = live?.frame?.provenance ?? session?.provenance

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold text-white">Detection Replay</h1>
        <p className="text-sm text-smoke-400">
          Play registered image sequences through the pipeline, or watch a local video with a
          browser-native player. Detector output is experimental, not confirmed fire evidence.
        </p>
      </div>

      <div className="flex gap-2">
        <button
          onClick={() => setMode('images')}
          className={classNames(
            'inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium',
            mode === 'images'
              ? 'bg-ember-500 text-ink-950'
              : 'border border-ink-600 text-smoke-300 hover:bg-ink-800',
          )}
        >
          <ScanLine className="h-4 w-4" /> Image sequence
        </button>
        <button
          onClick={() => setMode('video')}
          className={classNames(
            'inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium',
            mode === 'video'
              ? 'bg-ember-500 text-ink-950'
              : 'border border-ink-600 text-smoke-300 hover:bg-ink-800',
          )}
        >
          <Film className="h-4 w-4" /> Local video
        </button>
      </div>

      {mode === 'images' ? (
        <Card title="Run a sequence" subtitle="Pick a registered sequence and start a replay session">
          <div className="flex flex-wrap items-end gap-3">
            <label className="min-w-[240px] flex-1">
              <span className="mb-1 block text-xs text-smoke-400">Sequence</span>
              <select
                value={sequenceId}
                onChange={(e) => setChosenSequence(e.target.value)}
                className="w-full rounded-lg border border-ink-600 bg-ink-850 px-3 py-2 text-sm text-white outline-none focus:border-ember-500"
              >
                {sequences.loading && <option>Loading…</option>}
                {sequences.data?.items.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.id} — {s.frame_count} frames ({s.provenance})
                  </option>
                ))}
              </select>
            </label>
            <button
              onClick={start}
              disabled={busy || !sequenceId}
              className="inline-flex items-center gap-2 rounded-lg bg-ember-500 px-4 py-2 text-sm font-medium text-ink-950 transition-colors hover:bg-ember-400 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Play className="h-4 w-4" /> {session ? 'Restart replay' : 'Start replay'}
            </button>
          </div>
          {selectedSequence && (
            <div className="mt-3 flex flex-wrap gap-2 text-xs">
              <Badge>{selectedSequence.frame_count} frames</Badge>
              <Badge>
                {selectedSequence.image_width ?? '?'}×{selectedSequence.image_height ?? '?'}
              </Badge>
              <ProvenanceBadge provenance={selectedSequence.provenance as never} />
              {selectedSequence.camera_id && <Badge>camera {selectedSequence.camera_id}</Badge>}
            </div>
          )}
        </Card>
      ) : (
        <Card
          title="Local video"
          subtitle="HTTP range streaming with the browser's native player (no transcoding)"
        >
          <div className="flex flex-wrap items-end gap-3">
            <label className="min-w-[280px] flex-1">
              <span className="mb-1 block text-xs text-smoke-400">Video under data/videos</span>
              <select
                value={videoId}
                onChange={(e) => {
                  setChosenVideo(e.target.value)
                  setVideoError(null)
                  setAnalysis(null)
                }}
                className="w-full rounded-lg border border-ink-600 bg-ink-850 px-3 py-2 text-sm text-white outline-none focus:border-ember-500"
              >
                {videos.loading && <option>Loading…</option>}
                {!videos.loading && !videos.data?.videos.length && <option>No local videos</option>}
                {videos.data?.videos.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.label}
                  </option>
                ))}
              </select>
            </label>
            <button
              onClick={runAnalysis}
              disabled={analyzing || !videoId}
              className="inline-flex items-center gap-2 rounded-lg border border-ink-600 px-4 py-2 text-sm text-smoke-200 hover:bg-ink-800 disabled:opacity-50"
            >
              <Zap className="h-4 w-4" /> {analyzing ? 'Analyzing…' : 'Run sampled detection'}
            </button>
          </div>

          {selectedVideo && (
            <>
              <div className="mt-3 flex flex-wrap gap-2">
                <Badge>{selectedVideo.width}×{selectedVideo.height}</Badge>
                <Badge>{selectedVideo.fps} fps</Badge>
                <Badge>{selectedVideo.frame_count} frames</Badge>
                <Badge>{selectedVideo.duration_s?.toFixed(2)} s</Badge>
                {selectedVideo.is_time_lapse && <Badge>time-lapse</Badge>}
                <Badge>{selectedVideo.camera_id ?? 'no camera'}</Badge>
              </div>
              <div className="mt-4 overflow-hidden rounded-lg border border-ink-700 bg-black">
                <video
                  key={selectedVideo.id}
                  controls
                  preload="metadata"
                  className="aspect-video w-full bg-black"
                  src={videoStreamUrl(selectedVideo.id)}
                  onError={() =>
                    setVideoError(
                      'The browser could not play this video. The file is H.264/MP4; check browser codec support or stream compatibility.',
                    )
                  }
                >
                  Your browser does not support the video tag.
                </video>
              </div>
              {videoError && <div className="mt-2 text-xs text-red-300">{videoError}</div>}
              <p className="mt-2 text-xs text-smoke-400">{selectedVideo.notes}</p>
            </>
          )}

          {analysis && (
            <div className="mt-4 rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-xs text-amber-100">
              <div className="font-medium">
                Experimental run {analysis.run_id}: {analysis.frames_sampled} frames sampled,{' '}
                {analysis.detections_total} detections
              </div>
              <div className="mt-1 text-amber-100/80">
                Detector {analysis.detector.name} v{analysis.detector.version} (
                {analysis.detector.provenance}
                {analysis.detector.learned ? ', learned' : ', heuristic'}). Timestamp mapping:{' '}
                {analysis.timestamp_mapping}.{' '}
                {analysis.alert_id ? `Alert ${analysis.alert_id} created.` : 'No new alert.'}
              </div>
              <div className="mt-2 flex gap-3">
                <a
                  className="text-amber-200 underline"
                  href={assetUrl(
                    `/videos/${encodeURIComponent(analysis.video_id)}/analyses/${encodeURIComponent(analysis.run_id)}/report`,
                  )}
                >
                  report.md
                </a>
                <a
                  className="text-amber-200 underline"
                  href={assetUrl(
                    `/videos/${encodeURIComponent(analysis.video_id)}/analyses/${encodeURIComponent(analysis.run_id)}/detections.csv`,
                  )}
                >
                  detections.csv
                </a>
              </div>
            </div>
          )}
        </Card>
      )}

      {error != null && (
        <div>
          <ErrorState error={error} />
        </div>
      )}

      {session && mode === 'images' && (
        <>
          <div className="grid gap-5 lg:grid-cols-3">
            <Card
              className="overflow-hidden p-0 lg:col-span-2"
              title={showOriginal ? 'Original frame' : 'Annotated frame'}
              subtitle={
                live?.frame
                  ? `${live.frame.filename} · frame ${live.frame.index}`
                  : 'Waiting for the first frame…'
              }
              actions={
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setShowOriginal((v) => !v)}
                    className="rounded-md border border-ink-600 px-2 py-1 text-[11px] text-smoke-300 hover:bg-ink-800"
                  >
                    {showOriginal ? 'Annotated' : 'Original'}
                  </button>
                  <span
                    className={classNames(
                      'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] ring-1 ring-inset',
                      connected
                        ? 'bg-emerald-500/10 text-emerald-300 ring-emerald-500/30'
                        : 'bg-ink-700/50 text-smoke-300 ring-ink-600/50',
                    )}
                  >
                    <Radio className="h-3 w-3" /> {connected ? 'live' : 'polling'}
                  </span>
                </div>
              }
            >
              <div className="relative bg-black">
                {showOriginal && originalJpeg ? (
                  <img
                    src={`data:image/jpeg;base64,${originalJpeg}`}
                    alt="Original replay frame"
                    className="aspect-video w-full object-contain"
                  />
                ) : live?.image_jpeg_base64 ? (
                  <img
                    src={`data:image/jpeg;base64,${live.image_jpeg_base64}`}
                    alt="Annotated replay frame"
                    className="aspect-video w-full object-contain"
                  />
                ) : (
                  <div className="grid aspect-video w-full place-items-center text-xs text-smoke-400">
                    <div className="flex flex-col items-center gap-2">
                      <ScanLine className="h-6 w-6" />
                      No frame rendered yet — the first frame is being fetched.
                    </div>
                  </div>
                )}
                <div
                  className={classNames(
                    'absolute left-2 top-2 rounded px-2 py-1 text-[10px] font-medium uppercase tracking-wider ring-1',
                    provenance === 'simulated'
                      ? 'bg-black/60 text-violet-200 ring-violet-400/30'
                      : 'bg-black/60 text-emerald-200 ring-emerald-400/30',
                  )}
                >
                  {provenance === 'simulated'
                    ? 'Simulated demo data'
                    : 'Real footage · experimental detector'}
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-2 border-t border-ink-700/60 p-3">
                <button
                  onClick={() => control(() => api.pauseReplay(session.id))}
                  disabled={session.status !== 'running'}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-ink-600 px-3 py-1.5 text-xs text-smoke-300 hover:bg-ink-800 disabled:opacity-40"
                >
                  <Pause className="h-3.5 w-3.5" /> Pause
                </button>
                <button
                  onClick={() => control(() => api.resumeReplay(session.id))}
                  disabled={session.status === 'running'}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-ink-600 px-3 py-1.5 text-xs text-smoke-300 hover:bg-ink-800 disabled:opacity-40"
                >
                  <Play className="h-3.5 w-3.5" /> Resume
                </button>
                <button
                  onClick={() => step(1)}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-ink-600 px-3 py-1.5 text-xs text-smoke-300 hover:bg-ink-800"
                >
                  <StepForward className="h-3.5 w-3.5" /> Step 1
                </button>
                <button
                  onClick={() => step(10)}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-ink-600 px-3 py-1.5 text-xs text-smoke-300 hover:bg-ink-800"
                >
                  <StepForward className="h-3.5 w-3.5" /> Step 10
                </button>
                <button
                  onClick={() => control(() => api.resetReplay(session.id))}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-ink-600 px-3 py-1.5 text-xs text-smoke-300 hover:bg-ink-800"
                >
                  <RotateCcw className="h-3.5 w-3.5" /> Reset
                </button>
                <span className="ml-auto text-xs text-smoke-400">
                  {session.frame_index} / {session.frame_count} · {session.status}
                </span>
              </div>
            </Card>

            <div className="space-y-5">
              <Card title="Session stats">
                <dl className="grid grid-cols-2 gap-3 text-sm">
                  <div>
                    <dt className="text-xs text-smoke-400">Frames emitted</dt>
                    <dd className="text-lg tabular-nums text-white">{session.frames_emitted}</dd>
                  </div>
                  <div>
                    <dt className="text-xs text-smoke-400">Detections</dt>
                    <dd className="text-lg tabular-nums text-white">{session.detections_total}</dd>
                  </div>
                  <div>
                    <dt className="text-xs text-smoke-400">Temporal alerts</dt>
                    <dd className="text-lg tabular-nums text-amber-300">{alerts}</dd>
                  </div>
                  <div>
                    <dt className="text-xs text-smoke-400">Provenance</dt>
                    <dd className="mt-1">
                      <ProvenanceBadge provenance={session.provenance as never} />
                    </dd>
                  </div>
                </dl>
                {live?.frame && (
                  <div className="mt-3 space-y-1 border-t border-ink-800 pt-3 text-xs text-smoke-400">
                    <div>timestamp {formatTimestamp(live.frame.timestamp)}</div>
                    <div>camera {live.frame.camera_id ?? '—'}</div>
                    <div>
                      detector {live.frame.detector_name ?? '—'}{' '}
                      {live.frame.detector_provenance && (
                        <ProvenanceBadge provenance={live.frame.detector_provenance as never} />
                      )}
                    </div>
                    {live.frame.detector_caveat && (
                      <div className="text-amber-300/80">{live.frame.detector_caveat}</div>
                    )}
                  </div>
                )}
              </Card>

              <Card
                title="Detections this frame"
                subtitle={
                  live?.detections?.length
                    ? `${live.detections.length} box(es)`
                    : 'none on the latest frame'
                }
              >
                {live?.detections?.length ? (
                  <ul className="space-y-1.5 text-xs">
                    {live.detections.map((d, i) => {
                      const bbox = d.bbox as { x1: number; y1: number; x2: number; y2: number }
                      return (
                        <li
                          key={i}
                          className="flex items-center justify-between rounded-md bg-ink-800/50 px-2 py-1.5"
                        >
                          <span className="text-smoke-300">
                            [{bbox?.x1.toFixed(0)}, {bbox?.y1.toFixed(0)}] → [
                            {bbox?.x2.toFixed(0)}, {bbox?.y2.toFixed(0)}]
                          </span>
                          <span className="tabular-nums text-sky-300">
                            {((d.confidence as number) ?? 0).toFixed(2)}
                          </span>
                        </li>
                      )
                    })}
                  </ul>
                ) : (
                  <EmptyState
                    title="No detections"
                    icon={<ScanLine className="h-5 w-5 text-smoke-400" />}
                  >
                    Move the replay forward to see the configured detector produce boxes.
                  </EmptyState>
                )}
              </Card>
            </div>
          </div>

          <Card
            title="Pipeline events"
            subtitle={`${events.length} events · ${confirmEvents.length} confirmations`}
            actions={
              <span className="inline-flex items-center gap-1 text-[11px] text-smoke-400">
                <Layers className="h-3 w-3" /> streamed over WebSocket
              </span>
            }
          >
            {events.length ? (
              <ul className="max-h-72 space-y-1 overflow-auto font-mono text-[11px] leading-relaxed">
                {events
                  .slice()
                  .reverse()
                  .map((e, i) => (
                    <li
                      key={i}
                      className={classNames(
                        'flex items-start gap-2 rounded px-2 py-1',
                        e.type === 'temporal_alert'
                          ? 'bg-amber-500/10 text-amber-200'
                          : e.type === 'incident_created'
                            ? 'bg-ember-500/10 text-ember-200'
                            : e.type === 'error'
                              ? 'bg-red-500/10 text-red-200'
                              : 'text-smoke-400',
                      )}
                    >
                      {e.type === 'incident_created' && <Zap className="mt-0.5 h-3 w-3 shrink-0" />}
                      {e.type === 'temporal_alert' && (
                        <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
                      )}
                      <span className="shrink-0 text-smoke-400/70">{e.type}</span>
                      <span className="truncate">
                        {e.message ?? (e.data ? JSON.stringify(e.data).slice(0, 220) : '')}
                      </span>
                    </li>
                  ))}
              </ul>
            ) : (
              <Spinner label="Waiting for pipeline events…" />
            )}
          </Card>
        </>
      )}

      {!session && mode === 'images' && sequences.data && (
        <EmptyState title="No active replay" icon={<Play className="h-6 w-6 text-smoke-400" />}>
          Choose a sequence above and start a replay. Registered real sequences stay labeled real;
          demo sequences stay simulated.
        </EmptyState>
      )}

      {mode === 'video' && !videos.data?.videos.length && !videos.loading && (
        <EmptyState title="No local videos" icon={<VideoIcon className="h-6 w-6 text-smoke-400" />}>
          Add MP4 files under <code>backend/data/videos/</code> (with an optional{' '}
          <code>manifest.json</code>) and reload.
        </EmptyState>
      )}
    </div>
  )
}

function dataError(payload: { data?: Record<string, unknown> }): string {
  return typeof payload.data?.error === 'string' ? payload.data.error : 'Replay error'
}

