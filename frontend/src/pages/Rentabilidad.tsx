import { useEffect, useRef, useState } from 'react'
import api from '../api/client'
import {
  TrendingUp, TrendingDown, ShoppingCart, Wallet, Receipt, Info,
  Coffee, ScanLine, Loader2,
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

      {/* ── Margen por producto ── */}
      {prodData && (
        <div className="bg-white rounded-2xl border border-gray-200 overflow-hidden">
          <div className="flex flex-wrap items-center gap-3 px-4 py-3 border-b border-gray-100">
            <p className="flex items-center gap-2 text-sm font-bold text-gray-700">
              <Coffee size={15} className="text-forest" /> Margen por producto
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

          {prodData.productos.length === 0 ? (
            <p className="px-4 py-6 text-sm text-gray-400">Sin productos de venta con precio configurado.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-[11px] uppercase tracking-wide text-gray-400 border-b border-gray-100">
                    <th className="text-left px-4 py-2 font-bold">Producto</th>
                    <th className="text-right px-3 py-2 font-bold">Vendidos 30d</th>
                    <th className="text-right px-3 py-2 font-bold">Precio</th>
                    <th className="text-right px-3 py-2 font-bold">Costo</th>
                    <th className="text-right px-4 py-2 font-bold">Margen</th>
                    <th className="text-right px-4 py-2 font-bold">%</th>
                  </tr>
                </thead>
                <tbody>
                  {prodData.productos.map(p => (
                    <tr key={p.producto_id} className="border-b border-gray-50 last:border-0">
                      <td className="px-4 py-2">
                        <p className="font-semibold text-gray-700">{p.nombre}</p>
                        {!p.costo_completo && p.insumos_sin_costo.length > 0 && (
                          <p className="text-[11px] text-amber-600">
                            falta costo de: {p.insumos_sin_costo.slice(0, 3).join(', ')}
                            {p.insumos_sin_costo.length > 3 ? '…' : ''}
                          </p>
                        )}
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-gray-500">
                        {p.unidades_30d > 0 ? p.unidades_30d : '—'}
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-gray-700">{fmt(p.precio_venta)}</td>
                      <td className={`px-3 py-2 text-right font-mono ${p.costo_completo ? 'text-gray-500' : 'text-amber-600'}`}>
                        {p.costo != null ? `${p.costo_completo ? '' : '≥ '}${fmt(p.costo)}` : '—'}
                      </td>
                      <td className={`px-4 py-2 text-right font-mono font-bold ${
                        p.margen == null ? 'text-gray-300' : p.margen >= 0 ? 'text-green-700' : 'text-red-600'}`}>
                        {p.margen != null ? fmt(p.margen) : '—'}
                      </td>
                      <td className={`px-4 py-2 text-right font-mono ${p.costo_completo ? 'text-gray-400' : 'text-amber-600'}`}>
                        {p.pct_margen != null ? `${p.pct_margen}%${p.costo_completo ? '' : ' *'}` : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="flex items-start gap-2 px-4 py-3 bg-gray-50 border-t border-gray-100">
            <Info size={13} className="text-gray-400 shrink-0 mt-0.5" />
            <p className="text-[11px] text-gray-500 leading-relaxed">{prodData.nota}</p>
          </div>
        </div>
      )}
    </div>
  )
}
