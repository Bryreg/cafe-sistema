import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useTurno } from '../contexts/TurnoContext'
import api from '../api/client'
import {
  Coffee, LogOut, CheckCircle2, Circle,
  AlertTriangle, ChevronRight, Lock, TrendingUp, TrendingDown,
  UserCheck, ChevronDown, ChevronUp, Sparkles,
  Cake, Clock, Bell, X as XIcon, ImageIcon, Banknote,
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
  const [pendienteConsig, setPendienteConsig] = useState<{ items: PendienteConsignacion[], total_pendiente: number } | null>(null)

  // Reloj
  useEffect(() => {
    const t = setInterval(() => setTime(hora()), 30000)
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

    // Popup pastelería — una vez por sesión
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

  // Movimientos — se actualiza cuando el turno cambia (incluyendo ingresos/egresos)
  useEffect(() => {
    if (turno?.id) {
      api.get(`/caja/${turno.id}/movimientos`).then(r => setMovimientos(r.data)).catch(() => null)
    } else {
      setMovimientos([])
    }
  }, [turno?.id, turno?.ingresos_movimientos, turno?.egresos_movimientos])

  // Pasos del turno
  const pasos = [
    { label: 'Apertura',        done: !!turno,                        accion: () => navigate('/apertura') },
    { label: 'Conteo apertura', done: !!turno?.tiene_conteo_apertura, accion: () => navigate('/conteo-apertura') },
    { label: 'Ventas',          done: !!turno?.tiene_ventas,          accion: () => navigate('/ventas') },
    { label: 'Conteo cierre',   done: !!turno?.tiene_conteo_cierre,   accion: () => navigate('/conteo-cierre') },
    { label: 'Cierre',          done: turno?.estado === 'cerrado',    accion: () => navigate('/cierre') },
  ]
  const pasoActualIdx = pasos.findIndex(p => !p.done)
  const nextStep = pasoActualIdx >= 0 ? pasos[pasoActualIdx] : null

  const toggleLimpieza = async () => {
    const nuevo = !limpiezaDiaria
    setLimpiezaDiaria(nuevo)
    try {
      await api.patch(`/dashboard/${user?.tienda_id}/checklist`, { campo: 'limpieza_check', valor: nuevo })
    } catch { setLimpiezaDiaria(!nuevo) }
  }

  const agotados = alertas.filter(a => a.nivel === 'agotado')
  const bajos    = alertas.filter(a => a.nivel === 'bajo')

  return (
    <div className="min-h-screen bg-warm-50 flex flex-col">

      {/* ── Header ── */}
      <header className="bg-white border-b border-warm-200 px-4 pb-3 header-safe flex items-center justify-between sticky top-0 z-10">
        <div className="flex items-center gap-2">
          <Coffee size={18} className="text-forest" />
          <span className="font-bold text-warm-700 text-sm">Sistema Café</span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-warm-400 tabular-nums">{time}</span>
          <span className="text-xs text-warm-500 font-medium">{user?.nombre?.split(' ')[0]}</span>
          {comunicados.length > 0 && (
            <div className="relative">
              <Bell size={16} className="text-amber-500" />
              <span className="absolute -top-1.5 -right-1.5 bg-red-500 text-white text-[8px] font-bold w-3.5 h-3.5 rounded-full flex items-center justify-center leading-none">
                {comunicados.length}
              </span>
            </div>
          )}
          <button
            onClick={() => { if (window.confirm('¿Cerrar sesión?')) { logout(); navigate('/login') } }}
            className="p-2 text-warm-400 hover:text-red-500 transition-colors"
          >
            <LogOut size={15} />
          </button>
        </div>
      </header>

      {/* ── Contenido ── */}
      <div className="flex-1 p-4 max-w-lg mx-auto w-full space-y-3 pb-nav">

        {/* Saludo */}
        <div className="pt-1">
          <p className="text-lg font-bold text-warm-700">
            {saludo()}, <span style={{ color: 'oklch(35% 0.05 155)' }}>{user?.nombre?.split(' ')[0]}</span>
          </p>
          <p className="text-xs text-warm-400 capitalize">
            {new Date().toLocaleDateString('es-CO', { weekday: 'long', day: 'numeric', month: 'long' })}
          </p>
        </div>

        {/* ── Comunicados del admin ── */}
        {comunicados.length > 0 && (
          <div className="space-y-2">
            {comunicados.map(c => (
              <div key={c.id} className={`rounded-2xl border p-4 flex gap-3 items-start ${
                c.urgente ? 'bg-red-50 border-red-200' : 'bg-amber-50 border-amber-200'
              }`}>
                <div className={`w-8 h-8 rounded-xl flex items-center justify-center shrink-0 ${
                  c.urgente ? 'bg-red-100' : 'bg-amber-100'
                }`}>
                  {c.urgente
                    ? <AlertTriangle size={15} className="text-red-600" />
                    : <Bell size={15} className="text-amber-600" />
                  }
                </div>
                <div className="flex-1 min-w-0">
                  {c.titulo && (
                    <p className={`text-xs font-bold uppercase tracking-wide mb-0.5 ${
                      c.urgente ? 'text-red-700' : 'text-amber-700'
                    }`}>{c.titulo}</p>
                  )}
                  <p className={`text-sm leading-snug ${c.urgente ? 'text-red-800' : 'text-amber-900'}`}>
                    {c.mensaje}
                  </p>
                </div>
                <button
                  onClick={async () => {
                    await api.post(`/comunicados/${c.id}/leer`)
                    setComunicados(prev => prev.filter(x => x.id !== c.id))
                  }}
                  className={`shrink-0 text-xs font-semibold px-2.5 py-1.5 rounded-lg transition-colors ${
                    c.urgente
                      ? 'bg-red-100 text-red-600 hover:bg-red-200'
                      : 'bg-amber-100 text-amber-700 hover:bg-amber-200'
                  }`}
                >
                  OK
                </button>
              </div>
            ))}
          </div>
        )}

        {/* ── Consignaciones pendientes ── */}
        {pendienteConsig && pendienteConsig.items.filter(i => i.pendiente > 0).length > 0 && (() => {
          const items = pendienteConsig.items.filter(i => i.pendiente > 0)
          return (
            <div className="rounded-2xl p-4 space-y-2.5" style={{
              background: 'oklch(97% 0.025 65)',
              border: '2px solid oklch(82% 0.10 65)',
            }}>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Banknote size={15} style={{ color: 'oklch(52% 0.18 65)' }} />
                  <span className="text-xs font-bold uppercase tracking-wide" style={{ color: 'oklch(38% 0.12 65)' }}>
                    {items.length === 1 ? '1 consignación pendiente' : `${items.length} consignaciones pendientes`}
                  </span>
                </div>
                <span className="text-xs font-bold font-mono px-2 py-0.5 rounded-full"
                  style={{ background: 'oklch(88% 0.09 65)', color: 'oklch(38% 0.14 65)' }}>
                  {fmt(pendienteConsig.total_pendiente)}
                </span>
              </div>
              <div className="space-y-1.5">
                {items.map(item => (
                  <div key={item.turno_id} className="flex items-center justify-between rounded-xl px-3 py-2"
                    style={{ background: 'oklch(93% 0.04 65)' }}>
                    <span className="text-sm capitalize" style={{ color: 'oklch(40% 0.08 65)' }}>
                      {parseUTC(item.fecha_cierre).toLocaleDateString('es-CO', { weekday: 'long', day: 'numeric', month: 'short' })}
                    </span>
                    <span className="text-sm font-bold font-mono" style={{ color: 'oklch(38% 0.14 65)' }}>
                      {fmt(item.pendiente)}
                    </span>
                  </div>
                ))}
              </div>
              <button
                onClick={() => navigate('/consignaciones')}
                className="w-full py-2.5 rounded-xl text-xs font-bold transition-colors"
                style={{ background: 'oklch(72% 0.14 65)', color: '#fff' }}
              >
                Registrar consignación →
              </button>
            </div>
          )
        })()}

        {/* ── Tarjeta de turno ── */}
        {turno ? (
          <div className="rounded-2xl p-4 space-y-3 text-white"
            style={{ background: 'linear-gradient(135deg, oklch(32% 0.045 155), oklch(28% 0.05 155))' }}>

            {/* Estado + hora */}
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-green-400" />
                <span className="text-xs font-semibold text-green-300 uppercase tracking-wide">Turno activo</span>
              </div>
              <span className="text-xs tabular-nums" style={{ color: 'oklch(72% 0.03 155)' }}>{time}</span>
            </div>

            {/* Progress bar */}
            <div className="flex gap-1">
              {pasos.map((p, i) => (
                <div key={i} className="flex-1 h-1 rounded-full transition-colors" style={{
                  background: p.done
                    ? 'oklch(72% 0.13 155)'
                    : i === pasoActualIdx
                      ? 'oklch(68% 0.14 65)'
                      : 'oklch(40% 0.04 155)',
                }} />
              ))}
            </div>

            {/* Step labels */}
            <div className="flex gap-1">
              {pasos.map((p, i) => (
                <div key={i} className="flex-1 flex flex-col items-center gap-0.5">
                  {p.done
                    ? <CheckCircle2 size={11} className="text-green-400" />
                    : i === pasoActualIdx
                      ? <Circle size={11} className="text-amber-400" />
                      : <Circle size={11} style={{ color: 'oklch(45% 0.05 155)' }} />
                  }
                  <span className={`text-[9px] text-center leading-tight font-medium ${
                    p.done ? 'text-green-400' : i === pasoActualIdx ? 'text-amber-400' : 'opacity-40'
                  }`} style={{ color: (p.done || i === pasoActualIdx) ? undefined : 'oklch(65% 0.03 155)' }}>
                    {p.label}
                  </span>
                </div>
              ))}
            </div>

            {/* Totales */}
            <div className="flex gap-2 pt-1">
              {[
                { label: 'Ventas',   value: turno.total_ventas   },
                { label: 'Efectivo', value: turno.total_efectivo },
                { label: 'Tarjeta',  value: turno.total_tarjeta  },
              ].map(({ label, value }) => (
                <div key={label} className="flex-1 text-center rounded-xl py-2"
                  style={{ background: 'oklch(26% 0.03 155)' }}>
                  <p className="text-[9px] uppercase tracking-wide" style={{ color: 'oklch(60% 0.05 155)' }}>{label}</p>
                  <p className="text-xs font-bold font-mono" style={{ color: 'oklch(85% 0.005 75)' }}>{fmt(value)}</p>
                </div>
              ))}
            </div>

            {/* Historial de ventas */}
            {ventas.length > 0 && (
              <div>
                <button
                  onClick={() => setShowVentas(v => !v)}
                  className="w-full flex items-center justify-between px-1 py-1 text-xs"
                  style={{ color: 'oklch(60% 0.05 155)' }}
                >
                  <span className="font-semibold uppercase tracking-wide">
                    {ventas.length} registro{ventas.length > 1 ? 's' : ''} de venta
                  </span>
                  {showVentas ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                </button>
                {showVentas && (
                  <div className="rounded-xl overflow-hidden divide-y mt-1"
                    style={{ background: 'oklch(26% 0.03 155)' }}>
                    {ventas.map(v => (
                      <div key={v.id} className="flex items-center justify-between px-3 py-2">
                        <div>
                          <p className="text-xs" style={{ color: 'oklch(55% 0.05 155)' }}>
                            {parseUTC(v.fecha_registro).toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit' })}
                          </p>
                          <p className="text-sm font-bold font-mono text-white">{fmt(v.venta_total)}</p>
                          {v.nota && (
                            <p className="text-xs italic" style={{ color: 'oklch(55% 0.05 155)' }}>{v.nota}</p>
                          )}
                        </div>
                        <div className="text-right text-xs space-y-0.5">
                          <p className="text-green-400 font-semibold">Ef: {fmt(v.efectivo_calculado)}</p>
                          {v.tarjetas > 0 && <p className="text-blue-400">Tarj: {fmt(v.tarjetas)}</p>}
                          {v.nota_credito > 0 && <p className="text-red-400">NC: {fmt(v.nota_credito)}</p>}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        ) : (
          /* ── Sin turno: CTA para abrir ── */
          <button
            onClick={() => navigate('/apertura')}
            className="w-full text-white font-bold py-5 rounded-2xl text-base flex items-center justify-center gap-3 transition-colors active:scale-[0.98]"
            style={{ background: 'oklch(35% 0.05 155)' }}
          >
            <Coffee size={22} /> Abrir nuevo turno <ChevronRight size={20} />
          </button>
        )}

        {/* ── CTA del paso actual ── */}
        {nextStep && turno && (
          <button
            onClick={nextStep.accion}
            className="w-full text-white font-bold py-4 rounded-2xl text-sm flex items-center justify-center gap-3 active:scale-[0.98] transition-all"
            style={{ background: 'oklch(64% 0.14 65)', boxShadow: '0 6px 20px oklch(64% 0.14 65 / 0.28)' }}
          >
            <span className="text-xs uppercase tracking-widest opacity-80 font-medium">Paso {pasoActualIdx + 1}</span>
            <span className="font-bold">{nextStep.label}</span>
            <ChevronRight size={18} />
          </button>
        )}

        {/* ── Cierre cuando el conteo esté listo ── */}
        {turno?.tiene_conteo_cierre && turno.estado === 'abierto' && (
          <button
            onClick={() => navigate('/cierre')}
            className="w-full text-white font-bold py-4 rounded-2xl text-sm flex items-center justify-center gap-3 active:scale-[0.98] transition-all"
            style={{ background: 'oklch(35% 0.05 155)' }}
          >
            <Lock size={16} /> Cerrar turno <ChevronRight size={18} />
          </button>
        )}

        {/* ── Cuadre de llegada ── */}
        {turno && turno.estado === 'abierto' && (() => {
          const sinEntrega = !turno.ultima_entrega_fecha
          const hace4h = turno.ultima_entrega_fecha
            ? (Date.now() - parseUTC(turno.ultima_entrega_fecha).getTime()) > 4 * 60 * 60 * 1000
            : false
          const conDiff = turno.ultima_entrega_diferencia_efectivo !== null
            && turno.ultima_entrega_diferencia_efectivo !== 0

          if (sinEntrega) return (
            <button
              onClick={() => navigate('/entrega')}
              className="w-full text-white font-bold py-4 rounded-2xl text-sm flex flex-col items-center gap-1 active:scale-[0.98] transition-all"
              style={{ background: 'oklch(64% 0.14 65)' }}
            >
              <div className="flex items-center gap-2">
                <UserCheck size={18} /> Cuadre de llegada
              </div>
              <span className="text-xs font-normal opacity-75">Registra tu entrada al turno</span>
            </button>
          )
          if (conDiff) return (
            <button
              onClick={() => navigate('/entrega')}
              className="w-full border-2 border-red-300 bg-red-50 text-red-700 font-semibold py-3 rounded-2xl text-sm flex items-center justify-center gap-2 active:scale-[0.98] transition-all"
            >
              <AlertTriangle size={15} /> Último cuadre con diferencia — nuevo cuadre
            </button>
          )
          if (hace4h) return (
            <button
              onClick={() => navigate('/entrega')}
              className="w-full border-2 border-amber-200 text-amber-700 bg-amber-50 font-semibold py-3 rounded-2xl text-sm flex items-center justify-center gap-2 active:scale-[0.98] transition-all"
            >
              <UserCheck size={16} /> Nuevo cuadre de llegada
            </button>
          )
          return (
            <button
              onClick={() => navigate('/entrega')}
              className="w-full border-2 border-forest-100 text-forest font-semibold py-3 rounded-2xl text-sm flex items-center justify-center gap-2 active:scale-[0.98] bg-forest-50 transition-all"
            >
              <UserCheck size={16} /> ✓ Cuadre realizado — registrar otro
            </button>
          )
        })()}

        {/* ── Stock crítico ── */}
        {alertas.length > 0 && (
          <div className="bg-white border border-red-200 rounded-2xl overflow-hidden">
            <div className="flex items-center justify-between px-4 pt-3 pb-2">
              <div className="flex items-center gap-2">
                <AlertTriangle size={14} className="text-red-500" />
                <span className="text-xs font-bold text-red-700 uppercase tracking-wide">Stock crítico</span>
              </div>
              <button onClick={() => navigate('/pedido')} className="text-xs text-red-600 font-semibold hover:underline">
                Pedir →
              </button>
            </div>
            {agotados.length > 0 && (
              <div className="bg-red-50 px-4 py-2 space-y-1.5">
                <p className="text-[10px] font-bold text-red-500 uppercase tracking-widest">Agotados</p>
                {agotados.map(a => (
                  <div key={a.producto_id} className="flex items-center justify-between">
                    <span className="text-sm font-semibold text-red-800">{a.producto}</span>
                    <span className="text-xs font-bold text-red-600 bg-red-100 px-2 py-0.5 rounded-full font-mono">
                      {Math.round(a.stock_actual)} {a.unidad}
                    </span>
                  </div>
                ))}
              </div>
            )}
            {bajos.length > 0 && (
              <div className={`px-4 py-2 space-y-1.5 ${agotados.length > 0 ? 'border-t border-red-100' : ''}`}>
                {agotados.length > 0 && (
                  <p className="text-[10px] font-bold text-amber-500 uppercase tracking-widest">Por agotarse</p>
                )}
                {bajos.map(a => (
                  <div key={a.producto_id} className="flex items-center justify-between">
                    <span className="text-sm font-medium text-warm-600">{a.producto}</span>
                    <span className="text-xs font-semibold text-amber-700 bg-amber-50 px-2 py-0.5 rounded-full border border-amber-200 font-mono">
                      {Math.round(a.stock_actual)}/{Math.round(a.stock_minimo)} {a.unidad}
                    </span>
                  </div>
                ))}
              </div>
            )}
            <div className="px-4 pb-2 pt-1">
              <p className="text-xs text-warm-400">
                {agotados.length > 0 ? `${agotados.length} agotado${agotados.length > 1 ? 's' : ''} · ` : ''}
                {bajos.length > 0 ? `${bajos.length} bajo mínimo` : ''}
              </p>
            </div>
          </div>
        )}

        {/* ── Limpieza ── */}
        <button
          onClick={toggleLimpieza}
          className="w-full flex items-center justify-between px-4 py-3 rounded-2xl border-2 transition-all active:scale-[0.98]"
          style={{
            background: limpiezaDiaria ? 'oklch(95% 0.015 155)' : 'white',
            borderColor: limpiezaDiaria ? 'oklch(72% 0.13 155)' : 'oklch(92% 0.006 75)',
          }}
        >
          <div className="flex items-center gap-2.5">
            <Sparkles size={16} style={{ color: limpiezaDiaria ? 'oklch(48% 0.12 155)' : 'oklch(58% 0.01 60)' }} />
            <span className="text-sm font-semibold"
              style={{ color: limpiezaDiaria ? 'oklch(35% 0.05 155)' : 'oklch(40% 0.01 60)' }}>
              Limpieza diaria
            </span>
          </div>
          <div className="flex items-center gap-1.5">
            {limpiezaDiaria
              ? <><CheckCircle2 size={16} className="text-forest" /><span className="text-xs font-medium text-forest">Hecha</span></>
              : <span className="text-xs text-warm-400">Marcar como hecha</span>
            }
          </div>
        </button>

        {/* ── Movimientos del turno ── */}
        {turno && movimientos.length > 0 && (
          <div className="bg-white border border-warm-200 rounded-2xl overflow-hidden">
            <button
              onClick={() => setShowMovimientos(v => !v)}
              className="w-full flex items-center justify-between px-4 py-3"
            >
              <div className="flex items-center gap-2">
                <TrendingUp size={14} className="text-warm-400" />
                <span className="text-xs font-bold text-warm-600 uppercase tracking-wide">Movimientos</span>
                <span className="bg-warm-100 text-warm-600 text-[10px] font-bold px-1.5 py-0.5 rounded-full">
                  {movimientos.length}
                </span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="text-xs text-warm-400 font-mono">
                  {movimientos.filter(m => m.tipo === 'ingreso').length > 0 && (
                    <><TrendingUp size={10} className="inline text-green-500" /> {movimientos.filter(m => m.tipo === 'ingreso').length}</>
                  )}
                  {' '}
                  {movimientos.filter(m => m.tipo === 'egreso').length > 0 && (
                    <><TrendingDown size={10} className="inline text-red-400" /> {movimientos.filter(m => m.tipo === 'egreso').length}</>
                  )}
                </span>
                {showMovimientos ? <ChevronUp size={14} className="text-warm-400" /> : <ChevronDown size={14} className="text-warm-400" />}
              </div>
            </button>
            {showMovimientos && (
              <div className="border-t border-warm-100 divide-y divide-warm-50">
                {movimientos.map(m => (
                  <div key={m.id} className="flex items-center gap-3 px-4 py-3">
                    {m.imagen_url ? (
                      <img src={m.imagen_url} alt="" className="w-10 h-10 rounded-xl object-cover border border-warm-200 shrink-0" />
                    ) : (
                      <div className="w-10 h-10 rounded-xl bg-warm-100 flex items-center justify-center shrink-0">
                        <ImageIcon size={14} className="text-warm-400" />
                      </div>
                    )}
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-semibold text-warm-700 truncate">{m.concepto}</p>
                      <p className="text-xs text-warm-400">
                        {parseUTC(m.fecha).toLocaleString('es-CO', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })}
                      </p>
                    </div>
                    <span className={`text-sm font-bold font-mono shrink-0 ${m.tipo === 'ingreso' ? 'text-green-600' : 'text-red-500'}`}>
                      {m.tipo === 'ingreso' ? '+' : '−'}{fmt(m.valor)}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

      </div>{/* /content */}

      {/* ── Modal: pastelería por impulsar ── */}
      {showImpulso && impulso.length > 0 && (
        <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/60"
          onClick={() => setShowImpulso(false)}>
          <div className="bg-white w-full max-w-md rounded-t-3xl overflow-hidden shadow-2xl"
            onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between px-5 pt-5 pb-3"
              style={{ background: 'linear-gradient(135deg, oklch(94% 0.04 65), oklch(97% 0.02 75))' }}>
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-2xl flex items-center justify-center"
                  style={{ background: 'oklch(72% 0.13 65)' }}>
                  <Cake size={20} className="text-white" />
                </div>
                <div>
                  <p className="text-sm font-bold text-warm-700">Pastelería por impulsar</p>
                  <p className="text-xs text-warm-500">
                    {impulso.length} producto{impulso.length > 1 ? 's' : ''} · rotación 5 días
                  </p>
                </div>
              </div>
              <button onClick={() => setShowImpulso(false)} className="p-1 text-warm-400 hover:text-warm-600">
                <XIcon size={18} />
              </button>
            </div>
            <div className="divide-y divide-warm-100 max-h-64 overflow-y-auto">
              {impulso.map(item => (
                <div key={item.lote_id} className={`flex items-center gap-3 px-5 py-3.5 ${item.urgente ? 'bg-red-50' : ''}`}>
                  <div className={`w-9 h-9 rounded-xl flex items-center justify-center shrink-0 ${
                    item.urgente ? 'bg-red-100' : 'bg-amber-100'
                  }`}>
                    <Clock size={15} className={item.urgente ? 'text-red-600' : 'text-amber-600'} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-semibold text-warm-700 truncate">{item.producto_nombre}</p>
                    <p className="text-xs text-warm-400">
                      {item.cantidad_restante} {item.cantidad_restante === 1 ? 'unidad' : 'unidades'} disponibles
                    </p>
                  </div>
                  <div className="text-right shrink-0">
                    <span className={`text-xs font-bold px-2.5 py-1 rounded-full ${
                      item.urgente ? 'bg-red-100 text-red-700' : 'bg-amber-100 text-amber-700'
                    }`}>
                      {item.dias_en_inventario}d
                    </span>
                    {item.urgente && <p className="text-[10px] text-red-500 font-semibold mt-0.5">¡Último día!</p>}
                  </div>
                </div>
              ))}
            </div>
            <div className="px-5 pt-3 pb-6 space-y-3" style={{ background: 'oklch(98% 0.006 75)' }}>
              <p className="text-xs text-warm-400 text-center">
                💡 Ofrécelos activamente — llevan {Math.min(...impulso.map(i => i.dias_en_inventario))}–{Math.max(...impulso.map(i => i.dias_en_inventario))} días en inventario
              </p>
              <button
                onClick={() => setShowImpulso(false)}
                className="w-full py-3.5 rounded-2xl text-sm font-bold text-white"
                style={{ background: 'oklch(58% 0.13 65)' }}
              >
                ¡Entendido, a vender! 🍰
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Navegación inferior ── */}
      <BaristaBottomNav alertaBadge={alertas.length > 0 ? alertas.length : undefined} />

    </div>
  )
}
