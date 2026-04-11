// Minimal service worker for PWA installability.
// No caching — this app requires a live server connection (SSE).
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
