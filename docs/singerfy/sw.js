// Singerfy: siempre trae la página nueva de la red (sin la copia guardada); sin conexión, usa la última que tenga.
const CACHE = "singerfy-v12";
self.addEventListener("install", (e) => { self.skipWaiting(); e.waitUntil(caches.open(CACHE).then((c) => c.addAll(["./", "manifest.webmanifest", "icono-192.png", "apple-touch-icon.png"]))); });
self.addEventListener("activate", (e) => e.waitUntil((async () => { for (const k of await caches.keys()) if (k !== CACHE) await caches.delete(k); await self.clients.claim(); })()));
self.addEventListener("fetch", (e) => {
  if (e.request.method !== "GET") return;
  const pagina = e.request.mode === "navigate" || /\/(index\.html)?(\?.*)?$/.test(new URL(e.request.url).pathname + new URL(e.request.url).search) || e.request.url.includes("version.json");
  e.respondWith(fetch(e.request, pagina ? { cache: "no-store" } : {}).then((r) => { const copia = r.clone(); caches.open(CACHE).then((c) => c.put(e.request, copia)); return r; }).catch(() => caches.match(e.request, { ignoreSearch: true })));
});
