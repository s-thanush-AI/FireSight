import { useState } from 'react'
import { Database, FileSearch, FolderOpen, FileVideo } from 'lucide-react'
import { api } from '../lib/api'
import type { RegisteredSequence } from '../lib/api'
import { useAsync } from '../lib/hooks'
import { Badge, Card, ErrorState, ProvenanceBadge, Spinner } from '../components/ui'

export function DatasetsPage() {
  const datasets = useAsync(() => api.datasets(), [])
  const cameras = useAsync(() => api.cameras(), [])
  const [path, setPath] = useState('')
  const [report, setReport] = useState<Record<string, unknown> | null>(null)
  const [error, setError] = useState<unknown>(null)

  const [seqId, setSeqId] = useState('')
  const [seqPath, setSeqPath] = useState('')
  const [seqName, setSeqName] = useState('')
  const [seqCamera, setSeqCamera] = useState('')
  const [registering, setRegistering] = useState(false)
  const [regError, setRegError] = useState<unknown>(null)
  const [regResult, setRegResult] = useState<RegisteredSequence | null>(null)

  const inspect = async () => {
    setError(null)
    setReport(null)
    try {
      const res = await api.inspectDataset(path)
      setReport(res)
    } catch (err) {
      setError(err)
    }
  }

  const register = async () => {
    setRegError(null)
    setRegResult(null)
    setRegistering(true)
    try {
      const res = await api.registerSequence({
        id: seqId.trim(),
        root_path: seqPath.trim(),
        name: seqName.trim() || undefined,
        camera_id: seqCamera || undefined,
      })
      setRegResult(res)
      setSeqId('')
      setSeqPath('')
      setSeqName('')
      setSeqCamera('')
      datasets.reload()
      window.dispatchEvent(new Event('firesight:sequences-changed'))
    } catch (err) {
      setRegError(err)
    } finally {
      setRegistering(false)
    }
  }

  const canRegister = seqId.trim() !== '' && seqPath.trim() !== '' && !registering

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold text-white">Datasets</h1>
        <p className="text-sm text-smoke-400">
          Registered sequences and safe, path-confined dataset inspection. Real datasets are never
          downloaded automatically.
        </p>
      </div>

      {datasets.data && (
        <div className="flex flex-wrap gap-2 text-xs text-smoke-400">
          <Badge>
            <FolderOpen className="mr-1 h-3 w-3" /> {datasets.data.data_root}
          </Badge>
          <Badge>
            {datasets.data.data_root_exists ? 'data root present' : 'data root missing'}
          </Badge>
          {Object.entries(datasets.data.docs).map(([k, v]) => (
            <a
              key={k}
              href={v}
              target="_blank"
              rel="noreferrer"
              className="rounded-full bg-ink-700/40 px-2 py-0.5 text-smoke-300 ring-1 ring-inset ring-ink-600/50 hover:text-white"
            >
              {k} docs ↗
            </a>
          ))}
        </div>
      )}

      {datasets.loading && !datasets.data ? (
        <Spinner />
      ) : datasets.error ? (
        <ErrorState error={datasets.error} retry={datasets.reload} />
      ) : (
        <Card
          title="Registered sequences"
          subtitle={`${datasets.data?.registered.length ?? 0} sequence(s)`}
          actions={<Database className="h-4 w-4 text-smoke-400" />}
        >
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-left text-smoke-400">
                <tr>
                  <th className="pb-2">ID</th>
                  <th className="pb-2">Frames</th>
                  <th className="pb-2">Resolution</th>
                  <th className="pb-2">Camera</th>
                  <th className="pb-2">Provenance</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-800">
                {datasets.data?.registered.map((s) => (
                  <tr key={s.id}>
                    <td className="py-2 font-mono text-[11px] text-smoke-200">{s.id}</td>
                    <td className="py-2 tabular-nums text-smoke-300">{s.frame_count}</td>
                    <td className="py-2 text-smoke-300">
                      {s.image_width ?? '?'}×{s.image_height ?? '?'}
                    </td>
                    <td className="py-2 font-mono text-[11px] text-smoke-300">
                      {s.camera_id ?? '—'}
                    </td>
                    <td className="py-2">
                      <ProvenanceBadge provenance={s.provenance as never} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      <Card
        title="Inspect a dataset"
        subtitle="Path must resolve under the configured data root"
        actions={<FileSearch className="h-4 w-4 text-smoke-400" />}
      >
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex-1 min-w-[220px]">
            <span className="mb-1 block text-xs text-smoke-400">Relative path</span>
            <input
              value={path}
              onChange={(e) => setPath(e.target.value)}
              placeholder="demo"
              className="w-full rounded-lg border border-ink-600 bg-ink-850 px-3 py-2 text-sm text-white outline-none focus:border-ember-500"
            />
          </label>
          <button
            onClick={inspect}
            disabled={!path}
            className="rounded-lg bg-ember-500 px-4 py-2 text-sm font-medium text-ink-950 hover:bg-ember-400 disabled:opacity-50"
          >
            Inspect
          </button>
        </div>
        {error != null && (
          <div className="mt-3">
            <ErrorState error={error} />
          </div>
        )}
        {report && (
          <pre className="mt-3 max-h-72 overflow-auto rounded-md bg-black/40 px-3 py-2 font-mono text-[11px] text-emerald-200">
            {JSON.stringify(report, null, 2)}
          </pre>
        )}
      </Card>

      <Card
        title="Register footage sequence"
        subtitle="Register a directory of JPG/JPEG/PNG frames as real footage"
        actions={<FileVideo className="h-4 w-4 text-smoke-400" />}
      >
        <p className="mb-3 text-xs text-smoke-400">
          This registers a directory <span className="text-smoke-300">relative to the data root</span>{' '}
          that already contains extracted frames (<code className="font-mono">.jpg</code>,{' '}
          <code className="font-mono">.jpeg</code>, <code className="font-mono">.png</code>). It does
          not upload MP4 files and does not accept RTSP streams — extract frames first (see the README).
        </p>
        <div className="grid gap-3 sm:grid-cols-2">
          <label>
            <span className="mb-1 block text-xs text-smoke-400">Sequence ID</span>
            <input
              value={seqId}
              onChange={(e) => setSeqId(e.target.value)}
              placeholder="cctv-ridge-1"
              className="w-full rounded-lg border border-ink-600 bg-ink-850 px-3 py-2 text-sm text-white outline-none focus:border-ember-500"
            />
          </label>
          <label>
            <span className="mb-1 block text-xs text-smoke-400">Frames directory (relative)</span>
            <input
              value={seqPath}
              onChange={(e) => setSeqPath(e.target.value)}
              placeholder="cctv/ridge-1"
              className="w-full rounded-lg border border-ink-600 bg-ink-850 px-3 py-2 text-sm text-white outline-none focus:border-ember-500"
            />
          </label>
          <label>
            <span className="mb-1 block text-xs text-smoke-400">Display name (optional)</span>
            <input
              value={seqName}
              onChange={(e) => setSeqName(e.target.value)}
              placeholder="Ridge camera 1"
              className="w-full rounded-lg border border-ink-600 bg-ink-850 px-3 py-2 text-sm text-white outline-none focus:border-ember-500"
            />
          </label>
          <label>
            <span className="mb-1 block text-xs text-smoke-400">Camera (optional)</span>
            <select
              value={seqCamera}
              onChange={(e) => setSeqCamera(e.target.value)}
              className="w-full rounded-lg border border-ink-600 bg-ink-850 px-3 py-2 text-sm text-white outline-none focus:border-ember-500"
            >
              <option value="">— no camera —</option>
              {cameras.data?.items.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.id} — {c.name}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="mt-3 flex items-center gap-3">
          <button
            onClick={register}
            disabled={!canRegister}
            className="rounded-lg bg-ember-500 px-4 py-2 text-sm font-medium text-ink-950 hover:bg-ember-400 disabled:opacity-50"
          >
            {registering ? 'Registering…' : 'Register sequence'}
          </button>
          <span className="text-xs text-smoke-500">Provenance will be recorded as “real”.</span>
        </div>
        {regError != null && (
          <div className="mt-3">
            <ErrorState error={regError} />
          </div>
        )}
        {regResult && (
          <div className="mt-3 rounded-md bg-emerald-500/10 px-3 py-2 text-xs text-emerald-200 ring-1 ring-inset ring-emerald-500/30">
            <div className="font-medium">
              Registered “{regResult.id}” — {regResult.frame_count} frame(s)
              {regResult.timestamps_available ? ' with timestamps' : ' (timestamps unknown)'}.
            </div>
            <div className="mt-1 text-emerald-300/80">
              Camera: {regResult.camera_id ?? '—'} · {regResult.image_width ?? '?'}×
              {regResult.image_height ?? '?'} · provenance {regResult.provenance}. Select it in Replay.
            </div>
            {regResult.warnings.length > 0 && (
              <ul className="mt-2 list-disc space-y-0.5 pl-4 text-amber-300">
                {regResult.warnings.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            )}
          </div>
        )}
      </Card>

      {datasets.data && datasets.data.local_dirs_not_registered.length > 0 && (
        <Card title="Local directories (not registered)" subtitle="Present under the data root">
          <ul className="space-y-1 text-xs text-smoke-400">
            {datasets.data.local_dirs_not_registered.map((d) => (
              <li key={d.name} className="font-mono">
                {d.name} — {d.path}
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  )
}
