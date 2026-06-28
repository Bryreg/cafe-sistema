import api from '../api/client'

export type EstadoPush = 'unsupported' | 'denied' | 'default' | 'suscrito'

/**
 * Convierte la VAPID public key (base64url) al ArrayBuffer que espera
 * pushManager.subscribe({ applicationServerKey }). Helper estándar de web-push.
 * Devuelve ArrayBuffer (no Uint8Array) para satisfacer BufferSource en TS 5.7+,
 * donde Uint8Array es genérico sobre su buffer (ArrayBufferLike).
 */
function urlBase64ToUint8Array(base64String: string): ArrayBuffer {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4)
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/')
  const rawData = atob(base64)
  const buffer = new ArrayBuffer(rawData.length)
  const outputArray = new Uint8Array(buffer)
  for (let i = 0; i < rawData.length; i++) {
    outputArray[i] = rawData.charCodeAt(i)
  }
  return buffer
}

function pushSoportado(): boolean {
  return 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window
}

/**
 * navigator.serviceWorker.ready NUNCA resuelve si no hay un SW registrado (en
 * `vite dev` el SW de injectManifest no se sirve, y en algún navegador el
 * registro puede no completar). Lo corremos contra un timeout para que la UI
 * jamás quede colgada esperando.
 */
function swReady(timeoutMs = 3000): Promise<ServiceWorkerRegistration | null> {
  return Promise.race([
    navigator.serviceWorker.ready,
    new Promise<null>((resolve) => setTimeout(() => resolve(null), timeoutMs)),
  ])
}

/**
 * Estado actual del canal push en ESTE dispositivo/navegador.
 * - "unsupported": el navegador no soporta SW + Push (p.ej. iPhone fuera de PWA instalada).
 * - "denied": el usuario bloqueó las notificaciones.
 * - "default": soportado pero aún sin permiso/suscripción.
 * - "suscrito": permiso concedido y suscripción activa registrada.
 */
export async function estadoPush(): Promise<EstadoPush> {
  if (!pushSoportado()) return 'unsupported'
  if (Notification.permission === 'denied') return 'denied'

  const reg = await swReady()
  if (!reg) return 'default'  // SW aún no activo (dev o registro pendiente)
  const sub = await reg.pushManager.getSubscription()
  if (sub && Notification.permission === 'granted') return 'suscrito'

  return 'default'
}

/**
 * Pide permiso, se suscribe al PushManager con la VAPID key del backend y
 * registra la suscripción para esta tienda. Lanza Error si no se concede.
 */
export async function activarPush(tiendaId: number): Promise<EstadoPush> {
  if (!pushSoportado()) {
    throw new Error('Este dispositivo no soporta notificaciones push.')
  }

  const permiso = await Notification.requestPermission()
  if (permiso !== 'granted') {
    throw new Error('Permiso de notificaciones denegado.')
  }

  const reg = await swReady(8000)
  if (!reg) {
    throw new Error('El service worker no está listo. Recargá la página e intentá de nuevo.')
  }
  const publicKey = (await api.get('/notificaciones/push/public-key')).data.public_key as string

  const sub = await reg.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: urlBase64ToUint8Array(publicKey),
  })

  await api.post('/notificaciones/push/subscribe', {
    tienda_id: tiendaId,
    subscription: sub.toJSON(),
  })

  return 'suscrito'
}

/**
 * Cancela la suscripción de este dispositivo: avisa al backend y la elimina
 * del navegador.
 */
export async function desactivarPush(): Promise<void> {
  if (!pushSoportado()) return

  const reg = await swReady(8000)
  if (!reg) return
  const sub = await reg.pushManager.getSubscription()
  if (!sub) return

  await api.delete('/notificaciones/push/unsubscribe', { data: { endpoint: sub.endpoint } })
  await sub.unsubscribe()
}
