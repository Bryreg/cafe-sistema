import { ReactNode, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Wallet, ShoppingCart, Receipt, TrendingUp, TrendingDown, HelpCircle, ArrowRight } from 'lucide-react'
import api from '../../api/client'
import { RentabilidadData, fmt } from './helpers'

interface Tienda { id: number; nombre: string }

function isoLocal(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
// "Hoy" según el reloj de COLOMBIA (el negocio), no el del navegador.
function hoyBogota(): Date {
  const s = new Date().toLocaleDateString('en-CA', { timeZone: 'America/Bogota' })
  const [y, m, d] = s.split('-').map(Number)
  return new Date(y, m - 1, d)
}
type Periodo = 'mes' | 'mes_pasado' | '30d' | 'anio'
function rangoPeriodo(p: Periodo): { desde: string; hasta: string } {
  const hoy = hoyBogota()
  if (p === 'mes') return { desde: isoLocal(new Date(hoy.getFullYear(), hoy.getMonth(), 1)), hasta: isoLocal(hoy) }
  if (p === 'mes_pasado') {
    return {
      desde: isoLocal(new Date(hoy.getFullYear(), hoy.getMonth() - 1, 1)),
      hasta: isoLocal(new Date(hoy.getFullYear(), hoy.getMonth(), 0)),
    }
  }
  if (p === '30d') {
    const d = new Date(hoy); d.setDate(d.getDate() - 29)
    return { desde: isoLocal(d), hasta: isoLocal(hoy) }
  }
  return { desde: isoLocal(new Date(hoy.getFullYear(), 0, 1)), hasta: isoLocal(hoy) }
}

const MESES_CORTOS = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']
const nombreMes = (ym: string) => {
  const [a, m] = ym.split('-')
  return `${MESES_CORTOS[Number(m) - 1]} ${a}`
}

function Kpi({ label, value, sub, Icon, tint }: {
  label: string; value: string; sub?: ReactNode; Icon: typeof Wallet; tint: string
}) {
  return (
    <div className="bg-white rounded-2xl border border-warm-200 p-4">
      <div className="flex items-center gap-2 mb-1.5">
        <Icon size={14} className={tint} />
        <p className="text-[11px] font-bold uppercase tracking-wide text-warm-400">{label}</p>
      </div>
      <p className="text-xl font-bold text-warm-700 font-mono leading-none tabular-nums">{value}</p>
      {sub && <p className="text-xs text-warm-400 mt-1.5">{sub}</p>}
    </div>
  )
}

export default function PnLView({ onVerMetodologia }: { onVerMetodologia: () => void }) {
  const [periodo, setPeriodo] = useState<Periodo>('mes')
  const [tiendas, setTiendas] = useState<Tienda[]>([])
  const [tiendaId, setTiendaId] = useState<number | null>(null)
  const [data, setData] = useState<RentabilidadData | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    api.get<Tienda[]>('/auth/tiendas').then(r => setTiendas(r.data)).catch(() => {})
  }, [])

  useEffect(() => {
    // Guard anti-carrera: si el filtro cambia antes de la respuesta, se descarta.
    let vigente = true
    const { desde, hasta } = rangoPeriodo(periodo)
    setLoading(true)
    api.get<RentabilidadData>('/rentabilidad/', {
      params: { desde, hasta, ...(tiendaId ? { tienda_id: tiendaId } : {}) },
    })
      .then(r => { if (vigente) setData(r.data) })
      .catch(() => { if (vigente) setData(null) })
      .finally(() => { if (vigente) setLoading(false) })
    return () => { vigente = false }
  }, [periodo, tiendaId])

  const r = data?.resumen
  const margenPositivo = (r?.margen_neto ?? 0) >= 0

  return (
    <div className="space-y-3">
      {/* Filtros (viven acá: es la única vista donde aplican) */}
      <div className="sticky top-[52px] z-10 -mx-1 px-1 py-1.5 bg-warm-50/90 backdrop-blur-sm flex items-center gap-1.5 overflow-x-auto">
        {(([['mes', 'Este mes'], ['mes_pasado', 'Mes pasado'], ['30d', '30 días'], ['anio', 'Este año']]) as [Periodo, string][]).map(([p, lbl]) => (
          <button key={p} onClick={() => setPeriodo(p)}
            className={`shrink-0 min-h-[40px] px-3 rounded-full text-xs font-bold border transition-colors ${
              periodo === p ? 'bg-forest text-white border-forest' : 'bg-white text-warm-500 border-warm-200'}`}>
            {lbl}
          </button>
        ))}
        <select value={tiendaId ?? ''} onChange={e => setTiendaId(e.target.value ? Number(e.target.value) : null)}
          className="shrink-0 ml-auto border border-warm-200 rounded-full px-3 min-h-[40px] text-xs font-bold bg-white text-warm-600">
          <option value="">Todas las sedes</option>
          {tiendas.map(t => <option key={t.id} value={t.id}>{t.nombre}</option>)}
        </select>
      </div>

      {loading && (
        <div className="space-y-3" aria-label="Cargando">
          <div className="h-24 rounded-2xl bg-warm-100 animate-pulse" />
          <div className="h-40 rounded-2xl bg-warm-100 animate-pulse" />
        </div>
      )}
      {!loading && !data && <p className="text-sm text-warm-400 px-1">No se pudo cargar la información.</p>}

      {!loading && data && r && (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <Kpi label="Ventas" value={fmt(r.ventas)} Icon={Wallet} tint="text-forest"
              sub={`${r.n_tickets} tickets`} />
            <Kpi label="Compras proveedor" value={fmt(r.compras)} Icon={ShoppingCart} tint="text-gold-600"
              sub={`${r.n_facturas} facturas recibidas`} />
            {/* El valor ya son las DOS mitades: egresos de caja sin adoptar +
                obligaciones devengadas (services/rentabilidad.py). El detalle por
                categoría vive en Costos, no acá. */}
            <Kpi label="Costos operativos" value={fmt(r.gastos)} Icon={Receipt} tint="text-danger-500"
              sub={<Link to="/costos" className="font-semibold text-forest underline decoration-dotted">
                Ver el detalle en Costos
              </Link>} />
            <div className={`rounded-2xl border p-4 border-l-[3px] ${margenPositivo ? 'bg-success-50 border-success-200 border-l-success-500' : 'bg-danger-50 border-danger-200 border-l-danger-500'}`}>
              <div className="flex items-center gap-2 mb-1.5">
                {margenPositivo ? <TrendingUp size={14} className="text-success-600" /> : <TrendingDown size={14} className="text-danger-500" />}
                {/* MISMO número que el hero del Pulso (resumen.margen_neto). Se
                    llamaba "Margen operativo" acá y "Margen neto" allá: dos nombres
                    para la misma plata es exactamente la confusión que este módulo
                    vino a sacar. Un número, un nombre. */}
                <p className="text-[11px] font-bold uppercase tracking-wide text-warm-400">Margen neto</p>
              </div>
              <p className={`text-xl font-bold font-mono leading-none tabular-nums ${margenPositivo ? 'text-success-600' : 'text-danger-700'}`}>
                {fmt(r.margen_neto)}
              </p>
              {/* Sin muletilla cuando hay cobertura: el número ya resta arriendo y
                  nómina. Cuando NO la hay, se declara — un margen sin costos fijos
                  leído como si los tuviera es la mentira que esta fase corrige. */}
              <p className="text-xs text-warm-400 mt-1.5">
                {r.pct_margen_neto != null ? `${r.pct_margen_neto}% de la venta` : 'sin ventas'}
                {r.tiene_costos_fijos ? '' : ' · sin costos fijos cargados'}
              </p>
            </div>
          </div>

          {/* COGS teórico: base de consumo (complementa a compras = base de recepción) */}
          {r.cogs_teorico != null && (
            <div className="bg-white rounded-2xl border border-warm-200 p-4">
              <p className="text-[11px] font-bold uppercase tracking-wide text-warm-500 mb-2">
                Costo de lo VENDIDO (teórico) — sin la distorsión del stockeo
              </p>
              <div className="grid grid-cols-3 gap-2 text-center">
                <div>
                  <p className="text-[10px] uppercase font-bold text-warm-400">Consumo teórico</p>
                  <p className="text-sm font-mono font-bold text-warm-700 mt-0.5 tabular-nums">{fmt(r.cogs_teorico)}</p>
                </div>
                <div>
                  <p className="text-[10px] uppercase font-bold text-warm-400">Margen bruto real</p>
                  <p className="text-sm font-mono font-bold text-success-600 mt-0.5 tabular-nums">
                    {fmt(r.margen_bruto_real ?? 0)}
                    {r.pct_margen_bruto_real != null && <span className="text-warm-400 font-normal"> ({r.pct_margen_bruto_real}%)</span>}
                  </p>
                </div>
                <div>
                  <p className="text-[10px] uppercase font-bold text-warm-400">Compras − consumo</p>
                  <p className={`text-sm font-mono font-bold mt-0.5 tabular-nums ${(r.brecha_compras ?? 0) >= 0 ? 'text-gold-700' : 'text-danger-700'}`}>
                    {fmt(r.brecha_compras ?? 0)}
                  </p>
                </div>
              </div>
              <p className="text-[11px] text-warm-400 mt-2">
                Brecha positiva = stockeaste (compraste más de lo consumido). Cubre el {r.pct_venta_costeada ?? '—'}% de la venta (productos con costo).
              </p>
            </div>
          )}

          {/* Por mes: solo aporta con rango multi-mes */}
          {data.por_mes.length > 1 && (
            <div className="bg-white rounded-2xl border border-warm-200 overflow-hidden">
              <p className="px-4 py-3 text-sm font-bold text-warm-700 border-b border-warm-100">Por mes</p>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-[11px] uppercase tracking-wide text-warm-400 border-b border-warm-100">
                      <th className="text-left px-4 py-2 font-bold">Mes</th>
                      <th className="text-right px-3 py-2 font-bold">Ventas</th>
                      <th className="text-right px-3 py-2 font-bold">Compras</th>
                      <th className="text-right px-3 py-2 font-bold">Gastos</th>
                      <th className="text-right px-4 py-2 font-bold">Margen</th>
                      <th className="text-right px-4 py-2 font-bold">%</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.por_mes.map(m => (
                      <tr key={m.mes} className="border-b border-warm-100 last:border-0">
                        <td className="px-4 py-2.5 font-semibold text-warm-700">{nombreMes(m.mes)}</td>
                        <td className="px-3 py-2.5 text-right font-mono text-warm-700 tabular-nums">{fmt(m.ventas)}</td>
                        <td className="px-3 py-2.5 text-right font-mono text-warm-500 tabular-nums">{fmt(m.compras)}</td>
                        <td className="px-3 py-2.5 text-right font-mono text-warm-500 tabular-nums">{fmt(m.gastos)}</td>
                        <td className={`px-4 py-2.5 text-right font-mono font-bold tabular-nums ${m.margen_neto >= 0 ? 'text-success-600' : 'text-danger-500'}`}>
                          {fmt(m.margen_neto)}
                        </td>
                        <td className="px-4 py-2.5 text-right font-mono text-warm-400 tabular-nums">
                          {m.pct_margen_neto != null ? `${m.pct_margen_neto}%` : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Por sede (detalle completo) */}
          {!tiendaId && data.por_sede.length > 1 && (
            <div className="grid sm:grid-cols-2 gap-3">
              {data.por_sede.map(s => (
                <div key={s.tienda_id ?? 'corporativo'} className="bg-white rounded-2xl border border-warm-200 p-4">
                  <p className="text-sm font-bold text-warm-700 mb-2">{s.tienda}</p>
                  <div className="grid grid-cols-3 gap-2 text-center">
                    <div>
                      <p className="text-[10px] uppercase font-bold text-warm-400">Ventas</p>
                      <p className="text-sm font-mono font-bold text-warm-700 mt-0.5 tabular-nums">{fmt(s.ventas)}</p>
                    </div>
                    <div>
                      <p className="text-[10px] uppercase font-bold text-warm-400">Compras+Gastos</p>
                      <p className="text-sm font-mono font-bold text-warm-500 mt-0.5 tabular-nums">{fmt(s.compras + s.gastos)}</p>
                    </div>
                    <div>
                      <p className="text-[10px] uppercase font-bold text-warm-400">Margen</p>
                      <p className={`text-sm font-mono font-bold mt-0.5 tabular-nums ${s.margen_neto >= 0 ? 'text-success-600' : 'text-danger-500'}`}>
                        {fmt(s.margen_neto)}
                      </p>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* El detalle del gasto se AMPUTÓ de acá: eran conceptos de texto libre
              agrupados por string crudo. En Costos el mismo dinero está agrupado por
              categoría, que es la única forma de leerlo sin adivinar. */}
          <Link to="/costos"
            className="flex items-center gap-3 bg-white rounded-2xl border border-warm-200 px-4 py-3">
            <Receipt size={16} className="text-danger-500 shrink-0" />
            <span className="min-w-0 flex-1">
              <span className="block text-sm font-bold text-warm-700">En qué se fueron los {fmt(r.gastos)}</span>
              <span className="block text-xs text-warm-400">
                El detalle vive en Costos, agrupado por categoría
              </span>
            </span>
            <ArrowRight size={15} className="text-warm-400 shrink-0" />
          </Link>

          <button onClick={onVerMetodologia}
            className="flex items-center gap-1.5 text-xs text-warm-500 font-semibold min-h-[44px] px-1">
            <HelpCircle size={13} /> ¿Cómo se calcula esto?
          </button>
        </>
      )}
    </div>
  )
}
