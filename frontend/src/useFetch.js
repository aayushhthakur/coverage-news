import { useCallback, useEffect, useRef, useState } from 'react'
import { getJSON } from './api'

// Small stale-while-revalidate cache so switching tabs is instant.
const cache = new Map()

export function useFetch(path) {
  const [state, setState] = useState(() => ({ data: cache.get(path) ?? null, error: null, loading: !cache.has(path) }))
  const ctrlRef = useRef(null)

  const load = useCallback(async () => {
    ctrlRef.current?.abort()
    const ctrl = new AbortController()
    ctrlRef.current = ctrl
    setState((s) => ({ ...s, loading: true, error: null }))
    try {
      const data = await getJSON(path, { signal: ctrl.signal })
      cache.set(path, data)
      if (!ctrl.signal.aborted) setState({ data, error: null, loading: false })
    } catch (error) {
      if (!ctrl.signal.aborted) setState((s) => ({ ...s, error, loading: false }))
    }
  }, [path])

  useEffect(() => {
    setState({ data: cache.get(path) ?? null, error: null, loading: !cache.has(path) })
    load()
    return () => ctrlRef.current?.abort()
  }, [path, load])

  return { ...state, reload: load }
}
