import { useEffect, useState, useCallback } from 'react'
import { useNavigate, NavLink, useLocation } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'
import {
  Coffee, LogOut, Bell, ChevronRight, ChevronUp, ChevronDown,
  AlertTriangle, Banknote, Package, TrendingUp, TrendingDown,
  BarChart2, ClipboardList, Inbox, Sparkles, ShoppingCart,
  ClipboardCheck, FileText, Zap, LayoutGrid, Check,
  Home, DollarSign, X as XIcon,
  Menu, LayoutDashboard, Layers, Wrench, Activity, Users, Link2,
} from 'lucide-react'

// ─── Navegación admin completa (mirror de Layout) ────────────────────────────
const NAV_ADMIN = [
  { to: '/dashboard',          label: 'Dashboard',      icon: LayoutDashboard },
  { to: '/control-inventario', label: 'Inventario',     icon: Layers          },
  { to: '/pedidos-admin',      label: 'Pedidos',        icon: ClipboardList   },
  { to: '/compras',            label: 'Compras',        icon: ShoppingCart    },
  { to: '/consignaciones',     label: 'Consignaciones', icon: Banknote        },
  { to: '/mantenimientos',     label: 'Mantenimientos', icon: Wrench          },
  { to: '/auditorias',         label: 'Auditorías',     icon: ClipboardCheck  },
  { to: '/audit-log',          label: 'Historial',      icon: Activity        },
  { to: '/comunicados',        label: 'Comunicados',    icon: Bell            },
  { to: '/bandeja',            label: 'Bandeja',        icon: Inbox           },
  { to: '/informes',           label: 'Informes',       icon: BarChart2       },
  { to: '/usuarios',           label: 'Usuarios',       icon: Users           },
  { to: '/siigo-mapeo',        label: 'Mapeo Siigo',    icon: Link2           },
]

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
]
const TOOLS_MORE = [
  { id: 'bandeja',    label: 'Bandeja',    icon: Inbox,          path: '/bandeja',          tint: '#c08a3e' },
  { id: 'consig',     label: 'Consig.',    icon: Banknote,       path: '/consignaciones',   tint: '#2a8d8a' },
  { id: 'auditoria',  label: 'Auditoría',  icon: ClipboardCheck, path: '/auditorias',       tint: '#8a5dc7' },
  { id: 'limpieza',   label: 'Limpieza',   icon: Sparkles,       path: '/limpieza',         tint: '#d169a4' },
  { id: 'compras',    label: 'Compras',    icon: ShoppingCart,   path: '/compras',          tint: '#7a6a55' },
  { id: 'calibrar',   label: 'Calibrar',   icon: Zap,            path: '/control-inventario', tint: '#a14e9a' },
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
  stock_actual: number; stock_minimo: number
  nivel: 'agotado' | 'bajo'
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
  cantidad: number   // unidades Siigo
  total: number      // $ valor
}

// ─── AdminHub ─────────────────────────────────────────────────────────────────
export default function AdminHub() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  const tiendaId = user?.tienda_id ?? 1

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
  const [siigoTotales, setSiigoTotales] = useState<{ total: number; efectivo: number; tarjeta: number; otros: number; facturas_count: number } | null>(null)

  // Reloj
  useEffect(() => {
    const t = setInterval(() => setTime(hora()), 30000)
    return () => clearInterval(t)
  }, [])

  // Datos base
  useEffect(() => {
    api.get(`/dashboard/${tiendaId}`).then(r => setDash(r.data)).catch(() => null)
    api.get(`/inventario/alertas/${tiendaId}`).then(r => setAlertas(r.data)).catch(() => null)
    api.get(`/consignaciones/pendiente/${tiendaId}`).then(r => setConsigPendiente(r.data)).catch(() => null)
    api.get(`/caja/activo/${tiendaId}`).then(r => setTurno(r.data)).catch(() => null)
  }, [tiendaId])

  // Ventas Siigo — carga al iniciar y refresca cada 5 min
  const fetchSiigoTotales = useCallback(() => {
    const hoy = today()
    api.get(`/siigo/totales?fecha_desde=${hoy}&fecha_hasta=${hoy}`)
      .then(r => setSiigoTotales(r.data))
      .catch(() => null)
  }, [])

  useEffect(() => {
    fetchSiigoTotales()
    const t = setInterval(fetchSiigoTotales, 5 * 60 * 1000)
    return () => clearInterval(t)
  }, [fetchSiigoTotales])

  // Movimientos del turno activo
  useEffect(() => {
    if (turno?.id) {
      api.get(`/caja/${turno.id}/movimientos`).then(r => setMovimientos(r.data)).catch(() => null)
    }
  }, [turno?.id])

  // Top productos Siigo — según período
  const fetchTopProductos = useCallback((p: 'hoy' | 'semana' | 'mes') => {
    const desde = p === 'hoy' ? today() : p === 'semana' ? daysAgo(7) : daysAgo(30)
    const hasta = today()
    api.get(`/siigo/ventas-por-producto?fecha_desde=${desde}&fecha_hasta=${hasta}`)
      .then(r => setTopProductos((r.data.productos ?? []).slice(0, 5)))
      .catch(() => setTopProductos([]))
  }, [])

  useEffect(() => { fetchTopProductos(periodo) }, [periodo, fetchTopProductos])

  // ── Derived ──────────────────────────────────────────────────────────────────
  // siigoTotales: live refresh every 5 min; dash: immediate fallback from local DB
  const ventasDia   = siigoTotales?.total    ?? dash?.ventas_dia    ?? 0
  const ventasAyer  = dash?.ventas_ayer ?? 0
  const efectivo    = siigoTotales?.efectivo ?? (dash as any)?.efectivo_dia ?? 0
  const tarjeta     = siigoTotales?.tarjeta  ?? (dash as any)?.tarjeta_dia  ?? 0
  const otros       = siigoTotales?.otros ?? 0
  const delta       = ventasAyer > 0 ? ventasDia - ventasAyer : 0
  const deltaPct    = ventasAyer > 0 ? (delta / ventasAyer) * 100 : 0
  const positive    = delta >= 0

  const agotados    = alertas.filter(a => a.nivel === 'agotado')
  const bajos       = alertas.filter(a => a.nivel === 'bajo')
  const totalAlerts = alertas.length

  const consigItems = consigPendiente?.items.filter(i => i.pendiente > 0) ?? []
  const hayConsig   = consigItems.length > 0
  const hayAlertas  = totalAlerts > 0 || hayConsig

  const maxUnidades = topProductos.length > 0 ? Math.max(...topProductos.map(p => p.cantidad)) : 1

  return (
    <div className="min-h-screen flex flex-col"
      style={{ background: 'oklch(97% 0.012 75)', fontFamily: '"Plus Jakarta Sans", -apple-system, system-ui, sans-serif', color: 'oklch(22% 0.01 60)' }}>

      {/* ── Header ─────────────────────────────────────────────────────── */}
      <header className="sticky top-0 z-10 flex items-center justify-between header-safe px-4 pb-3"
        style={{ background: 'rgba(255,255,255,0.95)', backdropFilter: 'blur(12px)', borderBottom: '1px solid oklch(94% 0.008 75)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
          <button
            className="md:hidden"
            onClick={() => setMenuOpen(true)}
            style={{ padding: '4px 2px', background: 'transparent', border: 'none', cursor: 'pointer', color: 'oklch(45% 0.01 60)', display: 'flex', alignItems: 'center' }}
            aria-label="Abrir menú"
          >
            <Menu size={20} />
          </button>
          <div style={{ width: 28, height: 28, borderRadius: 9, background: 'oklch(95% 0.015 155)', border: '1px solid oklch(90% 0.025 155)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Coffee size={14} style={{ color: 'oklch(35% 0.05 155)' }} />
          </div>
          <div>
            <p style={{ margin: 0, fontSize: 13, fontWeight: 700, color: 'oklch(22% 0.01 60)', letterSpacing: '-0.005em' }}>
              Admin · {user?.nombre?.split(' ')[0]}
            </p>
            <p style={{ margin: 0, fontSize: 10, color: 'oklch(58% 0.01 60)', fontWeight: 500, fontVariantNumeric: 'tabular-nums' }}>
              {new Date().toLocaleDateString('es-CO', { weekday: 'short', day: 'numeric', month: 'short' })} · {time}
            </p>
          </div>
          {/* Desktop nav — hidden on mobile */}
          <nav className="hidden md:flex items-center gap-1 ml-6">
            {[
              { label: 'Inicio',         path: '/dashboard' },
              { label: 'Inventario',     path: '/inventario' },
              { label: 'Informes',       path: '/informes' },
              { label: 'Consignaciones', path: '/consignaciones' },
              { label: 'Comunicados',    path: '/comunicados' },
              { label: 'Pedidos',        path: '/pedidos-admin' },
              { label: 'Compras',        path: '/compras' },
              { label: 'Bandeja',        path: '/bandeja' },
            ].map(item => (
              <button
                key={item.path}
                onClick={() => navigate(item.path)}
                style={{
                  padding: '5px 10px',
                  borderRadius: 7,
                  border: 'none',
                  background: location.pathname === item.path ? 'oklch(93% 0.025 155)' : 'transparent',
                  color: location.pathname === item.path ? 'oklch(30% 0.06 155)' : 'oklch(50% 0.01 60)',
                  fontSize: 13,
                  fontWeight: 600,
                  cursor: 'pointer',
                  fontFamily: 'inherit',
                  whiteSpace: 'nowrap',
                }}
              >
                {item.label}
              </button>
            ))}
          </nav>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{ position: 'relative' }}>
            <Bell size={16} style={{ color: 'oklch(58% 0.01 60)' }} />
            {hayAlertas && (
              <span style={{ position: 'absolute', top: -4, right: -4, background: '#d97757', color: '#fff', fontSize: 8, fontWeight: 700, minWidth: 13, height: 13, padding: '0 3px', borderRadius: 999, display: 'flex', alignItems: 'center', justifyContent: 'center', border: '1.5px solid oklch(97% 0.012 75)' }}>
                {totalAlerts + (hayConsig ? 1 : 0)}
              </span>
            )}
          </div>
          <button
            onClick={() => { if (window.confirm('¿Cerrar sesión?')) { logout(); navigate('/login') } }}
            style={{ padding: 6, background: 'transparent', border: 'none', cursor: 'pointer', color: 'oklch(72% 0.008 60)' }}
          >
            <LogOut size={14} />
          </button>
        </div>
      </header>

      {/* ── Scroll body ────────────────────────────────────────────────── */}
      <div className="flex-1 pb-nav max-w-5xl mx-auto w-full" style={{ padding: '0 16px 16px' }}>

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
            {dash && (
              <span style={{ fontSize: 10, fontWeight: 600, color: 'oklch(72% 0.05 155)', fontVariantNumeric: 'tabular-nums' }}>
                {/* transacciones not available yet */}
              </span>
            )}
          </div>

          {/* Big number */}
          <div style={{ marginBottom: 4 }}>
            <span style={{ fontSize: 36, fontWeight: 700, color: '#fff', letterSpacing: '-0.025em', fontVariantNumeric: 'tabular-nums', lineHeight: 1 }}>
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
                <span style={{ fontSize: 11, fontWeight: 700, color: positive ? 'oklch(88% 0.14 145)' : 'oklch(85% 0.14 30)', fontVariantNumeric: 'tabular-nums' }}>
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
                <p style={{ margin: '2px 0 0', fontSize: 13, fontWeight: 700, color: m.c, fontVariantNumeric: 'tabular-nums' }}>{fmt(m.v)}</p>
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
                style={{
                  width: '100%', display: 'flex', alignItems: 'center', gap: 12,
                  padding: '11px 14px', borderRadius: 16, cursor: 'pointer', fontFamily: 'inherit', textAlign: 'left',
                  background: '#fff', border: '1px solid oklch(88% 0.10 65)',
                }}
              >
                <div style={{ width: 32, height: 32, borderRadius: 11, background: 'oklch(94% 0.08 65)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                  <Banknote size={15} style={{ color: 'oklch(48% 0.16 65)' }} />
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <p style={{ margin: 0, fontSize: 10, fontWeight: 700, color: 'oklch(42% 0.16 65)', letterSpacing: '.07em', textTransform: 'uppercase' }}>
                    Consignaciones pendientes
                  </p>
                  <p style={{ margin: '1px 0 0', fontSize: 13, fontWeight: 600, color: 'oklch(28% 0.01 60)' }}>
                    {consigItems.length} turno{consigItems.length > 1 ? 's' : ''} · <span style={{ fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}>{fmt(consigPendiente?.total_pendiente ?? 0)}</span>
                  </p>
                </div>
                <ChevronRight size={14} style={{ color: 'oklch(72% 0.008 60)', flexShrink: 0 }} />
              </button>
            )}

            {/* Stock crítico */}
            {totalAlerts > 0 && (
              <div style={{ background: '#fff', border: '1px solid oklch(90% 0.05 30)', borderRadius: 18, overflow: 'hidden' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '11px 14px 10px', background: 'linear-gradient(180deg, oklch(98% 0.02 30), oklch(96% 0.03 30))', borderBottom: '1px solid oklch(94% 0.04 30)' }}>
                  <div style={{ width: 28, height: 28, borderRadius: 10, background: 'oklch(94% 0.05 30)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                    <AlertTriangle size={14} style={{ color: '#c64a3a' }} />
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <p style={{ margin: 0, fontSize: 12.5, fontWeight: 700, color: '#8a3325', letterSpacing: '-0.005em' }}>Stock crítico</p>
                    <p style={{ margin: 0, fontSize: 10, fontWeight: 600, letterSpacing: '.04em', textTransform: 'uppercase', color: '#a8493a' }}>
                      {agotados.length} agotados · {bajos.length} bajos
                    </p>
                  </div>
                  <button
                    onClick={() => navigate('/pedidos-admin')}
                    style={{ display: 'flex', alignItems: 'center', gap: 3, padding: '5px 10px', borderRadius: 10, background: '#c64a3a', color: '#fff', border: 'none', fontFamily: 'inherit', fontSize: 11, fontWeight: 700, cursor: 'pointer', flexShrink: 0 }}
                  >
                    Pedir <ChevronRight size={11} />
                  </button>
                </div>
                {agotados.length > 0 && (
                  <div style={{ background: 'oklch(98% 0.018 30)', padding: '8px 14px 9px' }}>
                    <p style={{ margin: '0 0 4px', fontSize: 9, fontWeight: 700, color: '#c64a3a', letterSpacing: '.1em', textTransform: 'uppercase' }}>Agotados</p>
                    {agotados.map(a => (
                      <div key={a.producto_id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '4px 0' }}>
                        <span style={{ fontSize: 12.5, fontWeight: 600, color: '#7a2a20' }}>{a.producto}</span>
                        <span style={{ fontSize: 10, fontWeight: 700, color: '#fff', background: '#c64a3a', padding: '2px 8px', borderRadius: 999, fontVariantNumeric: 'tabular-nums' }}>
                          0 {a.unidad}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
                {bajos.length > 0 && (
                  <div style={{ padding: '8px 14px 10px', borderTop: agotados.length > 0 ? '1px solid oklch(96% 0.018 30)' : 'none' }}>
                    <p style={{ margin: '0 0 4px', fontSize: 9, fontWeight: 700, color: 'oklch(50% 0.14 75)', letterSpacing: '.1em', textTransform: 'uppercase' }}>Por agotarse</p>
                    {bajos.map(a => (
                      <div key={a.producto_id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '4px 0' }}>
                        <span style={{ fontSize: 12.5, fontWeight: 500, color: 'oklch(35% 0.01 60)' }}>{a.producto}</span>
                        <span style={{ fontSize: 10, fontWeight: 600, fontVariantNumeric: 'tabular-nums', color: 'oklch(38% 0.12 75)', background: 'oklch(97% 0.04 75)', border: '1px solid oklch(90% 0.07 75)', padding: '2px 8px', borderRadius: 999 }}>
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
          <div style={{ display: 'flex', alignItems: 'center', gap: 9, padding: '10px 14px', marginBottom: 13, background: 'oklch(96% 0.018 145)', border: '1px solid oklch(88% 0.06 145)', borderRadius: 14 }}>
            <span style={{ width: 22, height: 22, borderRadius: 8, background: 'oklch(88% 0.10 145)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
              <Check size={11} style={{ color: 'oklch(32% 0.10 145)' }} />
            </span>
            <span style={{ flex: 1, fontSize: 12.5, fontWeight: 600, color: 'oklch(32% 0.08 145)' }}>
              Todo en orden — sin alertas activas
            </span>
          </div>
        )}

        {/* ── Top productos ────────────────────────────────────────────── */}
        <div style={{ marginBottom: 13 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', margin: '0 4px 10px' }}>
            <span style={{ fontSize: 10, fontWeight: 700, color: 'oklch(58% 0.01 60)', letterSpacing: '.1em', textTransform: 'uppercase' }}>
              Top productos
            </span>
            {/* Period selector */}
            <div style={{ display: 'flex', padding: 2, background: 'oklch(94% 0.008 75)', borderRadius: 999, gap: 1 }}>
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

          <div style={{ background: '#fff', borderRadius: 18, border: '1px solid oklch(94% 0.008 75)', padding: '6px 14px 8px' }}>
            {topProductos.length === 0 ? (
              <p style={{ margin: '12px 0', textAlign: 'center', fontSize: 12, color: 'oklch(65% 0.01 60)' }}>
                Sin datos de Siigo para este período
              </p>
            ) : topProductos.map((p, i) => {
              const barW = (p.cantidad / maxUnidades) * 100
              return (
                <div key={i} style={{
                  display: 'grid', gridTemplateColumns: '20px 1fr auto', alignItems: 'center', gap: 10,
                  padding: '9px 0',
                  borderBottom: i < topProductos.length - 1 ? '1px solid oklch(96% 0.008 75)' : 'none',
                }}>
                  <span style={{ fontSize: 11, fontWeight: 700, color: i === 0 ? 'oklch(35% 0.14 65)' : 'oklch(72% 0.008 60)', fontVariantNumeric: 'tabular-nums', letterSpacing: '.02em' }}>
                    #{i + 1}
                  </span>
                  <div style={{ minWidth: 0 }}>
                    <p style={{ margin: 0, fontSize: 12.5, fontWeight: 600, color: 'oklch(28% 0.01 60)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {p.nombre}
                    </p>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 3 }}>
                      <div style={{ flex: 1, height: 4, background: 'oklch(95% 0.008 75)', borderRadius: 999, overflow: 'hidden', maxWidth: 100 }}>
                        <div style={{
                          width: `${barW}%`, height: '100%', borderRadius: 999,
                          background: i === 0
                            ? 'linear-gradient(90deg, oklch(55% 0.16 65), oklch(60% 0.14 50))'
                            : 'oklch(78% 0.06 145)',
                        }} />
                      </div>
                      <span style={{ fontSize: 10.5, fontWeight: 600, color: 'oklch(58% 0.01 60)', fontVariantNumeric: 'tabular-nums' }}>
                        {Math.round(p.cantidad)} u
                      </span>
                    </div>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <p style={{ margin: 0, fontSize: 11.5, fontWeight: 700, color: 'oklch(30% 0.05 155)', fontVariantNumeric: 'tabular-nums' }}>
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
          <p style={{ margin: '0 4px 8px', fontSize: 10, fontWeight: 700, color: 'oklch(58% 0.01 60)', letterSpacing: '.1em', textTransform: 'uppercase' }}>
            Herramientas
          </p>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            {TOOLS_MAIN.map(({ label, sublabel, icon: Icon, path, tint }) => (
              <button
                key={path}
                onClick={() => navigate(path)}
                style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '12px 12px', borderRadius: 16, background: '#fff', border: '1px solid oklch(94% 0.008 75)', cursor: 'pointer', fontFamily: 'inherit', textAlign: 'left' }}
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
                  <p style={{ margin: 0, fontSize: 13, fontWeight: 700, color: 'oklch(28% 0.01 60)', letterSpacing: '-0.005em' }}>{label}</p>
                  <p style={{ margin: '1px 0 0', fontSize: 10, color: 'oklch(58% 0.01 60)', fontWeight: 500 }}>{sublabel}</p>
                </div>
              </button>
            ))}
          </div>
          {/* Dashed "más" button with color dots */}
          <button
            onClick={() => setShowMas(true)}
            style={{ marginTop: 8, width: '100%', display: 'flex', alignItems: 'center', gap: 10, padding: '11px 14px', background: 'oklch(95% 0.012 75)', border: '1px dashed oklch(85% 0.012 75)', borderRadius: 14, cursor: 'pointer', fontFamily: 'inherit' }}
          >
            <LayoutGrid size={14} style={{ color: 'oklch(58% 0.01 60)' }} />
            <span style={{ flex: 1, textAlign: 'left', fontSize: 12, fontWeight: 700, color: 'oklch(40% 0.01 60)' }}>
              {TOOLS_MORE.length} herramientas más
            </span>
            <span style={{ display: 'flex', gap: 3, marginRight: 6 }}>
              {TOOLS_MORE.slice(0, 5).map(t => (
                <span key={t.id} style={{ width: 6, height: 6, borderRadius: 999, background: `color-mix(in oklch, ${t.tint} 70%, oklch(85% 0.008 75))` }} />
              ))}
            </span>
            <ChevronRight size={14} style={{ color: 'oklch(58% 0.01 60)' }} />
          </button>
        </div>

        {/* ── Actividad reciente ───────────────────────────────────────── */}
        <div style={{ background: '#fff', border: '1px solid oklch(94% 0.008 75)', borderRadius: 16, overflow: 'hidden' }}>
          <button
            onClick={() => setActividadOpen(v => !v)}
            style={{ width: '100%', display: 'flex', alignItems: 'center', gap: 10, padding: '11px 14px', background: 'transparent', border: 'none', cursor: 'pointer', fontFamily: 'inherit', textAlign: 'left' }}
          >
            <div style={{ width: 28, height: 28, borderRadius: 9, background: 'oklch(96% 0.008 75)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
              <TrendingUp size={13} style={{ color: 'oklch(40% 0.05 155)' }} />
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <p style={{ margin: 0, fontSize: 12.5, fontWeight: 700, color: 'oklch(28% 0.01 60)' }}>Actividad reciente</p>
              <p style={{ margin: '1px 0 0', fontSize: 10.5, color: 'oklch(58% 0.01 60)', fontWeight: 500 }}>
                {movimientos.length > 0
                  ? `${movimientos.filter(m => m.tipo === 'ingreso').length} ingreso${movimientos.filter(m => m.tipo === 'ingreso').length !== 1 ? 's' : ''} · ${movimientos.filter(m => m.tipo === 'egreso').length} egreso${movimientos.filter(m => m.tipo === 'egreso').length !== 1 ? 's' : ''} · turno en curso`
                  : turno ? 'Sin movimientos este turno' : 'Sin turno activo'
                }
              </p>
            </div>
            {actividadOpen
              ? <ChevronUp size={14} style={{ color: 'oklch(58% 0.01 60)' }} />
              : <ChevronDown size={14} style={{ color: 'oklch(58% 0.01 60)' }} />}
          </button>
          {actividadOpen && movimientos.length > 0 && (
            <div style={{ borderTop: '1px solid oklch(96% 0.008 75)' }}>
              {movimientos.slice(0, 8).map((m, i) => (
                <div key={m.id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 14px', borderBottom: i < Math.min(movimientos.length, 8) - 1 ? '1px solid oklch(97% 0.008 75)' : 'none' }}>
                  <span style={{ width: 24, height: 24, borderRadius: 8, background: m.tipo === 'ingreso' ? 'oklch(94% 0.04 145)' : 'oklch(96% 0.03 30)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                    {m.tipo === 'ingreso'
                      ? <TrendingUp size={11} style={{ color: '#2d8a5f' }} />
                      : <TrendingDown size={11} style={{ color: '#c64a3a' }} />}
                  </span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <p style={{ margin: 0, fontSize: 12.5, fontWeight: 600, color: 'oklch(28% 0.01 60)' }}>{m.concepto}</p>
                    <p style={{ margin: 0, fontSize: 10, color: 'oklch(58% 0.01 60)', fontVariantNumeric: 'tabular-nums' }}>
                      {parseUTC(m.fecha).toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit' })}
                    </p>
                  </div>
                  <span style={{ fontSize: 12.5, fontWeight: 700, fontVariantNumeric: 'tabular-nums', color: m.tipo === 'ingreso' ? '#2d8a5f' : '#c64a3a' }}>
                    {m.tipo === 'ingreso' ? '+' : '−'}{fmt(m.valor)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

      </div>{/* /scroll */}

      {/* ── Drawer de navegación ─────────────────────────────────────── */}
      {menuOpen && (
        <div style={{ position: 'fixed', inset: 0, zIndex: 60, display: 'flex' }}>
          {/* Backdrop */}
          <div
            style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,.45)' }}
            onClick={() => setMenuOpen(false)}
          />
          {/* Panel */}
          <div style={{ position: 'relative', background: '#fff', width: 256, height: '100%', display: 'flex', flexDirection: 'column', boxShadow: '4px 0 24px rgba(0,0,0,.15)', paddingTop: 'env(safe-area-inset-top, 0px)' }}>
            {/* Drawer header */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 16px', borderBottom: '1px solid oklch(94% 0.008 75)' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Coffee size={15} style={{ color: 'oklch(35% 0.05 155)' }} />
                <span style={{ fontWeight: 700, fontSize: 13, color: 'oklch(22% 0.01 60)', fontFamily: '"Plus Jakarta Sans", system-ui, sans-serif' }}>Sistema Café</span>
              </div>
              <button
                onClick={() => setMenuOpen(false)}
                style={{ padding: 4, background: 'transparent', border: 'none', cursor: 'pointer', color: 'oklch(58% 0.01 60)' }}
                aria-label="Cerrar menú"
              >
                <XIcon size={18} />
              </button>
            </div>
            {/* Links */}
            <div style={{ flex: 1, overflowY: 'auto', padding: '8px 8px' }}>
              {NAV_ADMIN.map(({ to, label, icon: Icon }) => (
                <NavLink
                  key={to} to={to}
                  onClick={() => setMenuOpen(false)}
                  style={({ isActive }) => ({
                    display: 'flex', alignItems: 'center', gap: 12,
                    padding: '11px 14px', borderRadius: 12, marginBottom: 2,
                    fontSize: 13.5, fontWeight: isActive ? 700 : 500,
                    color: isActive ? 'oklch(35% 0.05 155)' : 'oklch(35% 0.01 60)',
                    background: isActive ? 'oklch(95% 0.018 155)' : 'transparent',
                    textDecoration: 'none', fontFamily: '"Plus Jakarta Sans", system-ui, sans-serif',
                    transition: 'background .15s',
                  })}
                >
                  <Icon size={16} />
                  {label}
                </NavLink>
              ))}
            </div>
            {/* User footer */}
            <div style={{ padding: '12px 16px', borderTop: '1px solid oklch(94% 0.008 75)' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div>
                  <p style={{ margin: 0, fontSize: 13, fontWeight: 700, color: 'oklch(22% 0.01 60)', fontFamily: '"Plus Jakarta Sans", system-ui, sans-serif' }}>{user?.nombre}</p>
                  <span style={{ fontSize: 10.5, padding: '1px 7px', borderRadius: 999, fontWeight: 600, background: 'oklch(93% 0.02 290)', color: 'oklch(40% 0.1 290)', fontFamily: '"Plus Jakarta Sans", system-ui, sans-serif' }}>admin</span>
                </div>
                <button
                  onClick={() => { setMenuOpen(false); if (window.confirm('¿Cerrar sesión?')) { logout(); navigate('/login') } }}
                  style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11.5, color: 'oklch(58% 0.01 60)', background: 'transparent', border: 'none', cursor: 'pointer', fontFamily: '"Plus Jakarta Sans", system-ui, sans-serif' }}
                >
                  <LogOut size={13} /> Salir
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── "Más herramientas" overlay ────────────────────────────────── */}
      {showMas && (
        <div
          style={{ position: 'fixed', inset: 0, zIndex: 50, display: 'flex', alignItems: 'flex-end', justifyContent: 'center', background: 'rgba(0,0,0,.5)' }}
          onClick={() => setShowMas(false)}
        >
          <div
            style={{ background: 'oklch(97% 0.012 75)', width: '100%', maxWidth: 448, borderRadius: '24px 24px 0 0', padding: '20px 16px 32px', boxShadow: '0 -8px 40px rgba(0,0,0,.2)' }}
            onClick={e => e.stopPropagation()}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
              <p style={{ margin: 0, fontSize: 13, fontWeight: 700, color: 'oklch(22% 0.01 60)' }}>Más herramientas</p>
              <button onClick={() => setShowMas(false)} style={{ padding: 6, background: 'transparent', border: 'none', cursor: 'pointer', color: 'oklch(58% 0.01 60)' }}>
                <XIcon size={18} />
              </button>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
              {TOOLS_MORE.map(({ label, icon: Icon, path, tint }) => (
                <button
                  key={path}
                  onClick={() => { setShowMas(false); navigate(path) }}
                  style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6, padding: '12px 8px', borderRadius: 16, background: '#fff', border: '1px solid oklch(94% 0.008 75)', cursor: 'pointer', fontFamily: 'inherit' }}
                >
                  <div style={{ width: 32, height: 32, borderRadius: 10, background: `linear-gradient(135deg, color-mix(in oklch, ${tint} 18%, #fff), color-mix(in oklch, ${tint} 8%, #fff))`, border: `1px solid color-mix(in oklch, ${tint} 25%, #fff)`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                    <Icon size={15} style={{ color: tint }} />
                  </div>
                  <span style={{ fontSize: 11, fontWeight: 600, color: 'oklch(35% 0.01 60)', textAlign: 'center', lineHeight: 1.2 }}>{label}</span>
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* ── Admin bottom nav ─────────────────────────────────────────── */}
      <nav className="md:hidden" style={{ display: 'flex', borderTop: '1px solid oklch(94% 0.008 75)', background: 'rgba(255,255,255,.95)', paddingBottom: 'env(safe-area-inset-bottom, 0px)', backdropFilter: 'blur(12px)' }}>
        {[
          { icon: Home,         label: 'Inicio',  path: '/dashboard',   active: true  },
          { icon: DollarSign,   label: 'Ventas',  path: '/informes',    active: false },
          { icon: Inbox,        label: 'Comuni.', path: '/comunicados', active: false },
          { icon: LayoutGrid,   label: 'Más',     path: null,           active: false },
        ].map((item, i) => (
          <button
            key={i}
            onClick={() => item.path ? navigate(item.path) : setShowMas(true)}
            style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 3, padding: '12px 0 8px', background: 'transparent', border: 'none', cursor: 'pointer', fontFamily: 'inherit', position: 'relative' }}
          >
            {item.active && (
              <span style={{ position: 'absolute', top: 0, left: '50%', transform: 'translateX(-50%)', width: 22, height: 2.5, background: 'oklch(35% 0.05 155)', borderRadius: 999 }} />
            )}
            <item.icon size={20} style={{ color: item.active ? 'oklch(35% 0.05 155)' : 'oklch(72% 0.008 60)' }} />
            <span style={{ fontSize: 9.5, fontWeight: 600, color: item.active ? 'oklch(35% 0.05 155)' : 'oklch(72% 0.008 60)' }}>
              {item.label}
            </span>
          </button>
        ))}
      </nav>

    </div>
  )
}
