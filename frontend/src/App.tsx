import { lazy, Suspense, useCallback, useMemo } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { AppContext } from './lib/app-context'
import { api } from './lib/api'
import { Spinner } from './components/ui'
import { useAsync } from './lib/hooks'

const OverviewPage = lazy(() => import('./pages/OverviewPage').then((m) => ({ default: m.OverviewPage })))
const ReplayPage = lazy(() => import('./pages/ReplayPage').then((m) => ({ default: m.ReplayPage })))
const LiveSourcesPage = lazy(() =>
  import('./pages/LiveSourcesPage').then((m) => ({ default: m.LiveSourcesPage })),
)
const AlertsPage = lazy(() => import('./pages/AlertsPage').then((m) => ({ default: m.AlertsPage })))
const MapPage = lazy(() => import('./pages/MapPage').then((m) => ({ default: m.MapPage })))
const IncidentsPage = lazy(() =>
  import('./pages/IncidentsPage').then((m) => ({ default: m.IncidentsPage })),
)
const IncidentDetailPage = lazy(() =>
  import('./pages/IncidentDetailPage').then((m) => ({ default: m.IncidentDetailPage })),
)
const CamerasPage = lazy(() => import('./pages/CamerasPage').then((m) => ({ default: m.CamerasPage })))
const EvaluationPage = lazy(() =>
  import('./pages/EvaluationPage').then((m) => ({ default: m.EvaluationPage })),
)
const ModelsPage = lazy(() => import('./pages/ModelsPage').then((m) => ({ default: m.ModelsPage })))
const DatasetsPage = lazy(() =>
  import('./pages/DatasetsPage').then((m) => ({ default: m.DatasetsPage })),
)
const SystemPage = lazy(() => import('./pages/SystemPage').then((m) => ({ default: m.SystemPage })))

export default function App() {
  const { data, loading, error, reload } = useAsync(() => api.status(), [], { pollMs: 15000 })

  const value = useMemo(
    () => ({ status: data, loading, error, reload }),
    [data, loading, error, reload],
  )

  const guardedReload = useCallback(() => void reload(), [reload])

  return (
    <AppContext.Provider value={{ ...value, reload: guardedReload }}>
      <Suspense
        fallback={
          <div className="grid min-h-screen place-items-center bg-ink-950">
            <Spinner label="Loading FireSight…" />
          </div>
        }
      >
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<OverviewPage />} />
            <Route path="replay" element={<ReplayPage />} />
            <Route path="live" element={<LiveSourcesPage />} />
            <Route path="alerts" element={<AlertsPage />} />
            <Route path="map" element={<MapPage />} />
            <Route path="incidents" element={<IncidentsPage />} />
            <Route path="incidents/:id" element={<IncidentDetailPage />} />
            <Route path="cameras" element={<CamerasPage />} />
            <Route path="evaluation" element={<EvaluationPage />} />
            <Route path="models" element={<ModelsPage />} />
            <Route path="datasets" element={<DatasetsPage />} />
            <Route path="status" element={<SystemPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </Suspense>
    </AppContext.Provider>
  )
}
