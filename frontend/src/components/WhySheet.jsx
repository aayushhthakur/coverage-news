import { useEffect, useRef, useState } from 'react'
import { hoursLabel } from '../format'
import { CloseIcon } from './Icons'

function Row({ label, value, frac, note }) {
  const pct = Math.round(Math.max(0, Math.min(1, frac)) * 100)
  return (
    <li className="py-3">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-[16px] font-medium">{label}</span>
        <span className="text-[16px] font-semibold tabular-nums">{value}</span>
      </div>
      <div className="mt-2 h-2 overflow-hidden rounded-full bg-bar-track" role="presentation">
        <div className="h-full rounded-full bg-accent" style={{ width: `${pct}%` }} />
      </div>
      {note && <p className="mt-1.5 text-[14px] text-ink-3">{note}</p>}
    </li>
  )
}

/** Bottom sheet: "Why this is ranked here". `item` carries `score` from the API. */
export default function WhySheet({ item, onClose }) {
  const closeRef = useRef(null)
  const [drag, setDrag] = useState(0)
  const startY = useRef(null)

  useEffect(() => {
    if (!item) return
    const prev = document.activeElement
    closeRef.current?.focus()
    const onKey = (e) => e.key === 'Escape' && onClose()
    addEventListener('keydown', onKey)
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      removeEventListener('keydown', onKey)
      document.body.style.overflow = overflow
      prev?.focus?.()
    }
  }, [item, onClose])

  if (!item) return null
  const s = item.score
  const lastHourPct = s.publishers ? Math.round((s.added_last_hour / s.publishers) * 100) : 0

  // swipe down on the handle area to dismiss
  const onTouchStart = (e) => { startY.current = e.touches[0].clientY }
  const onTouchMove = (e) => { if (startY.current != null) setDrag(Math.max(0, e.touches[0].clientY - startY.current)) }
  const onTouchEnd = () => { if (drag > 90) onClose(); setDrag(0); startY.current = null }

  return (
    <div className="fixed inset-0 z-50" role="presentation">
      <div className="absolute inset-0 bg-black/45" onClick={onClose} aria-hidden="true" />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="why-title"
        className="absolute inset-x-0 bottom-0 mx-auto max-h-[88vh] max-w-[480px] overflow-y-auto rounded-t-3xl bg-surface pb-safe shadow-2xl"
        style={{ transform: `translateY(${drag}px)`, transition: drag ? 'none' : 'transform 160ms ease-out' }}
      >
        <div onTouchStart={onTouchStart} onTouchMove={onTouchMove} onTouchEnd={onTouchEnd} className="px-safe pt-2">
          <div className="mx-auto h-1.5 w-10 rounded-full bg-line" aria-hidden="true" />
          <div className="mt-2 flex items-center justify-between">
            <h2 id="why-title" className="text-[20px] font-semibold">Why this is ranked here</h2>
            <button ref={closeRef} type="button" onClick={onClose} aria-label="Close"
              className="-mr-2 inline-flex h-11 w-11 items-center justify-center rounded-full text-ink-2">
              <CloseIcon />
            </button>
          </div>
        </div>

        <div className="px-safe pb-5">
          <p className="line-clamp-2 text-[16px] text-ink-2">{item.headline}</p>
          <ul className="mt-2 divide-y divide-line">
            <Row
              label="Publishers covering it"
              value={`${s.publishers} of ${s.total_publishers}`}
              frac={s.publishers / s.total_publishers}
              note="Counted once per publisher, however many articles each wrote."
            />
            <Row
              label="Coverage from the last hour"
              value={`${lastHourPct}%`}
              frac={s.v}
              note={s.publishers < 3
                ? 'Not counted until at least 3 publishers cover it.'
                : `${s.added_last_hour} of ${s.publishers} publishers joined in the last hour.`}
            />
            <Row
              label="Tier 1 publishers"
              value={`${s.tier1_publishers} of ${s.tier1_list_size}`}
              frac={s.t}
              note={`Major outlets on the ${s.topic === 'Technology' ? 'Tech' : s.topic} list.`}
            />
            <Row
              label="Age"
              value={hoursLabel(s.age_hours)}
              frac={s.decay}
              note={`Since the latest report. Weight halves every ${s.half_life_hours}h for ${s.topic === 'Technology' ? 'Tech' : s.topic}.`}
            />
          </ul>

          {(item.breaking || s.all_clickbait) && (
            <div className="mt-3 space-y-2">
              {item.breaking && (
                <p className="rounded-xl bg-breaking/10 p-3 text-[14px] text-ink">
                  <b className="text-breaking">Breaking:</b> under 2 hours old and among the fastest-growing in its topic, so it is lifted into the top 3.
                </p>
              )}
              {s.all_clickbait && (
                <p className="rounded-xl bg-surface-2 p-3 text-[14px] text-ink">
                  Every headline for this was flagged as clickbait, so its score is halved.
                </p>
              )}
            </div>
          )}

          <p className="mt-4 text-[14px] text-ink-3">
            Score {s.s.toFixed(2)} = (0.4 × coverage + 0.3 × last hour + 0.3 × Tier 1) × age weight
          </p>
        </div>
      </div>
    </div>
  )
}
