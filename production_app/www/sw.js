/* Production Workspace service worker (FU42).
 * Served at /sw.js (scope /) as a plain www template, same mechanism as robots.txt.
 * Strategy: network-first for the app shell and the workspace bundle (filenames are
 * fixed, no hash) so a normal reload always gets the freshest build online, with the
 * cached copy as the offline fallback. Icons/manifest are cache-first. API, socket,
 * private files and non-GET requests are never intercepted: production and handover
 * actions are server-truth transactions and must always hit the network.
 */
const VERSION = 'production-workspace-v1';
const SHELL_CACHE = VERSION + '-shell';
const STATIC_CACHE = VERSION + '-static';
const SHELL_URLS = [
  '/production_workspace',
  '/assets/production_app/workspace/assets/index.js',
  '/assets/production_app/workspace/assets/index.css',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(SHELL_CACHE)
      .then((cache) =>
        // Hosts may serve assets with long-lived immutable cache headers;
        // precache must revalidate or a new install could copy a stale file.
        cache.addAll(
          SHELL_URLS.map((url) => new Request(url, { cache: 'no-cache' }))
        )
      )
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => key.indexOf(VERSION) !== 0)
            .map((key) => caches.delete(key))
        )
      )
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (
    url.pathname.indexOf('/api/') === 0 ||
    url.pathname.indexOf('/socket.io') === 0 ||
    url.pathname.indexOf('/private/') === 0
  ) {
    return;
  }

  if (request.mode === 'navigate') {
    event.respondWith(networkFirst(request, SHELL_CACHE, true));
    return;
  }
  if (url.pathname.indexOf('/assets/production_app/workspace/assets/') === 0) {
    event.respondWith(networkFirst(request, SHELL_CACHE, false));
    return;
  }
  if (url.pathname.indexOf('/assets/production_app/') === 0) {
    event.respondWith(cacheFirst(request, STATIC_CACHE));
  }
});

async function networkFirst(request, cacheName, isNavigation) {
  const cache = await caches.open(cacheName);
  try {
    // Navigations already come back no-cache from the www page; the fixed-name
    // bundle/css may sit behind immutable HTTP caches, so revalidate them.
    const response = await fetch(
      isNavigation ? request : new Request(request, { cache: 'no-cache' })
    );
    if (response && response.ok) {
      cache.put(request, response.clone());
    }
    return response;
  } catch (err) {
    const cached = await cache.match(request, { ignoreSearch: isNavigation });
    if (cached) return cached;
    return new Response('Offline', {
      status: 503,
      statusText: 'Offline',
      headers: { 'Content-Type': 'text/plain' },
    });
  }
}

async function cacheFirst(request, cacheName) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (response && response.ok) {
    cache.put(request, response.clone());
  }
  return response;
}
