// Service worker mínimo: habilita la instalación (PWA) y da fallback offline.
// Estrategia network-first para estáticos del mismo origen → SIEMPRE fresco online
// (sin staleness), y si no hay red sirve la última copia cacheada. La API (/api/)
// no se toca (siempre va a la red); los POST tampoco se cachean.
const CACHE = 'biblio-shell-v9';

self.addEventListener('install', (e) => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil((async () => {
  // borra cachés de versiones anteriores (evita servir estáticos viejos)
  const keys = await caches.keys();
  await Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)));
  await self.clients.claim();
})()));

self.addEventListener('fetch', (e) => {
  const req = e.request;
  const url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== location.origin) return;  // solo GET mismo origen
  if (url.pathname.startsWith('/api/')) return;                        // la API va siempre a la red
  e.respondWith(
    fetch(req)
      .then((res) => {
        if (res && res.ok) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy));
        }
        return res;
      })
      .catch(() => caches.match(req))   // sin red → última copia cacheada
  );
});

// --- Web Push: avisos de vencimiento al celular ---
self.addEventListener('push', (e) => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (_) {}
  const title = d.title || '📚 Biblioteca';
  const body = d.body || 'Tenés un aviso de la biblioteca.';
  const url = d.url || '/credencial.html';
  e.waitUntil(self.registration.showNotification(title, {
    body,
    icon: '/icon-192.png',
    badge: '/icon-192.png',
    tag: 'biblio-vencimiento',   // reemplaza el aviso anterior en vez de apilar
    data: { url },
  }));
});

self.addEventListener('notificationclick', (e) => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || '/credencial.html';
  e.waitUntil((async () => {
    const wins = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (const w of wins) {
      if (w.url.includes(url) && 'focus' in w) return w.focus();
    }
    if (self.clients.openWindow) return self.clients.openWindow(url);
  })());
});
