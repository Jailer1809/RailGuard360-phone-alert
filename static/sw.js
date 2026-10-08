const CACHE_NAME = "railguard-v3";
const ASSETS = [
  "/",
  "/receiver",
  "/app.js",
  "/detector.js",
  "/manifest.json",
  "/railguard-icon.svg"
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(ASSETS)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then(keys => Promise.all(
    keys.filter(key => key.startsWith("railguard-") && key !== CACHE_NAME).map(key => caches.delete(key))
  )).then(() => clients.claim()));
});

self.addEventListener("fetch", (e) => {
  // Let network handle API requests directly
  if (e.request.url.includes("/api/")) {
    return;
  }
  e.respondWith(
    fetch(e.request).then(response => {
      if (response.ok && new URL(e.request.url).origin === self.location.origin) {
        const copy = response.clone();
        caches.open(CACHE_NAME).then(cache => cache.put(e.request, copy));
      }
      return response;
    }).catch(() => caches.match(e.request))
  );
});
