import { href } from '../router'
import { topicClass } from '../topics'
import { ChartIcon, ChipIcon, GlobeIcon, HomeIcon, TrophyIcon } from './Icons'

const TABS = [
  { key: 'home', label: 'Home', topic: null, Icon: HomeIcon },
  { key: 'Geopolitics', label: 'Geopolitics', topic: 'Geopolitics', Icon: GlobeIcon },
  { key: 'Sports', label: 'Sports', topic: 'Sports', Icon: TrophyIcon },
  { key: 'Economics', label: 'Economics', topic: 'Economics', Icon: ChartIcon },
  { key: 'Technology', label: 'Tech', topic: 'Technology', Icon: ChipIcon },
]

export default function TabBar({ active }) {
  return (
    <nav aria-label="Sections" className="fixed inset-x-0 bottom-0 z-30 border-t border-line bg-surface/95 backdrop-blur pb-safe">
      <ul className="mx-auto grid max-w-[480px] grid-cols-5">
        {TABS.map((tab) => {
          const { key, label, topic } = tab
          const on = active === key
          return (
            <li key={key}>
              <a
                href={topic ? href.topic(topic) : href.home()}
                aria-current={on ? 'page' : undefined}
                className={`${topicClass(topic)} flex min-h-[56px] flex-col items-center justify-center gap-0.5 text-[12px] font-medium ${on ? 'text-topic' : 'text-ink-3'}`}
              >
                <tab.Icon width={24} height={24} strokeWidth={on ? 2.2 : 1.8} />
                <span>{label}</span>
              </a>
            </li>
          )
        })}
      </ul>
    </nav>
  )
}
