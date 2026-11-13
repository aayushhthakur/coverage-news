import { useState } from 'react'
import { clockTime, dayLabel, sourcesLabel, timeAgo } from '../format'
import { useFetch } from '../useFetch'
import { topicClass } from '../topics'
import { BackIcon, ExternalIcon, InfoIcon, LayersIcon } from './Icons'
import { HeroImage } from './Photo'
import { ErrorState } from './States'
import WhySheet from './WhySheet'

const TOPIC_SHORT = { Technology: 'Tech' }
const TIMELINE_STEP = 25
const readMinutes = (words) => Math.max(1, Math.round(words / 230))

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

      <main className={`${topicClass(data?.topic)} px-safe pb-8 pt-4`}>
        {loading && !data && <DetailSkeleton />}
        {error && !data && <ErrorState error={error} onRetry={reload} />}
        {data && (
          <>
            {data.image && <HeroImage image={data.image} />}
            {(data.topic || data.kind === 'story') && (
              <p className="mb-2 flex flex-wrap items-center gap-2 text-[13px] font-semibold">
                {data.topic && <span className="text-topic">{TOPIC_SHORT[data.topic] ?? data.topic}</span>}
                {data.kind === 'story' && (
                  <span className="inline-flex items-center gap-1 rounded-full bg-topic/12 px-2 py-0.5 text-topic">
                    <LayersIcon width={14} height={14} /> {data.label}
                  </span>
                )}
              </p>
            )}
            <h1 className="text-[22px] font-bold leading-tight">{data.headline}</h1>
            <p className="mt-3 text-[14px] text-ink-3">
              First reported {timeAgo(data.first_reported_at)} · {sourcesLabel(new Set(data.timeline.map((r) => r.publisher)).size)}
              {data.writeup && <> · {readMinutes(data.writeup.word_count)} min read</>}
            </p>

            {data.score && (
              <button type="button" onClick={() => setWhy({ ...data, score: data.score })}
                className="mt-4 flex min-h-[48px] w-full items-center justify-between rounded-xl border border-line bg-surface px-4 text-left">
                <span className="flex items-center gap-2 text-[16px] font-semibold">
                  <InfoIcon width={20} height={20} className="text-topic" /> Why this is ranked here
                </span>
                <span className="text-[14px] text-ink-3">{sourcesLabel(data.score.publishers)}</span>
              </button>
            )}

            {data.writeup
              ? <Article writeup={data.writeup} />
              : data.summary && <p className="mt-5 text-[17px] leading-relaxed">{data.summary}</p>}
            {data.writeup && <Sources items={data.writeup.sources} />}
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

/** The write-up: every passage is quoted from a publisher's feed summary, credited under it. */
function Article({ writeup }) {
  return (
    <article className="mt-6">
      {writeup.sections.map((sec) => (
        <section key={sec.key} className="mt-6 first:mt-0">
          <h2 className="mb-2 flex items-center gap-2 text-[18px] font-bold">
            <span aria-hidden="true" className="h-5 w-1 rounded-full bg-topic" />
            {sec.title}
          </h2>
          <div className="space-y-4">
            {sec.blocks.map((b, i) => (
              <div key={i}>
                {b.label && <h3 className="mb-1 text-[15px] font-semibold text-topic">{b.label}</h3>}
                <p className={`text-[17px] leading-relaxed ${b.generated ? 'text-ink-2' : ''}`}>{b.text}</p>
                {b.sources.length > 0 && (
                  <p className="mt-1 text-[13px] text-ink-3">— {b.sources.join(', ')}</p>
                )}
              </div>
            ))}
          </div>
        </section>
      ))}
      <p className="mt-6 rounded-xl bg-surface-2 px-4 py-3 text-[14px] text-ink-2">
        Built from the summaries these publishers put in their news feeds. Each passage is quoted as published
        and credited underneath; open a source below to read its full report.
      </p>
    </article>
  )
}

function Sources({ items }) {
  return (
    <Section title="Sources" count="most used first">
      <ol className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-surface">
        {items.map((p, i) => (
          <li key={p.publisher}>
            <a href={p.url} target="_blank" rel="noopener noreferrer"
              className="flex min-h-[56px] items-start gap-3 px-4 py-2.5">
              <span className="mt-0.5 w-6 shrink-0 text-[14px] font-semibold tabular-nums text-ink-3">{i + 1}</span>
              <span className="min-w-0 flex-1">
                <span className="flex flex-wrap items-baseline gap-x-2">
                  <span className="text-[16px] font-semibold">{p.publisher}</span>
                  <span className="text-[13px] text-ink-3">
                    {p.tier ? `Tier ${p.tier}` : 'Other'} · {p.passages > 0
                      ? `${p.passages} ${p.passages === 1 ? 'passage' : 'passages'}`
                      : 'covered, not quoted'}
                  </span>
                </span>
                <span className="line-clamp-2 text-[16px] text-ink-2">{p.title}</span>
              </span>
              <ExternalIcon width={16} height={16} className="mt-1 shrink-0 text-ink-3" />
            </a>
          </li>
        ))}
      </ol>
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
                  r.tier === 1 ? 'bg-topic' : 'bg-ink-3'} ${showDay ? 'top-[calc(50%+6px)]' : ''}`} />
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
          className="mt-2 min-h-[44px] w-full rounded-xl border border-line bg-surface text-[16px] font-semibold text-topic">
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
