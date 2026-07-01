import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useTurno } from '../contexts/TurnoContext'
import api from '../api/client'
import {
  Users, CheckCircle, Circle, ChevronRight, AlertTriangle,
  Clock, X, Check, LogOut, Package, BarChart2, Sun, Sunset, Moon,
  Cake, Wallet, Receipt,
} from 'lucide-react'
import { dark } from '../constants/darkTheme'
import ContadorEfectivo from '../components/ContadorEfectivo'

const fmt = (v: number) => `$${v.toLocaleString('es-CO')}`

// fecha_apertura viene en UTC naïve → normalizamos a Z y calculamos transcurrido
function tiempoEnTurno(desde: string): string {
  try {
    const s = desde.replace(' ', 'T').replace(/(\.\d{3})\d+/, '$1')
    const t = new Date(s.endsWith('Z') ? s : s + 'Z').getTime()
    const min = Math.max(0, Math.floor((Date.now() - t) / 60000))
    const h = Math.floor(min / 60), m = min % 60
    return h > 0 ? `${h}h ${m}m` : `${m}m`
  } catch { return '—' }
}

type TipoTurno = 'apertura' | 'intermedio' | 'cierre'
interface Barista { id: number; nombre: string; rol: string; tienda_id: number | null }
interface ImpulsoItem { lote_id: number; producto_nombre: string; cantidad_restante: number; dias_en_inventario: number; urgente: boolean }

const TURNOS: { tipo: TipoTurno; label: string; desc: string; Icon: typeof Sun }[] = [
  { tipo: 'apertura',    label: 'Apertura',    desc: 'Primer turno del día',   Icon: Sun    },
  { tipo: 'intermedio',  label: 'Intermedio',  desc: 'Relevo de turno',         Icon: Sunset },
  { tipo: 'cierre',      label: 'Cierre',      desc: 'Último turno del día',    Icon: Moon   },
]

export default function GestionTurno() {
  const { tiendaId, resetKiosk, isKiosk } = useAuth()
  const { turno, loading, refresh } = useTurno()
  const navigate = useNavigate()

  const [baristas, setBaristas] = useState<Barista[]>([])
  const [selected, setSelected] = useState<number[]>([])
  const [tipoTurno, setTipoTurno] = useState<TipoTurno | null>(null)
  const [baseReal, setBaseReal] = useState('')
  const [cajaFuerte, setCajaFuerte] = useState('')
  const [esperadoInicio, setEsperadoInicio] = useState<number | null>(null)
  const [justificacion, setJustificacion] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [impulso, setImpulso] = useState<ImpulsoItem[]>([])

  // step: null = no form | 'tipo' = elegir tipo | 'baristas' = elegir baristas + confirmar
  const [step, setStep] = useState<null | 'tipo' | 'baristas'>(null)

  useEffect(() => {
    // /auth/baristas filtra por la sede del token y excluye el usuario kiosko
    api.get('/auth/baristas').then(({ data }) => {
      setBaristas(data)
    }).catch(() => {})
    if (tiendaId) {
      api.get(`/caja/efectivo-inicio/${tiendaId}`)
        .then(r => setEsperadoInicio(r.data.esperado))
        .catch(() => {})
      // Recordatorio de pastelería por impulsar (qué ofrecer según días en inventario)
      api.get(`/inventario/pasteleria-impulso/${tiendaId}`)
        .then(r => setImpulso(r.data))
        .catch(() => {})
    }
  }, [tiendaId])

  const toggleBarista = (id: number) =>
    setSelected(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id])

  const elegirTipo = (tipo: TipoTurno) => {
    setTipoTurno(tipo)
    setStep('baristas')
  }

  const cancelar = () => {
    setStep(null); setTipoTurno(null)
    setSelected([]); setBaseReal(''); setCajaFuerte(''); setJustificacion(''); setError('')
  }

  const abrirTurno = async () => {
    if (!tiendaId || !tipoTurno) return
    setSaving(true); setError('')
    try {
      const { data } = await api.post('/caja/abrir', {
        tienda_id: tiendaId,
        tipo_turno: tipoTurno,
        base_real: Number(baseReal) || 0,
        caja_fuerte: Number(cajaFuerte) || 0,
        justificacion_apertura: justificacion || null,
        barista_ids: selected.length > 0 ? selected : null,
      })
      cancelar()
      await refresh()
      // Llevar directo al paso requerido para no quedar trabado: si el turno ya quedó
      // operativo (p.ej. turno intermedio con el día ya contado) → POS; si no → conteo.
      navigate(data?.es_operativo ? '/pos' : '/conteo-apertura')
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Error al abrir turno')
    } finally {
      setSaving(false)
    }
  }

  if (loading) return (
    <div className="min-h-screen flex items-center justify-center" style={{ background: dark.bg }}>
      <p className="text-sm animate-pulse" style={{ color: dark.inkSubtle }}>Cargando...</p>
    </div>
  )

  return (
    <div className="min-h-screen flex flex-col pb-24" style={{ background: dark.bg }}>

      {/* Header */}
      <header className="px-4 pt-4 pb-3 flex items-center gap-2 w-full max-w-5xl mx-auto" style={{ background: dark.bg }}>
        <div className="flex-1">
          <p className="text-[10px] font-bold uppercase tracking-widest" style={{ color: dark.amber }}>
            Gestión de turno
          </p>
          <p className="text-[16px] font-bold" style={{ color: dark.ink }}>
            {turno
              ? `Turno ${turno.tipo_turno ?? 'activo'}`
              : step === 'tipo' ? 'Seleccionar turno'
              : step === 'baristas' ? `Turno ${tipoTurno} — baristas`
              : 'Sin turno activo'}
          </p>
        </div>
        {isKiosk && !step && (
          <button onClick={resetKiosk} className="p-2 rounded-lg opacity-40 hover:opacity-70 transition-opacity"
            style={{ color: dark.inkSubtle }}>
            <LogOut size={16} />
          </button>
        )}
        {step && (
          <button onClick={cancelar} className="p-2 rounded-lg" style={{ color: dark.inkSubtle }}>
            <X size={18} />
          </button>
        )}
      </header>

      <div className="flex-1 px-4 space-y-4 w-full max-w-5xl mx-auto pb-8">

        {/* ── CON TURNO ACTIVO ── */}
        {turno && !step && (
          <>
            {/* Gate: estado operativo del turno */}
            {turno.es_operativo ? (
              <button
                onClick={() => navigate('/pos')}
                className="w-full py-4 rounded-2xl font-bold text-[15px] text-white flex items-center justify-center gap-2"
                style={{ background: dark.green }}>
                <Check size={18} strokeWidth={2.5} /> Ir al POS
              </button>
            ) : (
              <div className="rounded-2xl p-4 space-y-2" style={{ background: dark.surface, border: `1px solid ${dark.amberDim}` }}>
                <p className="text-[12px] font-bold flex items-center gap-2" style={{ color: dark.amber }}>
                  <AlertTriangle size={13} /> POS bloqueado — completá para vender
                </p>
                {!turno.tiene_conteo_apertura && !turno.dia_tiene_conteo_apertura && (
                  <button onClick={() => navigate('/conteo-apertura')}
                    className="w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl text-left"
                    style={{ background: dark.surfaceAlt }}>
                    {turno.tiene_conteo_apertura
                      ? <Check size={15} style={{ color: dark.green }} />
                      : <Circle size={15} style={{ color: dark.amber }} />}
                    <span className="text-[13px] font-semibold" style={{ color: dark.ink }}>Conteo de apertura</span>
                  </button>
                )}
              </div>
            )}

            {/* Tarjetas de estado — 2 columnas en desktop para no apilar vertical */}
            <div className="lg:grid lg:grid-cols-2 lg:gap-4 lg:items-start space-y-4 lg:space-y-0">

            {/* Baristas en turno */}
            {turno.baristas.length > 0 && (
              <div className="rounded-2xl p-4" style={{ background: dark.surface, border: `1px solid ${dark.border}` }}>
                <p className="text-[10px] font-bold uppercase tracking-widest mb-2.5" style={{ color: dark.inkSubtle }}>
                  Baristas en turno
                </p>
                <div className="flex flex-wrap gap-2">
                  {turno.baristas.map(b => (
                    <span key={b} className="px-3 py-1 rounded-full text-xs font-semibold"
                      style={{ background: dark.amberTint, color: dark.amber }}>
                      {b}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Ventas del día + tiempo en turno */}
            <div className="rounded-2xl p-4" style={{ background: dark.surface, border: `1px solid ${dark.border}` }}>
              <div className="flex items-center justify-between mb-2">
                <p className="text-[10px] font-bold uppercase tracking-widest" style={{ color: dark.inkSubtle }}>
                  Ventas del día
                </p>
                <span className="flex items-center gap-1 text-[11px] font-semibold" style={{ color: dark.inkMuted }}>
                  <Clock size={11} /> {tiempoEnTurno(turno.fecha_apertura)} en turno
                </span>
              </div>
              <p className="text-[32px] font-bold font-mono leading-none" style={{ color: dark.ink, letterSpacing: '-1px' }}>
                {fmt(turno.total_ventas ?? 0)}
              </p>
              <div className="grid grid-cols-3 gap-2 mt-3 pt-3" style={{ borderTop: `1px solid ${dark.border}` }}>
                {[
                  { l: 'Efectivo', v: fmt(turno.total_efectivo ?? 0), Icon: Wallet },
                  { l: 'Tarjeta',  v: fmt(turno.total_tarjeta ?? 0), Icon: Receipt },
                  { l: 'En caja',  v: fmt(turno.efectivo_esperado_actual ?? 0), Icon: Wallet },
                ].map(row => (
                  <div key={row.l}>
                    <p className="text-[10px] flex items-center gap-1" style={{ color: dark.inkSubtle }}>
                      <row.Icon size={10} /> {row.l}
                    </p>
                    <p className="text-[13px] font-semibold font-mono mt-0.5" style={{ color: dark.ink }}>{row.v}</p>
                  </div>
                ))}
              </div>
            </div>

            {/* Pastelería por impulsar — recordatorio según días en inventario */}
            {impulso.length > 0 && (
              <div className="rounded-2xl overflow-hidden" style={{ background: dark.surface, border: `1px solid ${dark.amberDim}` }}>
                <div className="px-4 py-2.5 flex items-center gap-2" style={{ background: dark.amberTint }}>
                  <Cake size={14} style={{ color: dark.amber }} />
                  <p className="text-[11px] font-bold uppercase tracking-wide" style={{ color: dark.amber }}>
                    Pastelería por impulsar · {impulso.length}
                  </p>
                </div>
                <div>
                  {impulso.slice(0, 6).map((it, i) => (
                    <div key={it.lote_id} className="flex items-center gap-3 px-4 py-2.5"
                      style={{ borderTop: i > 0 ? `1px solid ${dark.border}` : undefined }}>
                      <div className="flex-1 min-w-0">
                        <p className="text-[13px] font-semibold truncate" style={{ color: dark.ink }}>{it.producto_nombre}</p>
                        <p className="text-[11px]" style={{ color: dark.inkSubtle }}>
                          {it.cantidad_restante} {it.cantidad_restante === 1 ? 'unidad' : 'unidades'} disponibles
                        </p>
                      </div>
                      <span className="text-[11px] font-bold px-2 py-0.5 rounded-full flex-shrink-0"
                        style={{ background: it.urgente ? dark.dangerTint : dark.amberTint, color: it.urgente ? dark.danger : dark.amber }}>
                        {it.urgente ? '¡Último día!' : `${it.dias_en_inventario}d`}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Flujo de acciones */}
            <div className="rounded-2xl overflow-hidden" style={{ border: `1px solid ${dark.border}` }}>
              {[
                { label: 'Conteo de cierre', done: turno.tiene_conteo_cierre, to: '/conteo-cierre', icon: CheckCircle, note: 'Solo al cerrar el día' },
              ].map((item, i) => (
                <button
                  key={item.label}
                  onClick={() => navigate(item.to)}
                  className="w-full flex items-center gap-3 px-4 py-3.5 text-left transition-colors"
                  style={{
                    background: item.done ? 'oklch(94% 0.03 155 / 0.5)' : dark.surface,
                    borderTop: i > 0 ? `1px solid ${dark.border}` : undefined,
                  }}
                >
                  <div className="w-8 h-8 rounded-full flex items-center justify-center shrink-0"
                    style={{ background: item.done ? dark.green : dark.surfaceAlt }}>
                    {item.done
                      ? <Check size={14} color="#fff" strokeWidth={2.5} />
                      : <Circle size={14} style={{ color: dark.inkSubtle }} />}
                  </div>
                  <div className="flex-1">
                    <p className="text-[13px] font-semibold" style={{ color: item.done ? dark.green : dark.ink }}>
                      {item.label}
                    </p>
                    {item.note && !item.done && (
                      <p className="text-[11px] mt-0.5" style={{ color: dark.amber }}>{item.note}</p>
                    )}
                  </div>
                  <ChevronRight size={15} style={{ color: dark.inkSubtle }} />
                </button>
              ))}
            </div>

            {/* Más herramientas */}
            <div className="rounded-2xl overflow-hidden" style={{ border: `1px solid ${dark.border}` }}>
              {[
                { label: 'Mis ventas hoy', to: '/ventas-hoy', icon: BarChart2 },
                { label: 'Inventario',     to: '/inventario', icon: Package   },
              ].map((item, i) => (
                <button key={item.label} onClick={() => navigate(item.to)}
                  className="w-full flex items-center gap-3 px-4 py-3.5"
                  style={{ background: dark.surface, borderTop: i > 0 ? `1px solid ${dark.border}` : undefined }}>
                  <item.icon size={16} style={{ color: dark.inkSubtle }} />
                  <span className="flex-1 text-[13px]" style={{ color: dark.ink }}>{item.label}</span>
                  <ChevronRight size={15} style={{ color: dark.inkSubtle }} />
                </button>
              ))}
            </div>

            </div>
          </>
        )}

        {/* ── SIN TURNO + sin form ── */}
        {!turno && !step && (
          <div className="space-y-4">
            <div className="rounded-2xl p-8 text-center" style={{ background: dark.surface, border: `1px solid ${dark.border}` }}>
              <Clock size={32} style={{ color: dark.inkSubtle }} className="mx-auto mb-3" />
              <p className="text-[15px] font-bold mb-1" style={{ color: dark.ink }}>No hay turno activo</p>
              <p className="text-[12px]" style={{ color: dark.inkSubtle }}>Abre un turno para comenzar a vender</p>
            </div>
            <button
              onClick={() => setStep('tipo')}
              className="w-full py-4 rounded-2xl font-bold text-[15px] text-white"
              style={{ background: dark.green }}>
              Abrir turno
            </button>
          </div>
        )}

        {/* ── PASO 1: elegir tipo de turno ── */}
        {step === 'tipo' && (
          <div className="space-y-3">
            <p className="text-[12px]" style={{ color: dark.inkSubtle }}>
              ¿Qué turno vas a iniciar?
            </p>
            {TURNOS.map(({ tipo, label, desc, Icon }) => (
              <button
                key={tipo}
                onClick={() => elegirTipo(tipo)}
                className="w-full flex items-center gap-4 px-4 py-4 rounded-2xl text-left transition-all active:scale-95"
                style={{ background: dark.surface, border: `1px solid ${dark.border}` }}
              >
                <div className="w-10 h-10 rounded-xl flex items-center justify-center shrink-0"
                  style={{ background: dark.amberTint }}>
                  <Icon size={18} style={{ color: dark.amber }} />
                </div>
                <div className="flex-1">
                  <p className="text-[14px] font-bold capitalize" style={{ color: dark.ink }}>{label}</p>
                  <p className="text-[11px] mt-0.5" style={{ color: dark.inkSubtle }}>{desc}</p>
                </div>
                <ChevronRight size={16} style={{ color: dark.inkSubtle }} />
              </button>
            ))}
          </div>
        )}

        {/* ── PASO 2: baristas + base ── */}
        {step === 'baristas' && (
          <div className="space-y-4">

            {/* Tipo seleccionado (badge) */}
            <div className="flex items-center gap-2">
              <span className="px-3 py-1 rounded-full text-xs font-bold capitalize"
                style={{ background: dark.amberDim, color: dark.amber }}>
                {tipoTurno}
              </span>
              <button
                onClick={() => setStep('tipo')}
                className="text-[11px]"
                style={{ color: dark.inkSubtle }}>
                cambiar
              </button>
            </div>

            {/* Baristas + efectivo lado a lado en desktop */}
            <div className="lg:grid lg:grid-cols-2 lg:gap-4 lg:items-start space-y-4 lg:space-y-0">

            {/* Selección de baristas */}
            <div className="rounded-2xl p-4 space-y-2" style={{ background: dark.surface, border: `1px solid ${dark.border}` }}>
              <p className="text-[10px] font-bold uppercase tracking-widest mb-3 flex items-center gap-2"
                style={{ color: dark.inkSubtle }}>
                <Users size={12} /> Baristas en este turno
              </p>
              {baristas.length === 0 ? (
                <p className="text-[12px]" style={{ color: dark.inkSubtle }}>
                  No hay baristas configurados para esta sede.
                </p>
              ) : (
                baristas.map(b => (
                  <button
                    key={b.id}
                    onClick={() => toggleBarista(b.id)}
                    className="w-full flex items-center gap-3 px-3 py-2.5 rounded-xl transition-all"
                    style={{
                      background: selected.includes(b.id) ? dark.greenDim + '44' : 'rgba(255,255,255,0.04)',
                      border: `1px solid ${selected.includes(b.id) ? dark.greenDim : 'transparent'}`,
                    }}
                  >
                    <div className="w-7 h-7 rounded-full flex items-center justify-center text-[11px] font-bold"
                      style={{ background: selected.includes(b.id) ? dark.greenDim : dark.border, color: '#fff' }}>
                      {selected.includes(b.id) ? <Check size={12} /> : b.nombre[0]}
                    </div>
                    <span className="text-[13px] font-semibold" style={{ color: dark.ink }}>{b.nombre}</span>
                  </button>
                ))
              )}
            </div>

            {/* Contá el efectivo de la caja registradora (= base operativa, cuadre de llegada) */}
            <div className="space-y-2">
              <div>
                <p className="text-[10px] font-bold uppercase tracking-widest" style={{ color: dark.inkSubtle }}>
                  Efectivo de la caja registradora
                </p>
                <p className="text-[11px] mt-0.5" style={{ color: dark.inkSubtle }}>
                  Solo el efectivo con el que abrís la caja para operar. <strong>NO</strong> incluyas la caja fuerte.
                </p>
                {esperadoInicio !== null && (
                  <p className="text-[11px] mt-0.5" style={{ color: dark.inkSubtle }}>
                    Deberías tener{' '}
                    <span className="font-mono font-semibold" style={{ color: dark.ink }}>{fmt(esperadoInicio)}</span>
                    {' '}— lo que dejó el cierre anterior, pendiente de consignar
                  </p>
                )}
              </div>
              <ContadorEfectivo onTotal={t => setBaseReal(String(t))} />
              {esperadoInicio !== null && Number(baseReal) > 0 && (Number(baseReal) - esperadoInicio) !== 0 && (
                <p className="text-[12px] font-semibold pl-1" style={{ color: dark.amber }}>
                  Diferencia: {(Number(baseReal) - esperadoInicio) > 0 ? '+' : ''}{fmt(Number(baseReal) - esperadoInicio)} — registrá el motivo abajo
                </p>
              )}

              {/* Caja fuerte — reserva fija aparte, NO entra en el cuadre de la registradora */}
              <div className="rounded-2xl p-4 space-y-1.5 mt-2" style={{ background: dark.surface, border: `1px solid ${dark.border}` }}>
                <p className="text-[10px] font-bold uppercase tracking-widest" style={{ color: dark.inkSubtle }}>
                  Caja fuerte / reserva (opcional)
                </p>
                <p className="text-[11px]" style={{ color: dark.inkSubtle }}>
                  Efectivo que se guarda aparte, por si pasa algo extraordinario. Se registra pero
                  <strong> no</strong> cuenta en “debería haber en caja”.
                </p>
                <input
                  type="number" min="0" step="1000" inputMode="numeric"
                  value={cajaFuerte}
                  onChange={e => setCajaFuerte(e.target.value)}
                  placeholder="$0"
                  className="w-full bg-transparent text-[18px] font-mono font-semibold outline-none pt-1"
                  style={{ color: dark.ink }}
                />
              </div>
            </div>

            </div>

            <textarea
              value={justificacion}
              onChange={e => setJustificacion(e.target.value)}
              placeholder="Motivo si el efectivo contado difiere del esperado"
              rows={2}
              className="w-full rounded-xl px-3 py-2.5 text-sm resize-none outline-none"
              style={{ background: dark.surface, border: `1px solid ${dark.border}`, color: dark.ink }}
            />

            {error && (
              <div className="flex items-center gap-2 rounded-xl px-3 py-2.5 text-[12px]"
                style={{ background: dark.dangerTint, border: `1px solid ${dark.dangerDim}`, color: dark.danger }}>
                <AlertTriangle size={13} /> {error}
              </div>
            )}

            <button
              onClick={abrirTurno}
              disabled={saving}
              className="w-full py-4 rounded-2xl font-bold text-[15px] text-white disabled:opacity-50 flex items-center justify-center gap-2"
              style={{ background: dark.green }}>
              <Check size={18} strokeWidth={2.5} />
              {saving ? 'Abriendo...' : 'Confirmar apertura'}
            </button>
          </div>
        )}
      </div>

    </div>
  )
}
