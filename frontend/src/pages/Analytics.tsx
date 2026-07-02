import { useEffect, useState, useCallback } from 'react'
import {
  TrendingUp, Users, CreditCard, Banknote, Package,
  Coffee, AlertTriangle,
} from 'lucide-react'
import api from '../api/client'
import { StatTile, Card, SectionLabel, Pill, Toast } from '../components/ui'

// ─── API types ────────────────────────────────────────────────────────────────

interface Resumen {
  total_ventas: number
  n_tickets: number
  ticket_promedio: number
  total_efectivo: number
  total_tarjeta: number
  n_items: number
}

interface ProductoTop {
  producto_id: number
  nombre_producto: string
  unidades: number
  total: number
}

interface VentaHora {
  hora: number
  n_tickets: number
  total: number
}

interface PorBarista {
  usuario_id: number
  nombre: string
  total: number
  n_tickets: number
  ticket_promedio: number
}

interface MetodoPago {
  metodo_pago: string
  n_tickets: number
  total: number
}

interface Analytics {
  resumen: Resumen | null
  productosTop: ProductoTop[]
  ventasPorHora: VentaHora[]
  porBarista: PorBarista[]
  metodoPago: MetodoPago[]
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

const fmt = (v: number) => `$${Math.round(v).toLocaleString('es-CO')}`

type Rango = 'hoy' | 'semana' | 'mes' | 'custom'

function getRangoDates(rango: Rango, custom: { desde: string; hasta: string }) {
  const hoy = new Date()
  // Componentes LOCALES: toISOString es UTC y despues de las 19:00 Colombia da manana.
  const iso = (d: Date) =>
    `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

  if (rango === 'hoy') {
    const s = iso(hoy)
    return { desde: s, hasta: s }
  }
  if (rango === 'semana') {
    const lunes = new Date(hoy)
    lunes.setDate(hoy.getDate() - ((hoy.getDay() + 6) % 7))
    return { desde: iso(lunes), hasta: iso(hoy) }
  }
  if (rango === 'mes') {
    return { desde: `${hoy.getFullYear()}-${String(hoy.getMonth() + 1).padStart(2, '0')}-01`, hasta: iso(hoy) }
  }
  return custom
}

// ─── Mapa de calor por hora ───────────────────────────────────────────────────
// 24 celdas. Color por intensidad de total usando clases Tailwind.
// Escala: 0 = warm-100 (vacío), 1-20% = forest-50, 20-40 = forest-100,
//         40-60 = forest-400, 60-80 = forest-500, 80-100 = forest (DEFAULT).

function heatClass(valor: number, maxValor: number): string {
  if (maxValor === 0 || valor === 0) return 'bg-warm-100 text-warm-400'
  const pct = valor / maxValor
  if (pct < 0.15) return 'bg-forest-50 text-forest-700'
  if (pct < 0.30) return 'bg-forest-100 text-forest-700'
  if (pct < 0.50) return 'bg-forest-400 text-white'
  if (pct < 0.75) return 'bg-forest-500 text-white'
  return 'bg-forest text-white'
}

function MapaCalorHoras({ datos }: { datos: VentaHora[] }) {
  const maxTotal = Math.max(...datos.map(d => d.total), 1)

  return (
    <div className="overflow-x-auto">
      <div className="min-w-[600px]">
        {/* Etiquetas de horas */}
        <div className="grid grid-cols-24 gap-0.5 mb-1" style={{ gridTemplateColumns: 'repeat(24, minmax(0, 1fr))' }}>
          {datos.map(d => (
            <div key={d.hora} className="text-center text-[9px] font-bold text-warm-400 tabular-nums">
              {String(d.hora).padStart(2, '0')}
            </div>
          ))}
        </div>

        {/* Celdas de calor */}
        <div className="grid gap-0.5" style={{ gridTemplateColumns: 'repeat(24, minmax(0, 1fr))' }}>
          {datos.map(d => (
            <div
              key={d.hora}
              title={`${String(d.hora).padStart(2, '0')}:00 — ${fmt(d.total)} (${d.n_tickets} tickets)`}
              className={`
                relative group rounded-md aspect-square flex items-center justify-center
                transition-opacity cursor-default
                ${heatClass(d.total, maxTotal)}
              `}
            >
              {/* Tooltip on hover */}
              <div className="
                absolute bottom-full left-1/2 -translate-x-1/2 mb-1.5
                hidden group-hover:flex flex-col items-center
                z-10 pointer-events-none
              ">
                <div className="bg-bark-900 text-white text-[10px] font-semibold rounded-lg px-2 py-1.5 whitespace-nowrap shadow-lg">
                  <div className="font-mono tabular-nums">{fmt(d.total)}</div>
                  <div className="text-warm-300">{d.n_tickets} ticket{d.n_tickets !== 1 ? 's' : ''}</div>
                </div>
                <div className="w-1.5 h-1.5 bg-bark-900 rotate-45 -mt-1" />
              </div>
            </div>
          ))}
        </div>

        {/* Leyenda */}
        <div className="flex items-center gap-2 mt-3 justify-end">
          <span className="text-[10px] text-warm-400">Sin ventas</span>
          {(['bg-forest-50', 'bg-forest-100', 'bg-forest-400', 'bg-forest-500', 'bg-forest'] as const).map(c => (
            <div key={c} className={`w-3.5 h-3.5 rounded ${c} border border-warm-200`} />
          ))}
          <span className="text-[10px] text-warm-400">Máximo</span>
        </div>
      </div>
    </div>
  )
}

// ─── Top productos ────────────────────────────────────────────────────────────

function TopProductos({ datos }: { datos: ProductoTop[] }) {
  if (datos.length === 0) return (
    <div className="flex flex-col items-center gap-2 py-8">
      <Package size={28} className="text-warm-200" />
      <p className="text-xs text-warm-400">Sin ventas en el período</p>
    </div>
  )

  const maxUnidades = Math.max(...datos.map(d => d.unidades), 1)

  return (
    <div className="space-y-2.5">
      {datos.slice(0, 10).map((p, i) => (
        <div key={p.producto_id} className="flex items-center gap-3">
          <span className="text-[11px] font-bold text-warm-400 w-4 shrink-0 tabular-nums">{i + 1}</span>
          <div className="flex-1 min-w-0">
            <div className="flex items-center justify-between mb-1 gap-2">
              <span className="text-xs font-semibold text-warm-700 truncate">{p.nombre_producto}</span>
              <div className="flex items-center gap-2 shrink-0">
                <span className="text-[11px] text-warm-400 font-mono tabular-nums">{p.unidades} u</span>
                <span className="text-xs font-bold font-mono tabular-nums text-bark-800">{fmt(p.total)}</span>
              </div>
            </div>
            {/* Barra de proporción */}
            <div className="h-1.5 rounded-full bg-warm-100 overflow-hidden">
              <div
                className="h-full rounded-full bg-forest-400 transition-all"
                style={{ width: `${(p.unidades / maxUnidades) * 100}%` }}
              />
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

// ─── Por barista ──────────────────────────────────────────────────────────────

function TablaBaristas({ datos }: { datos: PorBarista[] }) {
  if (datos.length === 0) return (
    <div className="flex flex-col items-center gap-2 py-8">
      <Users size={28} className="text-warm-200" />
      <p className="text-xs text-warm-400">Sin datos de baristas en el período</p>
    </div>
  )

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm min-w-[400px]">
        <thead>
          <tr className="border-b border-warm-100">
            <th className="text-left py-2 px-3 text-[11px] font-bold uppercase tracking-wide text-warm-500">Barista</th>
            <th className="text-right py-2 px-3 text-[11px] font-bold uppercase tracking-wide text-warm-500">Tickets</th>
            <th className="text-right py-2 px-3 text-[11px] font-bold uppercase tracking-wide text-warm-500">Total</th>
            <th className="text-right py-2 px-3 text-[11px] font-bold uppercase tracking-wide text-warm-500">ATV</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-warm-100">
          {datos.map(b => (
            <tr key={b.usuario_id} className="hover:bg-warm-50 transition-colors">
              <td className="py-3 px-3 font-semibold text-warm-700">{b.nombre}</td>
              <td className="py-3 px-3 text-right font-mono tabular-nums text-warm-500">{b.n_tickets}</td>
              <td className="py-3 px-3 text-right font-mono tabular-nums font-bold text-bark-800">{fmt(b.total)}</td>
              <td className="py-3 px-3 text-right font-mono tabular-nums text-warm-600">{fmt(b.ticket_promedio)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ─── Métodos de pago ──────────────────────────────────────────────────────────

function metodoPagoTone(m: string): 'success' | 'clay' | 'gold' | 'warm' {
  if (m === 'efectivo') return 'success'
  if (m === 'tarjeta') return 'clay'
  if (m === 'mixto') return 'gold'
  return 'warm'
}

function metodoPagoLabel(m: string) {
  const MAP: Record<string, string> = { efectivo: 'Efectivo', tarjeta: 'Tarjeta', mixto: 'Mixto' }
  return MAP[m] ?? m
}

// ─── Componente principal ─────────────────────────────────────────────────────

export function AnaliticaContenido() {
  const [rango, setRango] = useState<Rango>('hoy')
  const [custom, setCustom] = useState(() => {
    const d = new Date()
    const s = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
    return { desde: s, hasta: s }
  })
  const [data, setData] = useState<Analytics>({
    resumen: null,
    productosTop: [],
    ventasPorHora: Array.from({ length: 24 }, (_, i) => ({ hora: i, n_tickets: 0, total: 0 })),
    porBarista: [],
    metodoPago: [],
  })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const { desde, hasta } = getRangoDates(rango, custom)

  const cargar = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = { fecha_desde: desde, fecha_hasta: hasta }
      const [resR, prodR, horasR, baristaR, metodoR] = await Promise.all([
        api.get<Resumen>('/pos/analytics/resumen', { params }),
        api.get<ProductoTop[]>('/pos/analytics/productos-top', { params }),
        api.get<VentaHora[]>('/pos/analytics/ventas-por-hora', { params }),
        api.get<PorBarista[]>('/pos/analytics/por-barista', { params }),
        api.get<MetodoPago[]>('/pos/analytics/metodo-pago', { params }),
      ])

      // Normalizar ventas-por-hora a exactamente 24 elementos
      const horasMap = new Map(horasR.data.map(h => [h.hora, h]))
      const horas24 = Array.from({ length: 24 }, (_, i) =>
        horasMap.get(i) ?? { hora: i, n_tickets: 0, total: 0 }
      )

      setData({
        resumen: resR.data,
        productosTop: prodR.data,
        ventasPorHora: horas24,
        porBarista: baristaR.data,
        metodoPago: metodoR.data,
      })
    } catch {
      setError('Error al cargar los datos de analítica. Verificá la conexión.')
    } finally {
      setLoading(false)
    }
  }, [desde, hasta])

  useEffect(() => { cargar() }, [cargar])

  const r = data.resumen
  const totalMetodos = data.metodoPago.reduce((s, m) => s + m.total, 0)
  const efectivoPct = totalMetodos > 0
    ? Math.round((data.metodoPago.find(m => m.metodo_pago === 'efectivo')?.total ?? 0) / totalMetodos * 100)
    : 0

  return (
    <div className="max-w-5xl mx-auto px-4 py-6 space-y-6">
      {/* ── Header ── */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-bark-800">Analítica de ventas</h1>
          <p className="text-xs text-warm-500 mt-0.5">
            {desde === hasta ? desde : `${desde} → ${hasta}`}
          </p>
        </div>

        {/* Filtro de rango */}
        <div className="flex flex-wrap items-center gap-2">
          {(['hoy', 'semana', 'mes'] as Rango[]).map(r => (
            <button
              key={r}
              onClick={() => setRango(r)}
              className={`px-3 py-1.5 rounded-xl text-xs font-bold transition-colors ${
                rango === r
                  ? 'bg-forest text-white'
                  : 'bg-warm-100 text-warm-600 hover:bg-warm-200'
              }`}
            >
              {r === 'hoy' ? 'Hoy' : r === 'semana' ? 'Esta semana' : 'Este mes'}
            </button>
          ))}
          <button
            onClick={() => setRango('custom')}
            className={`px-3 py-1.5 rounded-xl text-xs font-bold transition-colors ${
              rango === 'custom'
                ? 'bg-forest text-white'
                : 'bg-warm-100 text-warm-600 hover:bg-warm-200'
            }`}
          >
            Rango
          </button>
        </div>
      </div>

      {/* Custom date inputs */}
      {rango === 'custom' && (
        <Card padding="sm">
          <div className="flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-2 text-xs font-semibold text-warm-600">
              Desde
              <input
                type="date"
                value={custom.desde}
                onChange={e => setCustom(c => ({ ...c, desde: e.target.value }))}
                className="border border-warm-200 rounded-lg px-2 py-1 text-xs font-mono text-bark-800 focus:outline-none focus:ring-2 focus:ring-forest-400"
              />
            </label>
            <label className="flex items-center gap-2 text-xs font-semibold text-warm-600">
              Hasta
              <input
                type="date"
                value={custom.hasta}
                onChange={e => setCustom(c => ({ ...c, hasta: e.target.value }))}
                className="border border-warm-200 rounded-lg px-2 py-1 text-xs font-mono text-bark-800 focus:outline-none focus:ring-2 focus:ring-forest-400"
              />
            </label>
          </div>
        </Card>
      )}

      {/* Error */}
      {error && (
        <Toast tone="danger" duration={6000} onDismiss={() => setError(null)}>
          <AlertTriangle size={14} className="shrink-0" />
          {error}
        </Toast>
      )}

      {/* Loading overlay (skeleton tiles) */}
      {loading ? (
        <div className="space-y-4">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {[1, 2, 3, 4].map(i => (
              <div key={i} className="h-24 rounded-2xl bg-warm-100 animate-pulse" />
            ))}
          </div>
          <div className="h-32 rounded-2xl bg-warm-100 animate-pulse" />
          <div className="grid sm:grid-cols-2 gap-4">
            <div className="h-48 rounded-2xl bg-warm-100 animate-pulse" />
            <div className="h-48 rounded-2xl bg-warm-100 animate-pulse" />
          </div>
        </div>
      ) : (
        <>
          {/* ── KPIs ── */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <StatTile
              label="Total ventas"
              value={fmt(r?.total_ventas ?? 0)}
              tint="success"
            />
            <StatTile
              label="Tickets"
              value={r?.n_tickets ?? 0}
              sublabel={`${r?.n_items ?? 0} ítems`}
              tint="neutral"
            />
            <StatTile
              label="Ticket promedio"
              value={fmt(r?.ticket_promedio ?? 0)}
              tint="clay"
            />
            <StatTile
              label="% Efectivo"
              value={`${efectivoPct}%`}
              sublabel={`Tarjeta: ${100 - efectivoPct}%`}
              tint={efectivoPct >= 50 ? 'gold' : 'neutral'}
            />
          </div>

          {/* Métodos de pago (pills + totales) */}
          {data.metodoPago.length > 0 && (
            <Card padding="sm">
              <SectionLabel className="mb-3">Método de pago</SectionLabel>
              <div className="flex flex-wrap gap-3">
                {data.metodoPago.map(m => (
                  <div key={m.metodo_pago} className="flex items-center gap-2">
                    <Pill tone={metodoPagoTone(m.metodo_pago)}>
                      {metodoPagoLabel(m.metodo_pago)}
                    </Pill>
                    <span className="font-mono tabular-nums text-xs font-bold text-bark-800">
                      {fmt(m.total)}
                    </span>
                    <span className="text-[11px] text-warm-400">
                      ({m.n_tickets} tickets)
                    </span>
                  </div>
                ))}
              </div>
            </Card>
          )}

          {/* ── Mapa de calor por hora ── */}
          <Card>
            <SectionLabel className="mb-4">Ventas por hora del día</SectionLabel>
            {data.ventasPorHora.every(h => h.total === 0) ? (
              <div className="flex flex-col items-center gap-2 py-6">
                <Coffee size={28} className="text-warm-200" />
                <p className="text-xs text-warm-400">Sin ventas en el período seleccionado</p>
              </div>
            ) : (
              <MapaCalorHoras datos={data.ventasPorHora} />
            )}
          </Card>

          {/* ── Grid: top productos + por barista ── */}
          <div className="grid sm:grid-cols-2 gap-4">
            <Card>
              <SectionLabel className="mb-4">Top productos</SectionLabel>
              <TopProductos datos={data.productosTop} />
            </Card>

            <Card padding="none">
              <div className="px-4 pt-4 pb-2">
                <SectionLabel>Por barista</SectionLabel>
              </div>
              <TablaBaristas datos={data.porBarista} />
              <div className="h-2" />
            </Card>
          </div>
        </>
      )}
    </div>
  )
}
