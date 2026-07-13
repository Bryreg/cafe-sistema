import { useEffect, useRef, useState, type ReactNode } from 'react'
import api from '../api/client'
import {
  TrendingUp, TrendingDown, ShoppingCart, Wallet, Receipt, Info,
  Coffee, ScanLine, Loader2, Sparkles, Award, AlertTriangle, ArrowUpRight,
  Layers,
} from 'lucide-react'

// ─── Tipos ────────────────────────────────────────────────────────────────────
interface Bucket {
  ventas: number; compras: number; gastos: number
  margen_neto: number; pct_margen_neto: number | null
}
interface RentabilidadData {
  desde: string; hasta: string
  resumen: Bucket & {
    margen_bruto: number
    pct_margen_bruto: number | null
    n_tickets: number; n_facturas: number
  }
  por_mes: ({ mes: string } & Bucket)[]
  por_sede: ({ tienda_id: number; tienda: string } & Bucket)[]
  gastos_detalle: { concepto: string; total: number; n: number }[]
  nota: string
}
interface Tienda { id: number; nombre: string }

interface ProdMargen {
  producto_id: number; nombre: string; categoria: string; tipo: string
  precio_venta: number; costo: number | null; costo_completo: boolean
  insumos_sin_costo: string[]; margen: number | null; pct_margen: number | null
  // Costo completo = receta + desechables para llevar (capa aparte, no toca inventario).
  costo_desechables: number | null; costo_con_desechables: number | null
  desechables_sin_costo: string[]; margen_con_desechables: number | null
  pct_margen_con_desechables: number | null
  unidades_30d: number; venta_30d: number
}
interface PorProductoData {
  productos: ProdMargen[]
  facturas_pendientes_de_costos: number
  nota: string
}

const fmt = (v: number) => '$' + Math.round(v || 0).toLocaleString('es-CO')
const MESES_CORTOS = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']
const nombreMes = (ym: string) => {
  const [a, m] = ym.split('-')
  return `${MESES_CORTOS[Number(m) - 1]} ${a}`
}

function isoLocal(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

// "Hoy" según el reloj de COLOMBIA (el negocio), no el del navegador: un
// dispositivo en otra zona horaria armaría rangos corridos un día.
function hoyBogota(): Date {
  const s = new Date().toLocaleDateString('en-CA', { timeZone: 'America/Bogota' }) // YYYY-MM-DD
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

// ─── KPI card ─────────────────────────────────────────────────────────────────
function Kpi({ label, value, sub, Icon, tint }: {
  label: string; value: string; sub?: string; Icon: typeof Wallet; tint: string
}) {
  return (
    <div className="bg-white rounded-2xl border border-gray-200 p-4">
      <div className="flex items-center gap-2 mb-1.5">
        <Icon size={14} style={{ color: tint }} />
        <p className="text-[11px] font-bold uppercase tracking-wide text-gray-400">{label}</p>
      </div>
      <p className="text-xl font-bold text-gray-800 font-mono leading-none">{value}</p>
      {sub && <p className="text-xs text-gray-400 mt-1.5">{sub}</p>}
    </div>
  )
}

// ─── Barra horizontal para rankings (categoría / producto) ──────────────────────
function Bar({ label, value, max, right, tint, sub }: {
  label: string; value: number; max: number; right: string; tint: string; sub?: string
}) {
  const pct = max > 0 ? Math.max(3, Math.round((value / max) * 100)) : 0
  return (
    <div className="flex items-center gap-3 px-4 py-1.5">
      <div className="w-36 sm:w-44 shrink-0 min-w-0">
        <p className="text-sm font-semibold text-gray-700 truncate">{label}</p>
        {sub && <p className="text-[11px] text-gray-400 truncate">{sub}</p>}
      </div>
      <div className="flex-1 h-4 rounded-full bg-gray-100 overflow-hidden">
        <div className="h-full rounded-full" style={{ width: `${pct}%`, background: tint }} />
      </div>
      <span className="w-24 shrink-0 text-right text-sm font-mono font-bold text-gray-700">{right}</span>
    </div>
  )
}

// ─── Tarjeta de insight automático ──────────────────────────────────────────────
function InsightCard({ Icon, tint, bg, title, children }: {
  Icon: typeof Wallet; tint: string; bg: string; title: string; children: ReactNode
}) {
  return (
    <div className="rounded-2xl border p-4" style={{ borderColor: tint + '40', background: bg }}>
      <div className="flex items-center gap-2 mb-1.5">
        <Icon size={15} style={{ color: tint }} />
        <p className="text-[11px] font-bold uppercase tracking-wide" style={{ color: tint }}>{title}</p>
      </div>
      <p className="text-sm text-gray-700 leading-snug">{children}</p>
    </div>
  )
}

// ─── Página ───────────────────────────────────────────────────────────────────
export default function Rentabilidad() {
  const [periodo, setPeriodo] = useState<Periodo>('mes')
  const [tiendas, setTiendas] = useState<Tienda[]>([])
  const [tiendaId, setTiendaId] = useState<number | null>(null)
  const [data, setData] = useState<RentabilidadData | null>(null)
  const [loading, setLoading] = useState(false)

  // Margen por producto + backfill de costos desde las fotos guardadas
  const [prodData, setProdData] = useState<PorProductoData | null>(null)
  const [leyendo, setLeyendo] = useState(false)
  const [leyendoMsg, setLeyendoMsg] = useState('')
  const pararRef = useRef(false)
  // Filtro por categoría y criterio de orden de la tabla de márgenes.
  const [prodCat, setProdCat] = useState<string>('todas')
  const [prodSort, setProdSort] = useState<'utilidad' | 'margen' | 'unidades'>('utilidad')

  const fetchProductos = () =>
    api.get<PorProductoData>('/rentabilidad/por-producto')
      .then(r => setProdData(r.data))
      .catch(() => setProdData(null))

  useEffect(() => {
    api.get<Tienda[]>('/auth/tiendas').then(r => setTiendas(r.data)).catch(() => {})
    fetchProductos()
  }, [])

  const leerFacturas = async () => {
    if (!prodData) return
    setLeyendo(true)
    pararRef.current = false
    let pendientes = prodData.facturas_pendientes_de_costos
    try {
      while (pendientes > 0 && !pararRef.current) {
        setLeyendoMsg(`Leyendo facturas guardadas… quedan ${pendientes}`)
        const r = await api.post('/rentabilidad/backfill-costos?limite=2', null, { timeout: 300000 })
        const d = r.data
        if (d.detenido_por) { setLeyendoMsg(d.detenido_por); break }
        pendientes = d.pendientes
        // procesadas=0 → no queda nada que el lector pueda intentar: lo que
        // sobra necesita carga manual (el backend saltea las ya fallidas).
        if (d.procesadas === 0) {
          if (pendientes > 0) {
            setLeyendoMsg(`Quedan ${pendientes} facturas que no se pudieron leer solas — completá esos precios a mano en Pagos proveedores.`)
          }
          break
        }
      }
      if (pendientes === 0) setLeyendoMsg('Listo: todas las facturas con foto quedaron leídas.')
    } catch (e: any) {
      setLeyendoMsg(e.response?.data?.detail || 'Error leyendo facturas — intentá más tarde.')
    } finally {
      setLeyendo(false)
      fetchProductos()
    }
  }

  useEffect(() => {
    // Guard anti-carrera: si el filtro cambia antes de que llegue la respuesta,
    // la respuesta vieja se descarta (sin esto podía pisar a la nueva).
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

  // ── Margen por producto: utilidad aportada (margen × volumen), filtro y orden ──
  // La "utilidad 30d" usa el margen de RECETA (en el punto). Es lo más accionable:
  // un producto de margen medio pero mucho volumen aporta más plata que uno de
  // margen alto que casi no rota (el Americano vs. una bebida cara que no vende).
  const prodUtil = (p: ProdMargen) => (p.margen ?? 0) * p.unidades_30d
  const prodCats = prodData
    ? ['todas', ...Array.from(new Set(prodData.productos.map(p => p.categoria).filter(Boolean)))]
    : ['todas']
  const prodFiltered = (prodData?.productos ?? [])
    .filter(p => prodCat === 'todas' || p.categoria === prodCat)
  const prodSorted = [...prodFiltered].sort((a, b) => {
    if (prodSort === 'unidades') return b.unidades_30d - a.unidades_30d
    if (prodSort === 'margen') return (b.pct_margen ?? -Infinity) - (a.pct_margen ?? -Infinity)
    return prodUtil(b) - prodUtil(a)  // 'utilidad' (default)
  })
  const totalUtil = prodFiltered.reduce((s, p) => s + prodUtil(p), 0)

  // ── Análisis de negocio (todo client-side desde por-producto) ──────────────────
  // Base: productos que se vendieron y tienen margen calculado.
  const prodsSold = (prodData?.productos ?? []).filter(p => p.unidades_30d > 0 && p.margen != null)
  const utilTotalNeg = prodsSold.reduce((s, p) => s + prodUtil(p), 0)  // utilidad total del mix

  // Rollup por categoría: de dónde viene realmente la plata.
  const catMap = new Map<string, { venta: number; contrib: number; unidades: number }>()
  for (const p of prodsSold) {
    const k = p.categoria || 'otros'
    const e = catMap.get(k) ?? { venta: 0, contrib: 0, unidades: 0 }
    e.venta += p.venta_30d; e.contrib += prodUtil(p); e.unidades += p.unidades_30d
    catMap.set(k, e)
  }
  const catRollup = [...catMap.entries()]
    .map(([cat, v]) => ({ cat, ...v, pct: v.venta > 0 ? Math.round((v.contrib / v.venta) * 100) : 0 }))
    .sort((a, b) => b.contrib - a.contrib)
  const maxCatContrib = Math.max(1, ...catRollup.map(c => c.contrib))

  // Top productos por utilidad aportada (Pareto: los que sostienen el negocio).
  const topUtil = [...prodsSold].sort((a, b) => prodUtil(b) - prodUtil(a)).slice(0, 10)
  const maxTopUtil = Math.max(1, ...topUtil.map(prodUtil))

  // Oportunidades de precio: costo completo conocido, margen < 60%, con volumen real.
  // Sugerido = precio que llega a 68% de margen, redondeado a $100.
  const TARGET_MARGEN = 0.68
  const pricingOps = prodsSold
    .filter(p => p.costo_completo && p.pct_margen != null && p.pct_margen < 60 && p.costo != null)
    .map(p => {
      const sugerido = Math.round((p.costo! / (1 - TARGET_MARGEN)) / 100) * 100
      const ganancia = Math.max(0, (sugerido - p.precio_venta) * p.unidades_30d)
      return { p, sugerido, ganancia }
    })
    .filter(x => x.ganancia > 0 && x.sugerido > x.p.precio_venta)
    .sort((a, b) => b.ganancia - a.ganancia)
    .slice(0, 6)

  // Impacto de desechables (cuántos puntos de margen se comen para llevar).
  const conDesech = prodsSold.filter(p => p.pct_margen != null && p.pct_margen_con_desechables != null
    && p.costo_con_desechables !== p.costo)
  const dropPromedio = conDesech.length
    ? Math.round(conDesech.reduce((s, p) => s + (p.pct_margen! - p.pct_margen_con_desechables!), 0) / conDesech.length)
    : 0

  // Insights automáticos.
  const joya = topUtil[0]
  const oportunidad = pricingOps[0]
  const catEstrella = catRollup[0]

  return (
    <div className="space-y-4">
      {/* Header + filtros */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2">
          <TrendingUp size={20} className="text-forest" />
          <h1 className="text-lg font-bold text-gray-800">Rentabilidad</h1>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {([['mes', 'Este mes'], ['mes_pasado', 'Mes pasado'], ['30d', '30 días'], ['anio', 'Este año']] as [Periodo, string][]).map(([p, lbl]) => (
            <button key={p} onClick={() => setPeriodo(p)}
              className={`px-3 py-1.5 rounded-lg text-sm font-semibold border transition-colors ${
                periodo === p ? 'bg-forest text-white border-forest' : 'bg-white text-gray-500 border-gray-200 hover:bg-gray-50'
              }`}>
              {lbl}
            </button>
          ))}
          <select value={tiendaId ?? ''} onChange={e => setTiendaId(e.target.value ? Number(e.target.value) : null)}
            className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm bg-white">
            <option value="">Todas las sedes</option>
            {tiendas.map(t => <option key={t.id} value={t.id}>{t.nombre}</option>)}
          </select>
        </div>
      </div>

      {loading && <p className="text-sm text-gray-400">Cargando…</p>}

      {!loading && !data && (
        <p className="text-sm text-gray-400">No se pudo cargar la información.</p>
      )}

      {!loading && data && r && (
        <>
          {/* KPIs */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <Kpi label="Ventas" value={fmt(r.ventas)} Icon={Wallet} tint="#2d5a3f"
              sub={`${r.n_tickets} tickets`} />
            <Kpi label="Compras proveedor" value={fmt(r.compras)} Icon={ShoppingCart} tint="#b45309"
              sub={`${r.n_facturas} facturas recibidas`} />
            <Kpi label="Gastos de caja" value={fmt(r.gastos)} Icon={Receipt} tint="#9f1239"
              sub="egresos manuales (sin proveedor)" />
            <div className="bg-white rounded-2xl border border-gray-200 p-4"
              style={{ borderColor: margenPositivo ? '#bbe3c8' : '#fecaca', background: margenPositivo ? '#f2faf5' : '#fef2f2' }}>
              <div className="flex items-center gap-2 mb-1.5">
                {margenPositivo
                  ? <TrendingUp size={14} className="text-green-700" />
                  : <TrendingDown size={14} className="text-red-600" />}
                <p className="text-[11px] font-bold uppercase tracking-wide text-gray-400">Margen neto</p>
              </div>
              <p className={`text-xl font-bold font-mono leading-none ${margenPositivo ? 'text-green-800' : 'text-red-700'}`}>
                {fmt(r.margen_neto)}
              </p>
              <p className="text-xs text-gray-400 mt-1.5">
                {r.pct_margen_neto != null ? `${r.pct_margen_neto}% de la venta` : 'sin ventas en el período'}
                {' · '}bruto {fmt(r.margen_bruto)}{r.pct_margen_bruto != null ? ` (${r.pct_margen_bruto}%)` : ''}
              </p>
            </div>
          </div>

          {/* Por mes */}
          {data.por_mes.length > 0 && (
            <div className="bg-white rounded-2xl border border-gray-200 overflow-hidden">
              <p className="px-4 py-3 text-sm font-bold text-gray-700 border-b border-gray-100">Por mes</p>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-[11px] uppercase tracking-wide text-gray-400 border-b border-gray-100">
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
                      <tr key={m.mes} className="border-b border-gray-50 last:border-0">
                        <td className="px-4 py-2.5 font-semibold text-gray-700">{nombreMes(m.mes)}</td>
                        <td className="px-3 py-2.5 text-right font-mono text-gray-700">{fmt(m.ventas)}</td>
                        <td className="px-3 py-2.5 text-right font-mono text-gray-500">{fmt(m.compras)}</td>
                        <td className="px-3 py-2.5 text-right font-mono text-gray-500">{fmt(m.gastos)}</td>
                        <td className={`px-4 py-2.5 text-right font-mono font-bold ${m.margen_neto >= 0 ? 'text-green-700' : 'text-red-600'}`}>
                          {fmt(m.margen_neto)}
                        </td>
                        <td className="px-4 py-2.5 text-right font-mono text-gray-400">
                          {m.pct_margen_neto != null ? `${m.pct_margen_neto}%` : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Por sede (solo con "Todas") */}
          {!tiendaId && data.por_sede.length > 1 && (
            <div className="grid sm:grid-cols-2 gap-3">
              {data.por_sede.map(s => (
                <div key={s.tienda_id} className="bg-white rounded-2xl border border-gray-200 p-4">
                  <p className="text-sm font-bold text-gray-700 mb-2">{s.tienda}</p>
                  <div className="grid grid-cols-3 gap-2 text-center">
                    <div>
                      <p className="text-[10px] uppercase font-bold text-gray-400">Ventas</p>
                      <p className="text-sm font-mono font-bold text-gray-700 mt-0.5">{fmt(s.ventas)}</p>
                    </div>
                    <div>
                      <p className="text-[10px] uppercase font-bold text-gray-400">Compras+Gastos</p>
                      <p className="text-sm font-mono font-bold text-gray-500 mt-0.5">{fmt(s.compras + s.gastos)}</p>
                    </div>
                    <div>
                      <p className="text-[10px] uppercase font-bold text-gray-400">Margen</p>
                      <p className={`text-sm font-mono font-bold mt-0.5 ${s.margen_neto >= 0 ? 'text-green-700' : 'text-red-600'}`}>
                        {fmt(s.margen_neto)}
                      </p>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Detalle de gastos */}
          {data.gastos_detalle.length > 0 && (
            <div className="bg-white rounded-2xl border border-gray-200 overflow-hidden">
              <p className="px-4 py-3 text-sm font-bold text-gray-700 border-b border-gray-100">
                En qué se fue el gasto de caja
              </p>
              <div>
                {data.gastos_detalle.map((g, i) => (
                  <div key={i} className="flex items-center gap-3 px-4 py-2 border-b border-gray-50 last:border-0">
                    <span className="flex-1 text-sm text-gray-600 truncate">{g.concepto}</span>
                    <span className="text-xs text-gray-400 shrink-0">{g.n}×</span>
                    <span className="text-sm font-mono font-bold text-gray-700 shrink-0 w-24 text-right">{fmt(g.total)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Nota metodológica */}
          <div className="flex items-start gap-2 px-4 py-3 bg-blue-50 border border-blue-100 rounded-2xl">
            <Info size={14} className="text-blue-500 shrink-0 mt-0.5" />
            <p className="text-xs text-blue-800 leading-relaxed">{data.nota}</p>
          </div>
        </>
      )}

      {/* ── Insights automáticos: qué le dice esto del negocio ── */}
      {prodData && prodsSold.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          {joya && (
            <InsightCard Icon={Award} tint="#2d5a3f" bg="#f2faf5" title="Joya del negocio">
              <b>{joya.nombre}</b> te deja <b>{fmt(prodUtil(joya))}/mes</b> ({joya.unidades_30d} vend · {joya.pct_margen}% margen). Es lo que más plata aporta — cuidá su stock y calidad.
            </InsightCard>
          )}
          {oportunidad && (
            <InsightCard Icon={ArrowUpRight} tint="#b45309" bg="#fffbeb" title="Oportunidad de precio">
              <b>{oportunidad.p.nombre}</b> rinde solo <b>{oportunidad.p.pct_margen}%</b>. Subiéndolo a <b>{fmt(oportunidad.sugerido)}</b> ganás <b>~{fmt(oportunidad.ganancia)}/mes</b> más.
            </InsightCard>
          )}
          {catEstrella && (
            <InsightCard Icon={Layers} tint="#7c3aed" bg="#faf5ff" title="De dónde viene la plata">
              La categoría <b className="capitalize">{catEstrella.cat}</b> aporta <b>{utilTotalNeg > 0 ? Math.round((catEstrella.contrib / utilTotalNeg) * 100) : 0}%</b> de tu utilidad ({fmt(catEstrella.contrib)}/mes).
            </InsightCard>
          )}
          {dropPromedio > 0 && (
            <InsightCard Icon={AlertTriangle} tint="#9f1239" bg="#fef2f2" title="Peso de los desechables">
              Para llevar, los desechables te comen <b>~{dropPromedio} puntos</b> de margen. En el punto (cristalería) ganás más.
            </InsightCard>
          )}
        </div>
      )}

      {/* ── Utilidad por categoría + Top que sostienen el negocio ── */}
      {prodData && catRollup.length > 0 && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          <div className="bg-white rounded-2xl border border-gray-200 overflow-hidden">
            <p className="px-4 py-3 text-sm font-bold text-gray-700 border-b border-gray-100 flex items-center gap-2">
              <Layers size={15} className="text-forest" /> Utilidad por categoría
              <span className="text-xs font-normal text-gray-400">· 30 días</span>
            </p>
            <div className="py-2">
              {catRollup.map(c => (
                <Bar key={c.cat} label={c.cat.charAt(0).toUpperCase() + c.cat.slice(1)}
                  sub={`${fmt(c.venta)} venta · ${c.pct}% margen`}
                  value={c.contrib} max={maxCatContrib} right={fmt(c.contrib)} tint="#2d5a3f" />
              ))}
            </div>
          </div>
          <div className="bg-white rounded-2xl border border-gray-200 overflow-hidden">
            <p className="px-4 py-3 text-sm font-bold text-gray-700 border-b border-gray-100 flex items-center gap-2">
              <Sparkles size={15} className="text-forest" /> Top 10 que sostienen el negocio
            </p>
            <div className="py-2">
              {topUtil.map(p => (
                <Bar key={p.producto_id} label={p.nombre} sub={`${p.unidades_30d} vend · ${p.pct_margen}%`}
                  value={prodUtil(p)} max={maxTopUtil} right={fmt(prodUtil(p))} tint="oklch(55% 0.12 65)" />
              ))}
            </div>
          </div>
        </div>
      )}

      {/* ── Oportunidades de precio ── */}
      {prodData && pricingOps.length > 0 && (
        <div className="bg-white rounded-2xl border border-gray-200 overflow-hidden">
          <p className="px-4 py-3 text-sm font-bold text-gray-700 border-b border-gray-100 flex items-center gap-2">
            <ArrowUpRight size={15} className="text-amber-600" /> Oportunidades de precio
            <span className="text-xs font-normal text-gray-400">· margen bajo con volumen</span>
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-[11px] uppercase tracking-wide text-gray-400 border-b border-gray-100">
                  <th className="text-left px-4 py-2 font-bold">Producto</th>
                  <th className="text-right px-3 py-2 font-bold">Hoy</th>
                  <th className="text-right px-3 py-2 font-bold">Margen</th>
                  <th className="text-right px-3 py-2 font-bold">Sugerido</th>
                  <th className="text-right px-4 py-2 font-bold">Ganás/mes</th>
                </tr>
              </thead>
              <tbody>
                {pricingOps.map(({ p, sugerido, ganancia }) => (
                  <tr key={p.producto_id} className="border-b border-gray-50 last:border-0">
                    <td className="px-4 py-2 font-semibold text-gray-700">
                      {p.nombre}
                      <span className="text-[11px] text-gray-400 font-normal"> · {p.unidades_30d} vend</span>
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-gray-500">{fmt(p.precio_venta)}</td>
                    <td className="px-3 py-2 text-right font-mono font-bold text-red-600">{p.pct_margen}%</td>
                    <td className="px-3 py-2 text-right font-mono font-bold text-forest">{fmt(sugerido)}</td>
                    <td className="px-4 py-2 text-right font-mono font-bold text-green-700">+{fmt(ganancia)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="px-4 py-2 text-[11px] text-gray-400 border-t border-gray-100">
            Sugerido = precio para llegar a ~68% de margen (redondeado a $100). Estimación sobre ventas de 30 días; el margen usa el costo completo confirmado.
          </p>
        </div>
      )}

      {/* ── Margen por producto ── */}
      {prodData && (
        <div className="bg-white rounded-2xl border border-gray-200 overflow-hidden">
          <div className="flex flex-wrap items-center gap-3 px-4 py-3 border-b border-gray-100">
            <p className="flex items-center gap-2 text-sm font-bold text-gray-700">
              <Coffee size={15} className="text-forest" /> Margen por producto
              {totalUtil > 0 && (
                <span className="text-xs font-semibold text-gray-400">
                  · aporta {fmt(totalUtil)}/mes
                </span>
              )}
            </p>
            <div className="ml-auto flex items-center gap-2">
              {leyendo ? (
                <>
                  <span className="flex items-center gap-1.5 text-xs font-semibold text-amber-700">
                    <Loader2 size={13} className="animate-spin" /> {leyendoMsg}
                  </span>
                  <button onClick={() => { pararRef.current = true }}
                    className="px-2.5 py-1 rounded-lg text-xs font-semibold border border-gray-200 text-gray-500 hover:bg-gray-50">
                    Parar
                  </button>
                </>
              ) : (
                <>
                  {leyendoMsg && <span className="text-xs text-gray-500">{leyendoMsg}</span>}
                  {prodData.facturas_pendientes_de_costos > 0 && (
                    <button onClick={leerFacturas}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold text-white"
                      style={{ background: 'oklch(55% 0.12 65)' }}>
                      <ScanLine size={13} />
                      Leer costos de {prodData.facturas_pendientes_de_costos} facturas guardadas
                    </button>
                  )}
                </>
              )}
            </div>
          </div>

          {/* Filtro por categoría + criterio de orden */}
          {prodData.productos.length > 0 && (
            <div className="flex flex-wrap items-center gap-2 px-4 py-2.5 border-b border-gray-100 bg-gray-50/60">
              <div className="flex flex-wrap items-center gap-1.5">
                {prodCats.map(c => (
                  <button key={c} onClick={() => setProdCat(c)}
                    className={`px-2.5 py-1 rounded-lg text-xs font-semibold capitalize border transition-colors ${
                      prodCat === c ? 'bg-forest text-white border-forest' : 'bg-white text-gray-500 border-gray-200 hover:bg-gray-50'}`}>
                    {c}
                  </button>
                ))}
              </div>
              <div className="ml-auto flex items-center gap-1.5 text-xs">
                <span className="text-gray-400 font-semibold">Ordenar por:</span>
                {(([['utilidad', 'Utilidad'], ['margen', 'Margen %'], ['unidades', 'Más vendidos']]) as [typeof prodSort, string][]).map(([s, lbl]) => (
                  <button key={s} onClick={() => setProdSort(s)}
                    className={`px-2 py-1 rounded-lg font-semibold border transition-colors ${
                      prodSort === s ? 'bg-gray-800 text-white border-gray-800' : 'bg-white text-gray-500 border-gray-200 hover:bg-gray-50'}`}>
                    {lbl}
                  </button>
                ))}
              </div>
            </div>
          )}

          {prodData.productos.length === 0 ? (
            <p className="px-4 py-6 text-sm text-gray-400">Sin productos de venta con precio configurado.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-[11px] uppercase tracking-wide text-gray-400 border-b border-gray-100">
                    <th className="text-left px-4 py-2 font-bold">Producto</th>
                    <th className="text-right px-3 py-2 font-bold">Vend 30d</th>
                    <th className="text-right px-3 py-2 font-bold">Precio</th>
                    <th className="text-right px-3 py-2 font-bold">Costo</th>
                    <th className="text-right px-3 py-2 font-bold">Margen</th>
                    <th className="text-right px-4 py-2 font-bold">Utilidad 30d</th>
                  </tr>
                </thead>
                <tbody>
                  {prodSorted.map(p => {
                    const util = prodUtil(p)
                    const hayDesech = p.costo_con_desechables != null && p.costo != null
                      && p.costo_con_desechables !== p.costo
                    const pctColor = p.pct_margen == null ? 'text-gray-300'
                      : p.pct_margen >= 60 ? 'text-green-700'
                      : p.pct_margen >= 40 ? 'text-amber-600' : 'text-red-600'
                    return (
                      <tr key={p.producto_id} className="border-b border-gray-50 last:border-0">
                        <td className="px-4 py-2">
                          <p className="font-semibold text-gray-700">{p.nombre}</p>
                          {!p.costo_completo && p.insumos_sin_costo.length > 0 && (
                            <p className="text-[11px] text-amber-600">
                              falta costo de: {p.insumos_sin_costo.slice(0, 3).join(', ')}
                              {p.insumos_sin_costo.length > 3 ? '…' : ''}
                            </p>
                          )}
                          {p.desechables_sin_costo && p.desechables_sin_costo.length > 0 && (
                            <p className="text-[11px] text-gray-400">
                              falta desechable: {p.desechables_sin_costo.slice(0, 2).join(', ')}
                            </p>
                          )}
                        </td>
                        <td className="px-3 py-2 text-right font-mono text-gray-500">
                          {p.unidades_30d > 0 ? p.unidades_30d : '—'}
                        </td>
                        <td className="px-3 py-2 text-right font-mono text-gray-700">{fmt(p.precio_venta)}</td>
                        <td className="px-3 py-2 text-right font-mono">
                          <span className={p.costo_completo ? 'text-gray-500' : 'text-amber-600'}>
                            {p.costo != null ? `${p.costo_completo ? '' : '≥ '}${fmt(p.costo)}` : '—'}
                          </span>
                          {hayDesech && (
                            <span className="block text-[11px] text-orange-500">
                              p/llevar {fmt(p.costo_con_desechables!)}
                            </span>
                          )}
                        </td>
                        <td className="px-3 py-2 text-right font-mono">
                          <span className={`font-bold ${pctColor}`}>
                            {p.pct_margen != null ? `${p.pct_margen}%${p.costo_completo ? '' : ' *'}` : '—'}
                          </span>
                          {hayDesech && p.pct_margen_con_desechables != null && (
                            <span className="block text-[11px] text-orange-500">
                              llevar {p.pct_margen_con_desechables}%
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-2 text-right font-mono font-bold text-gray-800">
                          {p.unidades_30d > 0 && p.margen != null ? fmt(util) : '—'}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
          <div className="flex items-start gap-2 px-4 py-3 bg-gray-50 border-t border-gray-100">
            <Info size={13} className="text-gray-400 shrink-0 mt-0.5" />
            <p className="text-[11px] text-gray-500 leading-relaxed">
              <b>Utilidad 30d</b> = margen × unidades vendidas: lo que cada producto APORTA al mes.{' '}
              <b>p/llevar</b> suma los desechables (vaso, tapa, servilleta…); el margen en el punto
              es mayor porque ahí se usa cristalería. {prodData.nota}
            </p>
          </div>
        </div>
      )}
    </div>
  )
}
