import { useEffect, useState, useCallback } from 'react'
import { useNavigate, NavLink, useLocation } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'
import {
  Coffee, LogOut, Bell, ChevronRight, ChevronUp, ChevronDown,
  AlertTriangle, Banknote, Package, TrendingUp, TrendingDown,
  BarChart2, ClipboardList, Inbox, Sparkles,
  ClipboardCheck, Zap, LayoutGrid, Check,
  Home, DollarSign, X as XIcon,
  Menu, Wallet, Receipt,
} from 'lucide-react'
import { NAV_ADMIN } from '../constants/nav'

// ─── Helpers ─────────────────────────────────────────────────────────────────
function parseUTC(s: string): Date {
  const t = s.replace(' ', 'T').replace(/(\.\d{3})\d+/, '$1').replace('+00:00', 'Z')
  return new Date(t.endsWith('Z') ? t : t + 'Z')
}
function hora() {
  return new Date().toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit' })
}
function fmtTime(d: Date) {
  return d.toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit' })
}
const fmt = (v: number) => `$${Math.round(v).toLocaleString('es-CO')}`

function today() {
  const d = new Date()
  return d.toISOString().slice(0, 10)
}
function daysAgo(n: number) {
  const d = new Date()
  d.setDate(d.getDate() - n)
  return d.toISOString().slice(0, 10)
}

// ─── Tools ───────────────────────────────────────────────────────────────────
const TOOLS_MAIN = [
  { id: 'inventario',  label: 'Inventario',  sublabel: 'Stock por producto',  icon: Package,        path: '/control-inventario', tint: '#5b8def' },
  { id: 'comunicados', label: 'Comunicados', sublabel: 'Mensajes a baristas', icon: Inbox,          path: '/comunicados',         tint: '#c08a3e' },
  { id: 'informes',    label: 'Informes',    sublabel: 'Reportes y métricas', icon: BarChart2,      path: '/informes',            tint: '#2d5a3f' },
  { id: 'pedidos',     label: 'Pedidos',     sublabel: 'Solicitudes activas', icon: ClipboardList,  path: '/pedidos-admin',       tint: '#d97757' },
  { id: 'ticket',      label: 'Ticket',      sublabel: 'Config. de impresión', icon: Receipt,       path: '/config-ticket',       tint: '#4a7abf' },
]
const TOOLS_MORE = [
  { id: 'cuadres',       label: 'Cuadres',        icon: Wallet,         path: '/cuadre-turnos',    tint: '#2a7d5e' },
  { id: 'bandeja',       label: 'Bandeja',        icon: Inbox,          path: '/bandeja',          tint: '#c08a3e' },
  { id: 'consig',        label: 'Consig.',        icon: Banknote,       path: '/consignaciones',   tint: '#2a8d8a' },
  { id: 'auditoria',     label: 'Auditoría',      icon: ClipboardCheck, path: '/auditorias',       tint: '#8a5dc7' },
  { id: 'limpieza',      label: 'Limpieza',       icon: Sparkles,       path: '/limpieza',         tint: '#d169a4' },
  { id: 'calibrar',      label: 'Calibrar',       icon: Zap,            path: '/control-inventario', tint: '#a14e9a' },
  { id: 'cumplimiento',  label: 'Cumplimiento',   icon: ClipboardCheck, path: '/cumplimiento',     tint: '#2a7d9a' },
]

// ─── Interfaces ───────────────────────────────────────────────────────────────
interface DashData {
  ventas_dia: number
  ventas_ayer: number
  estado_caja: string
  total_efectivo?: number
  total_tarjeta?: number
  productos_criticos: number
  consignaciones_pendientes: number
}

interface AlertaStock {
  producto_id: number; producto: string; unidad: string
  stock_actual: number; stock_minimo: number; stock_critico: number; stock_ideal: number
  nivel: 'agotado' | 'bajo'
  estado: 'agotado' | 'critico' | 'bajo'
}

interface PendienteConsig {
  turno_id: number; fecha_apertura: string; fecha_cierre: string
  esperado: number; consignado: number; pendiente: number
}

interface TurnoActivo {
  id: number
  fecha_apertura: string
  total_ventas: number
  total_efectivo: number
  total_tarjeta: number
  estado: string
}

interface Movimiento {
  id: number; tipo: string; concepto: string; valor: number
  fecha: string; imagen_url: string | null
}

interface TopProducto {
  nombre: string
  cantidad: number   // unidades vendidas
  total: number      // $ valor
}

// ─── AdminHub ─────────────────────────────────────────────────────────────────
export default function AdminHub() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  const [sedes, setSedes] = useState<{ id: number; nombre: string }[]>([])
  const [tiendaId, setTiendaId] = useState<number>(user?.tienda_id ?? 1)

  const [time, setTime] = useState(hora())
  const [dash, setDash] = useState<DashData | null>(null)
  const [turno, setTurno] = useState<TurnoActivo | null>(null)
  const [alertas, setAlertas] = useState<AlertaStock[]>([])
  const [consigPendiente, setConsigPendiente] = useState<{ items: PendienteConsig[]; total_pendiente: number } | null>(null)
  const [movimientos, setMovimientos] = useState<Movimiento[]>([])
  const [topProductos, setTopProductos] = useState<TopProducto[]>([])
  const [periodo, setPeriodo] = useState<'hoy' | 'semana' | 'mes'>('hoy')
  const [actividadOpen, setActividadOpen] = useState(false)
  const [showMas,  setShowMas]  = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)

  // Reloj
  useEffect(() => {
    const t = setInterval(() => setTime(hora()), 30000)
    return () => clearInterval(t)
  }, [])

  // Sedes (para el selector — el resumen es POR sede, no general)
  useEffect(() => {
    api.get('/auth/tiendas').then(r => {
      setSedes(r.data)
      if (r.data.length && !r.data.some((t: { id: number }) => t.id === tiendaId)) setTiendaId(r.data[0].id)
    }).catch(() => null)
  }, [])

  // Datos base
  useEffect(() => {
    api.get(`/dashboard/${tiendaId}`).then(r => setDash(r.data)).catch(() => null)
    api.get(`/inventario/alertas/${tiendaId}`).then(r => setAlertas(r.data)).catch(() => null)
    api.get(`/consignaciones/pendiente/${tiendaId}`).then(r => setConsigPendiente(r.data)).catch(() => null)
    api.get(`/caja/activo/${tiendaId}`).then(r => setTurno(r.data)).catch(() => null)
  }, [tiendaId])

  // Movimientos del turno activo
  useEffect(() => {
    if (turno?.id) {
      api.get(`/caja/${turno.id}/movimientos`).then(r => setMovimientos(r.data)).catch(() => null)
    }
  }, [turno?.id])

  // Top productos del POS — según período
  const fetchTopProductos = useCallback((p: 'hoy' | 'semana' | 'mes') => {
    const desde = p === 'hoy' ? today() : p === 'semana' ? daysAgo(7) : daysAgo(30)
    const hasta = today()
    api.get(`/pos/analytics/productos-top?fecha_desde=${desde}&fecha_hasta=${hasta}`)
      .then(r => setTopProductos((r.data ?? []).slice(0, 5).map((x: any) => ({
        nombre: x.nombre_producto, cantidad: x.unidades, total: x.total,
      }))))
      .catch(() => setTopProductos([]))
  }, [])

  useEffect(() => { fetchTopProductos(periodo) }, [periodo, fetchTopProductos])

  // ── Derived ──────────────────────────────────────────────────────────────────
  // Totales del día desde el dashboard (ventas del POS nativo)
  const ventasDia   = dash?.ventas_dia ?? 0
  const ventasAyer  = dash?.ventas_ayer ?? 0
  const efectivo    = (dash as any)?.efectivo_dia ?? 0
  const tarjeta     = (dash as any)?.tarjeta_dia  ?? 0
  const otros       = 0
  const delta       = ventasAyer > 0 ? ventasDia - ventasAyer : 0
  const deltaPct    = ventasAyer > 0 ? (delta / ventasAyer) * 100 : 0
  const positive    = delta >= 0

  const agotados    = alertas.filter(a => a.estado === 'agotado')
  const criticos    = alertas.filter(a => a.estado === 'critico')
  const bajos       = alertas.filter(a => a.estado === 'bajo')
  const totalAlerts = alertas.length

  const consigItems = consigPendiente?.items.filter(i => i.pendiente > 0) ?? []
  const hayConsig   = consigItems.length > 0
  const hayAlertas  = totalAlerts > 0 || hayConsig

  const maxUnidades = topProductos.length > 0 ? Math.max(...topProductos.map(p => p.cantidad)) : 1

  return (
    <div className="w-full" style={{ fontFamily: '"Plus Jakarta Sans", -apple-system, system-ui, sans-serif' }}>

      {/* Contenido del dashboard — el chrome (nav, header, sesión) lo provee Layout */}
      <div className="w-full" style={{ padding: '4px 0 16px' }}>

        {/* ── HERO: Resumen del día ──────────────────────────────────── */}
        <div style={{
          borderRadius: 26, overflow: 'hidden', marginBottom: 13, color: '#fff',
          background: 'linear-gradient(165deg, oklch(32% 0.045 155) 0%, oklch(26% 0.05 155) 60%, oklch(22% 0.04 155) 100%)',
          padding: '16px 18px 16px',
          boxShadow: '0 12px 32px -20px rgba(28,55,42,.6)',
          marginTop: 14,
        }}>
          {/* Label row */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
            <span style={{ fontSize: 9.5, fontWeight: 700, color: 'oklch(72% 0.05 155)', letterSpacing: '.1em', textTransform: 'uppercase' }}>
              Ventas del día
            </span>
            {sedes.length > 1 ? (
              <select value={tiendaId} onChange={e => setTiendaId(Number(e.target.value))}
                style={{ fontSize: 12, fontWeight: 600, color: '#fff', background: 'oklch(30% 0.04 155 / 0.7)', border: '1px solid oklch(52% 0.05 155 / 0.5)', borderRadius: 8, padding: '3px 8px', cursor: 'pointer' }}>
                {sedes.map(s => <option key={s.id} value={s.id} style={{ color: '#111' }}>{s.nombre}</option>)}
              </select>
            ) : sedes.length === 1 ? (
              <span style={{ fontSize: 11, fontWeight: 600, color: 'oklch(80% 0.05 155)' }}>{sedes[0].nombre}</span>
            ) : null}
          </div>

          {/* Big number */}
          <div style={{ marginBottom: 4 }}>
            <span className="tabular-nums" style={{ fontSize: 36, fontWeight: 700, color: '#fff', letterSpacing: '-0.025em', lineHeight: 1 }}>
              {fmt(ventasDia)}
            </span>
          </div>

          {/* Delta pill */}
          <div style={{
            display: 'inline-flex', alignItems: 'center', gap: 5,
            padding: '4px 10px 4px 8px', borderRadius: 999, marginBottom: 14,
            background: ventasAyer === 0 ? 'oklch(35% 0.04 155 / 0.6)' : positive ? 'oklch(35% 0.10 145 / 0.7)' : 'oklch(45% 0.14 30 / 0.5)',
            border: ventasAyer === 0 ? '1px solid oklch(50% 0.04 155 / 0.4)' : positive ? '1px solid oklch(50% 0.12 145 / 0.5)' : '1px solid oklch(60% 0.14 30 / 0.4)',
          }}>
            {ventasAyer > 0 ? (
              positive
                ? <TrendingUp size={11} style={{ color: 'oklch(85% 0.16 145)' }} />
                : <TrendingDown size={11} style={{ color: 'oklch(82% 0.14 30)' }} />
            ) : null}
            {ventasAyer > 0 ? (
              <>
                <span className="tabular-nums" style={{ fontSize: 11, fontWeight: 700, color: positive ? 'oklch(88% 0.14 145)' : 'oklch(85% 0.14 30)' }}>
                  {positive ? '+' : ''}{deltaPct.toFixed(1)}%
                </span>
                <span style={{ fontSize: 10.5, color: 'oklch(72% 0.05 155)', fontWeight: 500 }}>
                  vs. ayer · {fmt(ventasAyer)}
                </span>
              </>
            ) : (
              <span style={{ fontSize: 10.5, color: 'oklch(72% 0.05 155)', fontWeight: 500 }}>Sin datos de ayer</span>
            )}
          </div>

          {/* Breakdown: Efectivo / Tarjeta / Otros */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, padding: '10px 0 0', borderTop: '1px solid oklch(38% 0.05 155)', marginBottom: 12 }}>
            {[
              { label: 'Efectivo', v: efectivo, c: 'oklch(85% 0.13 145)' },
              { label: 'Tarjeta',  v: tarjeta,  c: 'oklch(82% 0.10 240)' },
              { label: 'Otros',    v: otros,     c: 'oklch(80% 0.10 30)'  },
            ].map(m => (
              <div key={m.label}>
                <p style={{ margin: 0, fontSize: 9, fontWeight: 700, color: 'oklch(72% 0.05 155)', letterSpacing: '.08em', textTransform: 'uppercase' }}>{m.label}</p>
                <p className="tabular-nums" style={{ margin: '2px 0 0', fontSize: 13, fontWeight: 700, color: m.c }}>{fmt(m.v)}</p>
              </div>
            ))}
          </div>

          {/* Turno status row */}
          <button
            onClick={() => turno && navigate('/dashboard')}
            style={{
              width: '100%', display: 'flex', alignItems: 'center', gap: 8,
              padding: '9px 12px', borderRadius: 12,
              background: 'oklch(28% 0.04 155)', border: '1px solid oklch(38% 0.05 155)',
              cursor: 'pointer', fontFamily: 'inherit', textAlign: 'left',
            }}
          >
            <span style={{
              width: 7, height: 7, borderRadius: 999, flexShrink: 0,
              background: turno ? 'oklch(78% 0.18 145)' : 'oklch(75% 0.008 60)',
              boxShadow: turno ? '0 0 0 3px oklch(50% 0.12 145 / 0.4)' : 'none',
            }} />
            <span style={{ fontSize: 11.5, fontWeight: 600, color: 'oklch(88% 0.04 75)', flex: 1 }}>
              {turno
                ? <>Turno activo desde <strong style={{ fontWeight: 700, color: '#fff' }}>{fmtTime(parseUTC(turno.fecha_apertura))}</strong></>
                : <>Sin turno abierto</>
              }
            </span>
            <ChevronRight size={13} style={{ color: 'oklch(70% 0.04 155)', flexShrink: 0 }} />
          </button>
        </div>

        {/* ── Alertas ──────────────────────────────────────────────────── */}
        {hayAlertas ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 13 }}>

            {/* Consignaciones pendientes */}
            {hayConsig && (
              <button
                onClick={() => navigate('/consignaciones')}
                className="w-full text-left bg-white border border-gold-200 cursor-pointer"
                style={{
                  display: 'flex', alignItems: 'center', gap: 12,
                  padding: '11px 14px', borderRadius: 16, fontFamily: 'inherit',
                }}
              >
                <div className="bg-gold-100 flex items-center justify-center flex-shrink-0"
                  style={{ width: 32, height: 32, borderRadius: 11 }}>
                  <Banknote size={15} className="text-gold-500" />
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <p className="text-gold-600" style={{ margin: 0, fontSize: 10, fontWeight: 700, letterSpacing: '.07em', textTransform: 'uppercase' }}>
                    Consignaciones pendientes
                  </p>
                  <p className="text-bark-700" style={{ margin: '1px 0 0', fontSize: 13, fontWeight: 600 }}>
                    {consigItems.length} turno{consigItems.length > 1 ? 's' : ''} · <span className="tabular-nums" style={{ fontWeight: 700 }}>{fmt(consigPendiente?.total_pendiente ?? 0)}</span>
                  </p>
                </div>
                <ChevronRight size={14} className="text-warm-400 flex-shrink-0" />
              </button>
            )}

            {/* Stock crítico */}
            {totalAlerts > 0 && (
              <div className="bg-white border border-danger-100 overflow-hidden" style={{ borderRadius: 18 }}>
                <div className="flex items-center gap-[10px] border-b border-danger-100"
                  style={{ padding: '11px 14px 10px', background: 'linear-gradient(180deg, oklch(98% 0.02 30), oklch(96% 0.03 30))', borderBottom: '1px solid oklch(94% 0.04 30)' }}>
                  <div className="bg-danger-50 flex items-center justify-center flex-shrink-0"
                    style={{ width: 28, height: 28, borderRadius: 10 }}>
                    <AlertTriangle size={14} className="text-danger-500" />
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <p className="text-danger-700" style={{ margin: 0, fontSize: 12.5, fontWeight: 700, letterSpacing: '-0.005em' }}>Stock crítico</p>
                    <p style={{ margin: 0, fontSize: 10, fontWeight: 600, letterSpacing: '.04em', textTransform: 'uppercase', color: '#a8493a' }}>
                      {agotados.length} agotados · {criticos.length} críticos · {bajos.length} bajos
                    </p>
                  </div>
                  <button
                    onClick={() => navigate('/pedidos-admin')}
                    className="bg-danger-500 text-white flex items-center gap-[3px] flex-shrink-0"
                    style={{ padding: '5px 10px', borderRadius: 10, border: 'none', fontFamily: 'inherit', fontSize: 11, fontWeight: 700, cursor: 'pointer' }}
                  >
                    Pedir <ChevronRight size={11} />
                  </button>
                </div>
                {agotados.length > 0 && (
                  <div className="bg-danger-50" style={{ padding: '8px 14px 9px' }}>
                    <p className="text-danger-500" style={{ margin: '0 0 4px', fontSize: 9, fontWeight: 700, letterSpacing: '.1em', textTransform: 'uppercase' }}>Agotados</p>
                    {agotados.map(a => (
                      <div key={a.producto_id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '4px 0' }}>
                        <span style={{ fontSize: 12.5, fontWeight: 600, color: '#7a2a20' }}>{a.producto}</span>
                        <span className="tabular-nums text-white bg-danger-500" style={{ fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 999 }}>
                          0 {a.unidad}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
                {criticos.length > 0 && (
                  <div style={{ padding: '8px 14px 10px', borderTop: agotados.length > 0 ? '1px solid oklch(96% 0.018 30)' : 'none', background: 'oklch(98% 0.025 55)' }}>
                    <p style={{ margin: '0 0 4px', fontSize: 9, fontWeight: 700, color: 'oklch(42% 0.15 55)', letterSpacing: '.1em', textTransform: 'uppercase' }}>Críticos</p>
                    {criticos.map(a => (
                      <div key={a.producto_id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '4px 0' }}>
                        <span style={{ fontSize: 12.5, fontWeight: 600, color: 'oklch(35% 0.15 55)' }}>{a.producto}</span>
                        <span className="tabular-nums" style={{ fontSize: 10, fontWeight: 700, color: 'white', background: 'oklch(55% 0.18 55)', padding: '2px 8px', borderRadius: 999 }}>
                          {Math.round(a.stock_actual)}/{Math.round(a.stock_critico)} {a.unidad}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
                {bajos.length > 0 && (
                  <div style={{ padding: '8px 14px 10px', borderTop: (agotados.length > 0 || criticos.length > 0) ? '1px solid oklch(96% 0.018 30)' : 'none' }}>
                    <p style={{ margin: '0 0 4px', fontSize: 9, fontWeight: 700, color: 'oklch(50% 0.14 75)', letterSpacing: '.1em', textTransform: 'uppercase' }}>Por agotarse</p>
                    {bajos.map(a => (
                      <div key={a.producto_id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '4px 0' }}>
                        <span className="text-warm-600" style={{ fontSize: 12.5, fontWeight: 500 }}>{a.producto}</span>
                        <span className="tabular-nums" style={{ fontSize: 10, fontWeight: 600, color: 'oklch(38% 0.12 75)', background: 'oklch(97% 0.04 75)', border: '1px solid oklch(90% 0.07 75)', padding: '2px 8px', borderRadius: 999 }}>
                          {Math.round(a.stock_actual)}/{Math.round(a.stock_minimo)} {a.unidad}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        ) : (
          /* All-clear chip */
          <div className="bg-success-50 border border-success-200 flex items-center gap-[9px]"
            style={{ padding: '10px 14px', marginBottom: 13, borderRadius: 14 }}>
            <span className="bg-success-200 flex items-center justify-center flex-shrink-0"
              style={{ width: 22, height: 22, borderRadius: 8 }}>
              <Check size={11} className="text-success-700" />
            </span>
            <span className="text-success-700" style={{ flex: 1, fontSize: 12.5, fontWeight: 600 }}>
              Todo en orden — sin alertas activas
            </span>
          </div>
        )}

        {/* ── Top productos ────────────────────────────────────────────── */}
        <div style={{ marginBottom: 13 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', margin: '0 4px 10px' }}>
            <span className="text-warm-500" style={{ fontSize: 10, fontWeight: 700, letterSpacing: '.1em', textTransform: 'uppercase' }}>
              Top productos
            </span>
            {/* Period selector */}
            <div className="bg-warm-200" style={{ display: 'flex', padding: 2, borderRadius: 999, gap: 1 }}>
              {(['hoy', 'semana', 'mes'] as const).map(p => (
                <button
                  key={p}
                  onClick={() => setPeriodo(p)}
                  style={{
                    padding: '4px 11px', borderRadius: 999, cursor: 'pointer',
                    fontSize: 10.5, fontWeight: 700, border: 'none', fontFamily: 'inherit',
                    background: periodo === p ? '#fff' : 'transparent',
                    color: periodo === p ? 'oklch(30% 0.05 155)' : 'oklch(58% 0.01 60)',
                    boxShadow: periodo === p ? '0 1px 2px rgba(0,0,0,.08)' : 'none',
                  }}
                >
                  {p === 'hoy' ? 'Hoy' : p === 'semana' ? 'Semana' : 'Mes'}
                </button>
              ))}
            </div>
          </div>

          <div className="bg-white border border-warm-200" style={{ borderRadius: 18, padding: '6px 14px 8px' }}>
            {topProductos.length === 0 ? (
              <p className="text-warm-500" style={{ margin: '12px 0', textAlign: 'center', fontSize: 12 }}>
                Sin ventas en este período
              </p>
            ) : topProductos.map((p, i) => {
              const barW = (p.cantidad / maxUnidades) * 100
              return (
                <div key={i} style={{
                  display: 'grid', gridTemplateColumns: '20px 1fr auto', alignItems: 'center', gap: 10,
                  padding: '9px 0',
                  borderBottom: i < topProductos.length - 1 ? '1px solid oklch(96% 0.008 75)' : 'none',
                }}>
                  <span className="tabular-nums" style={{ fontSize: 11, fontWeight: 700, color: i === 0 ? 'oklch(35% 0.14 65)' : 'oklch(72% 0.008 60)', letterSpacing: '.02em' }}>
                    #{i + 1}
                  </span>
                  <div style={{ minWidth: 0 }}>
                    <p className="text-bark-700" style={{ margin: 0, fontSize: 12.5, fontWeight: 600, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {p.nombre}
                    </p>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 3 }}>
                      <div className="bg-warm-100" style={{ flex: 1, height: 4, borderRadius: 999, overflow: 'hidden', maxWidth: 100 }}>
                        <div style={{
                          width: `${barW}%`, height: '100%', borderRadius: 999,
                          background: i === 0
                            ? 'linear-gradient(90deg, oklch(55% 0.16 65), oklch(60% 0.14 50))'
                            : 'oklch(78% 0.06 145)',
                        }} />
                      </div>
                      <span className="tabular-nums text-warm-500" style={{ fontSize: 10.5, fontWeight: 600 }}>
                        {Math.round(p.cantidad)} u
                      </span>
                    </div>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <p className="tabular-nums text-forest-700" style={{ margin: 0, fontSize: 11.5, fontWeight: 700 }}>
                      {fmt(p.total)}
                    </p>
                  </div>
                </div>
              )
            })}
          </div>
        </div>

        {/* ── Herramientas ─────────────────────────────────────────────── */}
        <div style={{ marginBottom: 13 }}>
          <p className="text-warm-500" style={{ margin: '0 4px 8px', fontSize: 10, fontWeight: 700, letterSpacing: '.1em', textTransform: 'uppercase' }}>
            Herramientas
          </p>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            {TOOLS_MAIN.map(({ label, sublabel, icon: Icon, path, tint }) => (
              <button
                key={path}
                onClick={() => navigate(path)}
                className="bg-white border border-warm-200 text-left"
                style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '12px 12px', borderRadius: 16, cursor: 'pointer', fontFamily: 'inherit' }}
              >
                <div style={{
                  width: 36, height: 36, borderRadius: 12, flexShrink: 0,
                  background: `linear-gradient(135deg, color-mix(in oklch, ${tint} 18%, #fff), color-mix(in oklch, ${tint} 8%, #fff))`,
                  border: `1px solid color-mix(in oklch, ${tint} 25%, #fff)`,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                }}>
                  <Icon size={17} style={{ color: tint }} />
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <p className="text-bark-700" style={{ margin: 0, fontSize: 13, fontWeight: 700, letterSpacing: '-0.005em' }}>{label}</p>
                  <p className="text-warm-500" style={{ margin: '1px 0 0', fontSize: 10, fontWeight: 500 }}>{sublabel}</p>
                </div>
              </button>
            ))}
          </div>
          {/* Dashed "más" button with color dots */}
          <button
            onClick={() => setShowMas(true)}
            className="bg-warm-50 border border-dashed border-warm-300"
            style={{ marginTop: 8, width: '100%', display: 'flex', alignItems: 'center', gap: 10, padding: '11px 14px', borderRadius: 14, cursor: 'pointer', fontFamily: 'inherit' }}
          >
            <LayoutGrid size={14} className="text-warm-500" />
            <span className="text-warm-600" style={{ flex: 1, textAlign: 'left', fontSize: 12, fontWeight: 700 }}>
              {TOOLS_MORE.length} herramientas más
            </span>
            <span style={{ display: 'flex', gap: 3, marginRight: 6 }}>
              {TOOLS_MORE.slice(0, 5).map(t => (
                <span key={t.id} style={{ width: 6, height: 6, borderRadius: 999, background: `color-mix(in oklch, ${t.tint} 70%, oklch(85% 0.008 75))` }} />
              ))}
            </span>
            <ChevronRight size={14} className="text-warm-500" />
          </button>
        </div>

        {/* ── Actividad reciente ───────────────────────────────────────── */}
        <div className="bg-white border border-warm-200 overflow-hidden" style={{ borderRadius: 16 }}>
          <button
            onClick={() => setActividadOpen(v => !v)}
            style={{ width: '100%', display: 'flex', alignItems: 'center', gap: 10, padding: '11px 14px', background: 'transparent', border: 'none', cursor: 'pointer', fontFamily: 'inherit', textAlign: 'left' }}
          >
            <div className="bg-warm-100 flex items-center justify-center flex-shrink-0"
              style={{ width: 28, height: 28, borderRadius: 9 }}>
              <TrendingUp size={13} className="text-forest-500" />
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <p className="text-bark-700" style={{ margin: 0, fontSize: 12.5, fontWeight: 700 }}>Actividad reciente</p>
              <p className="text-warm-500" style={{ margin: '1px 0 0', fontSize: 10.5, fontWeight: 500 }}>
                {movimientos.length > 0
                  ? `${movimientos.filter(m => m.tipo === 'ingreso').length} ingreso${movimientos.filter(m => m.tipo === 'ingreso').length !== 1 ? 's' : ''} · ${movimientos.filter(m => m.tipo === 'egreso').length} egreso${movimientos.filter(m => m.tipo === 'egreso').length !== 1 ? 's' : ''} · turno en curso`
                  : turno ? 'Sin movimientos este turno' : 'Sin turno activo'
                }
              </p>
            </div>
            {actividadOpen
              ? <ChevronUp size={14} className="text-warm-500" />
              : <ChevronDown size={14} className="text-warm-500" />}
          </button>
          {actividadOpen && movimientos.length > 0 && (
            <div className="border-t border-warm-100">
              {movimientos.slice(0, 8).map((m, i) => (
                <div key={m.id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 14px', borderBottom: i < Math.min(movimientos.length, 8) - 1 ? '1px solid oklch(97% 0.008 75)' : 'none' }}>
                  <span className="flex items-center justify-center flex-shrink-0"
                    style={{ width: 24, height: 24, borderRadius: 8, background: m.tipo === 'ingreso' ? 'oklch(94% 0.04 145)' : 'oklch(96% 0.03 30)' }}>
                    {m.tipo === 'ingreso'
                      ? <TrendingUp size={11} style={{ color: '#2d8a5f' }} />
                      : <TrendingDown size={11} className="text-danger-500" />}
                  </span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <p className="text-bark-700" style={{ margin: 0, fontSize: 12.5, fontWeight: 600 }}>{m.concepto}</p>
                    <p className="text-warm-500 tabular-nums" style={{ margin: 0, fontSize: 10 }}>
                      {parseUTC(m.fecha).toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit' })}
                    </p>
                  </div>
                  <span className="tabular-nums" style={{ fontSize: 12.5, fontWeight: 700, color: m.tipo === 'ingreso' ? '#2d8a5f' : '#c64a3a' }}>
                    {m.tipo === 'ingreso' ? '+' : '−'}{fmt(m.valor)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

      </div>{/* /scroll */}

      {/* ── "Más herramientas" overlay ────────────────────────────────── */}
      {showMas && (
        <div
          style={{ position: 'fixed', inset: 0, zIndex: 50, display: 'flex', alignItems: 'flex-end', justifyContent: 'center', background: 'rgba(0,0,0,.5)' }}
          onClick={() => setShowMas(false)}
        >
          <div
            className="bg-warm-50 w-full"
            style={{ maxWidth: 448, borderRadius: '24px 24px 0 0', padding: '20px 16px 32px', boxShadow: '0 -8px 40px rgba(0,0,0,.2)' }}
            onClick={e => e.stopPropagation()}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
              <p className="text-warm-700" style={{ margin: 0, fontSize: 13, fontWeight: 700 }}>Más herramientas</p>
              <button onClick={() => setShowMas(false)} className="text-warm-500" style={{ padding: 6, background: 'transparent', border: 'none', cursor: 'pointer' }}>
                <XIcon size={18} />
              </button>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
              {TOOLS_MORE.map(({ label, icon: Icon, path, tint }) => (
                <button
                  key={path}
                  onClick={() => { setShowMas(false); navigate(path) }}
                  className="bg-white border border-warm-200 flex flex-col items-center gap-[6px]"
                  style={{ padding: '12px 8px', borderRadius: 16, cursor: 'pointer', fontFamily: 'inherit' }}
                >
                  <div style={{ width: 32, height: 32, borderRadius: 10, background: `linear-gradient(135deg, color-mix(in oklch, ${tint} 18%, #fff), color-mix(in oklch, ${tint} 8%, #fff))`, border: `1px solid color-mix(in oklch, ${tint} 25%, #fff)`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                    <Icon size={15} style={{ color: tint }} />
                  </div>
                  <span className="text-warm-600" style={{ fontSize: 11, fontWeight: 600, textAlign: 'center', lineHeight: 1.2 }}>{label}</span>
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

    </div>
  )
}
