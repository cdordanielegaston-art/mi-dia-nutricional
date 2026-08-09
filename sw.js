const CACHE = 'mdn-v39';

// Lo minimo para que la app abra sin internet. Los CDN NO estan aca a proposito:
// se cachean solos la primera vez que se usan (ver el fetch de abajo).
const ESENCIALES = [
  './',
  './index.html',
  './manifest.json',
  './hot-pot-192.png',
  './hot-pot-512.png'
];

// Se intentan cachear, pero si fallan NO rompen la instalacion.
const OPCIONALES = [
  'https://cdnjs.cloudflare.com/ajax/libs/react/18.2.0/umd/react.production.min.js',
  'https://cdnjs.cloudflare.com/ajax/libs/react-dom/18.2.0/umd/react-dom.production.min.js',
  'https://cdnjs.cloudflare.com/ajax/libs/babel-standalone/7.23.9/babel.min.js',
  'https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js'
];

// ─────────────────────────────────────────────────────────────────────────────
// 2026-08-08 — POR QUE ESTE ARCHIVO CAMBIO (la app no abria en el celular)
//
// Antes decia:  caches.open(CACHE).then(c => c.addAll(ASSETS))
// addAll es TODO O NADA: si UNO de los 9 archivos falla —y 4 son CDN externos,
// en el celular con datos moviles eso pasa— rechaza entero, el service worker
// nuevo NO se instala, y por lo tanto NUNCA corre 'activate', que es justo el
// que borra el cache viejo. Resultado: el celular queda clavado con lo viejo y
// no hay version nueva que lo arregle, porque ninguna llega a instalarse.
//
// Y ademas el fetch cacheaba la respuesta SIN mirar si estaba bien: un 404 o un
// 500 momentaneo de GitHub Pages (pasa mientras se publica) quedaba guardado
// como si fuera la app, y despues se servia eso.
//
// Las dos cosas juntas explican una pantalla en blanco que no se cura sola.
// Ahora: se cachea de a uno tolerando fallas, y solo se guardan respuestas OK.
// ─────────────────────────────────────────────────────────────────────────────

self.addEventListener('install', e => {
  e.waitUntil((async () => {
    const c = await caches.open(CACHE);
    // de a uno y tolerando fallas: que un CDN lento no impida instalar
    await Promise.all(
      ESENCIALES.concat(OPCIONALES).map(u => c.add(u).catch(() => null))
    );
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', e => {
  e.waitUntil((async () => {
    const ks = await caches.keys();
    await Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)));
    await self.clients.claim();
  })());
});

// Permite que la app pida "borrate y arranca de cero" (boton de reparar)
self.addEventListener('message', e => {
  if (e.data === 'RESET') {
    e.waitUntil((async () => {
      const ks = await caches.keys();
      await Promise.all(ks.map(k => caches.delete(k)));
      await self.registration.unregister();
    })());
  }
});

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  let url;
  try { url = new URL(req.url); } catch (err) { return; }

  const esApp = req.mode === 'navigate' || url.pathname.endsWith('/') ||
                url.pathname.endsWith('index.html') || url.pathname.endsWith('manifest.json');

  if (esApp) {
    // network-first: siempre la ultima version si hay internet; el cache es solo el paracaidas
    e.respondWith(
      fetch(req).then(res => {
        if (res && res.ok) {              // <- NUNCA guardar un 404/500 como si fuera la app
          const clone = res.clone();
          caches.open(CACHE).then(c => c.put(req, clone));
        }
        return res;
      }).catch(() => caches.match(req).then(r => r || caches.match('./index.html')))
    );
  } else {
    // cache-first para CDN y assets (para que ande sin internet)
    e.respondWith(
      caches.match(req).then(r => r || fetch(req).then(res => {
        if (res && res.ok) {
          const clone = res.clone();
          caches.open(CACHE).then(c => c.put(req, clone));
        }
        return res;
      }))
    );
  }
});
