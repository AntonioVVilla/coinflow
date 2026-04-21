// Minimal service worker for PWA installability
// Strategy: network-first for API calls, cache-first for static shell and
// pinned CDN libraries. Bump CACHE whenever the shell changes so clients
// pick up the new assets instead of holding onto stale copies.
const CACHE = 'cryptobot-v2';

// Static shell served from the app's own origin.
const SHELL = [
  '/',
  '/static/css/style.css',
  '/static/js/app.js',
  '/static/manifest.json',
];

// Third-party libraries we want available offline. The URLs must match the
// exact ones referenced from index.html (including query strings / integrity)
// or the cache lookup will miss.
const VENDOR = [
  'https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js',
  'https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3/dist/chartjs-adapter-date-fns.bundle.min.js',
  'https://cdn.jsdelivr.net/npm/chartjs-chart-financial@0.2.1/dist/chartjs-chart-financial.min.js',
  'https://cdn.jsdelivr.net/npm/hammerjs@2.0.8/hammer.min.js',
  'https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@2.0.1/dist/chartjs-plugin-zoom.min.js',
  'https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE).then((c) =>
      Promise.all([
        c.addAll(SHELL).catch(() => {}),
        // Vendor URLs are cached opportunistically — if the CDN is down at
        // install time we don't want the SW install itself to fail.
        ...VENDOR.map((u) => fetch(u, { mode: 'no-cors' }).then((r) => c.put(u, r)).catch(() => {})),
      ])
    )
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  // Never cache API or WebSocket requests
  if (url.pathname.startsWith('/api/') || url.pathname === '/ws') {
    return; // let it go to network
  }
  // Cache-first for our own static assets
  if (url.pathname.startsWith('/static/') || url.pathname === '/') {
    event.respondWith(cacheFirst(event.request));
    return;
  }
  // Cache-first for the pinned CDN dependencies we shipped above.
  if (VENDOR.includes(event.request.url)) {
    event.respondWith(cacheFirst(event.request));
  }
});

function cacheFirst(req) {
  return caches.match(req).then((cached) =>
    cached || fetch(req).then((resp) => {
      if (resp.ok) {
        const copy = resp.clone();
        caches.open(CACHE).then((c) => c.put(req, copy));
      }
      return resp;
    })
  );
}
