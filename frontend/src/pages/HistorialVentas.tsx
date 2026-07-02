import { useEffect, useMemo, useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'
import { Search, Receipt, Printer, ChevronDown, Banknote, CreditCard, Layers } from 'lucide-react'
import BaristaLayout from '../components/BaristaLayout'
import TicketRecibo, { TicketData } from '../components/TicketRecibo'

interface TItem {
  id: number; producto_id: number; nombre_producto: string
  cantidad: number; precio_unitario: number; subtotal: number; descuento: number
}
interface Ticket {
  id: number; tienda_id: number; caja_turno_id: number; usuario_id: number
  fecha: string; total: number; descuento: number; metodo_pago: string
  monto_efectivo: number; monto_tarjeta: number
  efectivo_recibido: number | null; cambio: number | null
  estado: string; items: TItem[]
}

const fmt = (v: number) => `$${(v ?? 0).toLocaleString('es-CO')}`
// Hora LOCAL: toISOString es UTC y despues de las 19:00 Colombia devuelve manana.
const hoyISO = () => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function parseFecha(raw: string): Date {
  const t = raw.replace(' ', 'T').replace(/(\.\d{3})\d+/, '$1').replace('+00:00', 'Z')
  return new Date(t.endsWith('Z') ? t : t + 'Z')
}

const METODO: Record<string, { label: string; Icon: typeof Banknote; cls: string }> = {
  efectivo: { label: 'Efectivo', Icon: Banknote,   cls: 'bg-green-100 text-green-700' },
  tarjeta:  { label: 'Tarjeta',  Icon: CreditCard, cls: 'bg-blue-100 text-blue-700' },
  mixto:    { label: 'Mixto',    Icon: Layers,     cls: 'bg-purple-100 text-purple-700' },
}

const anulado = (t: Ticket) => t.estado === 'anulado' || t.estado === 'reversado'

/**
 * HISTORIAL DE VENTAS — barista-facing. Consulta ventas del día / histórico con
 * búsqueda instantánea (factura #, producto), filtro por método y rango de fechas.
 * Ver detalle + reimprimir el ticket. Objetivo: encontrar una venta en < 10 s.
 */
export default function HistorialVentas() {
  const { user } = useAuth()
  const [desde, setDesde] = useState(hoyISO())
  const [hasta, setHasta] = useState(hoyISO())
  const [tickets, setTickets] = useState<Ticket[]>([])
  const [loading, setLoading] = useState(false)
  const [q, setQ] = useState('')
  const [metodo, setMetodo] = useState<'todos' | 'efectivo' | 'tarjeta' | 'mixto'>('todos')
  const [expandido, setExpandido] = useState<number | null>(null)
  const [reprint, setReprint] = useState<TicketData | null>(null)

  useEffect(() => {
    if (!user?.tienda_id) return
    setLoading(true)
    api.get<Ticket[]>(`/pos/tickets/historial?tienda_id=${user.tienda_id}&fecha_desde=${desde}&fecha_hasta=${hasta}`)
      .then(r => setTickets(r.data))
      .catch(() => setTickets([]))
      .finally(() => setLoading(false))
  }, [user?.tienda_id, desde, hasta])

  const filtrados = useMemo(() => {
    const term = q.trim().toLowerCase()
    return tickets.filter(t => {
      if (metodo !== 'todos' && t.metodo_pago !== metodo) return false
      if (!term) return true
      if (String(t.id).padStart(6, '0').includes(term) || String(t.id).includes(term)) return true
      return t.items.some(i => i.nombre_producto.toLowerCase().includes(term))
    })
  }, [tickets, q, metodo])

  const totalVendido = filtrados.filter(t => !anulado(t)).reduce((s, t) => s + t.total, 0)
  const nVentas = filtrados.filter(t => !anulado(t)).length

  // Reimpresión: monta el recibo oculto y dispara window.print()
  useEffect(() => {
    if (!reprint) return
    const id = setTimeout(() => window.print(), 80)
    return () => clearTimeout(id)
  }, [reprint])

  const reimprimir = (t: Ticket) => setReprint({
    id: t.id, fecha: t.fecha, total: t.total, cambio: t.cambio ?? 0,
    metodo_pago: (t.metodo_pago as TicketData['metodo_pago']),
    efectivo_recibido: t.efectivo_recibido ?? undefined,
    monto_efectivo: t.monto_efectivo, monto_tarjeta: t.monto_tarjeta,
    items: t.items.map(i => ({
      nombre_producto: i.nombre_producto, cantidad: i.cantidad,
      precio_unitario: i.precio_unitario, subtotal: i.subtotal, descuento: i.descuento,
    })),
  })

  return (
    <BaristaLayout title="Historial de ventas" width="wide">
      <div className="space-y-4">

        {/* Rango de fechas */}
        <div className="flex items-center gap-2">
          <input type="date" value={desde} max={hasta} onChange={e => setDesde(e.target.value)}
            className="flex-1 border-2 border-gray-200 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:border-amber-400" />
          <span className="text-gray-400 text-sm">a</span>
          <input type="date" value={hasta} min={desde} max={hoyISO()} onChange={e => setHasta(e.target.value)}
            className="flex-1 border-2 border-gray-200 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:border-amber-400" />
        </div>

        {/* Búsqueda instantánea */}
        <div className="relative">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <input value={q} onChange={e => setQ(e.target.value)} autoFocus
            placeholder="Buscar por # de factura o producto…"
            className="w-full pl-9 pr-3 py-2.5 border-2 border-gray-200 rounded-xl text-sm focus:outline-none focus:border-amber-400" />
        </div>

        {/* Filtro método */}
        <div className="flex gap-2">
          {(['todos', 'efectivo', 'tarjeta', 'mixto'] as const).map(m => (
            <button key={m} onClick={() => setMetodo(m)}
              className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-colors capitalize ${
                metodo === m ? 'bg-gray-800 text-white' : 'bg-gray-100 text-gray-500 hover:bg-gray-200'
              }`}>{m}</button>
          ))}
        </div>

        {/* Resumen del filtro */}
        <div className="flex items-center justify-between bg-amber-50 border border-amber-200 rounded-xl px-4 py-2.5">
          <span className="text-sm font-semibold text-amber-800">{nVentas} venta{nVentas !== 1 ? 's' : ''}</span>
          <span className="text-sm font-bold text-amber-800 font-mono">{fmt(totalVendido)}</span>
        </div>

        {loading && <p className="text-sm text-gray-400 text-center py-6 animate-pulse">Cargando ventas…</p>}

        {!loading && filtrados.length === 0 && (
          <div className="bg-white border border-gray-200 rounded-2xl px-4 py-10 text-center">
            <Receipt size={28} className="text-gray-300 mx-auto mb-2" />
            <p className="text-sm text-gray-500">No hay ventas para esta búsqueda</p>
          </div>
        )}

        {/* Lista de ventas */}
        <div className="space-y-2">
          {filtrados.map(t => {
            const fecha = parseFecha(t.fecha)
            const m = METODO[t.metodo_pago] ?? METODO.efectivo
            const abierto = expandido === t.id
            const nItems = t.items.reduce((s, i) => s + i.cantidad, 0)
            return (
              <div key={t.id} className={`bg-white border rounded-2xl overflow-hidden ${anulado(t) ? 'border-red-200 opacity-70' : 'border-gray-200'}`}>
                <button onClick={() => setExpandido(abierto ? null : t.id)}
                  className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-gray-50 transition-colors">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-bold text-gray-800">#{String(t.id).padStart(6, '0')}</span>
                      <span className={`text-[10px] px-1.5 py-0.5 rounded-md font-bold inline-flex items-center gap-1 ${m.cls}`}>
                        <m.Icon size={10} /> {m.label}
                      </span>
                      {anulado(t) && <span className="text-[10px] px-1.5 py-0.5 rounded-md font-bold bg-red-100 text-red-600">Anulada</span>}
                    </div>
                    <p className="text-xs text-gray-400 mt-0.5">
                      {fecha.toLocaleDateString('es-CO')} · {fecha.toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit' })}
                      <span className="text-gray-300"> · {nItems} ítem{nItems !== 1 ? 's' : ''}</span>
                    </p>
                  </div>
                  <span className="text-sm font-bold text-gray-800 font-mono shrink-0">{fmt(t.total)}</span>
                  <ChevronDown size={15} className={`text-gray-400 shrink-0 transition-transform ${abierto ? 'rotate-180' : ''}`} />
                </button>

                {abierto && (
                  <div className="border-t border-gray-100 px-4 py-3 space-y-2">
                    <div className="divide-y divide-gray-50">
                      {t.items.map(i => (
                        <div key={i.id} className="flex items-center justify-between py-1.5 text-sm">
                          <span className="text-gray-700">{i.cantidad}× {i.nombre_producto}</span>
                          <span className="text-gray-500 font-mono">{fmt(i.subtotal)}</span>
                        </div>
                      ))}
                    </div>
                    {t.descuento > 0 && (
                      <div className="flex justify-between text-xs text-amber-700">
                        <span>Descuento</span><span className="font-mono">−{fmt(t.descuento)}</span>
                      </div>
                    )}
                    {t.metodo_pago === 'mixto' && (
                      <p className="text-xs text-gray-400">
                        Efectivo {fmt(t.monto_efectivo)} · Tarjeta {fmt(t.monto_tarjeta)}
                      </p>
                    )}
                    {t.metodo_pago === 'efectivo' && t.efectivo_recibido != null && (
                      <p className="text-xs text-gray-400">
                        Recibido {fmt(t.efectivo_recibido)} · Cambio {fmt(t.cambio ?? 0)}
                      </p>
                    )}
                    <button onClick={() => reimprimir(t)}
                      className="w-full flex items-center justify-center gap-2 bg-gray-800 hover:bg-gray-900 text-white text-sm font-bold py-2.5 rounded-xl transition-colors">
                      <Printer size={15} /> Reimprimir ticket
                    </button>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>

      {/* Recibo oculto para imprimir */}
      {reprint && <TicketRecibo ticket={reprint} />}
    </BaristaLayout>
  )
}
