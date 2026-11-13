export function timeAgo(iso, now = Date.now()) {
  const mins = Math.max(0, Math.round((now - new Date(iso).getTime()) / 60000))
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins} min ago`
  const h = Math.floor(mins / 60)
  if (h < 24) return `${h}h ago`
  const d = Math.floor(h / 24)
  return `${d}d ago`
}

export function hoursLabel(h) {
  if (h < 1) return `${Math.max(1, Math.round(h * 60))} min`
  if (h < 10) return `${h.toFixed(1).replace(/\.0$/, '')}h`
  return `${Math.round(h)}h`
}

export function clockTime(iso) {
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

export function dayLabel(iso) {
  const d = new Date(iso)
  const today = new Date()
  const y = new Date(today); y.setDate(today.getDate() - 1)
  if (d.toDateString() === today.toDateString()) return 'Today'
  if (d.toDateString() === y.toDateString()) return 'Yesterday'
  return d.toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' })
}

export const sourcesLabel = (n) => `${n} ${n === 1 ? 'source' : 'sources'}`
