import { useEffect, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'
import {
  AlertTriangle, TrendingUp, TrendingDown, ArrowRight,
  ShoppingCart, Check, Banknote,
} from 'lucide-react'

const fmt = (v: number) => `$${Math.round(v).toLocaleString('es-CO')}`
const fmtSigned = (v: number) => (v === 0 ? '$0' : (v > 0 ? '+' : '') + fmt(v))
function parseUTC(s: string): Date {
  const t = s.replace(' ', 'T').replace(/(\.\d{3})\d+/, '$1')
  return new Date(t.endsWith('Z') ? t : t + 'Z')
}

// ─── Interfaces ──────────────────────────────────────────────────────────────
interface Sede { id: number; nombre: string }

interface DashData {
  tienda_id: number; tienda_nombre: string
  ventas_dia: number; diferencia_caja: number; estado_caja: string
  productos_criticos: number; consignaciones_pendientes: number
  solicitudes_pendientes: number; cumplimiento_checklist: number
  alertas: { tipo: string; mensaje: string; nivel: string }[]
  apertura_realizada: boolean; inventario_check: boolean
  pasteleria_check: boolean; siigo_check: boolean
  limpieza_check: boolean; cierre_realizado: boolean
}

interface Insumo {
  producto_id: number; nombre: string; unidad: string; categoria: string
  stock_apertura: number | null; stock_cierre: number | null
  stock_actual: number; stock_minimo: number
  diferencia: number | null; bajo_minimo: boolean
}

interface PendienteItem {
  turno_id: number; fecha_apertura: string; fecha_cierre: string
  esperado: number; consignado: number; pendiente: number
}

interface AdminResumen {
  tienda_id: number
  periodo: { desde: string; hasta: string }
  ventas_mes: number
  consignaciones: { count: number; monto: number }
  insumos: Insumo[]
  entradas: {
    total: number
    por_proveedor: { proveedor: string; total: number; count: number }[]
  }
  egresos: { total: number; count: number }
}

// ─── Main component ───────────────────────────────────────────────────────────
export default function Dashboard() {
  const { user } = useAuth()
  const navigate = useNavigate()

  const [sedes, setSedes]         = useState<Sede[]>([])
  const [tiendaId, setTiendaId]   = useState<number>(user?.tienda_id ?? 1)
  const [dashData, setDashData]   = useState<Record<number, DashData>>({})
  const [resumen, setResumen]     = useState<AdminResumen | null>(null)
  const [pendienteConsig, setPendienteConsig] = useState<{ items: PendienteItem[], total_pendiente: number } | null>(null)
  const [loading, setLoading]     = useState(true)

  useEffect(() => {
    api.get('/auth/tiendas').then(({ data }) => {
      setSedes(data)
      data.forEach((s: Sede) => {
        api.get(`/dashboard/${s.id}`).then(r =>
          setDashData(prev => ({ ...prev, [s.id]: r.data }))
        ).catch(() => null)
      })
    }).catch(() => null).finally(() => setLoading(false))
  }, [])

  const loadResumen = useCallback((tid: number) => {
    setResumen(null)
    api.get(`/dashboard/${tid}/admin-resumen`).then(r => setResumen(r.data)).catch(() => null)
  }, [])

  useEffect(() => { loadResumen(tiendaId) }, [tiendaId, loadResumen])

  useEffect(() => {
    setPendienteConsig(null)
    api.get(`/consignaciones/pendiente/${tiendaId}`).then(r => setPendienteConsig(r.data)).catch(() => null)
  }, [tiendaId])

  const active = dashData[tiendaId] ?? null

  // ── Checklist items ──────────────────────────────────────────────────────
  const checklist = active ? [
    { l: 'Apertura',   d: active.apertura_realizada  },
    { l: 'Inventario', d: active.inventario_check     },
    { l: 'Pastelería', d: active.pasteleria_check     },
    { l: 'Siigo cierre', d: active.siigo_check        },
  ] : []

  // ── Alertas consolidadas ──────────────────────────────────────────────────
  const alertas = active?.alertas ?? []
  const criticas = alertas.filter(a => a.nivel === 'critico')

  if (loading) return (
    <div className="flex items-center justify-center py-20">
      <p className="text-sm text-warm-400 animate-pulse">Cargando...</p>
    </div>
  )

  return (
    <div className="flex flex-col gap-3">

      {/* ── Tienda tabs + KPI strip ───────────────────────────────────────── */}
      <div className="flex flex-col sm:flex-row gap-2 sm:gap-3 sm:items-stretch">

        {/* Tabs */}
        <div className="flex gap-1 p-1 bg-white border border-warm-200 rounded-xl shrink-0">
          {sedes.length === 0
            ? [1, 2].map(i => <div key={i} className="w-28 h-9 rounded-lg bg-warm-100 animate-pulse" />)
            : sedes.map(s => {
                const d = dashData[s.id]
                const active_ = s.id === tiendaId
                const bad = d && d.diferencia_caja !== 0
                return (
                  <button
                    key={s.id}
                    onClick={() => setTiendaId(s.id)}
                    className="flex items-center gap-2 px-3 py-2 rounded-lg text-left transition-all"
                    style={{
                      background: active_ ? 'oklch(48% 0.12 155)' : 'transparent',
                      color: active_ ? '#fff' : 'oklch(45% 0.01 60)',
                    }}
                  >
                    <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{
                      background: active_ ? '#fff'
                        : !d ? 'oklch(75% 0.01 60)'
                        : bad ? 'oklch(57% 0.22 25)'
                        : 'oklch(55% 0.15 155)',
                    }} />
                    <span className="text-[13px] font-bold whitespace-nowrap">{s.nombre}</span>
                    {d && (
                      <span className="text-[11px] font-mono opacity-75 hidden sm:inline">
                        {fmt(d.ventas_dia)}
                      </span>
                    )}
                  </button>
                )
              })
          }
        </div>

        {/* KPI strip */}
        <div className="flex-1 grid grid-cols-2 sm:grid-cols-4 gap-px bg-warm-200 border border-warm-200 rounded-xl overflow-hidden">
          {[
            {
              l: 'Ventas mes',
              v: resumen ? fmt(resumen.ventas_mes) : '—',
              s: resumen ? `${resumen.periodo.desde.slice(5).replace('-','/')} – ${resumen.periodo.hasta.slice(5).replace('-','/')}` : '',
              tone: 'ok',
            },
            {
              l: 'Diferencia caja',
              v: active ? fmtSigned(active.diferencia_caja) : '—',
              s: active?.estado_caja === 'sin_turno' ? 'sin turno' : 'turno activo',
              tone: !active ? 'neu' : active.diferencia_caja === 0 ? 'ok' : 'bad',
            },
            {
              l: 'Productos críticos',
              v: active ? String(active.productos_criticos) : '—',
              s: 'bajo mínimo',
              tone: !active ? 'neu' : active.productos_criticos > 0 ? 'bad' : 'ok',
            },
            {
              l: 'Checklist hoy',
              v: active ? `${Math.round(active.cumplimiento_checklist)}%` : '—',
              s: active ? `${checklist.filter(c => c.d).length} de ${checklist.length} hechos` : '',
              tone: !active ? 'neu' : active.cumplimiento_checklist >= 100 ? 'ok' : 'warn',
            },
          ].map((k, i) => (
            <div key={i} className="bg-white px-3 py-2.5">
              <p className="text-[10px] font-bold uppercase tracking-wide text-warm-400">{k.l}</p>
              <p className="text-xl font-bold font-mono mt-0.5 leading-none" style={{
                color: k.tone === 'ok'   ? 'oklch(48% 0.15 155)'
                     : k.tone === 'bad'  ? 'oklch(50% 0.22 25)'
                     : k.tone === 'warn' ? 'oklch(52% 0.18 65)'
                     : 'oklch(55% 0.01 60)',
              }}>{k.v}</p>
              <p className="text-[10px] text-warm-300 mt-0.5">{k.s}</p>
            </div>
          ))}
        </div>
      </div>

      {/* ── Alert strip ────────────────────────────────────────────────────── */}
      {criticas.length > 0 && (
        <div className="flex items-center gap-3 px-3 py-2 bg-red-50 border border-red-200 rounded-lg text-[12px]">
          <AlertTriangle size={13} className="text-red-500 shrink-0" />
          <span className="font-bold text-red-700">{criticas.length} {criticas.length === 1 ? 'alerta' : 'alertas'}</span>
          <span className="w-px h-3 bg-red-200" />
          <span className="text-red-600 flex-1 truncate">
            {criticas.map(a => a.mensaje).join(' · ')}
          </span>
          <button
            onClick={() => navigate('/bandeja')}
            className="flex items-center gap-1 text-[11px] font-bold text-white bg-red-500 px-2.5 py-1 rounded-md hover:bg-red-600 transition-colors shrink-0"
          >
            Ir a bandeja <ArrowRight size={10} />
          </button>
        </div>
      )}

      {/* ── Main grid ──────────────────────────────────────────────────────── */}
      <div className="grid gap-3 grid-cols-1 md:grid-cols-[1.6fr_1fr]">

        {/* ── Inventario table ── */}
        <div className="bg-white border border-warm-200 rounded-xl overflow-hidden flex flex-col">
          <div className="flex items-center justify-between px-3.5 py-2.5 border-b border-warm-100">
            <p className="text-[11px] font-bold uppercase tracking-wide text-warm-400">
              Existencias para pedido — {active?.tienda_nombre ?? '…'}
            </p>
            <div className="flex items-center gap-2">
              {resumen && resumen.insumos.filter(i => i.bajo_minimo).length > 0 && (
                <span className="text-[10px] font-bold text-red-500">
                  {resumen.insumos.filter(i => i.bajo_minimo).length} bajo mínimo
                </span>
              )}
              <button
                onClick={() => navigate('/inventario')}
                className="text-[11px] font-bold px-2.5 py-1 rounded-md"
                style={{ background: 'oklch(95% 0.04 155)', color: 'oklch(40% 0.12 155)' }}
              >
                Ver inventario
              </button>
            </div>
          </div>
          <div className="overflow-auto flex-1">
            {!resumen ? (
              <div className="p-6 space-y-2">
                {[1,2,3,4].map(i => <div key={i} className="h-8 bg-warm-100 rounded animate-pulse" />)}
              </div>
            ) : resumen.insumos.length === 0 ? (
              <p className="text-sm text-warm-400 text-center py-10">Sin datos de inventario</p>
            ) : (
              <table className="w-full text-xs border-collapse">
                <thead>
                  <tr className="bg-warm-50 sticky top-0">
                    {['Producto', 'Inicio', 'Cierre', 'Actual', 'Mín.', 'Δ'].map((h, i) => (
                      <th key={h} className="py-2 px-3 text-[10px] font-bold uppercase tracking-wide text-warm-400 border-b border-warm-100"
                        style={{ textAlign: i === 0 ? 'left' : 'right' }}>
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {resumen.insumos.map(ins => {
                    const delta = ins.diferencia ?? (ins.stock_actual - (ins.stock_apertura ?? ins.stock_actual))
                    return (
                      <tr key={ins.producto_id}
                        style={{ background: ins.bajo_minimo ? 'oklch(97% 0.015 25)' : undefined }}>
                        <td className="py-2 px-3 border-b border-warm-50">
                          <div className="flex items-center gap-1.5">
                            {ins.bajo_minimo && <span className="w-1 h-1 rounded-full bg-red-500 shrink-0" />}
                            <div>
                              <p className="font-semibold" style={{ color: ins.bajo_minimo ? 'oklch(45% 0.20 25)' : 'oklch(25% 0.01 60)' }}>
                                {ins.nombre}
                              </p>
                              <p className="text-[10px] text-warm-300">{ins.unidad}</p>
                            </div>
                          </div>
                        </td>
                        <td className="py-2 px-3 text-right font-mono text-warm-400 border-b border-warm-50">
                          {ins.stock_apertura ?? '—'}
                        </td>
                        <td className="py-2 px-3 text-right font-mono text-warm-400 border-b border-warm-50">
                          {ins.stock_cierre ?? '—'}
                        </td>
                        <td className="py-2 px-3 text-right font-mono font-bold border-b border-warm-50 text-[13px]"
                          style={{ color: ins.bajo_minimo ? 'oklch(45% 0.20 25)' : 'oklch(25% 0.01 60)' }}>
                          {ins.stock_actual}
                        </td>
                        <td className="py-2 px-3 text-right font-mono text-warm-400 border-b border-warm-50">
                          {ins.stock_minimo}
                        </td>
                        <td className="py-2 px-3 text-right font-mono text-[11px] border-b border-warm-50"
                          style={{ color: delta < 0 ? 'oklch(45% 0.20 25)' : delta > 0 ? 'oklch(48% 0.15 155)' : 'oklch(55% 0.01 60)' }}>
                          {delta > 0 ? '+' : ''}{delta}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            )}
          </div>
        </div>

        {/* ── Right column ── */}
        <div className="flex flex-col gap-3">

          {/* Movimientos del mes + Top proveedores */}
          <div className="bg-white border border-warm-200 rounded-xl overflow-hidden">
            <div className="px-3.5 py-2.5 border-b border-warm-100">
              <p className="text-[11px] font-bold uppercase tracking-wide text-warm-400">Movimientos del mes</p>
            </div>
            <div className="p-3.5">
              <div className="grid grid-cols-2 gap-3 mb-3">
                <div>
                  <div className="flex items-center gap-1.5 mb-1">
                    <TrendingUp size={11} className="text-green-600" />
                    <span className="text-[11px] font-semibold text-warm-500">Entradas</span>
                  </div>
                  <p className="text-lg font-bold font-mono text-warm-800">
                    {resumen ? fmt(resumen.entradas.total) : '—'}
                  </p>
                  <p className="text-[10px] text-warm-300 mt-0.5">
                    {resumen ? `${resumen.entradas.por_proveedor.length} proveedores` : ''}
                  </p>
                </div>
                <div className="border-l border-warm-100 pl-3">
                  <div className="flex items-center gap-1.5 mb-1">
                    <TrendingDown size={11} className="text-red-400" />
                    <span className="text-[11px] font-semibold text-warm-500">Egresos caja</span>
                  </div>
                  <p className="text-lg font-bold font-mono text-red-600">
                    {resumen ? fmt(resumen.egresos.total) : '—'}
                  </p>
                  <p className="text-[10px] text-warm-300 mt-0.5">
                    {resumen ? `${resumen.egresos.count} movimientos` : ''}
                  </p>
                </div>
              </div>

              {resumen && resumen.entradas.por_proveedor.length > 0 && (
                <div className="border-t border-warm-100 pt-3">
                  <p className="text-[10px] font-bold uppercase tracking-wide text-warm-400 mb-2">Top proveedores</p>
                  <div className="space-y-2">
                    {resumen.entradas.por_proveedor.slice(0, 5).map(p => {
                      const pct = resumen.entradas.total > 0
                        ? Math.round((p.total / resumen.entradas.total) * 100)
                        : 0
                      return (
                        <div key={p.proveedor} className="flex items-center gap-2">
                          <span className="text-[11px] font-semibold text-warm-600 flex-1 truncate min-w-0">
                            {p.proveedor}
                          </span>
                          <div className="w-14 h-1 bg-warm-100 rounded-full overflow-hidden shrink-0">
                            <div className="h-full rounded-full"
                              style={{ width: `${pct}%`, background: 'oklch(60% 0.12 65)' }} />
                          </div>
                          <span className="text-[11px] font-semibold font-mono text-warm-500 shrink-0">
                            {fmt(p.total)}
                          </span>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Consignaciones + Checklist */}
          <div className="grid grid-cols-2 gap-3 flex-1">

            {/* Consignaciones */}
            <div className="bg-white border border-warm-200 rounded-xl overflow-hidden flex flex-col">
              <div className="px-3.5 py-2.5 border-b border-warm-100 flex items-center justify-between">
                <p className="text-[11px] font-bold uppercase tracking-wide text-warm-400">Consignaciones</p>
                {pendienteConsig && pendienteConsig.items.filter(i => i.pendiente > 0).length > 0 && (
                  <span className="text-[10px] font-bold px-1.5 py-0.5 rounded-full"
                    style={{ background: 'oklch(93% 0.04 65)', color: 'oklch(42% 0.15 65)' }}>
                    {pendienteConsig.items.filter(i => i.pendiente > 0).length} pendiente{pendienteConsig.items.filter(i => i.pendiente > 0).length > 1 ? 's' : ''}
                  </span>
                )}
              </div>
              <div className="p-3.5 flex flex-col flex-1">
                {!pendienteConsig ? (
                  <div className="space-y-2">
                    <div className="h-8 bg-warm-100 rounded animate-pulse" />
                    <div className="h-4 bg-warm-100 rounded animate-pulse" />
                  </div>
                ) : pendienteConsig.items.filter(i => i.pendiente > 0).length === 0 ? (
                  <div className="flex-1 flex flex-col items-center justify-center gap-1.5 py-4">
                    <Check size={18} style={{ color: 'oklch(48% 0.15 155)' }} />
                    <span className="text-[12px] font-semibold" style={{ color: 'oklch(48% 0.15 155)' }}>Al día</span>
                  </div>
                ) : (
                  <>
                    <div className="space-y-2 flex-1">
                      {pendienteConsig.items.filter(i => i.pendiente > 0).map(item => (
                        <div key={item.turno_id} className="flex items-center justify-between gap-2">
                          <span className="text-[11px] capitalize text-warm-600 truncate">
                            {parseUTC(item.fecha_cierre).toLocaleDateString('es-CO', { weekday: 'short', day: 'numeric', month: 'short' })}
                          </span>
                          <span className="text-[12px] font-bold font-mono shrink-0"
                            style={{ color: 'oklch(45% 0.18 65)' }}>
                            {fmt(item.pendiente)}
                          </span>
                        </div>
                      ))}
                    </div>
                    <div className="flex items-center justify-between pt-2 mt-2 border-t border-warm-100">
                      <span className="text-[10px] font-bold text-warm-400 uppercase tracking-wide">Total</span>
                      <span className="text-[13px] font-bold font-mono" style={{ color: 'oklch(45% 0.18 65)' }}>
                        {fmt(pendienteConsig.total_pendiente)}
                      </span>
                    </div>
                    <button
                      onClick={() => navigate('/consignaciones')}
                      className="mt-2 flex items-center justify-center gap-1 w-full py-2 rounded-lg text-[11px] font-bold transition-colors"
                      style={{
                        background: 'oklch(96% 0.025 65)',
                        border: '1px solid oklch(85% 0.06 65)',
                        color: 'oklch(45% 0.15 65)',
                      }}
                    >
                      Ver detalle <ArrowRight size={10} />
                    </button>
                  </>
                )}
              </div>
            </div>

            {/* Checklist */}
            <div className="bg-white border border-warm-200 rounded-xl overflow-hidden flex flex-col">
              <div className="px-3.5 py-2.5 border-b border-warm-100">
                <p className="text-[11px] font-bold uppercase tracking-wide text-warm-400">Checklist hoy</p>
              </div>
              <div className="p-3.5 flex-1">
                {checklist.length > 0 ? (
                  <div className="space-y-2">
                    {checklist.map(c => (
                      <div key={c.l} className="flex items-center gap-2">
                        <span className="w-3.5 h-3.5 rounded flex items-center justify-center shrink-0 transition-colors"
                          style={{
                            background: c.d ? 'oklch(48% 0.15 155)' : 'transparent',
                            border: c.d ? 'none' : '1.5px solid oklch(70% 0.01 60)',
                          }}>
                          {c.d && <Check size={9} color="#fff" strokeWidth={3} />}
                        </span>
                        <span className="text-[12px]"
                          style={{
                            color: c.d ? 'oklch(55% 0.01 60)' : 'oklch(25% 0.01 60)',
                            textDecoration: c.d ? 'line-through' : 'none',
                          }}>
                          {c.l}
                        </span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="space-y-2">
                    {[1,2,3,4].map(i => <div key={i} className="h-5 bg-warm-100 rounded animate-pulse" />)}
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Accesos rápidos */}
          <div className="bg-white border border-warm-200 rounded-xl p-3">
            <p className="text-[10px] font-bold uppercase tracking-wide text-warm-400 mb-2">Accesos rápidos</p>
            <div className="grid grid-cols-4 gap-2">
              {[
                { label: 'Bandeja',     to: '/bandeja',        badge: active?.solicitudes_pendientes ?? null },
                { label: 'Inventario',  to: '/inventario',     badge: active?.productos_criticos ?? null },
                { label: 'Compras',     to: '/compras',        badge: null },
                { label: 'Consign.',    to: '/consignaciones', badge: resumen?.consignaciones.count ?? null },
              ].map(({ label, to, badge }) => (
                <button key={to} onClick={() => navigate(to)}
                  className="relative flex flex-col items-center gap-1 py-2 rounded-lg border border-warm-200 bg-warm-50 hover:bg-amber-50 hover:border-amber-300 transition-colors text-[11px] font-semibold text-warm-600">
                  {badge ? (
                    <span className="absolute -top-1 -right-1 text-[10px] font-bold bg-red-500 text-white w-4 h-4 rounded-full flex items-center justify-center">
                      {badge}
                    </span>
                  ) : null}
                  {label === 'Compras' && <ShoppingCart size={14} className="text-warm-400" />}
                  {label === 'Bandeja' && <Banknote size={14} className="text-amber-500" />}
                  {label === 'Inventario' && <AlertTriangle size={14} className="text-blue-400" />}
                  {label === 'Consign.' && <Banknote size={14} className="text-teal-500" />}
                  {label}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
