const BASE = import.meta.env.VITE_API_BASE ?? '/api'

export async function getJSON(path, { signal, timeout = 15000 } = {}) {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(new DOMException('timeout', 'TimeoutError')), timeout)
  signal?.addEventListener('abort', () => ctrl.abort(signal.reason))
  try {
    const res = await fetch(`${BASE}${path}`, { signal: ctrl.signal, headers: { Accept: 'application/json' } })
    if (!res.ok) {
      const err = new Error(res.status === 404 ? 'Not found' : `Server error (${res.status})`)
      err.status = res.status
      throw err
    }
    return await res.json()
  } finally {
    clearTimeout(timer)
  }
}

export const listPath = (topic, subtopic) =>
  topic ? `/topics/${encodeURIComponent(topic)}${subtopic ? `?subtopic=${encodeURIComponent(subtopic)}` : ''}` : '/home'
