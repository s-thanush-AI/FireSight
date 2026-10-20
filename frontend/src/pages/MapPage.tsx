import { useEffect, useMemo, useState } from 'react'
import { CircleMarker, MapContainer, Polyline, Popup, TileLayer, Tooltip, useMap } from 'react-leaflet'
import { Info } from 'lucide-react'
import { api } from '../lib/api'
import { useAsync } from '../lib/hooks'
import { Card, ErrorState, GeometryBadge, ProvenanceBadge, Spinner } from '../components/ui'
import { formatCoord, formatDistance, formatTimestamp } from '../lib/format'

const ORIGIN: [number, number] = [37.2, -119.5]

function FitBounds({ points }: { points: [number, number][] }) {
  const map = useMap()
  useEffect(() => {
    if (!points.length) return
    if (points.length === 1) {
      map.setView(points[0], 12)
      return
    }
    map.fitBounds(points, { padding: [40, 40] })
  }, [map, points])
  return null
}

function destination(lat: number, lon: number, bearingDeg: number, distanceM: number): [number, number] {
  const R = 6371000
  const br = (bearingDeg * Math.PI) / 180
  const lat1 = (lat * Math.PI) / 180
  const lon1 = (lon * Math.PI) / 180
  const dr = distanceM / R
  const lat2 = Math.asin(
    Math.sin(lat1) * Math.cos(dr) + Math.cos(lat1) * Math.sin(dr) * Math.cos(br),
  )
  const lon2 =
    lon1 +
    Math.atan2(
      Math.sin(br) * Math.sin(dr) * Math.cos(lat1),
      Math.cos(dr) - Math.sin(lat1) * Math.sin(lat2),
    )
  return [(lat2 * 180) / Math.PI, (lon2 * 180) / Math.PI]
}

export function MapPage() {
  const geom = useAsync(() => api.geometry(), [], { pollMs: 15000 })
  const [basemap, setBasemap] = useState<'osm' | 'offline'>('osm')

  const points = useMemo<[number, number][]>(() => {
    if (!geom.data) return []
    const pts: [number, number][] = geom.data.cameras.map((c) => [c.latitude, c.longitude])
    for (const t of geom.data.triangulations) {
      if (t.latitude != null && t.longitude != null) pts.push([t.latitude, t.longitude])
    }
    return pts
  }, [geom.data])

  // Group observations by camera to draw rays toward their incident estimate.
  const rays = useMemo(() => {
    if (!geom.data) return []
    const byIncident = new Map<string, { lat: number; lon: number }>()
    for (const t of geom.data.triangulations) {
      if (t.latitude != null && t.longitude != null) {
        byIncident.set(t.incident_id, { lat: t.latitude, lon: t.longitude })
      }
    }
    const camById = new Map(geom.data.cameras.map((c) => [c.id, c]))
    const out: { from: [number, number]; to: [number, number]; cam: string }[] = []
    for (const o of geom.data.observations) {
      const target = o.incident_id ? byIncident.get(o.incident_id) : undefined
      const cam = camById.get(o.camera_id)
      if (!target || !cam) continue
      out.push({
        from: [cam.latitude, cam.longitude],
        to: [target.lat, target.lon],
        cam: cam.id,
      })
    }
    return out
  }, [geom.data])

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold text-white">Geolocation Map</h1>
        <p className="text-sm text-smoke-400">
          Camera positions, detected bearings and least-squares triangulation estimates. All demo
          geometry is computed by the real engine from simulated bearings.
        </p>
      </div>

      {geom.loading && !geom.data ? (
        <Spinner label="Loading geometry…" />
      ) : geom.error ? (
        <ErrorState error={geom.error} retry={geom.reload} />
      ) : (
        <div className="grid gap-5 lg:grid-cols-4">
          <Card className="relative overflow-hidden p-0 lg:col-span-3">
            <div className="pointer-events-none absolute right-3 top-3 z-[500]">
              <div className="pointer-events-auto flex overflow-hidden rounded-lg border border-ink-600 bg-ink-900/95 text-[11px] shadow-lg">
                <button
                  onClick={() => setBasemap('osm')}
                  className={basemap === 'osm' ? 'bg-ember-500 px-2.5 py-1.5 font-medium text-ink-950' : 'px-2.5 py-1.5 text-smoke-300 hover:bg-ink-800'}
                >
                  OpenStreetMap
                </button>
                <button
                  onClick={() => setBasemap('offline')}
                  className={basemap === 'offline' ? 'bg-ember-500 px-2.5 py-1.5 font-medium text-ink-950' : 'px-2.5 py-1.5 text-smoke-300 hover:bg-ink-800'}
                >
                  Offline schematic
                </button>
              </div>
            </div>
            <MapContainer
              center={ORIGIN}
              zoom={12}
              scrollWheelZoom
              className="h-[560px] w-full"
              style={{
                background: '#0a0f16',
                backgroundImage:
                  basemap === 'offline'
                    ? 'linear-gradient(rgba(148,163,184,0.10) 1px, transparent 1px), linear-gradient(90deg, rgba(148,163,184,0.10) 1px, transparent 1px)'
                    : undefined,
                backgroundSize: basemap === 'offline' ? '48px 48px' : undefined,
              }}
            >
              {basemap === 'osm' && (
                <TileLayer
                  attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
                  url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
                  maxZoom={19}
                />
              )}
              <FitBounds points={points} />

              {rays.map((r, i) => (
                <Polyline
                  key={i}
                  positions={[r.from, r.to]}
                  pathOptions={{ color: '#fbbf24', weight: 1.5, opacity: 0.5, dashArray: '5 5' }}
                />
              ))}

              {geom.data?.cameras.map((c) => (
                <CircleMarker
                  key={c.id}
                  center={[c.latitude, c.longitude]}
                  radius={8}
                  pathOptions={{
                    color: '#38bdf8',
                    fillColor: '#0ea5e9',
                    fillOpacity: 0.9,
                    weight: 2,
                  }}
                >
                  <Tooltip direction="top">Camera {c.id}</Tooltip>
                  <Popup>
                    <div className="space-y-1 text-xs">
                      <div className="font-semibold">{c.name}</div>
                      <div>{formatCoord(c.latitude, c.longitude)}</div>
                      <div>heading {c.heading_deg}° · hfov {c.hfov_deg}°</div>
                      <div>calibration: {c.calibration_status}</div>
                      <div>
                        <ProvenanceBadge provenance={c.provenance} />
                      </div>
                    </div>
                  </Popup>
                </CircleMarker>
              ))}

              {geom.data?.triangulations.map((t) =>
                t.latitude != null && t.longitude != null ? (
                  <CircleMarker
                    key={`t-${t.id}`}
                    center={[t.latitude, t.longitude]}
                    radius={7}
                    pathOptions={{
                      color: '#ff6b35',
                      fillColor: '#ff6b35',
                      fillOpacity: 0.85,
                      weight: 2,
                    }}
                  >
                    <Tooltip direction="top">Estimate ±{formatDistance(t.uncertainty_m)}</Tooltip>
                    <Popup>
                      <div className="space-y-1 text-xs">
                        <div className="font-semibold">Triangulated estimate</div>
                        <div>{formatCoord(t.latitude, t.longitude)}</div>
                        <div>uncertainty ± {formatDistance(t.uncertainty_m)}</div>
                        <div>ray separation {t.ray_separation_deg?.toFixed(1)}°</div>
                        <div>
                          <GeometryBadge quality={t.quality} />
                        </div>
                        <div className="text-slate-500">{formatTimestamp(t.created_at)}</div>
                      </div>
                    </Popup>
                  </CircleMarker>
                ) : null,
              )}

              {/* First camera's ray from the camera marker to make direction visible */}
              {geom.data?.cameras.slice(0, 2).map((c, idx) => {
                const end = destination(
                  c.latitude,
                  c.longitude,
                  c.heading_deg,
                  4000 + idx * 500,
                )
                return (
                  <Polyline
                    key={`heading-${c.id}`}
                    positions={[
                      [c.latitude, c.longitude],
                      end,
                    ]}
                    pathOptions={{ color: '#8aa0b6', weight: 1, opacity: 0.4 }}
                  />
                )
              })}
            </MapContainer>
            {basemap === 'offline' && (
              <div className="pointer-events-none absolute bottom-2 left-2 z-[500] rounded bg-black/75 px-2 py-1 text-[10px] text-smoke-300 ring-1 ring-ink-600">
                Offline schematic: geometry only, no map tiles or API key.
              </div>
            )}
          </Card>

          <div className="space-y-4">
            <Card title="Legend">
              <ul className="space-y-2 text-xs text-smoke-300">
                <li className="flex items-center gap-2">
                  <span className="h-3 w-3 rounded-full bg-sky-500" /> Camera position
                </li>
                <li className="flex items-center gap-2">
                  <span className="h-3 w-3 rounded-full bg-ember-500" /> Triangulated estimate
                </li>
                <li className="flex items-center gap-2">
                  <span className="h-0.5 w-5 bg-amber-glow" /> Bearing ray (dashed)
                </li>
                <li className="flex items-center gap-2">
                  <span className="h-0.5 w-5 bg-smoke-400" /> Camera heading
                </li>
              </ul>
            </Card>

            <Card title="Triangulations" subtitle={`${geom.data?.triangulations.length ?? 0} stored`}>
              {geom.data?.triangulations.length ? (
                <ul className="space-y-2 text-xs">
                  {geom.data.triangulations.slice(0, 8).map((t) => (
                    <li key={t.id} className="rounded-md bg-ink-800/50 px-2 py-1.5">
                      <div className="flex items-center justify-between">
                        <span className="font-mono text-[10px] text-smoke-400">
                          {t.incident_id.slice(-6)}
                        </span>
                        <GeometryBadge quality={t.quality} />
                      </div>
                      <div className="mt-1 text-smoke-300">{formatCoord(t.latitude, t.longitude)}</div>
                      <div className="text-smoke-400">± {formatDistance(t.uncertainty_m)}</div>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-xs text-smoke-400">
                  No triangulations yet. Run both demo replays so two cameras observe the same
                  event.
                </p>
              )}
            </Card>

            <div className="rounded-lg border border-ink-700/70 bg-ink-900/50 px-3 py-2 text-[11px] leading-relaxed text-smoke-400">
              <div className="mb-1 flex items-center gap-1 text-smoke-300">
                <Info className="h-3 w-3" /> Assumptions
              </div>
              Bearings are degrees clockwise from true north. Uncertainty is derived from assumed
              pixel and heading noise — treat locations as estimates, not measurements.
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
