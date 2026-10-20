import { useState } from 'react'
import { Camera as CameraIcon, Plus, Save, X } from 'lucide-react'
import { api } from '../lib/api'
import type { Camera } from '../lib/api'
import { useAsync } from '../lib/hooks'
import { Badge, Card, ErrorState, ProvenanceBadge, Spinner } from '../components/ui'
import { formatCoord } from '../lib/format'

const EMPTY: Partial<Camera> = {
  id: '',
  name: '',
  latitude: 0,
  longitude: 0,
  height_m: 10,
  heading_deg: 0,
  hfov_deg: 60,
  image_width: 1920,
  image_height: 1080,
  calibration_status: 'uncalibrated',
  calibration_uncertainty_deg: null,
  calibration_source: null,
  provenance: 'manual',
  notes: '',
}

export function CamerasPage() {
  const cameras = useAsync(() => api.cameras(), [])
  const [editing, setEditing] = useState<Partial<Camera> | null>(null)
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState<unknown>(null)

  const save = async () => {
    if (!editing) return
    setError(null)
    try {
      if (creating) await api.createCamera(editing)
      else await api.updateCamera(editing.id as string, editing)
      setEditing(null)
      setCreating(false)
      cameras.reload()
    } catch (err) {
      setError(err)
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-lg font-semibold text-white">Cameras</h1>
          <p className="text-sm text-smoke-400">
            Fixed observation cameras. Calibrated status and uncertainty drive geolocation quality.
          </p>
        </div>
        <button
          onClick={() => {
            setEditing({ ...EMPTY })
            setCreating(true)
          }}
          className="inline-flex items-center gap-1.5 rounded-lg bg-ember-500 px-3 py-2 text-sm font-medium text-ink-950 hover:bg-ember-400"
        >
          <Plus className="h-4 w-4" /> Add camera
        </button>
      </div>

      {cameras.data?.notice && (
        <div className="rounded-lg border border-ink-700/70 bg-ink-900/50 px-3 py-2 text-xs text-smoke-400">
          {cameras.data.notice}
        </div>
      )}

      {error != null && <ErrorState error={error} />}

      {editing && (
        <Card
          title={creating ? 'New camera' : `Edit ${editing.id}`}
          actions={
            <button onClick={() => setEditing(null)} className="text-smoke-400 hover:text-white">
              <X className="h-4 w-4" />
            </button>
          }
        >
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {(
              [
                ['id', 'ID (a-z, 0-9, -, _)', 'text'],
                ['name', 'Name', 'text'],
                ['latitude', 'Latitude', 'number'],
                ['longitude', 'Longitude', 'number'],
                ['height_m', 'Height (m)', 'number'],
                ['heading_deg', 'Heading (deg)', 'number'],
                ['hfov_deg', 'HFOV (deg)', 'number'],
                ['image_width', 'Image width', 'number'],
                ['image_height', 'Image height', 'number'],
              ] as const
            ).map(([key, label, type]) => (
              <label key={key}>
                <span className="mb-1 block text-xs text-smoke-400">{label}</span>
                <input
                  type={type}
                  value={String(editing[key] ?? '')}
                  disabled={!creating && key === 'id'}
                  onChange={(e) =>
                    setEditing({
                      ...editing,
                      [key]: type === 'number' ? Number(e.target.value) : e.target.value,
                    })
                  }
                  className="w-full rounded-lg border border-ink-600 bg-ink-850 px-3 py-2 text-sm text-white outline-none focus:border-ember-500 disabled:opacity-60"
                />
              </label>
            ))}
            <label>
              <span className="mb-1 block text-xs text-smoke-400">Calibration status</span>
              <select
                value={editing.calibration_status}
                onChange={(e) =>
                  setEditing({ ...editing, calibration_status: e.target.value as Camera['calibration_status'] })
                }
                className="w-full rounded-lg border border-ink-600 bg-ink-850 px-3 py-2 text-sm text-white outline-none focus:border-ember-500"
              >
                {['uncalibrated', 'approximate', 'calibrated', 'simulated'].map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span className="mb-1 block text-xs text-smoke-400">Calibration source</span>
              <input
                value={String(editing.calibration_source ?? '')}
                onChange={(e) =>
                  setEditing({ ...editing, calibration_source: e.target.value || null })
                }
                placeholder="required when 'calibrated'"
                className="w-full rounded-lg border border-ink-600 bg-ink-850 px-3 py-2 text-sm text-white outline-none focus:border-ember-500"
              />
            </label>
            <label>
              <span className="mb-1 block text-xs text-smoke-400">Calibration uncertainty (deg)</span>
              <input
                type="number"
                step="0.1"
                value={editing.calibration_uncertainty_deg ?? ''}
                onChange={(e) =>
                  setEditing({
                    ...editing,
                    calibration_uncertainty_deg: e.target.value === '' ? null : Number(e.target.value),
                  })
                }
                className="w-full rounded-lg border border-ink-600 bg-ink-850 px-3 py-2 text-sm text-white outline-none focus:border-ember-500"
              />
            </label>
          </div>
          <div className="mt-4">
            <button
              onClick={save}
              className="inline-flex items-center gap-1.5 rounded-lg bg-ember-500 px-4 py-2 text-sm font-medium text-ink-950 hover:bg-ember-400"
            >
              <Save className="h-4 w-4" /> Save camera
            </button>
          </div>
        </Card>
      )}

      {cameras.loading && !cameras.data ? (
        <Spinner />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {cameras.data?.items.map((c) => (
            <Card
              key={c.id}
              title={
                <span className="flex items-center gap-2">
                  <CameraIcon className="h-4 w-4 text-sky-300" /> {c.name}
                </span>
              }
              subtitle={c.id}
              actions={
                <button
                  onClick={() => {
                    setEditing({ ...c })
                    setCreating(false)
                  }}
                  className="text-xs text-ember-400 hover:text-ember-500"
                >
                  edit
                </button>
              }
            >
              <dl className="space-y-1.5 text-xs">
                <div className="flex justify-between">
                  <dt className="text-smoke-400">Position</dt>
                  <dd className="text-smoke-200">{formatCoord(c.latitude, c.longitude, 4)}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-smoke-400">Heading / HFOV</dt>
                  <dd className="text-smoke-200">
                    {c.heading_deg}° / {c.hfov_deg}°
                  </dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-smoke-400">Resolution</dt>
                  <dd className="text-smoke-200">
                    {c.image_width}×{c.image_height}
                  </dd>
                </div>
                <div className="flex items-center justify-between">
                  <dt className="text-smoke-400">Calibration</dt>
                  <dd>
                    <Badge
                      className={
                        c.calibration_status === 'calibrated'
                          ? 'bg-emerald-500/15 text-emerald-300 ring-emerald-500/30'
                          : c.calibration_status === 'simulated'
                            ? 'bg-violet-500/15 text-violet-300 ring-violet-500/30'
                            : 'bg-amber-500/15 text-amber-300 ring-amber-500/30'
                      }
                    >
                      {c.calibration_status}
                    </Badge>
                  </dd>
                </div>
                <div className="flex items-center justify-between">
                  <dt className="text-smoke-400">Provenance</dt>
                  <dd>
                    <ProvenanceBadge provenance={c.provenance} />
                  </dd>
                </div>
              </dl>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
