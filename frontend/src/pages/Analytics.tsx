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

/** Barras por hora con los NÚMEROS visibles (plata arriba, tickets abajo), solo el
 *  rango horario con ventas y el pico resaltado. Reemplaza el mapa de calor de
 *  colores, que obligaba a pasar el mouse celda por celda para ver algo. */
function BarrasHoras({ datos }: { datos: VentaHora[] }) {
  const conVentas = datos.filter(d => d.total > 0)
  if (conVentas.length === 0) return null
  const desde = Math.min(...conVentas.map(d => d.hora))
  const hasta = Math.max(...conVentas.map(d => d.hora))
  const rango = datos.filter(d => d.hora >= desde && d.hora <= hasta)
  const maxTotal = Math.max(...rango.map(d => d.total), 1)
  const pico = rango.reduce((a, b) => (b.total > a.total ? b : a), rango[0])
  const fmtK = (v: number) =>
    v >= 1_000_000 ? `$${(v / 1_000_000).toFixed(1)}M`
    : v >= 1_000 ? `$${Math.round(v / 1_000)}k`
    : `$${Math.round(v)}`

  return (
    <div>
      <div className="flex items-end gap-1 sm:gap-1.5" style={{ height: 170 }}>
        {rango.map(d => {
          const esPico = d.hora === pico.hora && d.total > 0
          const h = d.total > 0 ? Math.max(10, Math.round((d.total / maxTotal) * 110)) : 3
          return (
            <div key={d.hora} className="flex-1 flex flex-col items-center justify-end gap-0.5 min-w-0"
              title={`${String(d.hora).padStart(2, '0')}:00 — ${fmt(d.total)} · ${d.n_tickets} ticket${d.n_tickets !== 1 ? 's' : ''}`}>
              {d.total > 0 && (
                <span className={`text-[9px] font-bold font-mono tabular-nums whitespace-nowrap ${esPico ? 'text-forest-700' : 'text-warm-500'}`}>
                  {fmtK(d.total)}
                </span>
              )}
              <div
                className={`w-full rounded-t ${esPico ? 'bg-forest-600' : d.total > 0 ? 'bg-forest-400' : 'bg-warm-100'}`}
                style={{ height: h }}
              />
              <span className="text-[8px] text-warm-400 tabular-nums h-3">
                {d.total > 0 ? `${d.n_tickets}t` : ''}
              </span>
              <span className={`text-[9px] font-bold tabular-nums ${esPico ? 'text-forest-700' : 'text-warm-400'}`}>
                {String(d.hora).padStart(2, '0')}
              </span>
            </div>
          )
        })}
      </div>
      <p className="text-[10px] text-warm-400 mt-2">
        Hora pico: <strong className="text-warm-600">{String(pico.hora).padStart(2, '0')}:00</strong> con{' '}
        <strong className="text-warm-600 font-mono">{fmt(pico.total)}</strong> en {pico.n_tickets} tickets.
        Cada barra: plata arriba, tickets abajo.
      </p>
    </div>
  )
}

// ─── Top productos ────────────────────────────────────────────────────────────

// ─── Unidades vendidas por producto (lista completa) ─────────────────────────

const CATS_VENTA = [
  { key: 'todas', label: 'Todas' },
  { key: 'bebida', label: 'Bebidas' },
  { key: 'pasteleria', label: 'Pastelería' },
  { key: 'porciones', label: 'Porciones' },
] as const

/** Tabla completa de lo vendido en el período: cada producto con sus unidades y
 *  total, filtrable por categoría y buscable. TopProductos muestra el podio;
 *  esta sección es para REVISAR todo. */
function UnidadesPorProducto({ datos }: { datos: ProductoTop[] }) {
  const [cats, setCats] = useState<Record<number, string>>({})
  const [cat, setCat] = useState<string>('todas')
  const [busca, setBusca] = useState('')

  useEffect(() => {
    api.get('/inventario/productos')
      .then(r => {
        const m: Record<number, string> = {}
        for (const p of r.data ?? []) m[p.id] = p.categoria
        setCats(m)
      })
      .catch(() => setCats({}))
  }, [])

  const filtrados = datos
    .filter(d => cat === 'todas' || cats[d.producto_id] === cat)
    .filter(d => d.nombre_producto.toLowerCase().includes(busca.toLowerCase()))
    .sort((a, b) => b.unidades - a.unidades)
  const totUnidades = filtrados.reduce((s, d) => s + d.unidades, 0)
  const totPlata = filtrados.reduce((s, d) => s + d.total, 0)

  const exportar = async () => {
    const XLSX = await import('xlsx')
    const ws = XLSX.utils.aoa_to_sheet([
      ['Producto', 'Categoría', 'Unidades', 'Total'],
      ...filtrados.map(d => [d.nombre_producto, cats[d.producto_id] ?? '', d.unidades, d.total]),
    ])
    const wb = XLSX.utils.book_new()
    XLSX.utils.book_append_sheet(wb, ws, 'Unidades')
    XLSX.writeFile(wb, 'unidades_por_producto.xlsx')
  }

  if (datos.length === 0) return null

  return (
    <Card>
      <div className="flex items-center justify-between mb-3 gap-2 flex-wrap">
        <SectionLabel>Unidades por producto — {filtrados.length} productos · {totUnidades} u · {fmt(totPlata)}</SectionLabel>
        <button onClick={exportar}
          className="text-[11px] font-bold px-2.5 py-1 rounded-lg text-white shrink-0"
          style={{ background: 'oklch(48% 0.15 155)' }}>
          Excel
        </button>
      </div>
      <div className="flex items-center gap-2 mb-3 flex-wrap">
        {CATS_VENTA.map(c => (
          <button key={c.key} onClick={() => setCat(c.key)}
            className={`px-2.5 py-1 rounded-full text-[11px] font-bold ${cat === c.key ? 'bg-forest-500 text-white' : 'bg-warm-100 text-warm-500'}`}>
            {c.label}
          </button>
        ))}
        <input
          value={busca}
          onChange={e => setBusca(e.target.value)}
          placeholder="Buscar producto..."
          className="ml-auto text-xs px-2.5 py-1.5 rounded-lg border border-warm-200 outline-none focus:border-forest-400 min-w-[140px]"
        />
      </div>
      <div className="max-h-96 overflow-y-auto -mx-1 px-1">
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-white">
            <tr className="text-warm-400 border-b border-warm-100">
              <th className="text-left py-1.5 font-semibold">Producto</th>
              <th className="text-right py-1.5 font-semibold">Unid.</th>
              <th className="text-right py-1.5 font-semibold pl-3">Total</th>
            </tr>
          </thead>
          <tbody>
            {filtrados.map(d => (
              <tr key={d.producto_id} className="border-b border-warm-50">
                <td className="py-1.5 text-warm-700">{d.nombre_producto}</td>
                <td className="py-1.5 text-right font-mono font-bold text-bark-800 tabular-nums">{d.unidades}</td>
                <td className="py-1.5 text-right font-mono text-warm-500 tabular-nums pl-3">{fmt(d.total)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {filtrados.length === 0 && (
          <p className="text-xs text-warm-400 text-center py-6">Nada vendido con ese filtro en el período.</p>
        )}
      </div>
    </Card>
  )
}

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
              <BarrasHoras datos={data.ventasPorHora} />
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

          {/* ── Lista completa: unidades vendidas por producto ── */}
          <UnidadesPorProducto datos={data.productosTop} />
        </>
      )}
    </div>
  )
}
