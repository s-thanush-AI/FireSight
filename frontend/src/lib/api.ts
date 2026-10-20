/**
 * FireSight typed API client.
 *
 * This is the ONLY module that talks to the backend. All fetches go through
 * `request()` so base-URL handling, error shaping and JSON parsing stay in one
 * place. Never put API keys or secrets here — the backend never returns them
 * and the frontend never needs them.
 */

export type Provenance = 'real' | 'predicted' | 'simulated' | 'heuristic' | 'manual'
export type IncidentStatus =
  | 'candidate'
  | 'confirmed'
  | 'reviewed'
  | 'acknowledged'
  | 'dismissed'
export type GeometryQuality = 'strong' | 'moderate' | 'weak' | 'unavailable'
export type SeverityTier = 'info' | 'low' | 'medium' | 'high' | 'critical'
export type VlmAssessment = 'likely_smoke' | 'uncertain' | 'likely_not_smoke'
export type ReplayStatus = 'idle' | 'running' | 'paused' | 'finished' | 'error'

export interface HealthResponse {
  status: string
  version: string
  mode: 'demo' | 'real'
}

export interface DetectorInfo {
  name: string
  version: string
  available: boolean
  unavailable_reason: string | null
  provenance: string | null
  kind: string
  confidence_threshold: number
  iou_threshold: number
  image_size: number
  device: string
  weights_path: string | null
}

export interface VlmInfo {
  configured: boolean
  provider: string
  model: string | null
  base_url: string | null
  api_key_present: boolean
}

export interface StatusResponse {
  mode: 'demo' | 'real'
  version: string
  demo_banner: boolean
  detector: DetectorInfo
  vlm: VlmInfo
  active_replays: number
  incidents_by_status: Record<string, number>
  cameras: number
  sequences: number
  simulated_data_notice: string
}

export interface ConfigResponse {
  settings: Record<string, unknown>
  overrides: Record<string, unknown>
  configurable_keys: string[]
}

export interface Camera {
  id: string
  name: string
  latitude: number
  longitude: number
  height_m: number
  heading_deg: number
  hfov_deg: number
  image_width: number
  image_height: number
  calibration_status: 'uncalibrated' | 'approximate' | 'calibrated' | 'simulated'
  calibration_source: string | null
  calibration_uncertainty_deg: number | null
  provenance: Provenance
  notes: string | null
}

export interface SequenceInfo {
  id: string
  name: string
  dataset: string
  dataset_provenance: string
  frame_count: number
  image_width: number | null
  image_height: number | null
  start_ts: string | null
  end_ts: string | null
  provenance: string
  camera_id: string | null
  synthetic?: boolean
  root_path?: string
}

export interface ReplayStatusResponse {
  id: string
  sequence_id: string
  camera_id: string | null
  status: ReplayStatus
  speed: number
  frame_index: number
  frame_count: number
  frames_emitted: number
  detections_total: number
  alerts_total: number
  mode: string
  provenance: string
  error: string | null
  created_at: string | null
}

export interface ReplayFrame {
  index: number
  filename: string
  timestamp: string
  width: number
  height: number
  camera_id: string | null
  sequence_id: string
  provenance: string
}

export interface ReplayFrameResponse {
  replay_id: string
  frame: ReplayFrame | null
  image_jpeg_base64: string | null
  original_jpeg_base64: string | null
  detections: Record<string, unknown>[]
  events: Record<string, unknown>[]
}

export interface VideoInfo {
  id: string
  filename: string
  size_bytes: number
  fps: number
  frame_count: number
  width: number
  height: number
  duration_s: number | null
  label: string
  is_time_lapse: boolean
  camera_id: string | null
  capture_start_utc: string | null
  capture_end_utc: string | null
  source_archive: string | null
  notes: string
  stream_url: string
}

export interface VideoAnalysis {
  run_id: string
  video_id: string
  video: VideoInfo
  camera_id: string | null
  created_at: string
  detector: {
    name: string
    version: string
    provenance: string
    kind: string
    learned: boolean
    caveat: string | null
  }
  sample_every_s: number
  frames_sampled: number
  detections_total: number
  max_confidence: number
  first_detection_video_time_s: number | null
  alert_id: string | null
  verification_status: string
  timestamp_mapping: string
  notes: string[]
  output_dir: string
}

export interface AnalysisRun {
  id: string
  video_id: string
  created_at: string
  sample_every_s: number
  detector_name: string
  frames_sampled: number
  detections_total: number
  report_url: string
  csv_url: string
}

export interface AlertRecord {
  id: string
  source_type: string
  source_id: string | null
  camera_id: string | null
  event_time: string
  created_at: string
  detector_name: string
  detector_version: string | null
  confidence: number | null
  severity: string
  status: 'new' | 'acknowledged' | 'resolved'
  verification_status: string
  frame_ref: string | null
  evidence_path: string | null
  notes: string | null
  acknowledged_at: string | null
  resolved_at: string | null
}

export interface LiveSource {
  id: string
  name: string
  kind: 'rtsp' | 'file'
  target: string
  camera_id: string | null
  sample_fps: number
  threshold: number
  loop: boolean
  status: 'idle' | 'starting' | 'running' | 'reconnecting' | 'stalled' | 'finished' | 'stopped' | 'error'
  error: string | null
  last_frame_at: string | null
  frames_read: number
  frames_processed: number
  detections_total: number
  has_frame: boolean
  experimental: boolean
  frame_url: string
  stream_url: string
}

export interface BBox {
  x1: number
  y1: number
  x2: number
  y2: number
}

export interface Detection {
  camera_id: string | null
  sequence_id: string
  frame_index: number
  timestamp: string | null
  bbox: BBox
  confidence: number
  label: string
  provenance: Provenance
  detector_name: string
  detector_version: string
}

export interface IncidentSummary {
  id: string
  status: IncidentStatus
  severity_tier: SeverityTier
  title: string
  summary: string | null
  provenance: Provenance
  mode: string
  latitude: number | null
  longitude: number | null
  location_uncertainty_m: number | null
  geometry_quality: GeometryQuality | null
  vlm_assessment: VlmAssessment | null
  first_seen_ts: string | null
  created_at: string
}

export interface IncidentListResponse {
  items: IncidentSummary[]
  total: number
  limit: number
  offset: number
}

export interface Observation {
  id: number
  incident_id: string
  camera_id: string
  bearing_deg: number
  timestamp: string | null
  pixel_x: number | null
  pixel_y: number | null
  proxy_kind: string | null
  confidence: number | null
  evidence_type: string
  provenance: Provenance
  replay_id: string | null
  created_at: string
}

export interface Triangulation {
  id: number
  incident_id: string
  latitude: number | null
  longitude: number | null
  uncertainty_m: number | null
  ray_separation_deg: number | null
  intersection_angle_deg: number | null
  fit_residual_m: number | null
  quality: GeometryQuality
  method: string
  provenance: Provenance
  created_at: string
}

export interface StatusHistoryEntry {
  id: number
  incident_id: string
  from_status: string | null
  to_status: string
  action: string
  actor: string
  reason: string | null
  created_at: string
}

export interface VlmVerificationRow {
  id: number
  incident_id: string
  provider: string
  model_id: string | null
  request_time: string
  assessment: VlmAssessment | null
  visual_evidence: string | null
  alternative_explanations: string | null
  limitations: string | null
  recommended_next_action: string | null
  model_confidence: number | null
  provenance: Provenance
  status: string
  error: string | null
  duration_ms: number | null
}

export interface IncidentDetail {
  incident: IncidentSummary & { source_dataset?: string | null }
  observations: Observation[]
  triangulations: Triangulation[]
  history: StatusHistoryEntry[]
  vlm_verifications: VlmVerificationRow[]
  frames: Record<string, unknown>[]
}

export interface VerificationResponse {
  incident_id: string
  provider: string
  model_id: string | null
  status: string
  assessment: VlmAssessment | null
  visual_evidence: string | null
  alternative_explanations: string | null
  limitations: string | null
  recommended_next_action: string | null
  model_confidence: number | null
  error: string | null
  provenance: Provenance
  request_time: string
  duration_ms: number | null
}

export interface VerificationListResponse {
  items: VlmVerificationRow[]
  total: number
  provider: string
  provenance_notice: string
  simulated_default: boolean
}

export interface MetricRow {
  id: number
  run_id: string
  name: string
  value: number | null
  unit: string | null
  sample_count: number | null
  data_source: string | null
  ground_truth_available: number
  valid: number
  limitation: string | null
  created_at: string
}

export interface EvalRun {
  id: string
  name: string
  kind: string
  created_at: string
  metrics: MetricRow[]
}

export interface EvalRunsResponse {
  items: EvalRun[]
  total: number
}

export interface MetricsOverview {
  latest: EvalRun | null
  runs_count: number
  definitions: Record<string, string>
  honesty_notice: string
}

export interface GeometryResponse {
  cameras: Camera[]
  observations: Observation[]
  triangulations: Triangulation[]
  notice: string
  conventions: Record<string, unknown>
}

export interface ModelsResponse {
  detectors: (DetectorInfo & { active: boolean })[]
  vlm: {
    provider: string
    configured: boolean
    model: string | null
    base_url: string | null
    api_key_present: boolean
    note: string
  }
  training: { available: boolean; command: string; note: string }
}

export interface DatasetsResponse {
  registered: (SequenceInfo & { synthetic?: boolean })[]
  data_root: string
  data_root_exists: boolean
  local_dirs_not_registered: { name: string; path: string }[]
  docs: Record<string, string>
}

export interface RegisteredSequence {
  id: string
  name: string
  root_path: string
  frame_count: number
  image_width: number | null
  image_height: number | null
  start_ts: string | null
  end_ts: string | null
  timestamps_available: boolean
  camera_id: string | null
  provenance: string
  synthetic: boolean
  warnings: string[]
}

export interface DetectionInferenceResponse {
  sequence_id: string
  frame_index: number
  filename: string
  detections: Detection[]
  detector: DetectorInfo
  annotated_jpeg_base64: string | null
  provenance: string
  notice: string
}

export interface ReplayEvent {
  type: string
  replay_id?: string
  ts?: string
  message?: string
  data?: Record<string, unknown>
}

export class ApiError extends Error {
  status: number
  detail: string
  constructor(status: number, detail: string) {
    super(detail)
    this.status = status
    this.detail = detail
    this.name = 'ApiError'
  }
}

const API_BASE = (import.meta.env.VITE_API_BASE ?? '/api/v1').replace(/\/$/, '')

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${API_BASE}${path}`, {
      headers: { 'content-type': 'application/json', ...(init?.headers ?? {}) },
      ...init,
    })
  } catch (err) {
    throw new ApiError(0, `Cannot reach the FireSight API. Is the backend running? (${err})`)
  }
  const text = await res.text()
  let body: unknown = null
  if (text) {
    try {
      body = JSON.parse(text)
    } catch {
      body = text
    }
  }
  if (!res.ok) {
    const detail =
      body && typeof body === 'object' && 'detail' in body
        ? String((body as { detail: unknown }).detail)
        : `Request failed with status ${res.status}`
    throw new ApiError(res.status, detail)
  }
  return body as T
}

function qs(params: Record<string, string | number | boolean | undefined | null>): string {
  const entries = Object.entries(params).filter(([, v]) => v !== undefined && v !== null)
  if (!entries.length) return ''
  return '?' + entries.map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`).join('&')
}

export const api = {
  health: () => request<HealthResponse>('/health'),
  status: () => request<StatusResponse>('/status'),
  config: () => request<ConfigResponse>('/config'),
  updateConfig: (values: Record<string, unknown>) =>
    request<ConfigResponse>('/config', { method: 'PUT', body: JSON.stringify({ values }) }),

  models: () => request<ModelsResponse>('/models'),

  sequences: () => request<{ items: SequenceInfo[]; total: number }>('/sequences'),
  sequence: (id: string) =>
    request<SequenceInfo & { first_frames?: unknown[]; discovery_error?: string }>(
      `/sequences/${encodeURIComponent(id)}`,
    ),

  datasets: () => request<DatasetsResponse>('/datasets'),
  inspectDataset: (path: string, name?: string) =>
    request<Record<string, unknown>>('/datasets/inspect', {
      method: 'POST',
      body: JSON.stringify({ path, name }),
    }),
  registerSequence: (body: {
    id: string
    root_path: string
    name?: string
    camera_id?: string
  }) =>
    request<RegisteredSequence>('/sequences', {
      method: 'POST',
      body: JSON.stringify({ ...body, provenance: 'real' }),
    }),

  replays: () => request<{ items: ReplayStatusResponse[]; total: number }>('/replays'),
  createReplay: (sequence_id: string, camera_id?: string, speed?: number) =>
    request<ReplayStatusResponse>('/replays', {
      method: 'POST',
      body: JSON.stringify({ sequence_id, camera_id, speed }),
    }),
  replay: (id: string) => request<ReplayStatusResponse>(`/replays/${encodeURIComponent(id)}`),
  pauseReplay: (id: string) =>
    request<ReplayStatusResponse>(`/replays/${encodeURIComponent(id)}/pause`, { method: 'POST' }),
  resumeReplay: (id: string) =>
    request<ReplayStatusResponse>(`/replays/${encodeURIComponent(id)}/resume`, { method: 'POST' }),
  resetReplay: (id: string) =>
    request<ReplayStatusResponse>(`/replays/${encodeURIComponent(id)}/reset`, { method: 'POST' }),
  stepReplay: (id: string, n = 1) =>
    request<{ replay_id: string; frame: ReplayFrame | null; status: ReplayStatusResponse }>(
      `/replays/${encodeURIComponent(id)}/step${qs({ n })}`,
      { method: 'POST' },
    ),
  videos: () => request<{ videos: VideoInfo[]; count: number; notice: string }>('/videos'),
  video: (id: string) => request<VideoInfo>(`/videos/${encodeURIComponent(id)}`),
  analyzeVideo: (
    id: string,
    body: { sample_every_s?: number; threshold?: number; camera_id?: string; max_samples?: number },
  ) =>
    request<VideoAnalysis>(`/videos/${encodeURIComponent(id)}/analyze`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  videoAnalyses: (id: string) =>
    request<{ analyses: AnalysisRun[]; count: number }>(
      `/videos/${encodeURIComponent(id)}/analyses`,
    ),

  alerts: (params: { status?: string; source_type?: string; limit?: number } = {}) =>
    request<{ alerts: AlertRecord[]; count: number; notice: string }>(`/alerts${qs(params)}`),
  alertStats: () =>
    request<{ total: number; new: number; acknowledged: number; resolved: number; notice: string }>(
      '/alerts/stats',
    ),
  acknowledgeAlert: (id: string) =>
    request<AlertRecord>(`/alerts/${encodeURIComponent(id)}/acknowledge`, { method: 'POST' }),
  resolveAlert: (id: string) =>
    request<AlertRecord>(`/alerts/${encodeURIComponent(id)}/resolve`, { method: 'POST' }),

  liveSources: () =>
    request<{
      sources: LiveSource[]
      stats: { total: number; running: number }
      notice: string
    }>('/live/sources'),
  createLiveSource: (body: {
    name: string
    kind: 'rtsp' | 'file'
    url?: string
    path?: string
    camera_id?: string
    sample_fps?: number
    threshold?: number
    loop?: boolean
    min_consecutive?: number
  }) =>
    request<LiveSource>('/live/sources', { method: 'POST', body: JSON.stringify(body) }),
  stopLiveSource: (id: string) =>
    request<LiveSource>(`/live/sources/${encodeURIComponent(id)}/stop`, { method: 'POST' }),
  deleteLiveSource: (id: string) =>
    request<null>(`/live/sources/${encodeURIComponent(id)}`, { method: 'DELETE' }),

  replayFrame: (id: string) =>
    request<ReplayFrameResponse>(`/replays/${encodeURIComponent(id)}/frames/current`),
  replayEvents: (id: string, since = 0) =>
    request<{ events: ReplayEvent[]; total: number }>(
      `/replays/${encodeURIComponent(id)}/events${qs({ since })}`,
    ),

  incidents: (params: {
    status?: string
    provenance?: string
    severity?: string
    source?: string
    search?: string
    sort?: string
    limit?: number
    offset?: number
  } = {}) => request<IncidentListResponse>(`/incidents${qs(params)}`),
  incident: (id: string) => request<IncidentDetail>(`/incidents/${encodeURIComponent(id)}`),
  patchIncident: (id: string, action: string, reason?: string) =>
    request<IncidentSummary>(`/incidents/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      body: JSON.stringify({ action, reason }),
    }),
  report: (id: string) => request<Record<string, unknown>>(`/reports/${encodeURIComponent(id)}`),

  cameras: () => request<{ items: Camera[]; total: number; notice: string }>('/cameras'),
  camera: (id: string) => request<Camera>(`/cameras/${encodeURIComponent(id)}`),
  createCamera: (cam: Partial<Camera>) =>
    request<Camera>('/cameras', { method: 'POST', body: JSON.stringify(cam) }),
  updateCamera: (id: string, cam: Partial<Camera>) =>
    request<Camera>(`/cameras/${encodeURIComponent(id)}`, {
      method: 'PUT',
      body: JSON.stringify(cam),
    }),

  geometry: () => request<GeometryResponse>('/geometry'),

  metrics: () => request<MetricsOverview>('/evaluation/metrics'),
  evalRuns: () => request<EvalRunsResponse>('/evaluation/runs'),
  evalRun: (id: string) => request<EvalRun>(`/evaluation/runs/${encodeURIComponent(id)}`),
  runEvaluation: (name: string, kind = 'demo_fixture') =>
    request<{ run_id: string; created_at: string; metric_count: number; kind: string; provenance: string }>(
      '/evaluation/runs',
      { method: 'POST', body: JSON.stringify({ name, kind }) },
    ),

  verifyIncident: (id: string) =>
    request<VerificationResponse>(`/verification/${encodeURIComponent(id)}`, { method: 'POST' }),
  verifications: (id: string) =>
    request<VerificationListResponse>(`/verification/${encodeURIComponent(id)}`),

  inference: (sequence_id: string, frame_index: number, camera_id?: string) =>
    request<DetectionInferenceResponse>('/inference', {
      method: 'POST',
      body: JSON.stringify({ sequence_id, frame_index, camera_id }),
    }),
}

export function assetUrl(path: string): string {
  if (/^https?:\/\//.test(path)) return path
  if (path.startsWith('/api/')) {
    const base = API_BASE.startsWith('http') ? API_BASE.replace(/\/api\/v1$/, '') : ''
    return `${base}${path}`
  }
  return `${API_BASE}${path}`
}

export function evidenceUrl(id: string): string {
  return assetUrl(`/alerts/${encodeURIComponent(id)}/evidence`)
}

export function liveFrameUrl(id: string): string {
  return assetUrl(`/live/sources/${encodeURIComponent(id)}/frame`)
}

export function liveStreamUrl(id: string): string {
  return assetUrl(`/live/sources/${encodeURIComponent(id)}/stream`)
}

export function videoStreamUrl(id: string): string {
  return assetUrl(`/videos/${encodeURIComponent(id)}/stream`)
}

export function wsUrl(path: string): string {
  const base = API_BASE.startsWith('http')
    ? API_BASE
    : `${window.location.protocol}//${window.location.host}${API_BASE}`
  return base.replace(/^http/, 'ws') + path
}
