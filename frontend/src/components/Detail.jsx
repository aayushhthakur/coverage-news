import { useState } from 'react'
import { clockTime, dayLabel, sourcesLabel, timeAgo } from '../format'
import { href } from '../router'
import { useFetch } from '../useFetch'
import { BackIcon, ChevronIcon, ExternalIcon, InfoIcon, LayersIcon } from './Icons'
import { HeroImage } from './Photo'
import { ErrorState } from './States'
import WhySheet from './WhySheet'

const TIER_TITLES = { 1: 'Tier 1', 2: 'Tier 2', 3: 'Tier 3', other: 'Other sources' }
const TIMELINE_STEP = 25

function goBack() {
  if (history.length > 1) history.back()
  else location.hash = '#/'
}

export default function Detail({ kind, id }) {
  const { data, error, loading, reload } = useFetch(`/${kind === 'story' ? 'stories' : 'events'}/${id}`)
  const [why, setWhy] = useState(null)
  const [shown, setShown] = useState(TIMELINE_STEP)

  return (
    <>
      <header className="sticky top-0 z-20 border-b border-line bg-bg/95 backdrop-blur pt-safe">
        <div className="flex min-h-[52px] items-center gap-1 px-safe">
          <button type="button" onClick={goBack} aria-label="Back"
            className="-ml-2 inline-flex h-11 w-11 items-center justify-center rounded-full">
            <BackIcon />
          </button>
          <span className="text-[17px] font-semibold">{kind === 'story' ? 'Story' : 'Event'}</span>
        </div>
      </header>

      <main className="px-safe pb-8 pt-4">
        {loading && !data && <DetailSkeleton />}
        {error && !data && <ErrorState error={error} onRetry={reload} />}
        {data && (
          <>
            {data.image && <HeroImage image={data.image} />}
            {data.kind === 'story' && (
              <p className="mb-2 inline-flex items-center gap-1 rounded-full bg-story/12 px-2 py-0.5 text-[13px] font-semibold text-story">
                <LayersIcon width={14} height={14} /> {data.label} · {data.sub_events.length} angles
              </p>
            )}
            <h1 className="text-[22px] font-bold leading-tight">{data.headline}</h1>
            {data.summary && <p className="mt-2 text-[16px] text-ink-2">{data.summary}</p>}
            <p className="mt-3 text-[14px] text-ink-3">
              First reported {timeAgo(data.first_reported_at)} · {data.article_count} reports
            </p>

            {data.score && (
              <button type="button" onClick={() => setWhy({ ...data, score: data.score })}
                className="mt-4 flex min-h-[48px] w-full items-center justify-between rounded-xl border border-line bg-surface px-4 text-left">
                <span className="flex items-center gap-2 text-[16px] font-semibold">
                  <InfoIcon width={20} height={20} className="text-accent" /> Why this is ranked here
                </span>
                <span className="text-[14px] text-ink-3">{sourcesLabel(data.score.publishers)}</span>
              </button>
            )}

            {data.kind === 'story' && <SubEvents items={data.sub_events} />}
            <Coverage groups={data.publishers_by_tier} />
            <Timeline items={data.timeline} shown={shown} onMore={() => setShown((n) => n + TIMELINE_STEP)} />
          </>
        )}
      </main>
      <WhySheet item={why} onClose={() => setWhy(null)} />
    </>
  )
}

function Section({ title, count, children }) {
  return (
    <section className="mt-7">
      <h2 className="mb-2 flex items-baseline gap-2 text-[17px] font-semibold">
        {title} {count != null && <span className="text-[14px] font-normal text-ink-3">{count}</span>}
      </h2>
      {children}
    </section>
  )
}

function SubEvents({ items }) {
  const [all, setAll] = useState(false)
  const visible = all ? items : items.slice(0, 5)
  return (
    <Section title="Angles in this story" count={items.length}>
      <ul className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-surface">
        {visible.map((e) => (
          <li key={e.id}>
            <a href={href.item('event', e.id)} className="flex min-h-[56px] items-center gap-3 px-4 py-2.5">
              <span className="min-w-0 flex-1">
                <span className="line-clamp-2 text-[16px] font-medium">{e.headline}</span>
                <span className="text-[14px] text-ink-3">
                  {e.sources > 0 ? sourcesLabel(e.sources) : 'Unscored'} · {timeAgo(e.first_reported_at)}
                </span>
              </span>
              <ChevronIcon width={18} height={18} className="shrink-0 text-ink-3" />
            </a>
          </li>
        ))}
      </ul>
      {items.length > visible.length && (
        <button type="button" onClick={() => setAll(true)}
          className="mt-2 min-h-[44px] w-full rounded-xl border border-line bg-surface text-[16px] font-semibold text-accent">
          Show all {items.length} angles
        </button>
      )}
    </Section>
  )
}

function Coverage({ groups }) {
  const tiers = ['1', '2', '3', 'other'].filter((t) => groups[t]?.length)
  const total = tiers.reduce((n, t) => n + groups[t].length, 0)
  return (
    <Section title="Who is covering it" count={sourcesLabel(total)}>
      <div className="space-y-4">
        {tiers.map((t) => (
          <div key={t}>
            <h3 className="mb-1.5 text-[14px] font-semibold uppercase tracking-wide text-ink-3">
              {TIER_TITLES[t]} · {groups[t].length}
            </h3>
            <ul className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-surface">
              {groups[t].map((p) => (
                <li key={p.publisher}>
                  <a href={p.url} target="_blank" rel="noopener noreferrer"
                    className="flex min-h-[56px] items-start gap-3 px-4 py-2.5">
                    <span className="min-w-0 flex-1">
                      <span className="block text-[16px] font-semibold">{p.publisher}</span>
                      <span className="line-clamp-2 text-[16px] text-ink-2">{p.title}</span>
                    </span>
                    <span className="mt-0.5 flex shrink-0 items-center gap-1 text-[14px] text-ink-3">
                      {timeAgo(p.published_at)} <ExternalIcon width={16} height={16} />
                    </span>
                  </a>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </Section>
  )
}

function Timeline({ items, shown, onMore }) {
  let lastDay = null
  return (
    <Section title="Timeline" count={`${items.length} reports`}>
      <ol className="relative ml-2 border-l-2 border-line">
        {items.slice(0, shown).map((r, i) => {
          const day = dayLabel(r.published_at)
          const showDay = day !== lastDay
          lastDay = day
          return (
            <li key={i} className="relative pl-5">
              {showDay && <p className="pb-1 pt-3 text-[13px] font-semibold uppercase tracking-wide text-ink-3">{day}</p>}
              <span aria-hidden="true"
                className={`absolute -left-[7px] top-[calc(50%-6px)] h-3 w-3 rounded-full border-2 border-bg ${
                  r.tier === 1 ? 'bg-accent' : 'bg-ink-3'} ${showDay ? 'top-[calc(50%+6px)]' : ''}`} />
              <a href={r.url} target="_blank" rel="noopener noreferrer" className="block min-h-[44px] py-2">
                <span className="text-[14px] text-ink-3">
                  <time dateTime={r.published_at}>{clockTime(r.published_at)}</time> · <b className="font-semibold text-ink-2">{r.publisher}</b>
                </span>
                <span className="line-clamp-2 text-[16px]">{r.title}</span>
              </a>
            </li>
          )
        })}
      </ol>
      {shown < items.length && (
        <button type="button" onClick={onMore}
          className="mt-2 min-h-[44px] w-full rounded-xl border border-line bg-surface text-[16px] font-semibold text-accent">
          Show more ({items.length - shown} left)
        </button>
      )}
    </Section>
  )
}

function DetailSkeleton() {
  return (
    <div className="animate-pulse" aria-label="Loading">
      <div className="h-7 w-11/12 rounded bg-skeleton" />
      <div className="mt-2 h-7 w-2/3 rounded bg-skeleton" />
      <div className="mt-4 h-4 w-full rounded bg-skeleton" />
      <div className="mt-2 h-4 w-4/5 rounded bg-skeleton" />
      <div className="mt-5 h-12 w-full rounded-xl bg-skeleton" />
      <div className="mt-7 h-40 w-full rounded-xl bg-skeleton" />
    </div>
  )
}
