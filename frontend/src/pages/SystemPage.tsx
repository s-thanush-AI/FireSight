import { useState } from 'react'
import { RefreshCw, Save, Server } from 'lucide-react'
import { api } from '../lib/api'
import { useApp } from '../lib/app-context'
import { useAsync } from '../lib/hooks'
import { Badge, Card, ErrorState, Spinner } from '../components/ui'

export function SystemPage() {
  const { status, reload } = useApp()
  const config = useAsync(() => api.config(), [])
  const [edits, setEdits] = useState<Record<string, string>>({})
  const [saveMsg, setSaveMsg] = useState<string | null>(null)
  const [error, setError] = useState<unknown>(null)

  const applyConfig = async () => {
    setError(null)
    setSaveMsg(null)
    const values: Record<string, unknown> = {}
    for (const [k, v] of Object.entries(edits)) {
      if (v === '') continue
      values[k] = /^\d+(\.\d+)?$/.test(v) ? Number(v) : v
    }
    try {
      await api.updateConfig(values)
      setEdits({})
      setSaveMsg('Configuration updated. Detector/VLM rebuilt where relevant.')
      config.reload()
      reload()
    } catch (err) {
      setError(err)
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-lg font-semibold text-white">System</h1>
          <p className="text-sm text-smoke-400">
            Runtime status and a small set of safe, in-memory configuration overrides.
          </p>
        </div>
        <button
          onClick={() => {
            config.reload()
            reload()
          }}
          className="inline-flex items-center gap-1.5 rounded-lg border border-ink-600 px-3 py-2 text-sm text-smoke-300 hover:bg-ink-800"
        >
          <RefreshCw className="h-4 w-4" /> Refresh
        </button>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="Runtime status" actions={<Server className="h-4 w-4 text-smoke-400" />}>
          {status ? (
            <dl className="space-y-2 text-xs">
              <div className="flex justify-between">
                <dt className="text-smoke-400">Version</dt>
                <dd className="font-mono text-smoke-200">{status.version}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-smoke-400">Mode</dt>
                <dd>
                  <Badge
                    className={
                      status.mode === 'real'
                        ? 'bg-sky-500/15 text-sky-300 ring-sky-500/30'
                        : 'bg-violet-500/15 text-violet-300 ring-violet-500/30'
                    }
                  >
                    {status.mode}
                  </Badge>
                </dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-smoke-400">Active replays</dt>
                <dd className="tabular-nums text-smoke-200">{status.active_replays}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-smoke-400">Cameras</dt>
                <dd className="tabular-nums text-smoke-200">{status.cameras}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-smoke-400">Sequences</dt>
                <dd className="tabular-nums text-smoke-200">{status.sequences}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-smoke-400">Detector</dt>
                <dd className={status.detector.available ? 'text-emerald-300' : 'text-red-300'}>
                  {status.detector.name}:{status.detector.version}{' '}
                  {status.detector.available ? '(ready)' : '(unavailable)'}
                </dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-smoke-400">VLM</dt>
                <dd className="text-smoke-200">
                  {status.vlm.provider} {status.vlm.configured ? '(configured)' : '(simulated)'}
                </dd>
              </div>
            </dl>
          ) : (
            <Spinner />
          )}
          <p className="mt-3 rounded-md bg-ink-800/60 px-2 py-1.5 text-[11px] text-smoke-400">
            {status?.simulated_data_notice ?? 'Loading…'}
          </p>
        </Card>

        <Card title="Incidents by status">
          {status ? (
            <ul className="space-y-2 text-xs">
              {Object.entries(status.incidents_by_status).map(([k, v]) => (
                <li key={k} className="flex items-center justify-between">
                  <span className="text-smoke-400">{k}</span>
                  <span className="tabular-nums text-smoke-200">{v}</span>
                </li>
              ))}
            </ul>
          ) : (
            <Spinner />
          )}
        </Card>
      </div>

      <Card
        title="Configuration overrides"
        subtitle="Only whitelisted keys are accepted; secrets are never returned or exposed"
        actions={<Save className="h-4 w-4 text-smoke-400" />}
      >
        {config.loading && !config.data ? (
          <Spinner />
        ) : config.error ? (
          <ErrorState error={config.error} retry={config.reload} />
        ) : (
          <>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {config.data?.configurable_keys.map((key) => (
                <label key={key}>
                  <span className="mb-1 block font-mono text-[11px] text-smoke-400">{key}</span>
                  <input
                    value={edits[key] ?? ''}
                    onChange={(e) => setEdits({ ...edits, [key]: e.target.value })}
                    placeholder={
                      config.data?.overrides[key] != null
                        ? String(config.data.overrides[key])
                        : 'default'
                    }
                    className="w-full rounded-lg border border-ink-600 bg-ink-850 px-3 py-2 text-sm text-white outline-none focus:border-ember-500"
                  />
                </label>
              ))}
            </div>
            <div className="mt-4 flex items-center gap-3">
              <button
                onClick={applyConfig}
                disabled={!Object.keys(edits).length}
                className="inline-flex items-center gap-1.5 rounded-lg bg-ember-500 px-4 py-2 text-sm font-medium text-ink-950 hover:bg-ember-400 disabled:opacity-50"
              >
                <Save className="h-4 w-4" /> Apply overrides
              </button>
              {saveMsg && <span className="text-xs text-emerald-300">{saveMsg}</span>}
            </div>
            {error != null && (
              <div className="mt-3">
                <ErrorState error={error} />
              </div>
            )}
            <details className="mt-4">
              <summary className="cursor-pointer text-xs text-smoke-400">
                Redacted effective settings
              </summary>
              <pre className="mt-2 max-h-72 overflow-auto rounded-md bg-black/40 px-3 py-2 font-mono text-[11px] text-smoke-300">
                {JSON.stringify(config.data?.settings, null, 2)}
              </pre>
            </details>
          </>
        )}
      </Card>
    </div>
  )
}
