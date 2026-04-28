import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'
import {
  AlertTriangle, Wallet, Package, Cake, Banknote, UserCheck,
  ExternalLink, Trash2, Inbox, ChefHat, TrendingUp, CheckSquare,
  Clock, ArrowRight,
} from 'lucide-react'
import DifferenceBadge from '../components/DifferenceBadge'

interface ProductoCritico { nombre: string; stock_actual: number; stock_minimo: number; unidad: string }
interface Alerta { tipo: string; mensaje: string; nivel: string }
interface DashboardData {
  tienda_id: number; tienda_nombre: string
  ventas_dia: number; estado_caja: string; diferencia_caja: number
  productos_criticos: number; productos_criticos_lista: ProductoCritico[]
  consignaciones_pendientes: number; solicitudes_pendientes: number
  cumplimiento_checklist: number; alertas: Alerta[]
  apertura_realizada: boolean; inventario_check: boolean
  pasteleria_check: boolean; siigo_check: boolean
  limpieza_check: boolean; cierre_realizado: boolean
}
interface Entrega {
  id: number; fecha_hora: string
  efectivo_real: number; efectivo_esperado: number
  diferencia_efectivo: number; diferencia_tarjeta: number
  ventas_tarjeta_bold: number; imagen_url: string | null
}
interface Comparativo {
  tienda_id: number; tienda_nombre: string
  total_ventas: number; ticket_promedio: number; n_mermas: number; n_turnos: number
}

const CHECKLIST_ITEMS = [
  { campo: 'apertura_realizada', label: 'Apertura de turno',   manual: false },
  { campo: 'inventario_check',   label: 'Conteo inventario',   manual: false },
  { campo: 'pasteleria_check',   label: 'Pastelería',          manual: false },
  { campo: 'siigo_check',        label: 'Siigo cuadrado',      manual: true  },
  { campo: 'limpieza_check',     label: 'Limpieza',            manual: true  },
  { campo: 'cierre_realizado',   label: 'Cierre de turno',     manual: false },
] as const

const fmt = (v: number) => `$${v.toLocaleString('es-CO')}`

export default function Dashboard() {
  const { user } = useAuth()
  const navigate = useNavigate()

  const [tiendaSeleccionada, setTiendaSeleccionada] = useState<number>(user?.tienda_id ?? 1)
  const [data, setData] = useState<DashboardData | null>(null)
  const [data2, setData2] = useState<DashboardData | null>(null)
  const [comparativo, setComparativo] = useState<Comparativo[]>([])
  const [entregas, setEntregas] = useState<Entrega[]>([])
  const [mermasKpi, setMermasKpi] = useState<{ total_registros: number } | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const loadTienda = async (tid: number) => {
    const hoy = new Date()
    const desde = `${hoy.getFullYear()}-${String(hoy.getMonth() + 1).padStart(2, '0')}-01`
    const hasta = hoy.toISOString().slice(0, 10)
    const [dash, ent, mermas] = await Promise.all([
      api.get(`/dashboard/${tid}`),
      api.get(`/caja/entregas/tienda/${tid}`).catch(() => ({ data: [] })),
      api.get(`/informes/kpi-mermas?tienda_id=${tid}&fecha_desde=${desde}&fecha_hasta=${hasta}`).catch(() => ({ data: null })),
    ])
    return { dash: dash.data, ent: ent.data, mermas: mermas.data }
  }

  useEffect(() => {
    setLoading(true)
    setError('')
    Promise.all([
      loadTienda(1).catch(() => null),
      loadTienda(2).catch(() => null),
      api.get('/dashboard/comparativo').catch(() => ({ data: [] })),
    ]).then(([t1, t2, comp]) => {
      if (t1) setData(t1.dash)
      if (t2) setData2(t2.dash)
      setComparativo(comp.data ?? [])
      const sel = tiendaSeleccionada === 1 ? t1 : t2
      if (sel) { setEntregas(sel.ent); setMermasKpi(sel.mermas) }
    }).catch(e => setError(e?.response?.data?.detail || 'Error al cargar dashboard'))
    .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    if (!data && !data2) return
    loadTienda(tiendaSeleccionada)
      .then(({ dash, ent, mermas }) => {
        if (tiendaSeleccionada === 1) setData(dash)
        else setData2(dash)
        setEntregas(ent)
        setMermasKpi(mermas)
      }).catch(() => {})
  }, [tiendaSeleccionada])

  const toggleChecklist = async (campo: string, valorActual: boolean) => {
    if (!data) return
    const tid = tiendaSeleccionada
    const nuevoValor = !valorActual
    const update = (prev: DashboardData | null) => {
      if (!prev) return prev
      const updated = { ...prev, [campo]: nuevoValor }
      const campos = CHECKLIST_ITEMS.map(i => updated[i.campo as keyof DashboardData] as boolean)
      updated.cumplimiento_checklist = (campos.filter(Boolean).length / campos.length) * 100
      return updated
    }
    if (tid === 1) setData(update)
    else setData2(update)
    try {
      await api.patch(`/dashboard/${tid}/checklist`, { campo, valor: nuevoValor })
    } catch {
      const revert = (prev: DashboardData | null) => {
        if (!prev) return prev
        const reverted = { ...prev, [campo]: valorActual }
        const campos = CHECKLIST_ITEMS.map(i => reverted[i.campo as keyof DashboardData] as boolean)
        reverted.cumplimiento_checklist = (campos.filter(Boolean).length / campos.length) * 100
        return reverted
      }
      if (tid === 1) setData(revert)
      else setData2(revert)
    }
  }

  if (loading && !data && !data2) return (
    <div className="flex items-center justify-center py-16">
      <p className="text-sm text-warm-400 animate-pulse">Cargando dashboard...</p>
    </div>
  )

  if (error && !data && !data2) return (
    <div className="flex flex-col items-center justify-center py-16 gap-3">
      <AlertTriangle size={24} className="text-red-400" />
      <p className="text-sm text-red-500">{error}</p>
      <button onClick={() => window.location.reload()}
        className="text-xs text-forest hover:underline">Reintentar</button>
    </div>
  )

  const active = tiendaSeleccionada === 1 ? data : data2

  // ── Tarjeta comparativa de tienda ────────────────────────────────────────────
  const TiendaCard = ({ d, tid }: { d: DashboardData | null; tid: number }) => {
    if (!d) return null
    const isSelected = tiendaSeleccionada === tid
    const comp = comparativo.find(c => c.tienda_id === tid)
    const alertasCriticas = d.alertas.filter(a => a.nivel === 'critico').length
    const checkPct = Math.round(d.cumplimiento_checklist)
    return (
      <button
        onClick={() => setTiendaSeleccionada(tid)}
        className={`flex-1 text-left rounded-2xl border-2 p-4 transition-all ${
          isSelected
            ? 'border-forest bg-white shadow-sm'
            : 'border-warm-200 bg-warm-50 hover:border-warm-300'
        }`}
      >
        <div className="flex items-center justify-between mb-3">
          <p className="font-bold text-warm-800 text-sm">{d.tienda_nombre}</p>
          <div className="flex items-center gap-1.5">
            {alertasCriticas > 0 && (
              <span className="text-xs font-bold bg-red-100 text-red-600 px-1.5 py-0.5 rounded-full">
                {alertasCriticas} alerta{alertasCriticas > 1 ? 's' : ''}
              </span>
            )}
            <span className={`w-2 h-2 rounded-full ${
              d.estado_caja === 'sin_turno' ? 'bg-warm-300' :
              d.diferencia_caja !== 0 ? 'bg-red-500' : 'bg-forest'
            }`} />
          </div>
        </div>
        <p className="text-2xl font-bold text-warm-800 font-mono mb-1">{fmt(d.ventas_dia)}</p>
        <p className="text-xs text-warm-400 mb-3">ventas hoy</p>
        <div className="flex items-center justify-between text-xs">
          <span className="text-warm-500">Checklist {checkPct}%</span>
          <span className={`font-semibold ${d.productos_criticos > 0 ? 'text-red-500' : 'text-forest'}`}>
            {d.productos_criticos > 0 ? `${d.productos_criticos} críticos` : 'Stock OK'}
          </span>
        </div>
        <div className="mt-2 w-full bg-warm-200 rounded-full h-1">
          <div className="h-1 rounded-full transition-all" style={{ width: `${checkPct}%`, background: 'oklch(48% 0.12 155)' }} />
        </div>
      </button>
    )
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div>
        <h1 className="text-base font-bold text-warm-700">Panel de control</h1>
        <p className="text-xs text-warm-400 capitalize">
          {new Date().toLocaleDateString('es-CO', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })}
        </p>
      </div>

      {/* Comparativo de tiendas */}
      <div className="flex gap-3">
        <TiendaCard d={data} tid={1} />
        <TiendaCard d={data2} tid={2} />
      </div>

      {!active ? null : (
        <>
          {/* Alertas */}
          {active.alertas.length > 0 && (
            <div className="space-y-2">
              {active.alertas.map((a, i) => (
                <div key={i} className={`flex items-center gap-2.5 px-4 py-2.5 rounded-xl border text-sm ${
                  a.nivel === 'critico'
                    ? 'bg-red-50 border-red-200 text-red-700'
                    : 'bg-amber-50 border-amber-200 text-amber-700'
                }`}>
                  <AlertTriangle size={13} className="shrink-0" />
                  <span className="flex-1">{a.mensaje}</span>
                  {a.tipo === 'solicitud' && (
                    <button onClick={() => navigate('/bandeja')} className="flex items-center gap-1 text-xs font-semibold hover:underline">
                      Ver <ArrowRight size={11} />
                    </button>
                  )}
                  {a.tipo === 'inventario' && (
                    <button onClick={() => navigate('/inventario')} className="flex items-center gap-1 text-xs font-semibold hover:underline">
                      Ver <ArrowRight size={11} />
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* KPIs */}
          <div className="grid grid-cols-2 gap-3">
            <div className="bg-white rounded-xl border border-warm-200 p-4">
              <p className="text-xs text-warm-400 mb-1 flex items-center gap-1"><TrendingUp size={11} /> Ventas hoy</p>
              <p className="text-xl font-bold text-warm-800 font-mono">{fmt(active.ventas_dia)}</p>
            </div>
            <div className={`rounded-xl border p-4 ${active.diferencia_caja !== 0 ? 'bg-red-50 border-red-200' : 'bg-white border-warm-200'}`}>
              <p className="text-xs text-warm-400 mb-1 flex items-center gap-1"><Banknote size={11} /> Caja</p>
              <p className={`text-xl font-bold font-mono ${active.diferencia_caja !== 0 ? 'text-red-700' : 'text-forest'}`}>
                {active.diferencia_caja !== 0 ? fmt(active.diferencia_caja) : 'Cuadrada'}
              </p>
            </div>
            <div className={`rounded-xl border p-4 ${active.solicitudes_pendientes > 0 ? 'bg-amber-50 border-amber-200' : 'bg-white border-warm-200'}`}>
              <p className="text-xs text-warm-400 mb-1 flex items-center gap-1"><Inbox size={11} /> Solicitudes</p>
              <p className={`text-xl font-bold font-mono ${active.solicitudes_pendientes > 0 ? 'text-amber-700' : 'text-forest'}`}>
                {active.solicitudes_pendientes > 0 ? `${active.solicitudes_pendientes} pend.` : 'Al día'}
              </p>
            </div>
            <div className="bg-white rounded-xl border border-warm-200 p-4">
              <p className="text-xs text-warm-400 mb-1 flex items-center gap-1"><Trash2 size={11} /> Mermas mes</p>
              <p className="text-xl font-bold font-mono text-warm-700">
                {mermasKpi ? mermasKpi.total_registros : '—'}
              </p>
            </div>
          </div>

          {/* Checklist + Productos críticos */}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {/* Checklist */}
            <div className="bg-white rounded-xl border border-warm-200 p-4">
              <div className="flex items-center justify-between mb-3">
                <p className="text-sm font-semibold text-warm-700 flex items-center gap-1.5">
                  <CheckSquare size={13} className="text-forest" /> Checklist
                </p>
                <span className="text-xs font-bold text-forest">{Math.round(active.cumplimiento_checklist)}%</span>
              </div>
              <div className="w-full bg-warm-100 rounded-full h-1 mb-4">
                <div className="h-1 rounded-full transition-all" style={{ width: `${active.cumplimiento_checklist}%`, background: 'oklch(48% 0.12 155)' }} />
              </div>
              <div className="space-y-2.5">
                {CHECKLIST_ITEMS.map(({ campo, label, manual }) => {
                  const checked = active[campo as keyof DashboardData] as boolean
                  return (
                    <div key={campo} className="flex items-center justify-between gap-2">
                      <div className="flex items-center gap-2 min-w-0">
                        <div className="w-3.5 h-3.5 rounded-full shrink-0 flex items-center justify-center"
                          style={{ background: checked ? 'oklch(48% 0.12 155)' : 'oklch(92% 0.006 75)' }}>
                          {checked && (
                            <svg width="8" height="6" fill="none" viewBox="0 0 9 7">
                              <path d="M1 3.5L3.5 6L8 1" stroke="white" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                            </svg>
                          )}
                        </div>
                        <span className={`text-xs truncate ${checked ? 'text-warm-700' : 'text-warm-400'}`}>{label}</span>
                      </div>
                      {manual ? (
                        <button
                          onClick={() => toggleChecklist(campo, checked)}
                          className="relative inline-flex shrink-0 rounded-full transition-colors duration-200"
                          style={{ width: 30, height: 17, background: checked ? 'oklch(48% 0.12 155)' : 'oklch(85% 0.008 75)' }}
                        >
                          <span className="inline-block rounded-full bg-white shadow-sm transition-transform duration-200"
                            style={{ width: 13, height: 13, margin: 2, transform: checked ? 'translateX(13px)' : 'translateX(0)' }} />
                        </button>
                      ) : (
                        <span className={`text-xs shrink-0 ${checked ? 'text-forest' : 'text-warm-300'}`}>
                          {checked ? 'auto' : '—'}
                        </span>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>

            {/* Productos críticos */}
            <div className="bg-white rounded-xl border border-warm-200 p-4">
              <div className="flex items-center justify-between mb-3">
                <p className="text-sm font-semibold text-warm-700 flex items-center gap-1.5">
                  <Package size={13} className="text-red-400" /> Stock crítico
                </p>
                <button onClick={() => navigate('/inventario')} className="text-xs text-forest hover:underline flex items-center gap-0.5">
                  Ver todo <ArrowRight size={10} />
                </button>
              </div>
              {active.productos_criticos_lista.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-6 text-center">
                  <Package size={22} className="text-warm-200 mb-2" />
                  <p className="text-xs text-warm-400">Sin productos críticos</p>
                </div>
              ) : (
                <div className="space-y-2">
                  {active.productos_criticos_lista.map((p, i) => (
                    <div key={i} className="flex items-center justify-between gap-2 text-xs">
                      <span className="text-warm-700 truncate flex-1">{p.nombre}</span>
                      <span className="font-mono text-red-600 font-semibold shrink-0">
                        {p.stock_actual}{p.unidad} / mín {p.stock_minimo}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Cuadres de llegada */}
          {entregas.length > 0 && (
            <div>
              <div className="flex items-center gap-2 mb-2">
                <UserCheck size={13} className="text-forest" />
                <p className="text-xs font-semibold text-warm-400 uppercase tracking-wide">Cuadres de llegada</p>
                <span className="text-xs bg-forest-50 text-forest px-1.5 py-0.5 rounded-full font-medium">{entregas.length}</span>
              </div>
              <div className="bg-white rounded-xl border border-warm-200 overflow-hidden">
                {entregas.map(e => (
                  <div key={e.id} className="px-4 py-3 flex items-center justify-between gap-3 border-b border-warm-50 last:border-0">
                    <div className="flex-1 min-w-0">
                      <p className="text-xs text-warm-400">
                        {new Date(e.fecha_hora).toLocaleString('es-CO', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })}
                      </p>
                      <p className="text-sm font-bold text-warm-700 font-mono">{fmt(e.efectivo_real)}</p>
                    </div>
                    <div className="flex flex-col items-end gap-1 shrink-0">
                      <DifferenceBadge diferencia={e.diferencia_efectivo} />
                      {e.diferencia_tarjeta !== 0 && (
                        <span className="text-xs text-red-600 font-semibold">Bold Δ{fmt(e.diferencia_tarjeta)}</span>
                      )}
                      {e.imagen_url && (
                        <a href={e.imagen_url} target="_blank" rel="noreferrer"
                          className="text-xs text-blue-500 flex items-center gap-0.5 hover:underline">
                          <ExternalLink size={10} /> foto
                        </a>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Accesos rápidos */}
          <div>
            <p className="text-xs font-semibold text-warm-400 uppercase tracking-wide mb-2">Accesos rápidos</p>
            <div className="grid grid-cols-3 gap-2">
              {[
                { label: 'Bandeja', icon: Inbox, to: '/bandeja', color: 'text-amber-600', bg: 'bg-amber-50', border: 'border-amber-100',
                  badge: active.solicitudes_pendientes > 0 ? active.solicitudes_pendientes : null },
                { label: 'Inventario', icon: Package, to: '/inventario', color: 'text-blue-500', bg: 'bg-blue-50', border: 'border-blue-100',
                  badge: active.productos_criticos > 0 ? active.productos_criticos : null },
                { label: 'Pastelería', icon: Cake, to: '/pasteleria', color: 'text-pink-500', bg: 'bg-pink-50', border: 'border-pink-100', badge: null },
                { label: 'Recetas', icon: ChefHat, to: '/recetas', color: 'text-forest', bg: 'bg-forest-50', border: 'border-forest-100', badge: null },
                { label: 'Informes', icon: TrendingUp, to: '/informes', color: 'text-purple-500', bg: 'bg-purple-50', border: 'border-purple-100', badge: null },
                { label: 'Consign.', icon: Banknote, to: '/consignaciones', color: 'text-teal-600', bg: 'bg-teal-50', border: 'border-teal-100',
                  badge: active.consignaciones_pendientes > 0 ? active.consignaciones_pendientes : null },
              ].map(({ label, icon: Icon, to, color, bg, border, badge }) => (
                <button key={to} onClick={() => navigate(to)}
                  className={`relative flex flex-col items-center gap-1.5 px-2 py-3 rounded-xl border ${bg} ${border} hover:brightness-95 transition-all`}>
                  {badge !== null && (
                    <span className="absolute -top-1 -right-1 text-xs font-bold bg-red-500 text-white w-4 h-4 rounded-full flex items-center justify-center">
                      {badge}
                    </span>
                  )}
                  <Icon size={16} className={color} />
                  <span className="text-xs font-medium text-warm-600">{label}</span>
                </button>
              ))}
            </div>
          </div>

          {/* Turno info */}
          <div className="flex items-center gap-2 py-1">
            <Clock size={11} className="text-warm-300" />
            <p className="text-xs text-warm-300">
              {active.estado_caja === 'sin_turno'
                ? 'Sin turno activo hoy'
                : active.estado_caja === 'diferencia'
                  ? `Turno activo — diferencia de ${fmt(active.diferencia_caja)}`
                  : 'Turno activo — caja cuadrada'}
            </p>
          </div>
        </>
      )}
    </div>
  )
}
