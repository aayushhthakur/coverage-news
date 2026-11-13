import { timeAgo, sourcesLabel } from '../format'
import { href } from '../router'
import { ChevronIcon, LayersIcon } from './Icons'
import { CardImage } from './Photo'
import { topicClass } from '../topics'

const TOPIC_SHORT = { Technology: 'Tech' }

export default function EventCard({ item, showTopic, onWhy, eagerImage = false }) {
  const isStory = item.kind === 'story'
  return (
    <article className={`${topicClass(item.topic)} relative overflow-hidden rounded-2xl border border-line border-t-[3px] border-t-topic bg-surface shadow-[0_1px_0_rgba(0,0,0,0.02)]`}>
      {item.image && <CardImage image={item.image} eager={eagerImage} />}
      <div className="p-4">
        {(item.breaking || isStory || showTopic) && (
          <div className="mb-2 flex flex-wrap items-center gap-2 text-[13px] font-semibold">
            {item.breaking && (
              <span className="rounded-full bg-breaking px-2 py-0.5 uppercase tracking-wide text-white dark:text-black">Breaking</span>
            )}
            {isStory && (
              <span className="inline-flex items-center gap-1 rounded-full bg-topic/12 px-2 py-0.5 text-topic">
                <LayersIcon width={14} height={14} /> {item.label}
              </span>
            )}
            {showTopic && <span className="text-topic">{TOPIC_SHORT[item.topic] ?? item.topic}</span>}
          </div>
        )}

        <h2 className="line-clamp-3 text-[18px] font-semibold leading-snug">
          {/* stretched link: the whole card opens the event screen */}
          <a href={href.item(item.kind, item.id)} className="after:absolute after:inset-0 after:rounded-2xl after:content-['']">
            {item.headline}
          </a>
        </h2>
        {item.summary && <p className="mt-1.5 text-[16px] leading-relaxed text-ink-2">{item.summary}</p>}

        <div className="mt-3 flex items-center justify-between gap-3">
          <p className="min-w-0 truncate text-[14px] text-ink-3">
            <span className="font-medium text-ink-2">{item.publisher}</span> · {timeAgo(item.first_reported_at)}
          </p>
          <button
            type="button"
            onClick={() => onWhy(item)}
            aria-label={`${sourcesLabel(item.sources)}. Why this is ranked here`}
            className="relative z-10 -my-1 -mr-2 inline-flex min-h-[44px] shrink-0 items-center gap-1 rounded-full px-2"
          >
            <span className="rounded-full bg-surface-2 px-3 py-1 text-[14px] font-semibold text-ink">
              {sourcesLabel(item.sources)}
            </span>
            <ChevronIcon width={16} height={16} className="text-ink-3" />
          </button>
        </div>
      </div>
    </article>
  )
}

export function CardSkeleton() {
  return (
    <div className="animate-pulse rounded-2xl border border-line bg-surface p-4" aria-hidden="true">
      <div className="h-5 w-11/12 rounded bg-skeleton" />
      <div className="mt-2 h-5 w-3/4 rounded bg-skeleton" />
      <div className="mt-3 h-4 w-full rounded bg-skeleton" />
      <div className="mt-2 h-4 w-5/6 rounded bg-skeleton" />
      <div className="mt-4 flex justify-between">
        <div className="h-4 w-1/3 rounded bg-skeleton" />
        <div className="h-6 w-24 rounded-full bg-skeleton" />
      </div>
    </div>
  )
}
