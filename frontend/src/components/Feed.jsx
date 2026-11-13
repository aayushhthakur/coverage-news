import { useEffect, useRef, useState } from 'react'
import { listPath } from '../api'
import { href } from '../router'
import { useFetch } from '../useFetch'
import { usePullToRefresh } from '../usePullToRefresh'
import EventCard, { CardSkeleton } from './EventCard'
import { RefreshIcon } from './Icons'
import { EmptyState, ErrorState, StaleBanner } from './States'
import WhySheet from './WhySheet'

const TITLES = { Technology: 'Tech' }
// Mirrors config/taxonomy.yaml so chips still render when the API is unreachable;
// the API's own list wins when it loads.
const SUBTOPICS = {
  Geopolitics: ['Conflict', 'Diplomacy', 'Elections', 'Migration'],
  Sports: ['Cricket', 'Football', 'Tennis', 'Boxing'],
  Economics: ['Markets', 'Monetary Policy', 'Trade', 'Corporate'],
  Technology: ['AI', 'Big Tech', 'Cybersecurity', 'Space'],
}

export default function Feed({ topic, subtopic }) {
  const { data, error, loading, reload } = useFetch(listPath(topic, subtopic))
  const { pull, refreshing, ready } = usePullToRefresh(reload)
  const [why, setWhy] = useState(null)
  const title = topic ? TITLES[topic] ?? topic : 'Top stories'
  const items = data?.items ?? []
  const showSkeleton = loading && !data

  return (
    <>
      <header className="sticky top-0 z-20 border-b border-line bg-bg/95 backdrop-blur pt-safe">
        <div className="flex min-h-[52px] items-center justify-between px-safe">
          <h1 className="text-[22px] font-bold tracking-tight">{title}</h1>
          <button type="button" onClick={reload} aria-label="Refresh"
            className="-mr-2 inline-flex h-11 w-11 items-center justify-center rounded-full text-ink-2">
            <RefreshIcon width={22} height={22} className={loading && data ? 'animate-spin' : ''} />
          </button>
        </div>
        {topic && <SubtopicChips topic={topic} subtopic={subtopic} subtopics={data?.subtopics ?? SUBTOPICS[topic]} />}
      </header>

      {/* pull-to-refresh indicator */}
      <div className="flex items-end justify-center overflow-hidden text-ink-3" style={{ height: pull }} aria-hidden={!pull}>
        {pull > 0 && (
          <div className="mb-2 flex items-center gap-2 text-[14px]">
            <RefreshIcon width={18} height={18} className={refreshing ? 'animate-spin' : ''}
              style={{ transform: refreshing ? undefined : `rotate(${pull * 3}deg)` }} />
            {refreshing ? 'Refreshing…' : ready ? 'Release to refresh' : 'Pull to refresh'}
          </div>
        )}
      </div>

      <main className="px-safe pb-6 pt-3" aria-busy={loading}>
        {error && data && <StaleBanner onRetry={reload} />}
        {showSkeleton && (
          <div className="space-y-3" aria-label="Loading">{Array.from({ length: 5 }, (_, i) => <CardSkeleton key={i} />)}</div>
        )}
        {error && !data && <ErrorState error={error} onRetry={reload} />}
        {data && items.length === 0 && (
          <EmptyState
            title="Nothing here yet"
            body={subtopic
              ? `No ${subtopic} events in the last 48 hours.`
              : 'No events have been ranked yet. The pipeline runs every 15 minutes.'}
            onRetry={reload}
          />
        )}
        {items.length > 0 && (
          <ol className="space-y-3">
            {items.map((item, i) => (
              <li key={`${item.kind}-${item.id}`}>
                <EventCard item={item} showTopic={!topic} onWhy={setWhy} eagerImage={i < 2} />
              </li>
            ))}
          </ol>
        )}
      </main>
      <WhySheet item={why} onClose={() => setWhy(null)} />
    </>
  )
}

function SubtopicChips({ topic, subtopic, subtopics }) {
  const rowRef = useRef(null)
  // keep the selected chip in view
  useEffect(() => {
    rowRef.current?.querySelector('[aria-current="page"]')?.scrollIntoView({ block: 'nearest', inline: 'nearest' })
  }, [subtopic, subtopics])
  const chips = [null, ...(subtopics ?? [])]
  return (
    <nav aria-label={`${topic} subtopics`}>
      <ul ref={rowRef} className="no-scrollbar flex gap-2 overflow-x-auto px-safe pb-2.5">
        {chips.map((s) => {
          const on = (s ?? null) === (subtopic ?? null)
          return (
            <li key={s ?? 'all'} className="shrink-0">
              <a
                href={href.topic(topic, s)}
                aria-current={on ? 'page' : undefined}
                className={`inline-flex min-h-[44px] items-center rounded-full border px-4 text-[15px] font-medium ${
                  on ? 'border-ink bg-ink text-bg' : 'border-line bg-surface text-ink-2'}`}
              >
                {s ?? 'All'}
              </a>
            </li>
          )
        })}
      </ul>
    </nav>
  )
}
