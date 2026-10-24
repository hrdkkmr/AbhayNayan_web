const CACHE_NAME = 'abhaynayan-shell-v4';
const APP_SHELL = [
  '/', '/index.html', '/css/app.css', '/js/app.js', '/js/store.js', '/js/vision.js',
  '/js/inference.js', '/js/language.js', '/js/fhir.js', '/manifest.webmanifest',
  '/assets/abhaynayan-mark.svg', '/assets/terms/terms.json', '/js/terms.js', '/js/qr.js', '/js/distribution.js',
  '/js/vendor/qrcode-generator-2.0.4.mjs',
];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
  event.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key)))).then(() => self.clients.claim()));
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith('/api/')) {
    // No API result is cached; synthetic/demo fallback remains in the local app.
    return;
  }
  if (url.pathname === '/assets/terms/terms.json') {
    // Network first, so a new terms version is seen as soon as the device is online; the cached copy keeps it readable offline.
    event.respondWith(fetch(request).then((response) => {
      if (response.ok) { const clone = response.clone(); caches.open(CACHE_NAME).then((cache) => cache.put('/assets/terms/terms.json', clone)); }
      return response;
    }).catch(() => caches.match('/assets/terms/terms.json').then((cached) => cached || new Response('Offline', { status: 503 }))));
    return;
  }
  event.respondWith(caches.match(request).then((cached) => cached || fetch(request).then((response) => {
    if (response.ok && (url.pathname.startsWith('/js/') || url.pathname.startsWith('/css/') || url.pathname.startsWith('/assets/'))) {
      const clone = response.clone(); caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
    }
    return response;
  }).catch(() => request.mode === 'navigate' ? caches.match('/index.html') : new Response('Offline', { status: 503 }))));
});
