import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useTurno } from '../contexts/TurnoContext'
import api from '../api/client'
import {
  Coffee, LogOut,
  AlertTriangle, ChevronRight, Lock,
  TrendingUp, TrendingDown, UserCheck,
  Sparkles, Cake, Clock, Bell, X as XIcon, ImageIcon,
  Banknote, Trash2, Package, ShoppingCart, FileText,
  ClipboardList, ReceiptText, LayoutGrid, ChevronDown, ChevronUp,
  ClipboardCheck,
} from 'lucide-react'
import BaristaBottomNav from '../components/BaristaBottomNav'

// ─── Helpers ──────────────────────────────────────────────────────────────────
function parseUTC(s: string): Date {
  const t = s.replace(' ', 'T').replace(/(\.\d{3})\d+/, '$1').replace('+00:00', 'Z')
  return new Date(t.endsWith('Z') ? t : t + 'Z')
}
function hora() {
  return new Date().toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit' })
}
function saludo() {
  const h = new Date().getHours()
  if (h < 12) return 'Buenos días'
  if (h < 18) return 'Buenas tardes'
  return 'Buenas noches'
}
const fmt = (v: number) => `$${v.toLocaleString('es-CO')}`
function toMins(d: Date) { return d.getHours() * 60 + d.getMinutes() }
function fmtTime(d: Date) {
  return d.toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit' })
}

// ─── Tools ────────────────────────────────────────────────────────────────────
const TOOLS_MAIN = [
  { label: 'Mermas',     sublabel: 'Registrar pérdidas', icon: Trash2,       path: '/mermas',     tint: '#d97757' },
  { label: 'Inventario', sublabel: 'Stock actual',        icon: Package,      path: '/inventario', tint: '#5b8def' },
  { label: 'Pedido',     sublabel: 'Solicitar productos', icon: ShoppingCart, path: '/pedido',     tint: '#2d5a3f' },
  { label: 'Sencilla',   sublabel: 'Sencilla del día',    icon: FileText,     path: '/sencilla',   tint: '#c08a3e' },
]
const TOOLS_MORE = [
  { label: 'Pastelería',     icon: Cake,          path: '/pasteleria',     tint: '#e8894a' },
  { label: 'Conteos',        icon: ClipboardList, path: '/conteos',        tint: '#8a5dc7' },
  { label: 'Ingresos',       icon: ReceiptText,   path: '/ingresos',       tint: '#7a6a55' },
  { label: 'Limpieza',       icon: Sparkles,      path: '/limpieza',       tint: '#d169a4' },
  { label: 'Consignaciones', icon: Banknote,      path: '/consignaciones', tint: '#2a8d8a' },
  { label: 'C. Compras',     icon: ClipboardCheck, path: '/conteo-compras', tint: '#5a6dbf' },
]

// ─── Interfaces ──────────────────────────────────────────────────────────────
interface AlertaStock {
  producto_id: number; producto: string; unidad: string
  stock_actual: number; stock_minimo: number; cantidad_sugerida: number
  nivel: 'agotado' | 'bajo'
}
interface LoteImpulso {
  lote_id: number; producto_id: number; producto_nombre: string
  cantidad_restante: number; fecha_entrada: string
  dias_en_inventario: number; urgente: boolean
}
interface Comunicado {
  id: number; titulo: string | null; mensaje: string
  urgente: boolean; fecha_creacion: string
}
interface Movimiento {
  id: number; tipo: string; concepto: string; valor: number
  fecha: string; imagen_url: string | null
}
interface PendienteConsignacion {
  turno_id: number; fecha_apertura: string; fecha_cierre: string
  esperado: number; consignado: number; pendiente: number
}
interface Venta {
  id: number; venta_total: number; nota_credito: number
  vales: number; tarjetas: number; efectivo_calculado: number
  fecha_registro: string; nota: string | null
}

// ─── ShiftTimeline ────────────────────────────────────────────────────────────
interface PasoTL {
  id: string
  label: string
  labelShort: string
  done: boolean
  ts: Date | null
}

function ShiftTimeline({ pasos, currentIdx }: { pasos: PasoTL[]; currentIdx: number }) {
  const now = new Date()
  const apertura = pasos[0].ts!
  const startMin = toMins(apertura)
  const nowMin   = toMins(now)
  const elapsed  = Math.max(0, nowMin - startMin)
  const endMin   = Math.max(nowMin, startMin + 30)
  const span     = endMin - startMin
  const tlPos    = (d: Date) => Math.max(0, Math.min(1, (toMins(d) - startMin) / span))
  const hourTicks = Array.from({ length: Math.floor(span / 60) + 1 }, (_, i) => i * 60 / span).filter(t => t <= 1)

  // Dots: done=at ts, current=at 1 (now), future=hidden
  const dots = pasos.flatMap((p, i) => {
    if (!p.done && i !== currentIdx) return []           // future: skip
    if (p.done && !p.ts) return []                       // done but no timestamp: skip
    const pos = i === currentIdx ? 1 : tlPos(p.ts!)
    const kind: 'done' | 'current' = i === currentIdx ? 'current' : 'done'
    return [{ ...p, pos, kind }]
  })

  const elapsedH = Math.floor(elapsed / 60)
  const elapsedM = elapsed % 60

  return { dots, hourTicks, span, startMin, nowMin, elapsedH, elapsedM, apertura, now }
}

// ─── Hub ─────────────────────────────────────────────────────────────────────
export default function Hub() {
  const { user, logout } = useAuth()
  const { turno, refresh } = useTurno()
  const navigate = useNavigate()

  const [alertas, setAlertas] = useState<AlertaStock[]>([])
  const [impulso, setImpulso] = useState<LoteImpulso[]>([])
  const [showImpulso, setShowImpulso] = useState(false)
  const [comunicados, setComunicados] = useState<Comunicado[]>([])
  const [movimientos, setMovimientos] = useState<Movimiento[]>([])
  const [showMovimientos, setShowMovimientos] = useState(false)
  const [time, setTime] = useState(hora())
  const [ventas, setVentas] = useState<Venta[]>([])
  const [showVentas, setShowVentas] = useState(false)
  const [limpiezaDiaria, setLimpiezaDiaria] = useState(false)
  const [showMasTools, setShowMasTools] = useState(false)
  const [pendienteConsig, setPendienteConsig] = useState<{ items: PendienteConsignacion[], total_pendiente: number } | null>(null)
  const [, setTick] = useState(0)

  // Reloj + elapsed time refresh
  useEffect(() => {
    const t = setInterval(() => { setTime(hora()); setTick(n => n + 1) }, 30000)
    return () => clearInterval(t)
  }, [])

  // Carga inicial
  useEffect(() => {
    if (!user?.tienda_id) return
    api.get(`/inventario/alertas/${user.tienda_id}`).then(r => setAlertas(r.data)).catch(() => null)
    api.get(`/dashboard/${user.tienda_id}`).then(r => setLimpiezaDiaria(r.data.limpieza_check)).catch(() => null)
    api.get(`/consignaciones/pendiente/${user.tienda_id}`).then(r => setPendienteConsig(r.data)).catch(() => null)
    refresh()
    api.get('/comunicados/mis-comunicados').then(r => setComunicados(r.data)).catch(() => null)

    const sessionKey = `impulso_visto_${user.tienda_id}`
    if (!sessionStorage.getItem(sessionKey)) {
      api.get(`/inventario/pasteleria-impulso/${user.tienda_id}`)
        .then(r => {
          if (r.data.length > 0) { setImpulso(r.data); setShowImpulso(true) }
          sessionStorage.setItem(sessionKey, '1')
        })
        .catch(() => null)
    }
  }, [user?.tienda_id])  // eslint-disable-line

  // Ventas del turno
  useEffect(() => {
    if (turno?.id && turno.tiene_ventas) {
      api.get(`/ventas/turno/${turno.id}`).then(r => setVentas(r.data)).catch(() => null)
    } else {
      setVentas([])
    }
  }, [turno?.id, turno?.tiene_ventas])

  // Movimientos
  useEffect(() => {
    if (turno?.id) {
      api.get(`/caja/${turno.id}/movimientos`).then(r => setMovimientos(r.data)).catch(() => null)
    } else {
      setMovimientos([])
    }
  }, [turno?.id, turno?.ingresos_movimientos, turno?.egresos_movimientos])

  // ── Pasos del turno ──────────────────────────────────────────────────────
  const pasosNav = [
    { label: 'Apertura',        done: !!turno,                        accion: () => navigate('/apertura') },
    { label: 'Conteo apertura', done: !!turno?.tiene_conteo_apertura, accion: () => navigate('/conteo-apertura') },
    { label: 'Ventas',          done: !!turno?.tiene_ventas,          accion: () => navigate('/ventas') },
    { label: 'Conteo cierre',   done: !!turno?.tiene_conteo_cierre,   accion: () => navigate('/conteo-cierre') },
    { label: 'Cierre',          done: turno?.estado === 'cerrado',    accion: () => navigate('/cierre') },
  ]
  const pasoActualIdx = pasosNav.findIndex(p => !p.done)
  const nextStep = pasoActualIdx >= 0 ? pasosNav[pasoActualIdx] : null

  const toggleLimpieza = async () => {
    const nuevo = !limpiezaDiaria
    setLimpiezaDiaria(nuevo)
    try {
      await api.patch(`/dashboard/${user?.tienda_id}/checklist`, { campo: 'limpieza_check', valor: nuevo })
    } catch { setLimpiezaDiaria(!nuevo) }
  }

  const agotados = alertas.filter(a => a.nivel === 'agotado')
  const bajos    = alertas.filter(a => a.nivel === 'bajo')

  // ── Timeline data (only when turno exists) ───────────────────────────────
  const tlData = turno ? (() => {
    const aperturaDate = parseUTC(turno.fecha_apertura)
    const pasosTL: PasoTL[] = [
      { id: 'apertura',        label: 'Apertura',      labelShort: 'Apertura',  done: true,                        ts: aperturaDate },
      { id: 'conteo_apertura', label: 'C. apertura',   labelShort: 'C.apert.',  done: !!turno.tiene_conteo_apertura, ts: turno.ts_conteo_apertura ? parseUTC(turno.ts_conteo_apertura) : null },
      { id: 'ventas',          label: 'Ventas',        labelShort: 'Ventas',    done: !!turno.tiene_ventas,          ts: null },
      { id: 'conteo_cierre',   label: 'Conteo cierre', labelShort: 'C.cierre',  done: !!turno.tiene_conteo_cierre,   ts: turno.ts_conteo_cierre ? parseUTC(turno.ts_conteo_cierre) : null },
      { id: 'cierre',          label: 'Cierre',        labelShort: 'Cierre',    done: turno.estado === 'cerrado',    ts: null },
    ]
    const currentIdx = pasosTL.findIndex(p => !p.done)
    return { pasosTL, currentIdx, ...ShiftTimeline({ pasos: pasosTL, currentIdx }) }
  })() : null

  // ── Cuadre de llegada helpers ─────────────────────────────────────────────
  const sinEntrega  = turno ? !turno.ultima_entrega_fecha : false
  const hace4h      = turno?.ultima_entrega_fecha
    ? (Date.now() - parseUTC(turno.ultima_entrega_fecha).getTime()) > 4 * 60 * 60 * 1000
    : false
  const conDiff     = turno
    && turno.ultima_entrega_diferencia_efectivo !== null
    && turno.ultima_entrega_diferencia_efectivo !== 0

  return (
    <div className="min-h-screen flex flex-col" style={{ background: 'oklch(97% 0.012 75)', fontFamily: '"Plus Jakarta Sans", -apple-system, system-ui, sans-serif' }}>

      {/* ── Header ──────────────────────────────────────────────────────── */}
      <header className="border-b px-4 pb-3 header-safe flex items-center justify-between sticky top-0 z-10"
        style={{ background: 'rgba(255,255,255,0.95)', backdropFilter: 'blur(12px)', borderColor: 'oklch(94% 0.008 75)' }}>
        <div className="flex items-center gap-2">
          <Coffee size={15} style={{ color: 'oklch(35% 0.05 155)' }} />
          <span style={{ fontSize: 12, fontWeight: 700, color: 'oklch(35% 0.05 155)', letterSpacing: '.02em' }}>
            Hub · {user?.nombre?.split(' ')[0]}
          </span>
        </div>
        <div className="flex items-center gap-3">
          <span style={{ fontSize: 11, fontWeight: 600, color: 'oklch(58% 0.01 60)', fontVariantNumeric: 'tabular-nums' }}>{time}</span>
          {comunicados.length > 0 && (
            <div className="relative">
              <Bell size={15} style={{ color: 'oklch(58% 0.01 60)' }} />
              <span className="absolute -top-1.5 -right-1.5 text-white flex items-center justify-center font-bold"
                style={{ background: '#d97757', fontSize: 8, width: 13, height: 13, borderRadius: 999, border: '1.5px solid oklch(97% 0.012 75)' }}>
                {comunicados.length}
              </span>
            </div>
          )}
          <button
            onClick={() => { if (window.confirm('¿Cerrar sesión?')) { logout(); navigate('/login') } }}
            className="p-1.5 transition-colors"
            style={{ color: 'oklch(72% 0.008 60)' }}
          >
            <LogOut size={14} />
          </button>
        </div>
      </header>

      {/* ── Scroll content ──────────────────────────────────────────────── */}
      <div className="flex-1 pb-nav" style={{ padding: '0 16px 16px' }}>

        {/* Saludo */}
        <div style={{ padding: '14px 4px 10px' }}>
          <p style={{ fontSize: 18, fontWeight: 700, color: 'oklch(22% 0.01 60)', margin: 0 }}>
            {saludo()}, <span style={{ color: 'oklch(35% 0.05 155)' }}>{user?.nombre?.split(' ')[0]}</span>
          </p>
          <p style={{ fontSize: 11, color: 'oklch(58% 0.01 60)', margin: '2px 0 0', textTransform: 'capitalize' }}>
            {new Date().toLocaleDateString('es-CO', { weekday: 'long', day: 'numeric', month: 'long' })}
          </p>
        </div>

        {/* ── Comunicados del admin ──────────────────────────────────────── */}
        {comunicados.length > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 12 }}>
            {comunicados.map(c => (
              <div key={c.id} style={{
                display: 'flex', gap: 12, alignItems: 'flex-start',
                padding: '12px 14px', borderRadius: 16,
                background: c.urgente ? 'oklch(98% 0.02 30)' : 'oklch(98% 0.03 75)',
                border: `1px solid ${c.urgente ? 'oklch(90% 0.06 30)' : 'oklch(90% 0.07 75)'}`,
              }}>
                <div style={{
                  width: 30, height: 30, borderRadius: 10, flexShrink: 0,
                  background: c.urgente ? 'oklch(94% 0.04 30)' : 'oklch(94% 0.06 75)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                }}>
                  <AlertTriangle size={14} style={{ color: c.urgente ? '#c64a3a' : 'oklch(52% 0.15 65)' }} />
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  {c.titulo && (
                    <p style={{ margin: '0 0 2px', fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '.08em', color: c.urgente ? '#8a3325' : 'oklch(38% 0.12 65)' }}>
                      {c.titulo}
                    </p>
                  )}
                  <p style={{ margin: 0, fontSize: 13, lineHeight: 1.4, color: c.urgente ? '#6a2318' : 'oklch(28% 0.06 60)' }}>
                    {c.mensaje}
                  </p>
                </div>
                <button
                  onClick={async () => {
                    await api.post(`/comunicados/${c.id}/leer`)
                    setComunicados(prev => prev.filter(x => x.id !== c.id))
                  }}
                  style={{
                    flexShrink: 0, fontSize: 11, fontWeight: 700, padding: '5px 10px', borderRadius: 9,
                    background: c.urgente ? '#c64a3a' : 'oklch(72% 0.14 65)',
                    color: '#fff', border: 'none', cursor: 'pointer', fontFamily: 'inherit',
                  }}
                >OK</button>
              </div>
            ))}
          </div>
        )}

        {/* ── Consignaciones pendientes ──────────────────────────────────── */}
        {pendienteConsig && pendienteConsig.items.filter(i => i.pendiente > 0).length > 0 && (() => {
          const items = pendienteConsig.items.filter(i => i.pendiente > 0)
          return (
            <div style={{
              padding: '12px 14px', borderRadius: 18, marginBottom: 12,
              background: 'oklch(97% 0.025 65)', border: '2px solid oklch(82% 0.10 65)',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Banknote size={14} style={{ color: 'oklch(52% 0.18 65)' }} />
                  <span style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '.08em', color: 'oklch(38% 0.12 65)' }}>
                    {items.length === 1 ? '1 consignación pendiente' : `${items.length} consignaciones pendientes`}
                  </span>
                </div>
                <span style={{ fontSize: 11, fontWeight: 700, fontVariantNumeric: 'tabular-nums', padding: '3px 9px', borderRadius: 999, background: 'oklch(88% 0.09 65)', color: 'oklch(38% 0.14 65)' }}>
                  {fmt(pendienteConsig.total_pendiente)}
                </span>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {items.map(item => (
                  <div key={item.turno_id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 12px', borderRadius: 12, background: 'oklch(93% 0.04 65)' }}>
                    <span style={{ fontSize: 13, color: 'oklch(40% 0.08 65)', textTransform: 'capitalize' }}>
                      {parseUTC(item.fecha_cierre).toLocaleDateString('es-CO', { weekday: 'long', day: 'numeric', month: 'short' })}
                    </span>
                    <span style={{ fontSize: 13, fontWeight: 700, fontVariantNumeric: 'tabular-nums', color: 'oklch(38% 0.14 65)' }}>
                      {fmt(item.pendiente)}
                    </span>
                  </div>
                ))}
              </div>
              <button
                onClick={() => navigate('/consignaciones')}
                style={{ width: '100%', marginTop: 10, padding: '10px 0', borderRadius: 12, border: 'none', background: 'oklch(72% 0.14 65)', color: '#fff', fontSize: 12, fontWeight: 700, cursor: 'pointer', fontFamily: 'inherit' }}
              >
                Registrar consignación →
              </button>
            </div>
          )
        })()}

        {/* ── Hero: tarjeta de turno ─────────────────────────────────────── */}
        {turno && tlData ? (
          <div style={{
            borderRadius: 26, overflow: 'hidden', marginBottom: 12, color: '#fff',
            background: 'linear-gradient(165deg, oklch(32% 0.045 155) 0%, oklch(26% 0.05 155) 60%, oklch(22% 0.04 155) 100%)',
            padding: '16px 18px 18px',
            boxShadow: '0 12px 32px -20px rgba(28,55,42,.6)',
          }}>
            {/* Status pill + step count */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 14 }}>
              <div>
                {/* Pill */}
                <div style={{
                  display: 'inline-flex', alignItems: 'center', gap: 7,
                  padding: '4px 11px 4px 9px', borderRadius: 999, marginBottom: 8,
                  background: 'oklch(40% 0.06 155)', border: '1px solid oklch(50% 0.08 155)',
                }}>
                  <span style={{
                    width: 6, height: 6, borderRadius: 999, background: 'oklch(78% 0.18 145)',
                    boxShadow: '0 0 0 3px oklch(40% 0.10 145 / 0.5)', flexShrink: 0,
                  }} />
                  <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: '.06em', textTransform: 'uppercase', color: 'oklch(92% 0.05 145)' }}>
                    Turno · {new Date().getHours() < 14 ? 'Mañana' : 'Tarde'}
                  </span>
                </div>
                {/* Elapsed time */}
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
                  <span style={{ fontSize: 26, fontWeight: 700, letterSpacing: '-0.02em', fontVariantNumeric: 'tabular-nums', color: '#fff' }}>
                    {tlData.elapsedH}h {tlData.elapsedM.toString().padStart(2, '0')}m
                  </span>
                  <span style={{ fontSize: 11, color: 'oklch(72% 0.05 155)', fontWeight: 500 }}>en turno</span>
                </div>
              </div>
              <div style={{ textAlign: 'right' }}>
                <p style={{ margin: 0, fontSize: 9, fontWeight: 700, letterSpacing: '.08em', textTransform: 'uppercase', color: 'oklch(72% 0.05 155)' }}>Pasos</p>
                <p style={{ margin: '2px 0 0', fontSize: 18, fontWeight: 700, letterSpacing: '-0.02em', fontVariantNumeric: 'tabular-nums', color: '#fff' }}>
                  {tlData.pasosTL.filter(p => p.done).length}
                  <span style={{ color: 'oklch(72% 0.05 155)', fontWeight: 500 }}>/{tlData.pasosTL.length}</span>
                </p>
              </div>
            </div>

            {/* Timeline */}
            <div style={{ position: 'relative', padding: '14px 8px 10px' }}>
              {/* Track */}
              <div style={{ position: 'absolute', left: 8, right: 8, top: 22, height: 3, background: 'oklch(40% 0.05 155)', borderRadius: 999 }} />
              {/* Traversed */}
              <div style={{ position: 'absolute', left: 8, top: 22, height: 3, right: 8, background: 'linear-gradient(90deg, oklch(55% 0.13 145), oklch(78% 0.16 75))', borderRadius: 999 }} />
              {/* Hour ticks */}
              {tlData.hourTicks.map((t, i) => (
                <span key={i} style={{ position: 'absolute', top: 18, left: `calc(8px + (100% - 16px) * ${t})`, width: 1, height: 11, background: 'oklch(50% 0.05 155)', transform: 'translateX(-50%)' }} />
              ))}
              {/* Step dots */}
              <div style={{ position: 'relative', height: 48 }}>
                {tlData.dots.map(d => (
                  <div key={d.id} style={{
                    position: 'absolute', top: 0,
                    left: `calc(8px + (100% - 16px) * ${d.pos})`,
                    transform: 'translateX(-50%)',
                    display: 'flex', flexDirection: 'column', alignItems: 'center',
                    width: 64,
                  }}>
                    <div style={{
                      width: d.kind === 'current' ? 18 : 12,
                      height: d.kind === 'current' ? 18 : 12,
                      borderRadius: 999,
                      marginTop: d.kind === 'current' ? -7.5 : -4.5,
                      background: d.kind === 'current' ? '#d97757' : 'oklch(78% 0.16 75)',
                      border: d.kind === 'current' ? '3px solid #fff' : '2px solid oklch(28% 0.04 155)',
                      boxShadow: d.kind === 'current' ? '0 2px 8px oklch(60% 0.16 30 / 0.5)' : '0 0 0 3px oklch(40% 0.10 145 / 0.25)',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                    }}>
                      {d.kind === 'done' && (
                        <svg width="7" height="7" viewBox="0 0 7 7" fill="none">
                          <path d="M1 3.5L2.8 5.5L6 1.5" stroke="oklch(20% 0.04 155)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                        </svg>
                      )}
                    </div>
                    <span style={{ marginTop: 7, fontSize: 9, fontWeight: 700, letterSpacing: '.02em', color: d.kind === 'current' ? 'oklch(85% 0.10 50)' : 'oklch(82% 0.04 75)', whiteSpace: 'nowrap' }}>
                      {d.labelShort}
                    </span>
                    <span style={{ fontSize: 9, fontVariantNumeric: 'tabular-nums', fontWeight: 500, color: d.kind === 'current' ? 'oklch(75% 0.10 50)' : 'oklch(65% 0.04 155)' }}>
                      {d.kind === 'done' && d.ts ? fmtTime(d.ts) : d.kind === 'current' ? 'ahora' : ''}
                    </span>
                  </div>
                ))}
              </div>
              {/* Range labels */}
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 9, fontWeight: 600, fontVariantNumeric: 'tabular-nums', color: 'oklch(60% 0.05 155)' }}>
                <span>Abrió {fmtTime(tlData.apertura)}</span>
                <span style={{ color: 'oklch(85% 0.10 50)' }}>● {time}</span>
              </div>
            </div>

            {/* Stats row */}
            <div style={{ display: 'grid', gridTemplateColumns: '1.4fr 1fr 1fr', gap: 8, marginTop: 14, paddingTop: 12, borderTop: '1px solid oklch(38% 0.05 155)' }}>
              <div>
                <p style={{ margin: 0, fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '.08em', color: 'oklch(72% 0.05 155)' }}>Ventas</p>
                <p style={{ margin: '2px 0 0', fontSize: 20, fontWeight: 700, letterSpacing: '-0.02em', fontVariantNumeric: 'tabular-nums', color: '#fff' }}>
                  {fmt(turno.total_ventas)}
                </p>
              </div>
              <div>
                <p style={{ margin: 0, fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '.08em', color: 'oklch(72% 0.05 155)' }}>Efectivo</p>
                <p style={{ margin: '2px 0 0', fontSize: 13, fontWeight: 700, fontVariantNumeric: 'tabular-nums', color: 'oklch(88% 0.04 75)' }}>
                  {fmt(turno.total_efectivo)}
                </p>
              </div>
              <div>
                <p style={{ margin: 0, fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '.08em', color: 'oklch(72% 0.05 155)' }}>Tarjeta</p>
                <p style={{ margin: '2px 0 0', fontSize: 13, fontWeight: 700, fontVariantNumeric: 'tabular-nums', color: 'oklch(88% 0.04 75)' }}>
                  {fmt(turno.total_tarjeta)}
                </p>
              </div>
            </div>

            {/* Historial ventas (expandible) */}
            {ventas.length > 0 && (
              <div style={{ marginTop: 12, paddingTop: 10, borderTop: '1px solid oklch(30% 0.04 155)' }}>
                <button
                  onClick={() => setShowVentas(v => !v)}
                  style={{ width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between', background: 'transparent', border: 'none', cursor: 'pointer', padding: '0 0 0 2px', fontFamily: 'inherit' }}
                >
                  <span style={{ fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '.08em', color: 'oklch(65% 0.05 155)' }}>
                    {ventas.length} registro{ventas.length > 1 ? 's' : ''} de venta
                  </span>
                  {showVentas
                    ? <ChevronUp size={12} style={{ color: 'oklch(65% 0.05 155)' }} />
                    : <ChevronDown size={12} style={{ color: 'oklch(65% 0.05 155)' }} />}
                </button>
                {showVentas && (
                  <div style={{ marginTop: 8, borderRadius: 12, overflow: 'hidden', background: 'oklch(26% 0.03 155)' }}>
                    {ventas.map(v => (
                      <div key={v.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 12px', borderBottom: '1px solid oklch(30% 0.03 155)' }}>
                        <div>
                          <p style={{ margin: 0, fontSize: 11, color: 'oklch(55% 0.05 155)' }}>
                            {parseUTC(v.fecha_registro).toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit' })}
                          </p>
                          <p style={{ margin: '2px 0 0', fontSize: 14, fontWeight: 700, fontVariantNumeric: 'tabular-nums', color: '#fff' }}>{fmt(v.venta_total)}</p>
                          {v.nota && <p style={{ margin: '1px 0 0', fontSize: 11, fontStyle: 'italic', color: 'oklch(55% 0.05 155)' }}>{v.nota}</p>}
                        </div>
                        <div style={{ textAlign: 'right' }}>
                          <p style={{ margin: 0, fontSize: 11, fontWeight: 600, color: 'oklch(72% 0.18 145)' }}>Ef: {fmt(v.efectivo_calculado)}</p>
                          {v.tarjetas > 0 && <p style={{ margin: '2px 0 0', fontSize: 11, color: 'oklch(72% 0.12 240)' }}>Tarj: {fmt(v.tarjetas)}</p>}
                          {v.nota_credito > 0 && <p style={{ margin: '2px 0 0', fontSize: 11, color: 'oklch(70% 0.16 30)' }}>NC: {fmt(v.nota_credito)}</p>}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        ) : !turno ? (
          /* ── Sin turno: CTA abrir ── */
          <button
            onClick={() => navigate('/apertura')}
            style={{
              width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10,
              padding: '18px 0', borderRadius: 22, border: 'none', cursor: 'pointer',
              background: 'linear-gradient(135deg, oklch(35% 0.05 155), oklch(30% 0.06 155))',
              color: '#fff', fontSize: 16, fontWeight: 700, fontFamily: 'inherit',
              marginBottom: 12,
            }}
          >
            <Coffee size={22} /> Abrir nuevo turno <ChevronRight size={20} />
          </button>
        ) : null}

        {/* ── "Aún falta" strip ─────────────────────────────────────────── */}
        {turno && tlData && tlData.currentIdx >= 0 && tlData.pasosTL.length - tlData.currentIdx > 1 && (
          <div style={{
            display: 'flex', alignItems: 'center', gap: 8,
            padding: '10px 14px', marginBottom: 12,
            background: '#fff', border: '1px solid oklch(94% 0.008 75)', borderRadius: 14,
          }}>
            <span style={{ fontSize: 9.5, fontWeight: 700, letterSpacing: '.08em', textTransform: 'uppercase', color: 'oklch(58% 0.01 60)', flexShrink: 0 }}>
              Aún falta
            </span>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, flex: 1, overflow: 'hidden' }}>
              {tlData.pasosTL.slice(tlData.currentIdx + 1).map((p, i) => (
                <span key={p.id} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  {i > 0 && <span style={{ color: 'oklch(85% 0.008 75)', fontSize: 11 }}>→</span>}
                  <span style={{ padding: '3px 9px', borderRadius: 999, background: 'oklch(96% 0.008 75)', fontSize: 11, fontWeight: 600, color: 'oklch(40% 0.01 60)', whiteSpace: 'nowrap' }}>
                    {p.label}
                  </span>
                </span>
              ))}
            </div>
          </div>
        )}

        {/* ── CTA del paso actual ───────────────────────────────────────── */}
        {nextStep && turno && (
          <button
            onClick={nextStep.accion}
            style={{
              width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              padding: '16px 18px', marginBottom: 12, border: 'none', borderRadius: 18, cursor: 'pointer',
              background: 'linear-gradient(135deg, oklch(68% 0.15 65), oklch(60% 0.16 50))',
              color: '#fff', fontFamily: 'inherit',
              boxShadow: '0 10px 24px -14px oklch(60% 0.16 50 / 0.6)',
            }}
          >
            <div style={{ textAlign: 'left' }}>
              <p style={{ margin: 0, fontSize: 9.5, fontWeight: 700, letterSpacing: '.12em', textTransform: 'uppercase', opacity: 0.85 }}>
                Siguiente · Paso {pasoActualIdx + 1}
              </p>
              <p style={{ margin: '3px 0 0', fontSize: 16, fontWeight: 700, letterSpacing: '-0.01em' }}>
                {nextStep.label}
              </p>
            </div>
            <div style={{ width: 34, height: 34, borderRadius: 999, background: 'rgba(255,255,255,.18)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
              <ChevronRight size={16} />
            </div>
          </button>
        )}

        {/* ── Cierre disponible ─────────────────────────────────────────── */}
        {turno?.tiene_conteo_cierre && turno.estado === 'abierto' && (
          <button
            onClick={() => navigate('/cierre')}
            style={{
              width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
              padding: '14px 18px', marginBottom: 12, border: 'none', borderRadius: 18, cursor: 'pointer',
              background: 'oklch(35% 0.05 155)', color: '#fff', fontSize: 14, fontWeight: 700, fontFamily: 'inherit',
            }}
          >
            <Lock size={16} /> Cerrar turno <ChevronRight size={18} />
          </button>
        )}

        {/* ── Cuadre de llegada ─────────────────────────────────────────── */}
        {turno && turno.estado === 'abierto' && (
          sinEntrega ? (
            <button
              onClick={() => navigate('/entrega')}
              style={{
                width: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4,
                padding: '14px 18px', marginBottom: 12, border: 'none', borderRadius: 18, cursor: 'pointer',
                background: 'linear-gradient(135deg, oklch(68% 0.15 65), oklch(60% 0.16 50))',
                color: '#fff', fontFamily: 'inherit',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 14, fontWeight: 700 }}>
                <UserCheck size={18} /> Cuadre de llegada
              </div>
              <span style={{ fontSize: 11, opacity: 0.75 }}>Registra tu entrada al turno</span>
            </button>
          ) : conDiff ? (
            <button
              onClick={() => navigate('/entrega')}
              style={{
                width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
                padding: '12px 18px', marginBottom: 12, borderRadius: 18, cursor: 'pointer',
                border: '2px solid oklch(80% 0.12 30)', background: 'oklch(98% 0.02 30)',
                color: '#8a3325', fontSize: 13, fontWeight: 600, fontFamily: 'inherit',
              }}
            >
              <AlertTriangle size={14} /> Último cuadre con diferencia — nuevo cuadre
            </button>
          ) : hace4h ? (
            <button
              onClick={() => navigate('/entrega')}
              style={{
                width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
                padding: '12px 18px', marginBottom: 12, borderRadius: 18, cursor: 'pointer',
                border: '2px solid oklch(88% 0.09 75)', background: 'oklch(98% 0.03 75)',
                color: 'oklch(38% 0.12 65)', fontSize: 13, fontWeight: 600, fontFamily: 'inherit',
              }}
            >
              <UserCheck size={15} /> Nuevo cuadre de llegada
            </button>
          ) : (
            <button
              onClick={() => navigate('/entrega')}
              style={{
                width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
                padding: '12px 18px', marginBottom: 12, borderRadius: 18, cursor: 'pointer',
                border: '2px solid oklch(88% 0.06 155)', background: 'oklch(97% 0.018 155)',
                color: 'oklch(35% 0.05 155)', fontSize: 13, fontWeight: 600, fontFamily: 'inherit',
              }}
            >
              <UserCheck size={15} /> ✓ Cuadre realizado — registrar otro
            </button>
          )
        )}

        {/* ── Herramientas ─────────────────────────────────────────────── */}
        {turno && (
          <div style={{ marginBottom: 12 }}>
            <p style={{ margin: '0 4px 8px', fontSize: 10, fontWeight: 700, letterSpacing: '.1em', textTransform: 'uppercase', color: 'oklch(58% 0.01 60)' }}>
              Herramientas
            </p>
            {/* 2×2 grid */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
              {TOOLS_MAIN.map(({ label, sublabel, icon: Icon, path, tint }) => (
                <button
                  key={path}
                  onClick={() => navigate(path)}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 10,
                    padding: '12px 12px', borderRadius: 16,
                    background: '#fff', border: '1px solid oklch(94% 0.008 75)',
                    cursor: 'pointer', fontFamily: 'inherit', textAlign: 'left',
                  }}
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

            {/* Extra tools (expanded) */}
            {showMasTools && (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, marginTop: 8 }}>
                {TOOLS_MORE.map(({ label, icon: Icon, path, tint }) => (
                  <button
                    key={path}
                    onClick={() => navigate(path)}
                    style={{
                      display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6,
                      padding: '12px 8px', borderRadius: 16,
                      background: '#fff', border: '1px solid oklch(94% 0.008 75)',
                      cursor: 'pointer', fontFamily: 'inherit',
                    }}
                  >
                    <div style={{
                      width: 32, height: 32, borderRadius: 10,
                      background: `linear-gradient(135deg, color-mix(in oklch, ${tint} 18%, #fff), color-mix(in oklch, ${tint} 8%, #fff))`,
                      border: `1px solid color-mix(in oklch, ${tint} 25%, #fff)`,
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                    }}>
                      <Icon size={15} style={{ color: tint }} />
                    </div>
                    <span style={{ fontSize: 11, fontWeight: 600, color: 'oklch(35% 0.01 60)', textAlign: 'center', lineHeight: 1.2 }}>{label}</span>
                  </button>
                ))}
              </div>
            )}

            {/* Dashed "más" button */}
            <button
              onClick={() => setShowMasTools(v => !v)}
              style={{
                width: '100%', display: 'flex', alignItems: 'center', gap: 10,
                padding: '11px 14px', marginTop: 8,
                background: 'oklch(95% 0.012 75)', border: '1px dashed oklch(85% 0.012 75)',
                borderRadius: 14, cursor: 'pointer', fontFamily: 'inherit',
              }}
            >
              <LayoutGrid size={14} style={{ color: 'oklch(58% 0.01 60)' }} />
              <span style={{ flex: 1, textAlign: 'left', fontSize: 12, fontWeight: 700, color: 'oklch(40% 0.01 60)' }}>
                {showMasTools ? 'Menos herramientas' : `${TOOLS_MORE.length} herramientas más`}
              </span>
              {showMasTools
                ? <ChevronUp size={14} style={{ color: 'oklch(58% 0.01 60)' }} />
                : <ChevronRight size={14} style={{ color: 'oklch(58% 0.01 60)' }} />}
            </button>
          </div>
        )}

        {/* ── Stock crítico ─────────────────────────────────────────────── */}
        {alertas.length > 0 && (
          <div style={{ background: '#fff', border: '1px solid oklch(90% 0.05 30)', borderRadius: 18, overflow: 'hidden', marginBottom: 12 }}>
            {/* Header */}
            <div style={{
              display: 'flex', alignItems: 'center', gap: 10,
              padding: '11px 14px 10px',
              background: 'linear-gradient(180deg, oklch(98% 0.02 30), oklch(96% 0.03 30))',
              borderBottom: '1px solid oklch(94% 0.04 30)',
            }}>
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
                onClick={() => navigate('/pedido')}
                style={{ display: 'flex', alignItems: 'center', gap: 3, padding: '5px 10px', borderRadius: 10, background: '#c64a3a', color: '#fff', border: 'none', fontFamily: 'inherit', fontSize: 11, fontWeight: 700, cursor: 'pointer', flexShrink: 0 }}
              >
                Pedir <ChevronRight size={11} />
              </button>
            </div>
            {/* Agotados */}
            {agotados.length > 0 && (
              <div style={{ background: 'oklch(98% 0.018 30)', padding: '8px 14px 9px' }}>
                <p style={{ margin: '0 0 4px', fontSize: 9, fontWeight: 700, letterSpacing: '.1em', textTransform: 'uppercase', color: '#c64a3a' }}>Agotados</p>
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
            {/* Bajos */}
            {bajos.length > 0 && (
              <div style={{ padding: '8px 14px 10px', borderTop: agotados.length > 0 ? '1px solid oklch(96% 0.018 30)' : 'none' }}>
                <p style={{ margin: '0 0 4px', fontSize: 9, fontWeight: 700, letterSpacing: '.1em', textTransform: 'uppercase', color: 'oklch(50% 0.14 75)' }}>Por agotarse</p>
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

        {/* ── Limpieza ──────────────────────────────────────────────────── */}
        <button
          onClick={toggleLimpieza}
          style={{
            width: '100%', display: 'flex', alignItems: 'center', gap: 12,
            padding: '12px 14px', marginBottom: 12, borderRadius: 16, cursor: 'pointer', fontFamily: 'inherit', textAlign: 'left',
            background: limpiezaDiaria ? 'oklch(96% 0.018 155)' : '#fff',
            border: `1px solid ${limpiezaDiaria ? 'oklch(78% 0.10 155)' : 'oklch(94% 0.008 75)'}`,
            transition: 'all .2s',
          }}
        >
          <div style={{
            width: 30, height: 30, borderRadius: 10, flexShrink: 0,
            background: limpiezaDiaria ? 'oklch(88% 0.06 155)' : 'oklch(96% 0.04 320)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <Sparkles size={14} style={{ color: limpiezaDiaria ? 'oklch(38% 0.10 155)' : 'oklch(55% 0.15 320)' }} />
          </div>
          <span style={{ flex: 1, fontSize: 13, fontWeight: 600, color: limpiezaDiaria ? 'oklch(30% 0.06 155)' : 'oklch(40% 0.01 60)' }}>
            Limpieza diaria
          </span>
          <span style={{ fontSize: 11, color: limpiezaDiaria ? 'oklch(45% 0.10 155)' : 'oklch(58% 0.01 60)', fontWeight: 500 }}>
            {limpiezaDiaria ? 'Hecha' : 'Pendiente'}
          </span>
          {/* Pill toggle */}
          <div style={{
            width: 36, height: 20, borderRadius: 999, position: 'relative', flexShrink: 0,
            background: limpiezaDiaria ? 'oklch(48% 0.14 155)' : 'oklch(88% 0.008 75)',
            transition: 'background .2s',
          }}>
            <span style={{
              position: 'absolute', top: 3, borderRadius: 999,
              width: 14, height: 14, background: '#fff',
              boxShadow: '0 1px 3px rgba(0,0,0,.2)',
              left: limpiezaDiaria ? 19 : 3,
              transition: 'left .2s',
            }} />
          </div>
        </button>

        {/* ── Movimientos del turno ─────────────────────────────────────── */}
        {turno && movimientos.length > 0 && (
          <div style={{ background: '#fff', border: '1px solid oklch(94% 0.008 75)', borderRadius: 18, overflow: 'hidden', marginBottom: 12 }}>
            <button
              onClick={() => setShowMovimientos(v => !v)}
              style={{ width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 14px', background: 'transparent', border: 'none', cursor: 'pointer', fontFamily: 'inherit' }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <TrendingUp size={13} style={{ color: 'oklch(65% 0.01 60)' }} />
                <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: '.08em', textTransform: 'uppercase', color: 'oklch(40% 0.01 60)' }}>Movimientos</span>
                <span style={{ fontSize: 10, fontWeight: 700, padding: '2px 7px', borderRadius: 999, background: 'oklch(94% 0.008 75)', color: 'oklch(40% 0.01 60)' }}>
                  {movimientos.length}
                </span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ fontSize: 11, fontVariantNumeric: 'tabular-nums', color: 'oklch(58% 0.01 60)' }}>
                  {movimientos.filter(m => m.tipo === 'ingreso').length > 0 && (
                    <><TrendingUp size={10} style={{ display: 'inline', color: 'oklch(52% 0.18 145)' }} /> {movimientos.filter(m => m.tipo === 'ingreso').length} </>
                  )}
                  {movimientos.filter(m => m.tipo === 'egreso').length > 0 && (
                    <><TrendingDown size={10} style={{ display: 'inline', color: 'oklch(58% 0.16 30)' }} /> {movimientos.filter(m => m.tipo === 'egreso').length}</>
                  )}
                </span>
                {showMovimientos
                  ? <ChevronUp size={14} style={{ color: 'oklch(65% 0.01 60)' }} />
                  : <ChevronDown size={14} style={{ color: 'oklch(65% 0.01 60)' }} />}
              </div>
            </button>
            {showMovimientos && (
              <div style={{ borderTop: '1px solid oklch(96% 0.006 75)' }}>
                {movimientos.map(m => (
                  <div key={m.id} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '12px 14px', borderBottom: '1px solid oklch(97% 0.004 75)' }}>
                    {m.imagen_url ? (
                      <img src={m.imagen_url} alt="" style={{ width: 40, height: 40, borderRadius: 12, objectFit: 'cover', flexShrink: 0, border: '1px solid oklch(92% 0.008 75)' }} />
                    ) : (
                      <div style={{ width: 40, height: 40, borderRadius: 12, background: 'oklch(95% 0.008 75)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                        <ImageIcon size={14} style={{ color: 'oklch(65% 0.01 60)' }} />
                      </div>
                    )}
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <p style={{ margin: 0, fontSize: 13, fontWeight: 600, color: 'oklch(28% 0.01 60)' }}>{m.concepto}</p>
                      <p style={{ margin: '2px 0 0', fontSize: 11, color: 'oklch(58% 0.01 60)' }}>
                        {parseUTC(m.fecha).toLocaleString('es-CO', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })}
                      </p>
                    </div>
                    <span style={{ fontSize: 13, fontWeight: 700, fontVariantNumeric: 'tabular-nums', flexShrink: 0, color: m.tipo === 'ingreso' ? 'oklch(45% 0.18 145)' : 'oklch(50% 0.18 30)' }}>
                      {m.tipo === 'ingreso' ? '+' : '−'}{fmt(m.valor)}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

      </div>{/* /scroll */}

      {/* ── Modal: pastelería por impulsar ───────────────────────────────── */}
      {showImpulso && impulso.length > 0 && (
        <div
          style={{ position: 'fixed', inset: 0, zIndex: 50, display: 'flex', alignItems: 'flex-end', justifyContent: 'center', background: 'rgba(0,0,0,.6)' }}
          onClick={() => setShowImpulso(false)}
        >
          <div
            style={{ background: '#fff', width: '100%', maxWidth: 448, borderRadius: '24px 24px 0 0', overflow: 'hidden', boxShadow: '0 -8px 40px rgba(0,0,0,.2)' }}
            onClick={e => e.stopPropagation()}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '18px 20px 14px', background: 'linear-gradient(135deg, oklch(94% 0.04 65), oklch(97% 0.02 75))' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <div style={{ width: 40, height: 40, borderRadius: 14, background: 'oklch(72% 0.13 65)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <Cake size={20} style={{ color: '#fff' }} />
                </div>
                <div>
                  <p style={{ margin: 0, fontSize: 13, fontWeight: 700, color: 'oklch(28% 0.06 60)' }}>Pastelería por impulsar</p>
                  <p style={{ margin: '2px 0 0', fontSize: 11, color: 'oklch(50% 0.06 60)' }}>
                    {impulso.length} producto{impulso.length > 1 ? 's' : ''} · rotación 5 días
                  </p>
                </div>
              </div>
              <button onClick={() => setShowImpulso(false)} style={{ padding: 6, background: 'transparent', border: 'none', cursor: 'pointer', color: 'oklch(58% 0.01 60)' }}>
                <XIcon size={18} />
              </button>
            </div>
            <div style={{ maxHeight: 256, overflowY: 'auto' }}>
              {impulso.map(item => (
                <div key={item.lote_id} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '12px 20px', borderBottom: '1px solid oklch(96% 0.006 75)', background: item.urgente ? 'oklch(99% 0.01 30)' : 'transparent' }}>
                  <div style={{ width: 36, height: 36, borderRadius: 11, background: item.urgente ? 'oklch(94% 0.04 30)' : 'oklch(94% 0.06 75)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                    <Clock size={15} style={{ color: item.urgente ? '#c64a3a' : 'oklch(52% 0.15 65)' }} />
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <p style={{ margin: 0, fontSize: 13, fontWeight: 600, color: 'oklch(28% 0.01 60)' }}>{item.producto_nombre}</p>
                    <p style={{ margin: '2px 0 0', fontSize: 11, color: 'oklch(55% 0.01 60)' }}>
                      {item.cantidad_restante} {item.cantidad_restante === 1 ? 'unidad' : 'unidades'} disponibles
                    </p>
                  </div>
                  <div style={{ textAlign: 'right', flexShrink: 0 }}>
                    <span style={{ fontSize: 11, fontWeight: 700, padding: '3px 9px', borderRadius: 999, background: item.urgente ? 'oklch(94% 0.04 30)' : 'oklch(94% 0.06 75)', color: item.urgente ? '#c64a3a' : 'oklch(40% 0.14 65)' }}>
                      {item.dias_en_inventario}d
                    </span>
                    {item.urgente && <p style={{ margin: '3px 0 0', fontSize: 10, fontWeight: 700, color: '#c64a3a' }}>¡Último día!</p>}
                  </div>
                </div>
              ))}
            </div>
            <div style={{ padding: '14px 20px 28px', background: 'oklch(98% 0.006 75)' }}>
              <p style={{ margin: '0 0 12px', fontSize: 11, color: 'oklch(58% 0.01 60)', textAlign: 'center' }}>
                💡 Ofrécelos activamente — llevan {Math.min(...impulso.map(i => i.dias_en_inventario))}–{Math.max(...impulso.map(i => i.dias_en_inventario))} días en inventario
              </p>
              <button
                onClick={() => setShowImpulso(false)}
                style={{ width: '100%', padding: '14px 0', borderRadius: 18, border: 'none', background: 'linear-gradient(135deg, oklch(68% 0.15 65), oklch(60% 0.16 50))', color: '#fff', fontSize: 14, fontWeight: 700, cursor: 'pointer', fontFamily: 'inherit' }}
              >
                ¡Entendido, a vender! 🍰
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Navegación inferior ──────────────────────────────────────────── */}
      <BaristaBottomNav alertaBadge={alertas.length > 0 ? alertas.length : undefined} />

    </div>
  )
}
