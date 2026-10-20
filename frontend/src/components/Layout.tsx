import { useEffect, useState } from 'react'
import { Link, NavLink, Outlet } from 'react-router-dom'
import { Bell, Radar } from 'lucide-react'
import { wsUrl, type AlertRecord } from '../lib/api'
import { navItems } from './nav'
import { classNames } from '../lib/format'
import { DemoBanner, Spinner } from './ui'
import { useApp } from '../lib/app-context'

export function Layout() {
  const { status, loading, error } = useApp()

  return (
    <div className="flex min-h-screen bg-ink-950 text-slate-100">
      <aside className="sticky top-0 hidden h-screen w-64 shrink-0 flex-col border-r border-ink-800 bg-ink-900/60 px-3 py-4 md:flex">
        <div className="flex items-center gap-2 px-2 pb-4">
          <span className="grid h-9 w-9 place-items-center rounded-lg bg-gradient-to-br from-ember-500 to-amber-glow shadow-lg shadow-ember-500/20">
            <Radar className="h-5 w-5 text-ink-950" />
          </span>
          <div className="leading-tight">
            <div className="text-sm font-semibold tracking-wide">FireSight</div>
            <div className="text-[11px] text-smoke-400">research prototype</div>
          </div>
        </div>

        <nav className="flex-1 space-y-0.5">
          {navItems.map(({ to, label, icon: Icon, hint }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              title={hint}
              className={({ isActive }) =>
                classNames(
                  'flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition-colors',
                  isActive
                    ? 'bg-ember-500/15 text-ember-400 ring-1 ring-inset ring-ember-500/25'
                    : 'text-smoke-300 hover:bg-ink-800/70 hover:text-white',
                )
              }
            >
              <Icon className="h-4 w-4" />
              {label}
            </NavLink>
          ))}
        </nav>

        <div className="border-t border-ink-800 px-2 pt-3 text-[11px] text-smoke-400">
          <div className="flex items-center justify-between">
            <span>mode</span>
            <span
              className={classNames(
                'rounded px-1.5 py-0.5 font-medium',
                status?.mode === 'real'
                  ? 'bg-sky-500/15 text-sky-300'
                  : 'bg-violet-500/15 text-violet-300',
              )}
            >
              {status?.mode ?? '…'}
            </span>
          </div>
          <div className="mt-1 flex items-center justify-between">
            <span>version</span>
            <span className="font-mono">{status?.version ?? '—'}</span>
          </div>
          <p className="mt-2 leading-snug text-smoke-400/80">
            Not an operational warning service.
          </p>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 border-b border-ink-800 bg-ink-950/85 px-4 py-3 backdrop-blur md:px-6">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2 md:hidden">
              <Radar className="h-5 w-5 text-ember-500" />
              <span className="text-sm font-semibold">FireSight</span>
            </div>
            <div className="hidden text-xs text-smoke-400 md:block">
              Wildfire smoke detection &amp; geolocation — demonstration build
            </div>
            <div className="flex items-center gap-3 text-xs text-smoke-400">
              {loading && !status ? (
                <Spinner label="Connecting…" />
              ) : status ? (
                <>
                  <span className="hidden sm:inline">
                    cameras <strong className="text-smoke-300">{status.cameras}</strong>
                  </span>
                  <span className="hidden sm:inline">
                    sequences <strong className="text-smoke-300">{status.sequences}</strong>
                  </span>
                  <span
                    className={classNames(
                      'inline-flex items-center gap-1 rounded-full px-2 py-0.5 ring-1 ring-inset',
                      status.detector.available
                        ? 'bg-emerald-500/10 text-emerald-300 ring-emerald-500/30'
                        : 'bg-red-500/10 text-red-300 ring-red-500/30',
                    )}
                    title={status.detector.unavailable_reason ?? undefined}
                  >
                    detector {status.detector.available ? 'ready' : 'unavailable'}
                  </span>
                </>
              ) : (
                <span className="text-red-300">API unreachable</span>
              )}
            </div>
          </div>
        </header>

        <main className="mx-auto w-full max-w-[1400px] flex-1 px-4 py-5 md:px-6">
          {error && !status ? (
            <div className="mb-4 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">
              Could not load FireSight status. Start the backend with{' '}
              <code className="rounded bg-black/30 px-1">./scripts/dev.sh</code> or{' '}
              <code className="rounded bg-black/30 px-1">cd backend &amp;&amp; uv run firesight serve</code>.
            </div>
          ) : (
            <div className="mb-4">
              <DemoBanner notice={status?.simulated_data_notice} mode={status?.mode} />
            </div>
          )}
          <Outlet />
        </main>
        <AlertToaster />

        <footer className="border-t border-ink-800 px-4 py-3 text-center text-[11px] text-smoke-400 md:px-6">
          FireSight is a research/portfolio prototype. Detector output is a model prediction, not
          confirmed fire evidence. Never use this for emergency decisions.
        </footer>
      </div>
    </div>
  )
}


function AlertToaster() {
  const [alert, setAlert] = useState<AlertRecord | null>(null)

  useEffect(() => {
    let socket: WebSocket | null = null
    let retry: number | undefined
    let disposed = false

    const connect = () => {
      if (disposed) return
      socket = new WebSocket(wsUrl('/ws/alerts'))
      socket.onmessage = (msg) => {
        try {
          const payload = JSON.parse(msg.data)
          if (payload.type === 'alert' && payload.data?.id) {
            setAlert(payload.data as AlertRecord)
          }
        } catch {
          /* ignore malformed events */
        }
      }
      socket.onclose = () => {
        if (!disposed) retry = window.setTimeout(connect, 5000)
      }
      socket.onerror = () => socket?.close()
    }

    connect()
    return () => {
      disposed = true
      if (retry) window.clearTimeout(retry)
      if (socket) {
        socket.onclose = null
        socket.close()
      }
    }
  }, [])

  useEffect(() => {
    if (!alert) return
    const timer = window.setTimeout(() => setAlert(null), 8000)
    return () => window.clearTimeout(timer)
  }, [alert])

  if (!alert) return null
  return (
    <div className="fixed bottom-4 right-4 z-50 w-80 rounded-xl border border-amber-500/40 bg-ink-900/95 p-3 shadow-2xl shadow-black/50">
      <div className="flex items-start gap-2">
        <Bell className="mt-0.5 h-4 w-4 shrink-0 text-amber-300" />
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs font-semibold text-amber-200">Experimental alert</span>
            <button
              onClick={() => setAlert(null)}
              className="text-[11px] text-smoke-400 hover:text-white"
            >
              dismiss
            </button>
          </div>
          <p className="mt-1 truncate text-xs text-smoke-200">
            {alert.source_type} · {alert.detector_name}
            {alert.confidence != null ? ` · ${alert.confidence.toFixed(2)}` : ''}
          </p>
          <p className="mt-0.5 truncate font-mono text-[10px] text-smoke-500">{alert.id}</p>
          <Link
            to="/alerts"
            onClick={() => setAlert(null)}
            className="mt-1 inline-block text-[11px] text-amber-300 underline"
          >
            Review evidence
          </Link>
        </div>
      </div>
    </div>
  )
}
