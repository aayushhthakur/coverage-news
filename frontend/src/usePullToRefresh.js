import { useEffect, useRef, useState } from 'react'

const TRIGGER = 64
const MAX = 96

/** Pull down from the top of the page to refresh. Returns the current pull distance and state. */
export function usePullToRefresh(onRefresh) {
  const [pull, setPull] = useState(0)
  const [refreshing, setRefreshing] = useState(false)
  const start = useRef(null)
  const pullRef = useRef(0)
  const busy = useRef(false)

  useEffect(() => {
    const onStart = (e) => {
      if (busy.current || window.scrollY > 0 || document.body.style.overflow === 'hidden') return
      start.current = e.touches[0].clientY
    }
    const onMove = (e) => {
      if (start.current == null) return
      const dy = e.touches[0].clientY - start.current
      if (dy <= 0 || window.scrollY > 0) { pullRef.current = 0; setPull(0); return }
      const d = Math.min(MAX, dy * 0.5)
      pullRef.current = d
      setPull(d)
    }
    const onEnd = async () => {
      if (start.current == null) return
      start.current = null
      if (pullRef.current >= TRIGGER) {
        busy.current = true
        setRefreshing(true)
        setPull(48)
        try { await onRefresh() } finally {
          busy.current = false
          setRefreshing(false)
        }
      }
      pullRef.current = 0
      setPull(0)
    }
    addEventListener('touchstart', onStart, { passive: true })
    addEventListener('touchmove', onMove, { passive: true })
    addEventListener('touchend', onEnd)
    addEventListener('touchcancel', onEnd)
    return () => {
      removeEventListener('touchstart', onStart)
      removeEventListener('touchmove', onMove)
      removeEventListener('touchend', onEnd)
      removeEventListener('touchcancel', onEnd)
    }
  }, [onRefresh])

  return { pull, refreshing, ready: pull >= TRIGGER }
}
