import { useEffect, useRef } from 'react'
import Detail from './components/Detail'
import Feed from './components/Feed'
import TabBar from './components/TabBar'
import { useRoute } from './router'

export default function App() {
  const route = useRoute()
  // the tab stays highlighted while viewing an event opened from it
  const lastTab = useRef('home')
  if (route.name === 'home') lastTab.current = 'home'
  if (route.name === 'topic') lastTab.current = route.topic

  useEffect(() => { window.scrollTo(0, 0) }, [route.name, route.topic, route.subtopic, route.id])

  return (
    <div className="mx-auto min-h-dvh max-w-[480px] bg-bg pb-[calc(64px+env(safe-area-inset-bottom))] min-[481px]:border-x min-[481px]:border-line">
      {route.name === 'detail'
        ? <Detail key={`${route.kind}-${route.id}`} kind={route.kind} id={route.id} />
        : <Feed key={route.topic ?? 'home'} topic={route.name === 'topic' ? route.topic : null} subtopic={route.subtopic} />}
      <TabBar active={lastTab.current} />
    </div>
  )
}
