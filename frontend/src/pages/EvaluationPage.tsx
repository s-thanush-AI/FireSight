import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { PlayCircle, Radar } from 'lucide-react'
import { api } from '../lib/api'
import { useAsync } from '../lib/hooks'
import { Badge, Card, EmptyState, ErrorState, Spinner } from '../components/ui'
import { formatTimestamp } from '../lib/format'

export function EvaluationPage() {
  const overview = useAsync(() => api.metrics(), [])
  const runs = useAsync(() => api.evalRuns(), [])

  const chartData =
    overview.data?.latest?.metrics.map((m) => ({
      name: m.name.replace(/_/g, ' '),
      value: m.value ?? 0,
      valid: m.value != null,
    })) ?? []

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-white">Evaluation</h1>
          <p className="text-sm text-smoke-400">
            Metrics computed only where ground truth exists. Synthetic-fixture results validate
            pipeline mechanics — not real-world accuracy.
          </p>
        </div>
        <button
          onClick={async () => {
            await api.runEvaluation('Dashboard evaluation run')
            overview.reload()
            runs.reload()
          }}
          className="inline-flex items-center gap-1.5 rounded-lg bg-ember-500 px-3 py-2 text-sm font-medium text-ink-950 hover:bg-ember-400"
        >
          <PlayCircle className="h-4 w-4" /> Run demo fixture
        </button>
      </div>

      {overview.data && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-2 text-xs text-amber-100">
          {overview.data.honesty_notice}
        </div>
      )}

      {overview.loading && !overview.data ? (
        <Spinner />
      ) : overview.error ? (
        <ErrorState error={overview.error} retry={overview.reload} />
      ) : !overview.data?.latest ? (
        <EmptyState title="No evaluation runs yet" icon={<Radar className="h-6 w-6 text-smoke-400" />}>
          Run the demo-fixture evaluation to populate metrics. Unavailable metrics are returned with
          a reason instead of a fabricated number.
        </EmptyState>
      ) : (
        <div className="grid gap-5 lg:grid-cols-2">
          <Card
            title="Latest run metrics"
            subtitle={`${overview.data.latest.kind} · ${formatTimestamp(overview.data.latest.created_at)}`}
          >
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chartData} margin={{ top: 10, right: 10, left: -10, bottom: 40 }}>
                  <CartesianGrid stroke="#1f2d3d" vertical={false} />
                  <XAxis
                    dataKey="name"
                    tick={{ fill: '#8aa0b6', fontSize: 10 }}
                    angle={-30}
                    textAnchor="end"
                    interval={0}
                  />
                  <YAxis tick={{ fill: '#8aa0b6', fontSize: 10 }} />
                  <Tooltip
                    contentStyle={{
                      background: '#0c1219',
                      border: '1px solid #1f2d3d',
                      borderRadius: 8,
                      fontSize: 12,
                    }}
                  />
                  <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                    {chartData.map((d, i) => (
                      <Cell key={i} fill={d.valid ? '#ff6b35' : '#2b3d52'} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Card>

          <Card title="Metric detail" subtitle="Value, sample size and limitations">
            <ul className="space-y-2 text-xs">
              {overview.data.latest.metrics.map((m) => (
                <li key={m.id} className="rounded-md bg-ink-800/50 px-3 py-2">
                  <div className="flex items-center justify-between">
                    <span className="font-medium text-smoke-200">{m.name}</span>
                    <span className="tabular-nums text-white">
                      {m.value != null ? `${m.value.toFixed(3)} ${m.unit ?? ''}` : 'unavailable'}
                    </span>
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-smoke-400">
                    {m.sample_count != null && <Badge>n={m.sample_count}</Badge>}
                    {m.ground_truth_available ? (
                      <Badge className="bg-emerald-500/15 text-emerald-300 ring-emerald-500/30">
                        GT available
                      </Badge>
                    ) : (
                      <Badge className="bg-slate-500/15 text-slate-300 ring-slate-500/30">
                        no GT
                      </Badge>
                    )}
                    <span>{m.data_source}</span>
                  </div>
                  {m.limitation && (
                    <p className="mt-1 text-smoke-400/80">{m.limitation}</p>
                  )}
                </li>
              ))}
            </ul>
          </Card>

          <Card
            className="lg:col-span-2"
            title="Metric definitions"
            subtitle="How each number is computed"
          >
            <dl className="grid gap-2 text-xs sm:grid-cols-2">
              {Object.entries(overview.data.definitions).map(([k, v]) => (
                <div key={k} className="rounded-md bg-ink-800/40 px-3 py-2">
                  <dt className="font-mono text-[11px] text-ember-300">{k}</dt>
                  <dd className="mt-0.5 text-smoke-400">{v}</dd>
                </div>
              ))}
            </dl>
          </Card>
        </div>
      )}

      <Card title="Evaluation runs" subtitle={`${runs.data?.total ?? 0} stored`}>
        {runs.data?.items.length ? (
          <ul className="divide-y divide-ink-800 text-sm">
            {runs.data.items.map((r) => (
              <li key={r.id} className="flex items-center justify-between py-2">
                <div>
                  <div className="text-smoke-200">{r.name}</div>
                  <div className="text-xs text-smoke-400">
                    {r.kind} · {formatTimestamp(r.created_at)} · {r.metrics.length} metrics
                  </div>
                </div>
                <Badge>{r.id.slice(-8)}</Badge>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-xs text-smoke-400">No runs recorded yet.</p>
        )}
      </Card>
    </div>
  )
}
