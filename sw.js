/* Virtual Dyno service worker: it is what lets the installed app open with no signal (at the track, in a garage).
   Same-origin files are fetched from the network first, so a new deploy shows up at once, and the copy kept here is
   used only when the network fails or takes longer than 4 s. Anything on another origin (Open-Meteo) is left alone and
   goes straight to the network. Bump V only when the list below changes; a changed file needs no bump. */
const V = 'dyno-v1';
const CORE = ['./', 'index.html', 'manifest.webmanifest', 'fonts/vt323-latin-400-normal.woff2',
  'icons/icon-192.png', 'icons/icon-512.png', 'icons/icon-maskable-512.png', 'icons/apple-touch-icon.png'];

self.addEventListener('install', e => e.waitUntil(
  caches.open(V).then(c => c.addAll(CORE)).then(() => self.skipWaiting())));

self.addEventListener('activate', e => e.waitUntil(
  caches.keys().then(ks => Promise.all(ks.filter(k => k !== V).map(k => caches.delete(k)))).then(() => self.clients.claim())));

const network = (req, ms) => new Promise((ok, no) => {
  const t = setTimeout(() => no(new Error('slow')), ms);
  fetch(req).then(r => { clearTimeout(t); ok(r) }, er => { clearTimeout(t); no(er) });
});

self.addEventListener('fetch', e => {
  const r = e.request;
  if (r.method !== 'GET' || new URL(r.url).origin !== location.origin) return;
  e.respondWith(network(r, 4000).then(res => {
    if (res.ok) { const copy = res.clone(); caches.open(V).then(c => c.put(r, copy)) }
    return res;
  }).catch(() => caches.match(r, { ignoreSearch: true })
    .then(m => m || (r.mode === 'navigate' ? caches.match('index.html') : Response.error()))));
});
