const SHELL_CACHE = 'orderflow-shell-v2'
const CATALOGUE_CACHE = 'orderflow-catalogue-v1'
const IMAGE_CACHE = 'orderflow-images-v1'
const SHELL_URLS = ['/', '/manifest.webmanifest', '/orderflow-icon.svg']

async function putWithLimit(cache, request, response, maxEntries) {
  await cache.put(request, response)
  const keys = await cache.keys()
  const overflow = keys.length - maxEntries
  if (overflow > 0) {
    await Promise.all(keys.slice(0, overflow).map((key) => cache.delete(key)))
  }
}

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE)
      .then((cache) => cache.addAll(SHELL_URLS))
      .then(() => self.skipWaiting()),
  )
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys
          .filter((key) => ![SHELL_CACHE, CATALOGUE_CACHE, IMAGE_CACHE].includes(key))
          .map((key) => caches.delete(key)),
      ))
      .then(() => self.clients.claim()),
  )
})

self.addEventListener('fetch', (event) => {
  const request = event.request
  if (request.method !== 'GET') return

  const url = new URL(request.url)

  if (url.origin === self.location.origin && url.pathname === '/api/catalogue') {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok) {
            const copy = response.clone()
            void caches.open(CATALOGUE_CACHE).then((cache) => cache.put(request, copy))
          }
          return response
        })
        .catch(async () => {
          const cached = await caches.match(request)
          return cached ?? new Response(
            JSON.stringify({ detail: 'Catalogue is not cached for offline use yet.' }),
            { status: 503, headers: { 'Content-Type': 'application/json' } },
          )
        }),
    )
    return
  }

  if (url.origin === self.location.origin && url.pathname.startsWith('/assets/')) {
    event.respondWith(
      caches.open(SHELL_CACHE).then(async (cache) => {
        const cached = await cache.match(request)
        if (cached) return cached
        const response = await fetch(request)
        if (response.ok) await cache.put(request, response.clone())
        return response
      }),
    )
    return
  }

  if (url.hostname === 'images.unsplash.com') {
    event.respondWith(
      caches.open(IMAGE_CACHE).then(async (cache) => {
        const cached = await cache.match(request)
        if (cached) return cached
        const response = await fetch(request)
        if (response.ok || response.type === 'opaque') {
          await putWithLimit(cache, request, response.clone(), 60)
        }
        return response
      }),
    )
    return
  }

  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request).catch(async () => {
        const cached = await caches.match('/')
        return cached ?? Response.error()
      }),
    )
  }
})