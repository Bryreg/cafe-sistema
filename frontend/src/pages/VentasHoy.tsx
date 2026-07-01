import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { TrendingUp, CreditCard, Banknote, ShoppingBag, Clock, Coffee } from 'lucide-react'
import { useTurno } from '../contexts/TurnoContext'
import api from '../api/client'
import BaristaLayout from '../components/BaristaLayout'
import { StatTile, Card, SectionLabel, Pill, Toast } from '../components/ui'

// ─── Types ───────────────────────────────────────────────────────────────────

interface TicketItem {
  nombre_producto: string
  cantidad: number
  precio_unitario: number
  subtotal: number
}

interface Ticket {
  id: number
  fecha: string
  total: number
  metodo_pago: 'efectivo' | 'tarjeta' | 'mixto'
  monto_efectivo: number | null
  monto_tarjeta: number | null
  items: TicketItem[]
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

const fmt = (v: number) => `$${v.toLocaleString('es-CO')}`

function fmtHora(iso: string) {
  const d = new Date(iso)
  return d.toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit', hour12: false })
}

function resumenItems(items: TicketItem[]): string {
  if (items.length === 0) return '—'
  if (items.length === 1) return items[0].nombre_producto
  const primer = items[0].nombre_producto.split(' ')[0]
  return `${primer} + ${items.length - 1} más`
}

function metodoPagoLabel(m: Ticket['metodo_pago']) {
  if (m === 'efectivo') return 'Efectivo'
  if (m === 'tarjeta') return 'Tarjeta'
  return 'Mixto'
}

function metodoPagoTone(m: Ticket['metodo_pago']): 'success' | 'clay' | 'gold' {
  if (m === 'efectivo') return 'success'
  if (m === 'tarjeta') return 'clay'
  return 'gold'
}

// ─── Guard: sin turno activo ──────────────────────────────────────────────────

function SinTurno() {
  const navigate = useNavigate()
  return (
    <div className="min-h-screen bg-warm-50 flex flex-col items-center justify-center gap-4 px-6">
      <Coffee size={40} className="text-warm-300" />
      <p className="text-sm font-semibold text-warm-500 text-center">
        No hay turno activo. Abrí un turno para ver tus ventas.
      </p>
      <button
        onClick={() => navigate('/')}
        className="px-4 py-2 rounded-xl bg-forest text-white text-sm font-semibold"
      >
        Ir al inicio
      </button>
    </div>
  )
}

// ─── Componente principal ─────────────────────────────────────────────────────

export default function VentasHoy() {
  const { turno } = useTurno()

  const [tickets, setTickets] = useState<Ticket[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!turno) { setLoading(false); return }
    setLoading(true)
    api.get<Ticket[]>('/pos/tickets', { params: { turno_id: turno.id } })
      .then(r => setTickets(r.data))
      .catch(() => setError('No se pudieron cargar los tickets. Intentá de nuevo.'))
      .finally(() => setLoading(false))
  }, [turno?.id])

  if (!turno) return <SinTurno />

  // KPIs calculados client-side
  const totalTurno = tickets.reduce((s, t) => s + t.total, 0)
  const totalEfectivo = tickets.reduce((s, t) => s + (t.monto_efectivo ?? (t.metodo_pago === 'efectivo' ? t.total : 0)), 0)
  const totalTarjeta = tickets.reduce((s, t) => s + (t.monto_tarjeta ?? (t.metodo_pago === 'tarjeta' ? t.total : 0)), 0)
  const nVentas = tickets.length

  return (
    <BaristaLayout title="Mis ventas del turno">
      {/* Error */}
      {error && (
        <Toast tone="danger" duration={5000} onDismiss={() => setError(null)} className="mb-4">
          {error}
        </Toast>
      )}

      {/* KPIs */}
      <div className="grid grid-cols-2 gap-3 mb-6">
        <StatTile
          label="Total del turno"
          value={fmt(totalTurno)}
          tint="success"
          className="col-span-2"
        />
        <StatTile
          label="Ventas"
          value={nVentas}
          sublabel="tickets"
          tint="neutral"
        />
        <StatTile
          label="Efectivo"
          value={fmt(totalEfectivo)}
          tint="clay"
        />
        <StatTile
          label="Tarjeta"
          value={fmt(totalTarjeta)}
          tint="gold"
          className="col-span-2 sm:col-span-1"
        />
      </div>

      {/* Lista de tickets */}
      <SectionLabel className="mb-2">Tickets del turno</SectionLabel>

      {loading ? (
        <div className="flex flex-col gap-2">
          {[1, 2, 3].map(i => (
            <div key={i} className="h-16 rounded-2xl bg-warm-100 animate-pulse" />
          ))}
        </div>
      ) : tickets.length === 0 ? (
        <Card className="flex flex-col items-center gap-2 py-10">
          <ShoppingBag size={32} className="text-warm-200" />
          <p className="text-sm text-warm-400 font-semibold">Sin ventas aún en este turno</p>
        </Card>
      ) : (
        /* Mobile: lista. Desktop: tabla simple */
        <>
          {/* Mobile list (< sm) */}
          <Card padding="none" className="sm:hidden divide-y divide-warm-100">
            {[...tickets].reverse().map(ticket => (
              <div key={ticket.id} className="flex items-center gap-3 px-4 py-3">
                <div className="w-8 h-8 rounded-xl bg-warm-100 flex items-center justify-center shrink-0">
                  <Clock size={14} className="text-warm-400" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-semibold text-warm-700 truncate">
                    {resumenItems(ticket.items)}
                  </p>
                  <p className="text-[11px] text-warm-400">{fmtHora(ticket.fecha)}</p>
                </div>
                <div className="flex flex-col items-end gap-1 shrink-0">
                  <span className="font-mono tabular-nums text-sm font-bold text-bark-800">
                    {fmt(ticket.total)}
                  </span>
                  <Pill tone={metodoPagoTone(ticket.metodo_pago)}>
                    {metodoPagoLabel(ticket.metodo_pago)}
                  </Pill>
                </div>
              </div>
            ))}
          </Card>

          {/* Desktop table (>= sm) */}
          <Card padding="none" className="hidden sm:block overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-warm-100 text-left">
                  <th className="px-4 py-2.5 text-[11px] font-bold uppercase tracking-wide text-warm-500">Hora</th>
                  <th className="px-4 py-2.5 text-[11px] font-bold uppercase tracking-wide text-warm-500">Productos</th>
                  <th className="px-4 py-2.5 text-[11px] font-bold uppercase tracking-wide text-warm-500">Método</th>
                  <th className="px-4 py-2.5 text-[11px] font-bold uppercase tracking-wide text-warm-500 text-right">Total</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-warm-100">
                {[...tickets].reverse().map(ticket => (
                  <tr key={ticket.id} className="hover:bg-warm-50 transition-colors">
                    <td className="px-4 py-3 text-xs text-warm-500 font-mono">
                      {fmtHora(ticket.fecha)}
                    </td>
                    <td className="px-4 py-3 text-xs text-warm-700 max-w-[200px] truncate">
                      {resumenItems(ticket.items)}
                    </td>
                    <td className="px-4 py-3">
                      <Pill tone={metodoPagoTone(ticket.metodo_pago)}>
                        {metodoPagoLabel(ticket.metodo_pago)}
                      </Pill>
                    </td>
                    <td className="px-4 py-3 font-mono tabular-nums text-sm font-bold text-bark-800 text-right">
                      {fmt(ticket.total)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </>
      )}

      {/* Resumen final si hay ventas */}
      {!loading && tickets.length > 0 && (
        <div className="mt-4 flex items-center gap-2 px-1">
          <TrendingUp size={14} className="text-success-500" />
          <span className="text-xs text-warm-500">
            {nVentas} venta{nVentas !== 1 ? 's' : ''} · Promedio {fmt(Math.round(totalTurno / nVentas))} por ticket
          </span>
        </div>
      )}

      {/* Spacing for bottom nav */}
      <div className="h-4" />
    </BaristaLayout>
  )
}
