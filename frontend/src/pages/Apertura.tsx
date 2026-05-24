import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useTurno } from '../contexts/TurnoContext'
import api from '../api/client'
import { ArrowRight, AlertTriangle, Plus, Minus, ChevronDown, ChevronUp, Coins, LogOut } from 'lucide-react'

const fmt = (v: number) => `$${v.toLocaleString('es-CO')}`

const dark = {
  bg:         'oklch(10% 0.005 60)',
  surface:    'oklch(14% 0.008 60)',
  surfaceAlt: 'oklch(17% 0.008 60)',
  border:     'oklch(22% 0.01 60)',
  ink:        'oklch(94% 0.005 60)',
  inkMuted:   'oklch(60% 0.01 60)',
  inkSubtle:  'oklch(40% 0.01 60)',
  amber:      'oklch(82% 0.13 75)',
  amberDim:   'oklch(68% 0.14 65)',
  green:      'oklch(78% 0.13 155)',
  greenDim:   'oklch(48% 0.12 155)',
  danger:     'oklch(75% 0.16 25)',
  dangerDim:  'oklch(45% 0.16 25)',
}

const MONEDAS = [
  { valor: 50,    label: '$50'    },
  { valor: 100,   label: '$100'   },
  { valor: 200,   label: '$200'   },
  { valor: 500,   label: '$500'   },
  { valor: 1000,  label: '$1.000' },
]
const BILLETES = [
  { valor: 2000,   label: '$2.000'   },
  { valor: 5000,   label: '$5.000'   },
  { valor: 10000,  label: '$10.000'  },
  { valor: 20000,  label: '$20.000'  },
  { valor: 50000,  label: '$50.000'  },
  { valor: 100000, label: '$100.000' },
]

function FilaDenom({ valor, label, isBillete, cantidad, onChange }: {
  valor: number; label: string; isBillete: boolean; cantidad: number; onChange: (n: number) => void
}) {
  const subtotal = valor * cantidad
  return (
    <div className="flex items-center gap-3 px-4 py-2.5 transition-colors" style={{
      background: cantidad > 0
        ? (isBillete ? 'oklch(18% 0.05 155 / 0.6)' : 'oklch(18% 0.05 70 / 0.6)')
        : 'transparent',
    }}>
      <div className="w-16 shrink-0 text-center py-1 rounded-lg text-[11px] font-bold" style={{
        background: isBillete ? 'oklch(26% 0.07 155)' : 'oklch(26% 0.07 65)',
        color: isBillete ? dark.green : dark.amber,
      }}>
        {label}
      </div>
      <div className="flex items-center gap-2 flex-1 justify-center">
        <button
          onClick={() => onChange(Math.max(0, cantidad - 1))}
          disabled={cantidad === 0}
          className="w-9 h-9 rounded-xl flex items-center justify-center transition-colors"
          style={{ background: dark.surfaceAlt, color: dark.inkMuted, opacity: cantidad === 0 ? 0.3 : 1 }}
        >
          <Minus size={13} />
        </button>
        <input
          type="number"
          value={cantidad === 0 ? '' : cantidad}
          onChange={e => onChange(Math.max(0, parseInt(e.target.value) || 0))}
          placeholder="0"
          inputMode="numeric"
          className="w-14 text-center rounded-xl py-1.5 text-base font-bold outline-none"
          style={{
            background: dark.surface,
            border: `2px solid ${dark.border}`,
            color: dark.ink,
            fontFamily: '"JetBrains Mono", monospace',
          }}
          onFocus={e => (e.target.style.borderColor = dark.amberDim)}
          onBlur={e => (e.target.style.borderColor = dark.border)}
        />
        <button
          onClick={() => onChange(cantidad + 1)}
          className="w-9 h-9 rounded-xl flex items-center justify-center transition-colors"
          style={{ background: dark.amberDim, color: dark.bg }}
        >
          <Plus size={13} />
        </button>
      </div>
      <div className="w-[88px] text-right shrink-0" style={{ fontFamily: '"JetBrains Mono", monospace' }}>
        {subtotal > 0
          ? <span className="text-sm font-semibold" style={{ color: dark.amber }}>{fmt(subtotal)}</span>
          : <span className="text-xs" style={{ color: dark.inkSubtle }}>—</span>
        }
      </div>
    </div>
  )
}

function ContadorEfectivo({ onTotal }: { onTotal: (total: number) => void }) {
  const [cantidades, setCantidades] = useState<Record<number, number>>({})
  const [showMonedas, setShowMonedas] = useState(true)
  const [showBilletes, setShowBilletes] = useState(true)

  const setCantidad = (valor: number, isBillete: boolean, n: number) => {
    const key = isBillete ? valor + 1000000 : valor
    const nuevo = { ...cantidades, [key]: n }
    setCantidades(nuevo)
    onTotal(calcTotal(nuevo))
  }

  const getCantidad = (valor: number, isBillete: boolean) => {
    const key = isBillete ? valor + 1000000 : valor
    return cantidades[key] ?? 0
  }

  const calcTotal = (c: Record<number, number>) => {
    let t = 0
    MONEDAS.forEach(m => { t += m.valor * (c[m.valor] ?? 0) })
    BILLETES.forEach(b => { t += b.valor * (c[b.valor + 1000000] ?? 0) })
    return t
  }

  const total         = calcTotal(cantidades)
  const totalBilletes = BILLETES.reduce((s, b) => s + b.valor * (cantidades[b.valor + 1000000] ?? 0), 0)
  const totalMonedas  = MONEDAS.reduce((s, m) => s + m.valor * (cantidades[m.valor] ?? 0), 0)
  const hayAlgo       = total > 0

  return (
    <div className="rounded-2xl overflow-hidden" style={{
      background: dark.surface, border: `1px solid ${dark.border}`,
    }}>
      {/* Header del contador */}
      <div className="flex items-center justify-between px-4 py-3" style={{
        borderBottom: `1px solid ${dark.border}`,
      }}>
        <div className="flex items-center gap-2">
          <Coins size={15} style={{ color: dark.amber }} />
          <span className="text-sm font-bold" style={{ color: dark.ink }}>Contador de efectivo</span>
        </div>
        {hayAlgo && (
          <button
            onClick={() => { setCantidades({}); onTotal(0) }}
            className="text-xs transition-colors"
            style={{ color: dark.inkSubtle }}
            onMouseEnter={e => (e.currentTarget.style.color = dark.danger)}
            onMouseLeave={e => (e.currentTarget.style.color = dark.inkSubtle)}
          >
            Limpiar
          </button>
        )}
      </div>

      {/* Billetes */}
      <button
        onClick={() => setShowBilletes(!showBilletes)}
        className="w-full flex items-center justify-between px-4 py-2.5 transition-colors"
        style={{ background: dark.surfaceAlt }}
      >
        <div className="flex items-center gap-2">
          <span className="text-xs font-bold uppercase tracking-wide" style={{ color: dark.green }}>Billetes</span>
          {totalBilletes > 0 && (
            <span className="text-xs font-bold px-2 py-0.5 rounded-full font-mono" style={{
              background: 'oklch(22% 0.05 155)', color: dark.green,
            }}>
              {fmt(totalBilletes)}
            </span>
          )}
        </div>
        {showBilletes
          ? <ChevronUp size={14} style={{ color: dark.inkMuted }} />
          : <ChevronDown size={14} style={{ color: dark.inkMuted }} />
        }
      </button>
      {showBilletes && (
        <div>
          {BILLETES.map(b => (
            <div key={b.valor} style={{ borderBottom: `1px solid ${dark.border}` }}>
              <FilaDenom valor={b.valor} label={b.label} isBillete={true}
                cantidad={getCantidad(b.valor, true)} onChange={n => setCantidad(b.valor, true, n)} />
            </div>
          ))}
        </div>
      )}

      {/* Monedas */}
      <button
        onClick={() => setShowMonedas(!showMonedas)}
        className="w-full flex items-center justify-between px-4 py-2.5 transition-colors"
        style={{ background: dark.surfaceAlt, borderTop: `1px solid ${dark.border}` }}
      >
        <div className="flex items-center gap-2">
          <span className="text-xs font-bold uppercase tracking-wide" style={{ color: dark.amber }}>Monedas</span>
          {totalMonedas > 0 && (
            <span className="text-xs font-bold px-2 py-0.5 rounded-full font-mono" style={{
              background: 'oklch(22% 0.05 70)', color: dark.amber,
            }}>
              {fmt(totalMonedas)}
            </span>
          )}
        </div>
        {showMonedas
          ? <ChevronUp size={14} style={{ color: dark.inkMuted }} />
          : <ChevronDown size={14} style={{ color: dark.inkMuted }} />
        }
      </button>
      {showMonedas && (
        <div>
          {MONEDAS.map(m => (
            <div key={m.valor} style={{ borderBottom: `1px solid ${dark.border}` }}>
              <FilaDenom valor={m.valor} label={m.label} isBillete={false}
                cantidad={getCantidad(m.valor, false)} onChange={n => setCantidad(m.valor, false, n)} />
            </div>
          ))}
        </div>
      )}

      {/* Total */}
      <div className="px-4 py-4" style={{
        borderTop: `2px solid ${hayAlgo ? dark.amberDim : dark.border}`,
        background: hayAlgo ? 'oklch(16% 0.04 65)' : dark.surface,
      }}>
        <div className="flex items-center justify-between">
          <span className="text-sm font-semibold" style={{ color: dark.inkMuted }}>Total contado</span>
          <span className="text-2xl font-bold font-mono" style={{
            color: hayAlgo ? dark.amber : dark.inkSubtle,
            fontFamily: '"JetBrains Mono", monospace',
          }}>
            {hayAlgo ? fmt(total) : '$0'}
          </span>
        </div>
        {hayAlgo && (
          <p className="text-xs mt-1 text-right font-mono" style={{ color: dark.amberDim }}>
            {fmt(totalBilletes)} billetes · {fmt(totalMonedas)} monedas
          </p>
        )}
      </div>
    </div>
  )
}

export default function Apertura() {
  const { user, logout } = useAuth()
  const { turno, loading: turnoLoading, refresh } = useTurno()
  const navigate = useNavigate()
  const [baseReal, setBaseReal] = useState('')
  const [justificacion, setJustificacion] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [showContador, setShowContador] = useState(true)
  const [baseSistema, setBaseSistema] = useState(0)
  const [consignacionesDeducidas, setConsignacionesDeducidas] = useState(0)

  // Depender de turno?.id (no del objeto completo) evita re-disparos en cada
  // poll cuando turno ya existe pero el objeto es una nueva referencia.
  useEffect(() => {
    if (!turnoLoading && turno) navigate('/hub', { replace: true })
  }, [turno?.id, turnoLoading, navigate])

  useEffect(() => {
    if (!user?.tienda_id) return
    api.get(`/caja/historial/${user.tienda_id}`).then(({ data }) => {
      if (data.length > 0 && data[0].efectivo_final_real != null) {
        const ultimo = data[0]
        const consigs = ultimo.consignaciones_deducidas ?? 0
        setConsignacionesDeducidas(consigs)
        setBaseSistema((ultimo.efectivo_final_real ?? 0) - consigs)
      }
    }).catch(() => {})
  }, [user?.tienda_id])

  if (turnoLoading) return (
    <div className="min-h-screen flex items-center justify-center" style={{ background: dark.bg }}>
      <p className="text-sm animate-pulse" style={{ color: dark.inkSubtle }}>Consultando turno...</p>
    </div>
  )

  const diff     = Number(baseReal) - baseSistema
  const hayDiff  = Number(baseReal) > 0 && diff !== 0
  const canSubmit = Number(baseReal) > 0 && (!hayDiff || justificacion.trim())

  const abrir = async () => {
    setError(''); setLoading(true)
    try {
      await api.post('/caja/abrir', {
        tienda_id: user?.tienda_id,
        base_real: Number(baseReal),
        justificacion_apertura: justificacion || null,
      })
      // NO llamar refresh() aquí: causaba una race condition donde el useEffect
      // detectaba turno != null y navegaba a /hub justo cuando este código
      // navegaba a /conteo-apertura → doble navegación.
      // El poll de 15 s de TurnoContext actualizará el turno en segundo plano.
      navigate('/conteo-apertura')
    } catch (e: any) {
      const detail = e.response?.data?.detail || ''
      if (detail.toLowerCase().includes('ya existe un turno')) {
        await refresh(); navigate('/'); return
      }
      setError(detail || 'Error al abrir caja')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex flex-col" style={{ background: dark.bg }}>

      {/* Header */}
      <header className="flex items-center justify-between px-5 py-4 sticky top-0 z-10 header-safe"
        style={{ background: dark.surface, borderBottom: `1px solid ${dark.border}` }}>
        <div className="flex items-center gap-2">
          <span className="text-sm font-bold" style={{ color: dark.ink }}>Sistema Café</span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs" style={{ color: dark.inkMuted }}>{user?.nombre}</span>
          <button
            onClick={() => { logout(); navigate('/login') }}
            className="flex items-center gap-1 text-xs transition-colors"
            style={{ color: dark.inkSubtle }}
            onMouseEnter={e => (e.currentTarget.style.color = dark.danger)}
            onMouseLeave={e => (e.currentTarget.style.color = dark.inkSubtle)}
          >
            <LogOut size={13} /> Salir
          </button>
        </div>
      </header>

      {/* Step bar */}
      <div className="flex gap-1 px-5 pt-4 max-w-md mx-auto w-full">
        {[0, 1, 2, 3, 4].map(i => (
          <div key={i} className="flex-1 h-1 rounded-full" style={{
            background: i === 0 ? dark.amberDim : dark.border,
          }} />
        ))}
      </div>

      <div className="flex-1 px-4 pb-32 max-w-md mx-auto w-full space-y-5 pt-4">

        {/* Título */}
        <div>
          <p className="text-xs font-bold uppercase tracking-widest mb-1" style={{ color: dark.amberDim }}>
            Paso 1 de 5
          </p>
          <h1 className="text-2xl font-bold" style={{ color: dark.ink }}>Apertura de caja</h1>
          <p className="text-sm mt-0.5" style={{ color: dark.inkMuted }}>
            {new Date().toLocaleDateString('es-CO', { weekday: 'long', day: 'numeric', month: 'long' })}
          </p>
        </div>

        {turno && (
          <div className="rounded-2xl p-4"
            style={{ background: dark.surface, border: `1px solid ${dark.border}` }}>
            <p className="text-xs font-bold uppercase tracking-widest mb-2" style={{ color: dark.inkSubtle }}>
              Ventas del día
            </p>
            <p className="text-[28px] font-bold font-mono leading-none mb-3"
              style={{ color: dark.ink, letterSpacing: '-1px' }}>
              {fmt(turno.total_ventas ?? 0)}
            </p>
            <div className="grid grid-cols-2 gap-2 pt-3" style={{ borderTop: `1px solid ${dark.border}` }}>
              {[
                { l: 'Efectivo', v: fmt(turno.total_efectivo ?? 0) },
                { l: 'Tarjeta',  v: fmt(turno.total_tarjeta ?? 0) },
              ].map(row => (
                <div key={row.l} className="flex justify-between items-baseline gap-2">
                  <span className="text-xs" style={{ color: dark.inkSubtle }}>{row.l}</span>
                  <span className="text-sm font-semibold font-mono" style={{ color: dark.ink }}>{row.v}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {error && (
          <div className="flex items-center gap-2 text-sm px-4 py-3 rounded-xl"
            style={{ background: 'oklch(18% 0.05 25)', color: dark.danger, border: `1px solid ${dark.dangerDim}` }}>
            <AlertTriangle size={14} /> {error}
          </div>
        )}

        {/* Toggle contador */}
        <button
          onClick={() => setShowContador(!showContador)}
          className="w-full flex items-center justify-between px-4 py-3 rounded-xl transition-colors"
          style={{
            background: dark.surface,
            border: `2px dashed ${dark.border}`,
          }}
          onMouseEnter={e => (e.currentTarget.style.borderColor = dark.amberDim)}
          onMouseLeave={e => (e.currentTarget.style.borderColor = dark.border)}
        >
          <div className="flex items-center gap-2">
            <Coins size={16} style={{ color: dark.amber }} />
            <span className="text-sm font-semibold" style={{ color: dark.ink }}>
              {showContador ? 'Ocultar contador' : 'Contar billetes y monedas'}
            </span>
          </div>
          {showContador
            ? <ChevronUp size={16} style={{ color: dark.inkMuted }} />
            : <ChevronDown size={16} style={{ color: dark.inkMuted }} />
          }
        </button>

        {showContador && <ContadorEfectivo onTotal={total => { if (total > 0) setBaseReal(String(total)) }} />}

        {/* Panel de confirmación */}
        <div className="rounded-2xl p-5 space-y-4" style={{
          background: dark.surface, border: `1px solid ${dark.border}`,
        }}>
          <div>
            <label className="text-xs font-bold uppercase tracking-wide block mb-2" style={{ color: dark.inkMuted }}>
              Total en caja
            </label>
            <div className="relative">
              <span className="absolute left-4 top-1/2 -translate-y-1/2 text-xl font-bold" style={{ color: dark.inkSubtle }}>$</span>
              <input
                type="number"
                inputMode="numeric"
                value={baseReal}
                onChange={e => setBaseReal(e.target.value)}
                placeholder="0"
                className="w-full pl-10 pr-4 py-4 text-3xl font-bold rounded-xl outline-none transition-colors"
                style={{
                  background: dark.surfaceAlt,
                  border: `2px solid ${dark.border}`,
                  color: dark.ink,
                  fontFamily: '"JetBrains Mono", monospace',
                }}
                onFocus={e => (e.target.style.borderColor = dark.amberDim)}
                onBlur={e => (e.target.style.borderColor = dark.border)}
              />
            </div>
            {baseSistema > 0 && (
              <p className="text-xs mt-1.5" style={{ color: dark.inkSubtle }}>
                Base sistema: <span className="font-mono font-semibold" style={{ color: dark.inkMuted }}>{fmt(baseSistema)}</span>
                {consignacionesDeducidas > 0 && (
                  <span style={{ color: dark.inkSubtle }}> (tras descontar <span className="font-mono" style={{ color: dark.amberDim }}>{fmt(consignacionesDeducidas)}</span> en consignaciones)</span>
                )}
              </p>
            )}
          </div>

          {/* Diferencia */}
          {hayDiff && (
            <div className="flex items-center justify-between p-3 rounded-xl" style={{
              background: 'oklch(18% 0.05 25)',
              border: `1.5px solid ${dark.dangerDim}`,
            }}>
              <span className="text-sm font-medium" style={{ color: dark.danger }}>Diferencia vs sistema</span>
              <span className="text-lg font-bold font-mono" style={{ color: dark.danger }}>
                {diff > 0 ? '+' : ''}{fmt(diff)}
              </span>
            </div>
          )}

          {hayDiff && (
            <div>
              <label className="text-xs font-bold uppercase tracking-wide block mb-2" style={{ color: dark.danger }}>
                Justificación obligatoria
              </label>
              <textarea
                value={justificacion}
                onChange={e => setJustificacion(e.target.value)}
                placeholder="Explica la diferencia..."
                rows={2}
                className="w-full rounded-xl px-4 py-3 text-sm outline-none resize-none"
                style={{
                  background: dark.surfaceAlt,
                  border: `2px solid ${dark.dangerDim}`,
                  color: dark.ink,
                }}
                onFocus={e => (e.target.style.borderColor = dark.danger)}
                onBlur={e => (e.target.style.borderColor = dark.dangerDim)}
              />
            </div>
          )}
        </div>
      </div>

      {/* CTA sticky */}
      <div className="fixed bottom-0 left-0 right-0 p-4 max-w-md mx-auto" style={{
        background: `linear-gradient(to top, ${dark.bg} 70%, transparent)`,
      }}>
        <button
          onClick={abrir}
          disabled={!canSubmit || loading}
          className="w-full font-bold py-4 rounded-2xl text-base flex items-center justify-center gap-2 transition-all active:scale-[0.98]"
          style={{
            background: (!canSubmit || loading)
              ? dark.surfaceAlt
              : `linear-gradient(135deg, ${dark.amberDim}, ${dark.amber})`,
            color: (!canSubmit || loading) ? dark.inkSubtle : dark.bg,
            opacity: (!canSubmit || loading) ? 0.6 : 1,
            cursor: (!canSubmit || loading) ? 'not-allowed' : 'pointer',
          }}
        >
          {loading ? 'Abriendo...' : <>Abrir turno <ArrowRight size={18} /></>}
        </button>
      </div>
    </div>
  )
}
