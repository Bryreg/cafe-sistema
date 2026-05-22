import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useTurno } from '../contexts/TurnoContext'
import api from '../api/client'
import {
  Coffee, LogOut,
  AlertTriangle, ChevronRight,
  TrendingUp, TrendingDown, UserCheck,
  Sparkles, Cake, Clock, Bell, X as XIcon, ImageIcon,
  Banknote, Trash2, Package, ShoppingCart, FileText,
  ClipboardList, ReceiptText, LayoutGrid, ChevronDown, ChevronUp,
  ClipboardCheck, Check,
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
const fmt = (v: number) => `$${v.toLocaleString('es-CO')}`
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

interface Paso { label: string; done: boolean; doneAt: string | null; accion: () => void }

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

  // Movimientos
  useEffect(() => {
    if (turno?.id) {
      api.get(`/caja/${turno.id}/movimientos`).then(r => setMovimientos(r.data)).catch(() => null)
    } else {
      setMovimientos([])
    }
  }, [turno?.id, turno?.ingresos_movimientos, turno?.egresos_movimientos])

  // ── Pasos del turno ──────────────────────────────────────────────────────
  const pasos: Paso[] = turno ? [
    { label: 'Apertura',        done: true,                          doneAt: fmtTime(parseUTC(turno.fecha_apertura)),                                                              accion: () => navigate('/apertura')       },
    { label: 'Conteo apertura', done: !!turno.tiene_conteo_apertura, doneAt: turno.ts_conteo_apertura ? fmtTime(parseUTC(turno.ts_conteo_apertura)) : null,  accion: () => navigate('/conteo-apertura') },
    { label: 'Conteo cierre',   done: !!turno.tiene_conteo_cierre,   doneAt: turno.ts_conteo_cierre ? fmtTime(parseUTC(turno.ts_conteo_cierre)) : null,      accion: () => navigate('/conteo-cierre')  },
    { label: 'Cierre',          done: turno.estado === 'cerrado',    doneAt: null,                                                                                                accion: () => navigate('/cierre')         },
  ] : []
  const currentIdx = pasos.findIndex(p => !p.done)
  const nextStep = currentIdx >= 0 ? pasos[currentIdx] : null

  // ── Elapsed time ─────────────────────────────────────────────────────────
  const elapsed = turno ? (() => {
    const start = parseUTC(turno.fecha_apertura)
    const mins = Math.max(0, Math.floor((new Date().getTime() - start.getTime()) / 60000))
    return { h: Math.floor(mins / 60), m: mins % 60, startTime: fmtTime(start) }
  })() : null

  const toggleLimpieza = async () => {
    const nuevo = !limpiezaDiaria
    setLimpiezaDiaria(nuevo)
    try {
      await api.patch(`/dashboard/${user?.tienda_id}/checklist`, { campo: 'limpieza_check', valor: nuevo })
    } catch { setLimpiezaDiaria(!nuevo) }
  }

  const agotados = alertas.filter(a => a.nivel === 'agotado')
  const bajos    = alertas.filter(a => a.nivel === 'bajo')
  const hayAlertas = alertas.length > 0
  const todoEnOrden = !hayAlertas && !nextStep && limpiezaDiaria && !!turno

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

        {/* ── Comunicados del admin ──────────────────────────────────────── */}
        {comunicados.length > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 12, paddingTop: 14 }}>
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

        {/* ── Consignaciones pendientes (compact) ───────────────────────── */}
        {pendienteConsig && (() => {
          const items = pendienteConsig.items.filter(i => i.pendiente > 0)
          if (items.length === 0) return null
          return (
            <div style={{ padding: '11px 14px', borderRadius: 16, marginBottom: 12, background: 'oklch(97% 0.025 65)', border: '2px solid oklch(82% 0.10 65)' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 9 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
                  <Banknote size={14} style={{ color: 'oklch(52% 0.18 65)' }} />
                  <span style={{ fontSize: 11.5, fontWeight: 700, color: 'oklch(38% 0.12 65)' }}>
                    {items.length} consignación{items.length > 1 ? 'es' : ''} pendiente{items.length > 1 ? 's' : ''}
                  </span>
                </div>
                <span style={{ fontSize: 11, fontWeight: 700, fontVariantNumeric: 'tabular-nums', padding: '3px 9px', borderRadius: 999, background: 'oklch(88% 0.09 65)', color: 'oklch(38% 0.14 65)' }}>
                  {fmt(pendienteConsig.total_pendiente)}
                </span>
              </div>
              <button onClick={() => navigate('/consignaciones')} style={{ width: '100%', padding: '9px 0', borderRadius: 12, border: 'none', background: 'oklch(72% 0.14 65)', color: '#fff', fontSize: 12, fontWeight: 700, cursor: 'pointer', fontFamily: 'inherit' }}>
                Registrar consignación →
              </button>
            </div>
          )
        })()}

        {/* ── Hero: turno con checklist ──────────────────────────────────── */}
        {turno && elapsed ? (
          <div style={{
            borderRadius: 26, overflow: 'hidden', marginBottom: 12, color: '#fff',
            background: 'linear-gradient(165deg, oklch(32% 0.045 155) 0%, oklch(26% 0.05 155) 60%, oklch(22% 0.04 155) 100%)',
            padding: '16px 18px 18px',
            boxShadow: '0 12px 32px -20px rgba(28,55,42,.6)',
          }}>
            {/* Top row: pill + step counter */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 14 }}>
              {/* Pill */}
              <div style={{
                display: 'inline-flex', alignItems: 'center', gap: 7,
                padding: '4px 11px 4px 9px', borderRadius: 999,
                background: 'oklch(40% 0.06 155)', border: '1px solid oklch(50% 0.08 155)',
              }}>
                <span style={{
                  width: 6, height: 6, borderRadius: 999, background: 'oklch(78% 0.18 145)',
                  boxShadow: '0 0 0 3px oklch(40% 0.10 145 / 0.5)', flexShrink: 0,
                }} />
                <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: '.06em', textTransform: 'uppercase', color: 'oklch(92% 0.05 145)' }}>
                  Turno {new Date().getHours() < 14 ? 'Mañana' : 'Tarde'}
                </span>
              </div>
              {/* Step counter */}
              <div style={{ textAlign: 'right' }}>
                <p style={{ margin: 0, fontSize: 10, fontWeight: 700, letterSpacing: '.06em', textTransform: 'uppercase', color: 'oklch(72% 0.05 155)' }}>
                  {pasos.filter(p => p.done).length}/{pasos.length} PASOS
                </p>
              </div>
            </div>

            {/* Elapsed time */}
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginBottom: 4 }}>
              <span style={{ fontSize: 34, fontWeight: 700, letterSpacing: '-0.03em', fontVariantNumeric: 'tabular-nums', color: '#fff' }}>
                {elapsed.h}h {elapsed.m.toString().padStart(2, '0')}m
              </span>
              <span style={{ fontSize: 12, color: 'oklch(72% 0.05 155)', fontWeight: 500 }}>en turno</span>
            </div>

            {/* Subtitle */}
            <p style={{ margin: '0 0 14px', fontSize: 11, color: 'oklch(65% 0.06 155)', fontWeight: 500 }}>
              Abriste a las {elapsed.startTime} · ahora son las {time}
            </p>

            {/* Vertical checklist */}
            <div style={{
              background: 'oklch(28% 0.04 155 / 0.55)',
              border: '1px solid oklch(38% 0.05 155)',
              borderRadius: 14,
              padding: '4px 12px',
            }}>
              {pasos.map((paso, idx) => {
                const isCurrent = idx === currentIdx
                const isDone = paso.done && !isCurrent
                const isPending = !paso.done && !isCurrent
                return (
                  <div
                    key={paso.label}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 12,
                      padding: '10px 0',
                      borderBottom: idx < pasos.length - 1 ? '1px solid oklch(36% 0.05 155 / 0.5)' : 'none',
                    }}
                  >
                    {/* Status dot */}
                    {isDone ? (
                      <div style={{
                        width: 20, height: 20, borderRadius: 999, flexShrink: 0,
                        background: 'oklch(72% 0.16 145)',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                      }}>
                        <Check size={11} strokeWidth={3.5} color="oklch(20% 0.04 155)" />
                      </div>
                    ) : isCurrent ? (
                      <div style={{
                        width: 20, height: 20, borderRadius: 999, flexShrink: 0,
                        background: '#d97757',
                        boxShadow: '0 0 0 4px oklch(60% 0.16 30 / 0.22)',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                      }}>
                        <span style={{ width: 5, height: 5, borderRadius: 999, background: '#fff', display: 'block' }} />
                      </div>
                    ) : (
                      <div style={{
                        width: 20, height: 20, borderRadius: 999, flexShrink: 0,
                        background: 'transparent',
                        border: '1.5px solid oklch(50% 0.05 155)',
                      }} />
                    )}

                    {/* Label */}
                    <span style={{
                      flex: 1,
                      fontSize: 13, fontWeight: isCurrent ? 700 : isDone ? 500 : 400,
                      color: isDone ? 'oklch(72% 0.16 145)' : isCurrent ? '#fff' : 'oklch(55% 0.04 155)',
                    }}>
                      {paso.label}
                    </span>

                    {/* Right status */}
                    {isDone && paso.doneAt ? (
                      <span style={{ fontSize: 11, fontVariantNumeric: 'tabular-nums', fontWeight: 600, color: 'oklch(65% 0.10 145)', flexShrink: 0 }}>
                        {paso.doneAt}
                      </span>
                    ) : isDone ? (
                      <span style={{ fontSize: 11, fontWeight: 600, color: 'oklch(65% 0.10 145)', flexShrink: 0 }}>
                        ✓
                      </span>
                    ) : isCurrent ? (
                      <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: '.06em', textTransform: 'uppercase', color: 'oklch(75% 0.15 65)', flexShrink: 0 }}>
                        Ahora
                      </span>
                    ) : (
                      <span style={{ fontSize: 10, fontWeight: 500, color: 'oklch(50% 0.04 155)', flexShrink: 0 }}>
                        Pendiente
                      </span>
                    )}
                  </div>
                )
              })}
            </div>
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
                Siguiente · Paso {currentIdx + 1}
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

        {/* ── Stock crítico (promoted) ──────────────────────────────────── */}
        {hayAlertas && !!turno && (
          <div style={{
            background: '#fff',
            border: '1.5px solid oklch(82% 0.10 30)',
            borderRadius: 18,
            overflow: 'hidden',
            marginBottom: 12,
            boxShadow: '0 6px 18px -12px oklch(60% 0.18 30 / 0.4)',
          }}>
            {/* Header */}
            <div style={{
              display: 'flex', alignItems: 'center', gap: 10,
              padding: '11px 14px 10px',
              background: 'linear-gradient(180deg, oklch(98% 0.02 30), oklch(96% 0.03 30))',
              borderBottom: '1px solid oklch(94% 0.04 30)',
            }}>
              <div style={{
                width: 28, height: 28, borderRadius: 10, flexShrink: 0,
                background: '#c64a3a',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
              }}>
                <AlertTriangle size={14} style={{ color: '#fff' }} />
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
            {/* Por agotarse */}
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

        {/* ── Todo en orden ─────────────────────────────────────────────── */}
        {todoEnOrden && (
          <div style={{
            display: 'flex', alignItems: 'center', gap: 12,
            padding: '14px 16px', borderRadius: 18, marginBottom: 12,
            background: 'linear-gradient(180deg, oklch(96% 0.025 145), oklch(94% 0.04 145))',
            border: '1.5px solid oklch(85% 0.10 145)',
          }}>
            <div style={{
              width: 36, height: 36, borderRadius: 12, flexShrink: 0,
              background: 'oklch(72% 0.16 145)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}>
              <Check size={18} strokeWidth={3} color="#fff" />
            </div>
            <div>
              <p style={{ margin: 0, fontSize: 13, fontWeight: 700, color: 'oklch(28% 0.08 145)' }}>Todo en orden</p>
              <p style={{ margin: '2px 0 0', fontSize: 11, color: 'oklch(45% 0.10 145)', fontWeight: 500 }}>
                Sin alertas · limpieza hecha · pasos al día
              </p>
            </div>
          </div>
        )}

        {/* ── Limpieza toggle ───────────────────────────────────────────── */}
        {!!turno && (
          <button
            onClick={toggleLimpieza}
            style={{
              width: '100%', display: 'flex', alignItems: 'center', gap: 12,
              padding: '13px 14px', marginBottom: 12, borderRadius: 16, cursor: 'pointer', fontFamily: 'inherit', textAlign: 'left',
              background: limpiezaDiaria ? 'oklch(96% 0.018 145)' : '#fff',
              border: `1.5px solid ${limpiezaDiaria ? 'oklch(85% 0.10 145)' : 'oklch(92% 0.008 75)'}`,
              transition: 'all .2s',
            }}
          >
            <div style={{
              width: 32, height: 32, borderRadius: 10, flexShrink: 0,
              background: limpiezaDiaria ? 'oklch(88% 0.08 145)' : 'oklch(95% 0.04 320)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}>
              {limpiezaDiaria
                ? <Check size={15} strokeWidth={3} style={{ color: 'oklch(38% 0.12 145)' }} />
                : <Sparkles size={15} style={{ color: 'oklch(55% 0.15 320)' }} />}
            </div>
            <div style={{ flex: 1 }}>
              <span style={{ fontSize: 13, fontWeight: 600, color: limpiezaDiaria ? 'oklch(30% 0.08 145)' : 'oklch(40% 0.01 60)', display: 'block' }}>
                Limpieza diaria
              </span>
              <span style={{ fontSize: 11, color: limpiezaDiaria ? 'oklch(45% 0.10 145)' : 'oklch(58% 0.01 60)', fontWeight: 500 }}>
                {limpiezaDiaria ? 'Completada — buen trabajo' : 'Pendiente de marcar'}
              </span>
            </div>
            {/* Toggle */}
            <div style={{
              width: 40, height: 22, borderRadius: 999, position: 'relative', flexShrink: 0,
              background: limpiezaDiaria ? 'oklch(60% 0.16 145)' : 'oklch(88% 0.008 75)',
              transition: 'background .18s',
            }}>
              <span style={{
                position: 'absolute', top: 2, borderRadius: 999,
                width: 18, height: 18, background: '#fff',
                boxShadow: '0 1px 3px rgba(0,0,0,.2)',
                left: limpiezaDiaria ? 18 : 2,
                transition: 'left .18s cubic-bezier(.2,.7,.3,1)',
              }} />
            </div>
          </button>
        )}

        {/* ── Herramientas ─────────────────────────────────────────────── */}
        {!!turno && (
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

            {/* Dashed "más" button with color dot preview */}
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
              {!showMasTools && (
                <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                  {TOOLS_MORE.slice(0, 5).map(t => (
                    <span key={t.path} style={{ width: 8, height: 8, borderRadius: 999, background: t.tint, flexShrink: 0 }} />
                  ))}
                </div>
              )}
              {showMasTools
                ? <ChevronUp size={14} style={{ color: 'oklch(58% 0.01 60)' }} />
                : <ChevronRight size={14} style={{ color: 'oklch(58% 0.01 60)' }} />}
            </button>
          </div>
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
