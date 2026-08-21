import { useCallback, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Truck } from 'lucide-react'
import api from '../api/client'
import { useDato } from '../api/useDato'
import { FranjaDeConfianza } from '../components/ui'
import { Tienda } from '../components/plata/tipos'
import BannerProveedores from '../components/plata/BannerProveedores'

// ═════════════════════════════════════════════════════════════════════════════
// PAGO A PROVEEDORES — su propia pantalla, fuera de Plata
// ═════════════════════════════════════════════════════════════════════════════
// La plata que sale hacia proveedores volvió a tener pantalla propia (pedido del
// dueño). Antes vivía como pestaña adentro de Plata; con el rediseño del libro,
// Plata quedó para «lo que ya se movió» y el pago de facturas —que es un flujo
// con su propio ritmo (elegir proveedor, ver la deuda, registrar el pago)— pide
// su lugar aparte.
//
// La pantalla NO reimplementa nada: monta el `BannerProveedores` que ya existía,
// que trae su propio dashboard de facturas, sus filtros y el ÚNICO camino real
// para pagarle a un proveedor (`PATCH /facturas/{id}/pago`).
//
// `?factura=ID` en la URL abre esa factura y baja hasta ella: así un enlace desde
// otra parte (un vencido, un recordatorio) aterriza en la factura exacta, no en
// el tope de una lista de cincuenta.

export default function Proveedores() {
  const [params, setParams] = useSearchParams()

  const tiendas = useDato<Tienda[]>(
    () => api.get('/auth/tiendas'), 'las sedes', 'No se pudieron leer las sedes.')

  // `BannerProveedores` recarga su propio dashboard después de cada pago
  // (`refrescar = cargar() + onCambio()`), así que en pantalla propia esto es
  // solo la notificación hacia arriba: no hay más bloques que refrescar.
  const onCambio = useCallback(() => { /* nada que refrescar afuera */ }, [])

  // La factura a abrir viene de la URL (?factura=ID). Se limpia al atenderla para
  // que un refresh no vuelva a saltar a la misma fila.
  const facturaObjetivo = useMemo(() => {
    const raw = params.get('factura')
    const n = raw ? Number(raw) : NaN
    return Number.isInteger(n) && n > 0 ? n : null
  }, [params])

  const onObjetivoAtendido = useCallback(() => {
    setParams(prev => {
      const p = new URLSearchParams(prev)
      p.delete('factura')
      return p
    }, { replace: true })
  }, [setParams])

  const fuentes = useMemo(() => [tiendas], [tiendas])

  return (
    <div className="space-y-3 pb-8">
      <div className="flex items-center gap-2">
        <span className="w-9 h-9 rounded-xl bg-forest-50 text-forest flex items-center justify-center shrink-0">
          <Truck size={19} />
        </span>
        <div>
          <h1 className="text-lg font-bold text-warm-700">Pago a proveedores</h1>
          <p className="text-xs text-warm-500">
            Las facturas de mercancía y su deuda: elegí el proveedor, mirá lo que se debe y registrá el pago.
          </p>
        </div>
      </div>

      <FranjaDeConfianza fuentes={fuentes} />

      <BannerProveedores
        tiendas={tiendas}
        facturaObjetivo={facturaObjetivo}
        onObjetivoAtendido={onObjetivoAtendido}
        onCambio={onCambio} />
    </div>
  )
}
