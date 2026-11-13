import { useEffect, useState } from 'react'

// Hash routes:  #/   #/t/<Topic>   #/t/<Topic>/<Subtopic>   #/e/<id>   #/s/<id>
export function parse(hash) {
  const parts = hash.replace(/^#\/?/, '').split('/').filter(Boolean).map(decodeURIComponent)
  if (parts[0] === 't' && parts[1]) return { name: 'topic', topic: parts[1], subtopic: parts[2] ?? null }
  if (parts[0] === 'e' && parts[1]) return { name: 'detail', kind: 'event', id: Number(parts[1]) }
  if (parts[0] === 's' && parts[1]) return { name: 'detail', kind: 'story', id: Number(parts[1]) }
  return { name: 'home' }
}

export const href = {
  home: () => '#/',
  topic: (t, s) => `#/t/${encodeURIComponent(t)}${s ? `/${encodeURIComponent(s)}` : ''}`,
  item: (kind, id) => `#/${kind === 'story' ? 's' : 'e'}/${id}`,
}

export function useRoute() {
  const [route, setRoute] = useState(() => parse(location.hash))
  useEffect(() => {
    const on = () => setRoute(parse(location.hash))
    addEventListener('hashchange', on)
    return () => removeEventListener('hashchange', on)
  }, [])
  return route
}
