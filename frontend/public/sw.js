// Service worker: app shell cached for offline start; API is network-first with the
// last good response as an offline fallback; static assets are stale-while-revalidate.
const VERSION = 'v1'
const SHELL = `shell-${VERSION}`
const RUNTIME = `runtime-${VERSION}`
const API = `api-${VERSION}`
const PRECACHE = ['/', '/manifest.webmanifest', '/icons/icon-192.png', '/icons/icon.svg']

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => c.addAll(PRECACHE)).then(() => self.skipWaiting()))
})

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => ![SHELL, RUNTIME, API].includes(k)).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  )
})

async function networkFirst(req, cacheName) {
  const cache = await caches.open(cacheName)
  try {
    const res = await fetch(req)
    if (res.ok) cache.put(req, res.clone())
    return res
  } catch (err) {
    const hit = await cache.match(req)
    if (hit) return hit
    throw err
  }
}

async function staleWhileRevalidate(req) {
  const cache = await caches.open(RUNTIME)
  const hit = await cache.match(req)
  const fresh = fetch(req).then((res) => { if (res.ok) cache.put(req, res.clone()); return res }).catch(() => hit)
  return hit || fresh
}

self.addEventListener('fetch', (e) => {
  const req = e.request
  const url = new URL(req.url)
  if (req.method !== 'GET' || url.origin !== location.origin) return   // article links etc. go straight out
  if (url.pathname.startsWith('/api/')) return e.respondWith(networkFirst(req, API))
  if (req.mode === 'navigate') {
    return e.respondWith(networkFirst(req, SHELL).catch(() => caches.match('/')))
  }
  e.respondWith(staleWhileRevalidate(req))
})
