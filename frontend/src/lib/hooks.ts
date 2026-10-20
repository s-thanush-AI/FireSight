import { useCallback, useEffect, useRef, useState } from 'react'

interface AsyncState<T> {
  data: T | null
  loading: boolean
  error: unknown
  reload: () => void
}

/**
 * Small data-fetch hook. Polls only when `pollMs` is provided. Cancels on
 * unmount so a slow response never sets state on a dead component.
 */
export function useAsync<T>(
  fn: () => Promise<T>,
  deps: unknown[] = [],
  opts: { pollMs?: number; enabled?: boolean } = {},
): AsyncState<T> {
  const { pollMs, enabled = true } = opts
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(enabled)
  const [error, setError] = useState<unknown>(null)
  const alive = useRef(true)
  const fnRef = useRef(fn)
  useEffect(() => {
    fnRef.current = fn
  })

  const run = useCallback(async () => {
    try {
      const result = await fnRef.current()
      if (alive.current) {
        setData(result)
        setError(null)
      }
    } catch (err) {
      if (alive.current) setError(err)
    } finally {
      if (alive.current) setLoading(false)
    }
  }, [])

  useEffect(() => {
    alive.current = true
    if (!enabled) {
      setLoading(false)
      return
    }
    setLoading(true)
    void run()
    let timer: number | undefined
    if (pollMs) {
      timer = window.setInterval(() => void run(), pollMs)
    }
    return () => {
      alive.current = false
      if (timer) window.clearInterval(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, pollMs, enabled, run])

  return { data, loading, error, reload: run }
}

export function useInterval(fn: () => void, ms: number | null) {
  const ref = useRef(fn)
  useEffect(() => {
    ref.current = fn
  }, [fn])
  useEffect(() => {
    if (ms == null) return
    const t = window.setInterval(() => ref.current(), ms)
    return () => window.clearInterval(t)
  }, [ms])
}
