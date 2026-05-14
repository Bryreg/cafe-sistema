import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useTurno } from '../contexts/TurnoContext'
import api from '../api/client'
import { AlertTriangle, Lock, ChevronLeft, Plus, Minus, ChevronDown, ChevronUp, Check, X } from 'lucide-react'

const fmt = (v: number) => `$${v.toLocaleString('es-CO')}`

const BILLETES = [
  { valor: 2000,   label: '$2.000'   },
  { valor: 5000,   label: '$5.000'   },
  { valor: 10000,  label: '$10.000'  },
  { valor: 20000,  label: '$20.000'  },
  { valor: 50000,  label: '$50.000'  },
  { valor: 100000, label: '$100.000' },
]
const MONEDAS = [
  { valor: 50,   label: '$50'    },
  { valor: 100,  label: '$100'   },
  { valor: 200,  label: '$200'   },
  { valor: 500,  label: '$500'   },
  { valor: 1000, label: '$1.000' },
]

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
        />
        <button
          onClick={() => onChange(cantidad + 1)}
          className="w-9 h-9 rounded-xl flex items-center justify-center"
          style={{ background: dark.greenDim, color: '#fff' }}
        >
          <Plus size={13} />
        </button>
      </div>
      <div className="w-20 text-right shrink-0" style={{ fontFamily: '"JetBrains Mono", monospace' }}>
        {subtotal > 0
          ? <span className="text-sm font-bold" style={{ color: dark.ink }}>{fmt(subtotal)}</span>
          : <span className="text-xs" style={{ color: dark.inkSubtle }}>—</span>}
      </div>
    </div>
  )
}

function PanelCuadre({ label, contado, sistema }: {
  label: string; contado: number; sistema: number
}) {
  const diff = contado - sistema
  const cuadra = diff === 0
  return (
    <div className="rounded-2xl p-4 space-y-2" style={{
      background: cuadra ? 'oklch(18% 0.06 155)' : 'oklch(18% 0.07 25)',
      border: `1.5px solid ${cuadra ? 'oklch(32% 0.10 155)' : 'oklch(38% 0.14 25)'}`,
    }}>
      <p className="text-[10px] font-bold uppercase tracking-widest" style={{
        color: cuadra ? dark.green : dark.danger,
      }}>{label}</p>
      <div className="flex justify-between text-sm">
        <span style={{ color: dark.inkMuted }}>Sistema</span>
        <span className="font-semibold font-mono" style={{ color: dark.ink }}>{fmt(sistema)}</span>
      </div>
      <div className="flex justify-between text-sm">
        <span style={{ color: dark.inkMuted }}>Contado / Bold</span>
        <span className="font-semibold font-mono" style={{ color: dark.ink }}>{contado > 0 ? fmt(contado) : '—'}</span>
      </div>
      {contado > 0 && (
        <div className="flex items-center justify-between pt-2" style={{ borderTop: `1px solid ${dark.border}` }}>
          <span className="text-sm" style={{ color: dark.inkMuted }}>Diferencia</span>
          <div className="flex items-center gap-2">
            {cuadra ? (
              <>
                <Check size={13} style={{ color: dark.green }} />
                <span className="font-bold text-sm font-mono" style={{ color: dark.green }}>Cuadra</span>
              </>
            ) : (
              <>
                <X size={13} style={{ color: dark.danger }} />
                <span className="font-bold text-lg font-mono" style={{ color: dark.danger }}>
                  {diff > 0 ? '+' : ''}{fmt(Math.abs(diff))}
                </span>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

export default function Cierre() {
  const { user } = useAuth()
  const { turno, refresh } = useTurno()
  const navigate = useNavigate()

  const [cantidades, setCantidades] = useState<Record<string, number>>({})
  const [showBilletes, setShowBilletes] = useState(true)
  const [showMonedas, setShowMonedas] = useState(false)
  const [datafono, setDatafono] = useState('')
  const [justificacion, setJustificacion] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  // Depende solo de los campos relevantes para navegación, NO del objeto completo.
  // Si dependiera de `turno`, el efecto se dispararía en cada poll de 15 s
  // (nueva referencia de objeto) y podría sacar al barista de la página si
  // hubiera un error de red momentáneo que pusiera turno en null.
  useEffect(() => {
    if (!turno) { navigate('/hub', { replace: true }); return }
    if (!turno.tiene_conteo_cierre) navigate('/conteo-cierre', { replace: true })
  }, [turno?.id, turno?.tiene_conteo_cierre, navigate])

  if (!turno || !turno.tiene_conteo_cierre) return null

  const getB = (valor: number) => cantidades[`b_${valor}`] ?? 0
  const setB = (valor: number, n: number) => setCantidades(prev => ({ ...prev, [`b_${valor}`]: n }))
  const getM = (valor: number) => cantidades[`m_${valor}`] ?? 0
  const setM = (valor: number, n: number) => setCantidades(prev => ({ ...prev, [`m_${valor}`]: n }))

  const totalBilletes = BILLETES.reduce((s, b) => s + b.valor * getB(b.valor), 0)
  const totalMonedas  = MONEDAS.reduce((s, m) => s + m.valor * getM(m.valor), 0)
  const totalCaja     = totalBilletes + totalMonedas

  const efectivoEsperado = turno.efectivo_esperado_actual
  const diffEfectivo     = totalCaja > 0 ? totalCaja - efectivoEsperado : null

  const datafonoNum     = Number(datafono) || 0
  const diffTarjeta     = datafono.trim() !== '' ? datafonoNum - turno.total_tarjeta : null
  const requiereDatafono = turno.total_tarjeta > 0
  const datafonoDigitado = datafono.trim() !== ''

  const hayDiff  = (diffEfectivo !== null && diffEfectivo !== 0) || (diffTarjeta !== null && diffTarjeta !== 0)
  const canSubmit = totalCaja > 0 && (!requiereDatafono || datafonoDigitado) && (!hayDiff || justificacion.trim())

  const cerrar = async () => {
    if (!canSubmit) return
    setError(''); setLoading(true)
    try {
      await api.post(`/caja/${turno.id}/cerrar`, {
        efectivo_final_real: totalCaja,
        datafono_real: datafonoDigitado ? datafonoNum : null,
        justificacion_cierre: justificacion || null,
      })
      await refresh()
      navigate('/hub')
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Error al cerrar caja')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex flex-col" style={{ background: dark.bg }}>

      {/* Header */}
      <header className="flex items-center gap-2.5 px-4 pb-2.5 pt-3 shrink-0" style={{ background: dark.bg }}>
        <button
          onClick={() => navigate('/hub')}
          className="w-7 h-7 rounded-lg flex items-center justify-center"
          style={{ background: 'rgba(255,255,255,0.06)', color: dark.inkMuted }}
        >
          <ChevronLeft size={16} />
        </button>
        <div className="flex-1 min-w-0">
          <p className="text-[10px] font-bold uppercase tracking-widest" style={{ color: dark.amber }}>
            Cuadre de caja · Paso 5 de 5
          </p>
          <p className="text-[14px] font-bold leading-tight" style={{ color: dark.ink }}>
            Cierre de turno · {user?.nombre}
          </p>
        </div>
      </header>

      {/* Body */}
      <div className="flex-1 overflow-auto px-4 pb-32 space-y-4 pt-1">

        {/* Ventas del turno */}
        <div className="rounded-2xl p-4" style={{ background: dark.surface, border: `1px solid ${dark.border}` }}>
          <p className="text-[10px] font-bold uppercase tracking-widest mb-3" style={{ color: dark.inkSubtle }}>
            Sistema — ventas del turno
          </p>
          <div className="grid grid-cols-3 gap-3">
            {[
              { label: 'Total',    value: turno.total_ventas,   color: dark.ink   },
              { label: 'Efectivo', value: turno.total_efectivo, color: dark.green },
              { label: 'Tarjeta',  value: turno.total_tarjeta,  color: dark.amber },
            ].map(({ label, value, color }) => (
              <div key={label} className="text-center">
                <p className="text-[10px] mb-1" style={{ color: dark.inkSubtle }}>{label}</p>
                <p className="text-sm font-bold font-mono" style={{ color }}>{fmt(value)}</p>
              </div>
            ))}
          </div>
          {(turno.ingresos_movimientos > 0 || turno.egresos_movimientos > 0) && (
            <div className="grid grid-cols-2 gap-2 mt-3 pt-3" style={{ borderTop: `1px solid ${dark.border}` }}>
              {turno.ingresos_movimientos > 0 && (
                <div>
                  <p className="text-[10px]" style={{ color: dark.inkSubtle }}>Ingresos mov.</p>
                  <p className="text-sm font-bold font-mono" style={{ color: dark.green }}>{fmt(turno.ingresos_movimientos)}</p>
                </div>
              )}
              {turno.egresos_movimientos > 0 && (
                <div>
                  <p className="text-[10px]" style={{ color: dark.inkSubtle }}>Egresos mov.</p>
                  <p className="text-sm font-bold font-mono" style={{ color: dark.danger }}>{fmt(turno.egresos_movimientos)}</p>
                </div>
              )}
            </div>
          )}
        </div>

        {error && (
          <div className="flex items-center gap-2 rounded-xl px-3 py-2.5 text-[12px]"
            style={{ background: 'oklch(20% 0.08 25)', border: `1px solid ${dark.dangerDim}`, color: dark.danger }}>
            <AlertTriangle size={13} /> {error}
          </div>
        )}

        {/* Contador de efectivo */}
        <div className="rounded-2xl overflow-hidden" style={{ background: dark.surface, border: `1px solid ${dark.border}` }}>
          <div className="flex items-center justify-between px-4 py-3" style={{ borderBottom: `1px solid ${dark.border}` }}>
            <p className="text-[13px] font-bold" style={{ color: dark.ink }}>Cuenta el efectivo en caja</p>
            {totalCaja > 0 && (
              <span className="text-sm font-bold font-mono" style={{ color: dark.green }}>{fmt(totalCaja)}</span>
            )}
          </div>

          {/* Billetes */}
          <div>
            <button
              onClick={() => setShowBilletes(!showBilletes)}
              className="w-full flex items-center justify-between px-4 py-2.5 transition-colors"
              style={{ background: 'oklch(20% 0.06 155 / 0.5)' }}
            >
              <div className="flex items-center gap-2">
                <span className="text-[11px] font-bold uppercase tracking-wide" style={{ color: dark.green }}>Billetes</span>
                {totalBilletes > 0 && (
                  <span className="text-[11px] font-bold font-mono px-2 py-0.5 rounded-full"
                    style={{ background: 'oklch(26% 0.07 155)', color: dark.green }}>
                    {fmt(totalBilletes)}
                  </span>
                )}
              </div>
              {showBilletes ? <ChevronUp size={14} style={{ color: dark.green }} /> : <ChevronDown size={14} style={{ color: dark.green }} />}
            </button>
            {showBilletes && (
              <div style={{ borderTop: `1px solid ${dark.border}` }}>
                {BILLETES.map(b => (
                  <FilaDenom key={b.valor} valor={b.valor} label={b.label} isBillete cantidad={getB(b.valor)} onChange={n => setB(b.valor, n)} />
                ))}
              </div>
            )}
          </div>

          {/* Monedas */}
          <div style={{ borderTop: `1px solid ${dark.border}` }}>
            <button
              onClick={() => setShowMonedas(!showMonedas)}
              className="w-full flex items-center justify-between px-4 py-2.5 transition-colors"
              style={{ background: 'oklch(20% 0.05 70 / 0.4)' }}
            >
              <div className="flex items-center gap-2">
                <span className="text-[11px] font-bold uppercase tracking-wide" style={{ color: dark.amber }}>Monedas</span>
                {totalMonedas > 0 && (
                  <span className="text-[11px] font-bold font-mono px-2 py-0.5 rounded-full"
                    style={{ background: 'oklch(26% 0.07 65)', color: dark.amber }}>
                    {fmt(totalMonedas)}
                  </span>
                )}
              </div>
              {showMonedas ? <ChevronUp size={14} style={{ color: dark.amber }} /> : <ChevronDown size={14} style={{ color: dark.amber }} />}
            </button>
            {showMonedas && (
              <div style={{ borderTop: `1px solid ${dark.border}` }}>
                {MONEDAS.map(m => (
                  <FilaDenom key={m.valor} valor={m.valor} label={m.label} isBillete={false} cantidad={getM(m.valor)} onChange={n => setM(m.valor, n)} />
                ))}
              </div>
            )}
          </div>

          {/* Total summary */}
          {totalCaja > 0 && (
            <div className="px-4 py-3" style={{ borderTop: `1px solid ${dark.border}`, background: dark.surfaceAlt }}>
              <div className="flex justify-between items-center mb-1">
                <span className="text-[12px]" style={{ color: dark.inkMuted }}>Total contado</span>
                <span className="text-xl font-bold font-mono" style={{ color: dark.ink, letterSpacing: '-0.5px' }}>{fmt(totalCaja)}</span>
              </div>
              <div className="flex justify-between items-center text-[11px]">
                <span style={{ color: dark.inkSubtle }}>Esperado sistema</span>
                <span className="font-semibold font-mono" style={{ color: dark.amber }}>{fmt(efectivoEsperado)}</span>
              </div>
            </div>
          )}
        </div>

        {/* Datafono Bold */}
        <div className="rounded-2xl p-4 space-y-3" style={{ background: dark.surface, border: `1px solid ${dark.border}` }}>
          <div>
            <p className="text-[13px] font-bold" style={{ color: dark.ink }}>Datafono Bold</p>
            <p className="text-[11px] mt-0.5" style={{ color: dark.inkSubtle }}>
              {requiereDatafono
                ? 'Obligatorio — hubo ventas con tarjeta en este turno'
                : 'Ingresa el total que muestra el datafono'}
            </p>
          </div>
          <div className="rounded-xl px-4 py-3 flex items-center justify-between gap-3"
            style={{ background: dark.surfaceAlt, border: `1px solid ${datafonoDigitado ? dark.amberDim : dark.border}` }}>
            <span className="text-[12px]" style={{ color: dark.inkMuted }}>Total datáfono</span>
            <input
              type="number"
              value={datafono}
              onChange={e => setDatafono(e.target.value)}
              placeholder="0"
              inputMode="numeric"
              className="text-[22px] font-bold font-mono text-right bg-transparent outline-none w-40"
              style={{ color: dark.amber }}
            />
          </div>
        </div>

        {/* Resultado del cuadre */}
        {(totalCaja > 0 || datafonoDigitado) && (
          <div className="space-y-2.5">
            <p className="text-[10px] font-bold uppercase tracking-widest" style={{ color: dark.inkSubtle }}>
              Resultado del cuadre
            </p>
            {totalCaja > 0 && (
              <PanelCuadre label="Efectivo en caja" contado={totalCaja} sistema={efectivoEsperado} />
            )}
            {datafonoDigitado && (
              <PanelCuadre label="Tarjeta (Bold)" contado={datafonoNum} sistema={turno.total_tarjeta} />
            )}
          </div>
        )}

        {/* Monto a consignar */}
        <div className="rounded-2xl p-4" style={{
          background: 'oklch(16% 0.09 75)',
          border: '2px solid oklch(48% 0.20 75)',
        }}>
          <p className="text-[10px] font-bold uppercase tracking-widest mb-3" style={{ color: dark.amber }}>
            Monto a consignar al banco
          </p>
          <div className="space-y-1.5 text-sm">
            <div className="flex justify-between">
              <span style={{ color: dark.inkMuted }}>Ventas en efectivo</span>
              <span className="font-mono font-semibold" style={{ color: dark.ink }}>{fmt(turno.total_efectivo)}</span>
            </div>
            {turno.ingresos_movimientos > 0 && (
              <div className="flex justify-between">
                <span style={{ color: dark.inkMuted }}>+ Ingresos mov.</span>
                <span className="font-mono" style={{ color: dark.green }}>{fmt(turno.ingresos_movimientos)}</span>
              </div>
            )}
            {turno.egresos_movimientos > 0 && (
              <div className="flex justify-between">
                <span style={{ color: dark.inkMuted }}>− Vales / proveedores</span>
                <span className="font-mono" style={{ color: dark.danger }}>−{fmt(turno.egresos_movimientos)}</span>
              </div>
            )}
          </div>
          <div className="flex items-center justify-between mt-3 pt-3" style={{ borderTop: '1.5px solid oklch(38% 0.18 75)' }}>
            <span className="text-sm font-bold" style={{ color: dark.amber }}>Total a consignar</span>
            <span className="text-2xl font-bold font-mono" style={{ color: dark.amber, letterSpacing: '-0.5px' }}>
              {fmt(Math.max(0, turno.total_efectivo + turno.ingresos_movimientos - turno.egresos_movimientos))}
            </span>
          </div>
          <div className="flex justify-between mt-2 pt-2 text-[11px]" style={{ borderTop: `1px solid ${dark.border}` }}>
            <span style={{ color: dark.inkSubtle }}>Base que queda en caja</span>
            <span className="font-mono" style={{ color: dark.inkSubtle }}>{fmt(turno.base_real)}</span>
          </div>
        </div>

        {/* Justificación si hay diferencias */}
        {hayDiff && (
          <div>
            <p className="text-[10px] font-bold uppercase tracking-widest mb-2" style={{ color: dark.danger }}>
              Justificación de diferencias (obligatoria)
            </p>
            <textarea
              value={justificacion}
              onChange={e => setJustificacion(e.target.value)}
              placeholder="Explica las diferencias encontradas..."
              rows={2}
              className="w-full rounded-xl px-3 py-2.5 text-sm resize-none outline-none"
              style={{
                background: dark.surface,
                border: `1px solid ${dark.dangerDim}`,
                color: dark.ink,
              }}
            />
          </div>
        )}

        {requiereDatafono && !datafonoDigitado && (
          <p className="text-center text-[11px]" style={{ color: dark.amber }}>
            Debes registrar el total del datafono Bold para cerrar este turno.
          </p>
        )}

        <button
          onClick={() => navigate('/hub')}
          className="w-full text-sm py-2 transition-colors"
          style={{ color: dark.inkSubtle }}
        >
          ← Volver al hub
        </button>
      </div>

      {/* CTA sticky */}
      <div className="fixed bottom-0 left-0 right-0 px-4 pb-8 pt-3"
        style={{
          background: `linear-gradient(to top, ${dark.bg} 70%, transparent)`,
          borderTop: `1px solid ${dark.border}`,
        }}>
        <button
          onClick={canSubmit ? cerrar : undefined}
          disabled={!canSubmit || loading}
          className="w-full py-4 rounded-2xl text-[15px] font-bold flex items-center justify-center gap-2 transition-all"
          style={{
            background: canSubmit ? dark.greenDim : 'oklch(20% 0.04 155)',
            color: '#fff',
            opacity: !canSubmit || loading ? 0.55 : 1,
            cursor: !canSubmit ? 'not-allowed' : 'pointer',
          }}
        >
          {loading ? 'Cerrando turno...'
            : !canSubmit ? <><Lock size={14} /> Completa todos los pasos</>
            : <><Lock size={16} strokeWidth={2.5} /> Cerrar turno</>
          }
        </button>
      </div>
    </div>
  )
}
