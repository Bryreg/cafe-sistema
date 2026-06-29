/// <reference lib="webworker" />
import { precacheAndRoute } from 'workbox-precaching'
import { registerRoute } from 'workbox-routing'
import { NetworkFirst } from 'workbox-strategies'
import { ExpirationPlugin } from 'workbox-expiration'
import { CacheableResponsePlugin } from 'workbox-cacheable-response'

declare const self: ServiceWorkerGlobalScope & typeof globalThis

// Precache generado por vite-plugin-pwa (estrategia injectManifest).
precacheAndRoute(self.__WB_MANIFEST)

// Resiliencia offline para GETs de catálogo/inventario/tiendas (NetworkFirst:
// usa red con 5s de timeout y cae al cache si no hay conexión). Replica el
// runtimeCaching que existía con generateSW. Matchea por `pathname`, así también
// cubre el backend cross-origin en prod (Render), no solo el proxy same-origin.
registerRoute(
  ({ url, request }) =>
    request.method === 'GET' &&
    /^\/api\/v1\/(auth\/tiendas|inventario|catalogo)/.test(url.pathname),
  new NetworkFirst({
    cacheName: 'api-cache',
    networkTimeoutSeconds: 5,
    plugins: [
      new CacheableResponsePlugin({ statuses: [0, 200] }),
      new ExpirationPlugin({ maxEntries: 50, maxAgeSeconds: 60 * 60 }),
    ],
  }),
)

interface PushPayload {
  title?: string
  body?: string
  url?: string
  icon?: string
}

// ── Push: mostrar la notificación del sistema ───────────────────────────────
self.addEventListener('push', (event) => {
  let payload: PushPayload = {}
  try {
    payload = event.data?.json() ?? {}
  } catch {
    payload = { body: event.data?.text() }
  }
  const { title, body, url, icon } = payload
  event.waitUntil(
    self.registration.showNotification(title || 'Sistema Café', {
      body,
      icon: icon || '/icon-192.png',
      badge: '/icon-192.png',
      data: { url: url || '/dashboard' },
    }),
  )
})

// ── Click en la notificación: enfocar o abrir la ventana correcta ───────────
self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const targetUrl = (event.notification.data as { url?: string })?.url || '/dashboard'
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((windowClients) => {
      for (const client of windowClients) {
        if ('focus' in client) {
          client.focus()
          if ('navigate' in client) client.navigate(targetUrl)
          return
        }
      }
      return self.clients.openWindow(targetUrl)
    }),
  )
})

// ── Activación inmediata del SW nuevo ───────────────────────────────────────
self.addEventListener('install', () => {
  self.skipWaiting()
})
self.addEventListener('activate', () => {
  self.clients.claim()
})
