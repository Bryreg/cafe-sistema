import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useTurno } from '../contexts/TurnoContext'
import api from '../api/client'
import {
  Coffee, LogOut, DollarSign, Package, Cake, Trash2,
  Banknote, ShoppingCart, Coins, CheckCircle2, Circle,
  AlertTriangle, ChevronRight, Lock, TrendingUp, TrendingDown,
  Plus, ClipboardList, UserCheck, ChevronDown, ChevronUp, Sparkles,
  Upload, ImageIcon, X as XIcon,
} from 'lucide-react'

function parseUTC(s: string): Date {
  const t = s.replace(' ', 'T').replace(/(\.\d{3})\d+/, '$1').replace('+00:00', 'Z')
  return new Date(t.endsWith('Z') ? t : t + 'Z')
}

interface AlertaStock {
  producto_id: number; producto: string; unidad: string
  stock_actual: number; stock_minimo: number; cantidad_sugerida: number
  nivel: 'agotado' | 'bajo'
}
interface ItemPasteleria {
  id: number; producto_nombre: string; cantidad: number
  fecha_frescura: string; fecha_registro: string
  dias_en_stock: number; alerta_rotacion: boolean
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

interface Movimiento {
  id: number; tipo: string; concepto: string; valor: number
  fecha: string; imagen_url: string | null
}

const fmt = (v: number) => `$${v.toLocaleString('es-CO')}`

function MovimientoCaja({ turnoId, onClose }: { turnoId: number; onClose: () => void }) {
  const { refresh } = useTurno()
  const [tipo, setTipo] = useState<'ingreso' | 'egreso'>('ingreso')
  const [concepto, setConcepto] = useState('')
  const [valor, setValor] = useState('')
  const [archivo, setArchivo] = useState<File | null>(null)
  const [preview, setPreview] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  const onFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    if (!f) return
    setArchivo(f)
    setPreview(URL.createObjectURL(f))
  }

  const guardar = async () => {
    setError(''); setLoading(true)
    try {
      const form = new FormData()
      form.append('tipo', tipo)
      form.append('concepto', concepto)
      form.append('valor', valor)
      if (archivo) form.append('imagen', archivo)
      await api.post(`/caja/${turnoId}/movimiento`, form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      setConcepto(''); setValor(''); setArchivo(null); setPreview(null)
      await refresh()
      onClose()
    } catch (e: any) { setError(e.response?.data?.detail || 'Error') }
    finally { setLoading(false) }
  }

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-end justify-center p-0">
      <div className="bg-white w-full max-w-md rounded-t-3xl p-6 space-y-4">
        <div className="flex items-center justify-between">
          <p className="text-base font-bold text-warm-700">Movimiento de caja</p>
          <button onClick={onClose} className="text-warm-400 hover:text-warm-600 text-xl">✕</button>
        </div>
        {error && <p className="text-sm text-red-600">{error}</p>}
        <div className="flex gap-2">
          {(['ingreso', 'egreso'] as const).map(t => (
            <button key={t} onClick={() => setTipo(t)}
              className={`flex-1 py-2.5 rounded-xl text-sm font-semibold border-2 transition-colors ${
                tipo === t
                  ? t === 'ingreso' ? 'bg-green-100 border-green-400 text-green-700' : 'bg-red-100 border-red-400 text-red-700'
                  : 'border-warm-200 text-warm-400'
              }`}>
              {t === 'ingreso'
                ? <><TrendingUp size={14} className="inline mr-1" />Ingreso</>
                : <><TrendingDown size={14} className="inline mr-1" />Egreso</>}
            </button>
          ))}
        </div>
        <input value={concepto} onChange={e => setConcepto(e.target.value)} placeholder="Concepto"
          className="w-full border-2 border-warm-200 rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-forest transition-colors" />
        <input type="number" value={valor} onChange={e => setValor(e.target.value)} placeholder="Valor"
          className="w-full border-2 border-warm-200 rounded-xl px-4 py-3 text-lg font-bold focus:outline-none focus:border-forest transition-colors font-mono" />

        {/* Foto soporte */}
        <div>
          <p className="text-xs font-semibold text-warm-400 uppercase tracking-wide mb-2">Foto soporte (opcional)</p>
          <input ref={fileRef} type="file" accept="image/*" onChange={onFile} className="hidden" />
          {preview ? (
            <div className="relative">
              <img src={preview} alt="preview" className="w-full h-28 object-cover rounded-xl border-2 border-amber-300" />
              <button onClick={() => { setArchivo(null); setPreview(null) }}
                className="absolute top-2 right-2 bg-black/60 text-white rounded-full w-6 h-6 flex items-center justify-center text-xs">
                <XIcon size={12} />
              </button>
            </div>
          ) : (
            <button onClick={() => fileRef.current?.click()}
              className="w-full h-20 border-2 border-dashed border-warm-200 rounded-xl flex flex-col items-center justify-center gap-1.5 hover:border-amber-400 hover:bg-amber-50 transition-colors">
              <Upload size={16} className="text-warm-400" />
              <span className="text-xs text-warm-400">Toca para subir foto</span>
            </button>
          )}
        </div>

        <button onClick={guardar} disabled={!concepto || !valor || loading}
          className="w-full disabled:opacity-40 text-white font-bold py-3.5 rounded-xl text-sm transition-colors"
          style={{ background: 'oklch(35% 0.05 155)' }}>
          {loading ? 'Guardando...' : 'Registrar'}
        </button>
      </div>
    </div>
  )
}

interface Venta {
  id: number; venta_total: number; nota_credito: number
  vales: number; tarjetas: number; efectivo_calculado: number
  fecha_registro: string; nota: string | null
}

export default function Hub() {
  const { user, logout } = useAuth()
  const { turno, refresh } = useTurno()
  const navigate = useNavigate()
  const [alertas, setAlertas] = useState<AlertaStock[]>([])
  const [pasteleria, setPasteleria] = useState<ItemPasteleria[]>([])
  const [showMov, setShowMov] = useState(false)
  const [movimientos, setMovimientos] = useState<Movimiento[]>([])
  const [showMovimientos, setShowMovimientos] = useState(false)
  const [time, setTime] = useState(hora())
  const [ventas, setVentas] = useState<Venta[]>([])
  const [showVentas, setShowVentas] = useState(false)
  const [limpiezaDiaria, setLimpiezaDiaria] = useState(false)

  useEffect(() => {
    const t = setInterval(() => setTime(hora()), 30000)
    return () => clearInterval(t)
  }, [])

  useEffect(() => {
    if (!user?.tienda_id) return
    api.get(`/inventario/alertas/${user.tienda_id}`).then(r => setAlertas(r.data)).catch(() => null)
    api.get(`/pasteleria/tienda/${user.tienda_id}/activos`).then(r => setPasteleria(r.data)).catch(() => null)
    api.get(`/dashboard/${user.tienda_id}`).then(r => setLimpiezaDiaria(r.data.limpieza_check)).catch(() => null)
    refresh()
  }, [user?.tienda_id])

  useEffect(() => {
    if (turno?.id && turno.tiene_ventas) {
      api.get(`/ventas/turno/${turno.id}`).then(r => setVentas(r.data)).catch(() => null)
    } else {
      setVentas([])
    }
  }, [turno?.id, turno?.tiene_ventas])

  useEffect(() => {
    if (turno?.id) {
      api.get(`/caja/${turno.id}/movimientos`).then(r => setMovimientos(r.data)).catch(() => null)
    } else {
      setMovimientos([])
    }
  }, [turno?.id, showMov])

  const pasos = [
    { label: 'Apertura',        done: !!turno,                           accion: () => navigate('/apertura') },
    { label: 'Conteo apertura', done: !!turno?.tiene_conteo_apertura,    accion: () => navigate('/conteo-apertura') },
    { label: 'Ventas',          done: !!turno?.tiene_ventas,             accion: () => navigate('/ventas') },
    { label: 'Conteo cierre',   done: !!turno?.tiene_conteo_cierre,      accion: () => navigate('/conteo-cierre') },
    { label: 'Cierre',          done: turno?.estado === 'cerrado',       accion: () => navigate('/cierre') },
  ]
  const pasoActualIdx = pasos.findIndex(p => !p.done)
  const nextStep = pasoActualIdx >= 0 ? pasos[pasoActualIdx] : null

  const toggleLimpiezaDiaria = async () => {
    const nuevo = !limpiezaDiaria
    setLimpiezaDiaria(nuevo)
    try {
      await api.patch(`/dashboard/${user?.tienda_id}/checklist`, { campo: 'limpieza_check', valor: nuevo })
    } catch {
      setLimpiezaDiaria(!nuevo)
    }
  }

  interface Tile { label: string; icon: React.ReactNode; to: string; primary?: boolean; badge?: string }
  const tiles: Tile[] = [
    {
      label: 'Ventas', icon: <DollarSign size={20} />, to: '/ventas', primary: true,
    },
    {
      label: 'Inventario', icon: <Package size={20} />, to: '/inventario',
      badge: alertas.filter(a => a.nivel === 'agotado').length > 0
        ? String(alertas.filter(a => a.nivel === 'agotado').length)
        : alertas.length > 0 ? String(alertas.length) : undefined,
    },
    { label: 'Mermas',      icon: <Trash2 size={20} />,       to: '/mermas' },
    { label: 'Pastelería',  icon: <Cake size={20} />,         to: '/pasteleria' },
    { label: 'Consignación',icon: <Banknote size={20} />,     to: '/consignaciones' },
    { label: 'Pedido',      icon: <ShoppingCart size={20} />, to: '/pedido' },
    { label: 'Sencilla',    icon: <Coins size={20} />,        to: '/sencilla' },
    { label: 'Conteos',     icon: <ClipboardList size={20} />,to: '/conteos' },
    { label: 'Limpieza',    icon: <Sparkles size={20} />,     to: '/limpieza' },
  ]

  return (
    <div className="min-h-screen bg-warm-50 flex flex-col">
      {/* Header */}
      <header className="bg-white border-b border-warm-200 px-4 py-3 flex items-center justify-between sticky top-0 z-10">
        <div className="flex items-center gap-2">
          <Coffee size={18} className="text-forest" />
          <span className="font-bold text-warm-700 text-sm">Sistema Café</span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-warm-400">{time}</span>
          <span className="text-xs text-warm-500 font-medium">{user?.nombre}</span>
          <button onClick={() => { logout(); navigate('/login') }} className="text-warm-400 hover:text-red-500 transition-colors">
            <LogOut size={15} />
          </button>
        </div>
      </header>

      <div className="flex-1 p-4 max-w-lg mx-auto w-full space-y-4">

        {/* Saludo */}
        <div>
          <p className="text-lg font-bold text-warm-700">{saludo()}, {user?.nombre?.split(' ')[0]}</p>
          <p className="text-xs text-warm-400 capitalize">
            {new Date().toLocaleDateString('es-CO', { weekday: 'long', day: 'numeric', month: 'long' })}
          </p>
        </div>

        {/* ── Turn ribbon (when turno active) ── */}
        {turno && (
          <div className="rounded-2xl p-4 space-y-3 text-white"
            style={{ background: 'linear-gradient(135deg, oklch(32% 0.045 155), oklch(28% 0.05 155))' }}>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-green-400 inline-block" />
                <span className="text-xs font-semibold text-green-300 uppercase tracking-wide">Turno activo</span>
              </div>
              <span className="text-xs" style={{ color: 'oklch(72% 0.03 155)' }}>{time}</span>
            </div>

            {/* 5-segment progress bar */}
            <div className="flex gap-1">
              {pasos.map((p, i) => (
                <div key={i} className="flex-1 h-1 rounded-full transition-colors"
                  style={{
                    background: p.done
                      ? 'oklch(72% 0.13 155)'          // done: bright green
                      : i === pasoActualIdx
                      ? 'oklch(68% 0.14 65)'            // current: amber
                      : 'oklch(40% 0.04 155)',          // pending: dark green
                  }}
                />
              ))}
            </div>

            {/* Step labels */}
            <div className="flex gap-1">
              {pasos.map((p, i) => (
                <div key={i} className="flex-1 flex flex-col items-center gap-0.5">
                  {p.done
                    ? <CheckCircle2 size={12} className="text-green-400" />
                    : i === pasoActualIdx
                    ? <Circle size={12} className="text-amber-400" />
                    : <Circle size={12} style={{ color: 'oklch(45% 0.05 155)' }} />
                  }
                  <span className={`text-[9px] text-center leading-tight ${
                    p.done ? 'text-green-400' :
                    i === pasoActualIdx ? 'text-amber-400 font-bold' :
                    'opacity-50'
                  }`} style={{ color: p.done ? undefined : i === pasoActualIdx ? undefined : 'oklch(65% 0.03 155)' }}>
                    {p.label}
                  </span>
                </div>
              ))}
            </div>

            {/* Totals strip */}
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

            {/* Sales history toggle */}
            {ventas.length > 0 && (
              <div>
                <button onClick={() => setShowVentas(v => !v)}
                  className="w-full flex items-center justify-between px-1 py-1 text-xs transition-colors"
                  style={{ color: 'oklch(60% 0.05 155)' }}>
                  <span className="font-semibold uppercase tracking-wide">{ventas.length} registro{ventas.length > 1 ? 's' : ''} de venta</span>
                  {showVentas ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                </button>
                {showVentas && (
                  <div className="rounded-xl overflow-hidden divide-y mt-1"
                    style={{ background: 'oklch(26% 0.03 155)', borderColor: 'oklch(35% 0.04 155)' }}>
                    {ventas.map(v => (
                      <div key={v.id} className="flex items-center justify-between px-3 py-2">
                        <div>
                          <p className="text-xs" style={{ color: 'oklch(55% 0.05 155)' }}>
                            {parseUTC(v.fecha_registro).toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit' })}
                          </p>
                          <p className="text-sm font-bold font-mono text-white">{fmt(v.venta_total)}</p>
                          {v.nota && <p className="text-xs italic" style={{ color: 'oklch(55% 0.05 155)' }}>{v.nota}</p>}
                        </div>
                        <div className="text-right text-xs space-y-0.5">
                          <p className="text-green-400 font-semibold">Ef: {fmt(v.efectivo_calculado)}</p>
                          {v.tarjetas > 0 && <p className="text-blue-400">Tarj: {fmt(v.tarjetas)}</p>}
                          {v.nota_credito > 0 && <p className="text-red-400">NC: {fmt(v.nota_credito)}</p>}
                          {v.vales > 0 && <p className="text-amber-400">Vales: {fmt(v.vales)}</p>}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* ── Pastelería activa ── */}
        {pasteleria.length > 0 && (() => {
          const ahora = new Date()
          const conAlerta = pasteleria.filter(p => p.alerta_rotacion)
          return (
            <div className={`border rounded-2xl overflow-hidden ${conAlerta.length > 0 ? 'border-orange-200' : 'border-warm-200'}`}>
              <div className={`flex items-center justify-between px-4 pt-3 pb-2 ${conAlerta.length > 0 ? 'bg-orange-50' : 'bg-warm-50'}`}>
                <div className="flex items-center gap-2">
                  <Cake size={14} className={conAlerta.length > 0 ? 'text-orange-600' : 'text-warm-500'} />
                  <span className={`text-xs font-bold uppercase tracking-wide ${conAlerta.length > 0 ? 'text-orange-700' : 'text-warm-600'}`}>
                    Pastelería activa
                  </span>
                  {conAlerta.length > 0 && (
                    <span className="bg-orange-200 text-orange-800 text-[10px] font-bold px-1.5 py-0.5 rounded-full">
                      {conAlerta.length} por rotar
                    </span>
                  )}
                </div>
                <button onClick={() => navigate('/pasteleria')} className="text-xs text-forest font-semibold underline">
                  + Registrar
                </button>
              </div>
              <div className="divide-y divide-warm-100 bg-white">
                {pasteleria.map(p => {
                  const frescura = parseUTC(p.fecha_frescura)
                  const diffH = (frescura.getTime() - ahora.getTime()) / 3600000
                  const vencido = diffH < 0
                  const porVencer = !vencido && diffH < 2
                  return (
                    <div key={p.id} className={`px-4 py-3 ${p.alerta_rotacion ? 'bg-orange-50' : ''}`}>
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-semibold text-warm-700">{p.producto_nombre}</p>
                          <p className="text-xs text-warm-500">{p.cantidad} unidades · {p.dias_en_stock < 1 ? 'Hoy' : `${Math.floor(p.dias_en_stock)}d en stock`}</p>
                        </div>
                        <span className={`text-xs font-bold px-2 py-0.5 rounded-full shrink-0 ${
                          vencido ? 'bg-red-100 text-red-700' :
                          porVencer ? 'bg-orange-100 text-orange-700' :
                          'bg-green-100 text-green-700'
                        }`}>
                          {vencido ? 'VENCIDO' : porVencer ? `${Math.round(diffH * 60)}min` : diffH < 24 ? `${Math.round(diffH)}h` : 'Fresco'}
                        </span>
                      </div>
                      <button
                        onClick={async () => {
                          await api.patch(`/pasteleria/${p.id}/cerrar`, null, { params: { tienda_id: user?.tienda_id } })
                          setPasteleria(prev => prev.filter(x => x.id !== p.id))
                        }}
                        className="mt-2 text-xs text-warm-400 hover:text-red-500 transition-colors"
                      >
                        Marcar como terminado
                      </button>
                    </div>
                  )
                })}
              </div>
            </div>
          )
        })()}

        {/* ── Stock crítico ── */}
        {alertas.length > 0 && (() => {
          const agotados = alertas.filter(a => a.nivel === 'agotado')
          const bajos = alertas.filter(a => a.nivel === 'bajo')
          return (
            <div className="bg-white border border-red-200 rounded-2xl overflow-hidden">
              <div className="flex items-center justify-between px-4 pt-3 pb-2">
                <div className="flex items-center gap-2">
                  <AlertTriangle size={14} className="text-red-600" />
                  <span className="text-xs font-bold text-red-700 uppercase tracking-wide">Stock crítico</span>
                </div>
                <button onClick={() => navigate('/pedido')} className="text-xs text-red-600 font-semibold underline">
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
                        {a.stock_actual} {a.unidad}
                      </span>
                    </div>
                  ))}
                </div>
              )}
              {bajos.length > 0 && (
                <div className={`px-4 py-2 space-y-1.5 ${agotados.length > 0 ? 'border-t border-red-100' : ''}`}>
                  {agotados.length > 0 && <p className="text-[10px] font-bold text-amber-500 uppercase tracking-widest">Por agotarse</p>}
                  {bajos.map(a => (
                    <div key={a.producto_id} className="flex items-center justify-between">
                      <span className="text-sm font-medium text-warm-600">{a.producto}</span>
                      <span className="text-xs font-semibold text-amber-700 bg-amber-50 px-2 py-0.5 rounded-full border border-amber-200 font-mono">
                        {a.stock_actual}/{a.stock_minimo} {a.unidad}
                      </span>
                    </div>
                  ))}
                </div>
              )}
              <div className="px-4 pb-3 pt-1">
                <p className="text-xs text-warm-400">
                  {agotados.length > 0 ? `${agotados.length} agotado${agotados.length > 1 ? 's' : ''} · ` : ''}
                  {bajos.length > 0 ? `${bajos.length} bajo mínimo` : ''}
                </p>
              </div>
            </div>
          )
        })()}

        {/* ── No turno — open CTA ── */}
        {!turno && (
          <button onClick={() => navigate('/apertura')}
            className="w-full text-white font-bold py-5 rounded-2xl text-base flex items-center justify-center gap-3 transition-colors"
            style={{ background: 'oklch(35% 0.05 155)' }}>
            <Coffee size={22} /> Abrir nuevo turno
            <ChevronRight size={20} />
          </button>
        )}

        {/* ── Next step CTA (amber/attention) ── */}
        {nextStep && turno && (
          <button onClick={nextStep.accion}
            className="w-full text-white font-bold py-4 rounded-2xl text-sm flex items-center justify-center gap-3 transition-colors shadow-lg"
            style={{ background: 'oklch(68% 0.14 65)', boxShadow: '0 8px 24px oklch(68% 0.14 65 / 0.30)' }}>
            <span className="text-xs uppercase tracking-widest opacity-80">Continuar con paso {pasoActualIdx + 1}</span>
            <span className="font-bold">{nextStep.label}</span>
            <ChevronRight size={18} />
          </button>
        )}

        {/* ── Close turno if step 5 ready ── */}
        {turno?.tiene_conteo_cierre && turno.estado === 'abierto' && (
          <button onClick={() => navigate('/cierre')}
            className="w-full text-white font-bold py-4 rounded-2xl text-sm flex items-center justify-center gap-3 transition-colors"
            style={{ background: 'oklch(35% 0.05 155)' }}>
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
            <button onClick={() => navigate('/entrega')}
              className="w-full text-white font-bold py-4 rounded-2xl text-sm flex flex-col items-center gap-1 transition-colors"
              style={{ background: 'oklch(68% 0.14 65)' }}>
              <div className="flex items-center gap-2">
                <UserCheck size={18} /> Realizar cuadre de llegada
              </div>
              <span className="text-xs font-normal opacity-75">Registra tu entrada al turno</span>
            </button>
          )
          if (conDiff) return (
            <button onClick={() => navigate('/entrega')}
              className="w-full border-2 border-red-300 bg-red-50 text-red-700 font-semibold py-3 rounded-2xl text-sm flex items-center justify-center gap-2 transition-colors">
              <AlertTriangle size={15} /> Último cuadre con diferencia — nuevo cuadre
            </button>
          )
          if (hace4h) return (
            <button onClick={() => navigate('/entrega')}
              className="w-full border-2 border-amber-200 text-amber-700 bg-amber-50 hover:bg-amber-100 font-semibold py-3 rounded-2xl text-sm flex items-center justify-center gap-2 transition-colors">
              <UserCheck size={16} /> Nuevo cuadre de llegada
            </button>
          )
          return (
            <button onClick={() => navigate('/entrega')}
              className="w-full border-2 border-forest-100 text-forest font-semibold py-3 rounded-2xl text-sm flex items-center justify-center gap-2 transition-colors bg-forest-50 hover:bg-forest-100">
              <UserCheck size={16} /> ✓ Cuadre realizado — registrar otro
            </button>
          )
        })()}

        {/* ── Limpieza diaria ── */}
        <button
          onClick={toggleLimpiezaDiaria}
          className="w-full flex items-center justify-between px-4 py-3 rounded-2xl border-2 transition-all active:scale-[0.98]"
          style={{
            background: limpiezaDiaria ? 'oklch(95% 0.015 155)' : 'white',
            borderColor: limpiezaDiaria ? 'oklch(72% 0.13 155)' : 'oklch(92% 0.006 75)',
          }}
        >
          <div className="flex items-center gap-2.5">
            <Sparkles size={16} style={{ color: limpiezaDiaria ? 'oklch(48% 0.12 155)' : 'oklch(58% 0.01 60)' }} />
            <span className="text-sm font-semibold" style={{ color: limpiezaDiaria ? 'oklch(35% 0.05 155)' : 'oklch(40% 0.01 60)' }}>
              Limpieza diaria
            </span>
          </div>
          <div className="flex items-center gap-1.5">
            {limpiezaDiaria
              ? <><CheckCircle2 size={16} className="text-forest-500" /><span className="text-xs font-medium text-forest-500">Hecha</span></>
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
                <TrendingUp size={14} className="text-warm-500" />
                <span className="text-xs font-bold text-warm-600 uppercase tracking-wide">
                  Movimientos del turno
                </span>
                <span className="bg-warm-100 text-warm-600 text-[10px] font-bold px-1.5 py-0.5 rounded-full">
                  {movimientos.length}
                </span>
              </div>
              {showMovimientos ? <ChevronUp size={14} className="text-warm-400" /> : <ChevronDown size={14} className="text-warm-400" />}
            </button>
            {showMovimientos && (
              <div className="border-t border-warm-100 divide-y divide-warm-50">
                {movimientos.map(m => (
                  <div key={m.id} className="flex items-center gap-3 px-4 py-3">
                    {m.imagen_url ? (
                      <img src={m.imagen_url} alt="" className="w-10 h-10 rounded-lg object-cover border border-warm-200 shrink-0" />
                    ) : (
                      <div className="w-10 h-10 rounded-lg bg-warm-100 flex items-center justify-center shrink-0">
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

        {/* ── Quick movement ── */}
        {turno && !turno.tiene_conteo_cierre && (
          <button onClick={() => setShowMov(true)}
            className="w-full border-2 border-warm-200 text-warm-600 hover:border-warm-300 hover:bg-white font-semibold py-3 rounded-2xl text-sm flex items-center justify-center gap-2 transition-colors">
            <Plus size={16} /> Movimiento de caja
          </button>
        )}

        {/* ── Actions grid ── */}
        <div>
          <p className="text-xs font-semibold text-warm-400 uppercase tracking-wide mb-3">Acciones</p>
          <div className="grid grid-cols-4 gap-3">
            {tiles.map(({ label, icon, to, primary, badge }) => (
              <button key={to} onClick={() => navigate(to)}
                className={`relative flex flex-col items-center gap-2 p-3 rounded-2xl border transition-all active:scale-95 ${
                  primary
                    ? 'border-forest text-white'
                    : 'bg-white border-warm-200 hover:border-warm-300'
                }`}
                style={primary ? { background: 'oklch(35% 0.05 155)' } : undefined}>
                {badge && (
                  <span className="absolute -top-1.5 -right-1.5 bg-red-500 text-white text-[9px] font-bold w-4 h-4 rounded-full flex items-center justify-center">
                    {badge}
                  </span>
                )}
                <span className={primary ? 'text-white' : 'text-warm-500'}>{icon}</span>
                <span className={`text-[10px] font-semibold text-center leading-tight ${primary ? 'text-white' : 'text-warm-600'}`}>
                  {label}
                </span>
              </button>
            ))}
          </div>
        </div>

      </div>

      {showMov && turno && (
        <MovimientoCaja turnoId={turno.id} onClose={() => setShowMov(false)} />
      )}
    </div>
  )
}
