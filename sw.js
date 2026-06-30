const CACHE = 'mdn-v21';
const ASSETS = [
  './',
  './index.html',
  './manifest.json',
  './hot-pot-192.png',
  './hot-pot-512.png',
  'https://cdnjs.cloudflare.com/ajax/libs/react/18.2.0/umd/react.production.min.js',
  'https://cdnjs.cloudflare.com/ajax/libs/react-dom/18.2.0/umd/react-dom.production.min.js',
  'https://cdnjs.cloudflare.com/ajax/libs/babel-standalone/7.23.9/babel.min.js',
  'https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js'
];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(ASSETS)));
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))));
  self.clients.claim();
});

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  let url;
  try { url = new URL(req.url); } catch (err) { return; }
  const esApp = req.mode === 'navigate' || url.pathname.endsWith('/') || url.pathname.endsWith('index.html') || url.pathname.endsWith('manifest.json');
  if (esApp) {
    // network-first: SIEMPRE la ultima version si hay internet, cache solo offline
    e.respondWith(
      fetch(req).then(res => { const clone = res.clone(); caches.open(CACHE).then(c => c.put(req, clone)); return res; })
        .catch(() => caches.match(req).then(r => r || caches.match('./index.html')))
    );
  } else {
    // cache-first para CDN y assets (offline-friendly)
    e.respondWith(
      caches.match(req).then(r => r || fetch(req).then(res => { if (res.ok) { const clone = res.clone(); caches.open(CACHE).then(c => c.put(req, clone)); } return res; }))
    );
  }
});