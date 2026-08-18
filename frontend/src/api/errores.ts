import axios from 'axios'

/**
 * El mensaje de error del backend, TAL CUAL.
 *
 * Los `detail` de los routers están escritos para que el dueño sepa qué
 * corregir ("El monto va en positivo: el signo lo decide si es entrada o
 * salida"). Reemplazarlos por un "hubo un error" genérico es tirar la única
 * parte del error que sirve. El fallback es solo para cuando no hay respuesta
 * (se cayó la red, se cayó el server).
 *
 * Vivía en `components/plata/banco.ts`, que es una capa de vista. Subió acá
 * porque `api/useDato.ts` la necesita y la capa de datos no puede depender de
 * `components/`. `banco.ts` la re-exporta para no tocar sus diez consumidores.
 */
export function detalleDeError(e: unknown, fallback: string): string {
  if (axios.isAxiosError(e)) {
    const data = e.response?.data as { detail?: unknown } | undefined
    if (typeof data?.detail === 'string' && data.detail.trim()) return data.detail
  }
  return fallback
}
