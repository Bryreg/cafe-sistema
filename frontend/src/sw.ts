/// <reference lib="webworker" />
import { precacheAndRoute } from 'workbox-precaching'

declare const self: ServiceWorkerGlobalScope & typeof globalThis

// Precache generado por vite-plugin-pwa (estrategia injectManifest).
precacheAndRoute(self.__WB_MANIFEST)

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
