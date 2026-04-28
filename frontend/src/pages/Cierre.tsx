import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useTurno } from '../contexts/TurnoContext'
import api from '../api/client'
import { AlertTriangle, Lock, LogOut, Plus, Minus, ChevronDown, ChevronUp, CheckCircle2, XCircle } from 'lucide-react'

const fmt = (v: number) => `$${v.toLocaleString('es-CO')}`

const BILLETES = [
  { valor: 2000,   label: '$2.000',   tipo: 'billete' },
  { valor: 5000,   label: '$5.000',   tipo: 'billete' },
  { valor: 10000,  label: '$10.000',  tipo: 'billete' },
  { valor: 20000,  label: '$20.000',  tipo: 'billete' },
  { valor: 50000,  label: '$50.000',  tipo: 'billete' },
  { valor: 100000, label: '$100.000', tipo: 'billete' },
]
const MONEDAS = [
  { valor: 50,   label: '$50',    tipo: 'moneda' },
  { valor: 100,  label: '$100',   tipo: 'moneda' },
  { valor: 200,  label: '$200',   tipo: 'moneda' },
  { valor: 500,  label: '$500',   tipo: 'moneda' },
  { valor: 1000, label: '$1.000', tipo: 'moneda' },
]

function FilaDenom({ item, cantidad, onChange }: {
  item: { valor: number; label: string; tipo: string }
  cantidad: number
  onChange: (n: number) => void
}) {
  const subtotal = item.valor * cantidad
  const esBillete = item.tipo === 'billete'

  return (
    <div className={`flex items-center gap-3 px-4 py-2.5 transition-colors ${
      cantidad > 0 ? (esBillete ? 'bg-green-900/20' : 'bg-amber-900/10') : ''
    }`}>
      <div className={`w-16 shrink-0 text-center py-1 rounded-lg text-xs font-bold ${
        esBillete ? 'bg-green-800 text-green-200' : 'bg-amber-800 text-amber-200'
      }`}>
        {item.label}
      </div>
      <div className="flex items-center gap-2 flex-1 justify-center">
        <button
          onClick={() => onChange(Math.max(0, cantidad - 1))}
          disabled={cantidad === 0}
          className="w-9 h-9 rounded-xl bg-gray-700 hover:bg-gray-600 disabled:opacity-30 flex items-center justify-center active:scale-95 transition-colors"
        >
          <Minus size={13} className="text-gray-300" />
        </button>
        <input
          type="number"
          value={cantidad === 0 ? '' : cantidad}
          onChange={e => onChange(Math.max(0, parseInt(e.target.value) || 0))}
          placeholder="0"
          inputMode="numeric"
          className="w-14 text-center border-2 border-gray-600 bg-gray-800 rounded-xl py-1.5 text-base font-bold text-white focus:outline-none focus:border-forest-400"
          style={{ fontFamily: '"JetBrains Mono", monospace' }}
        />
        <button
          onClick={() => onChange(cantidad + 1)}
          className="w-9 h-9 rounded-xl flex items-center justify-center active:scale-95 transition-colors text-white"
          style={{ background: 'oklch(40% 0.08 155)' }}
        >
          <Plus size={13} />
        </button>
      </div>
      <div className="w-20 text-right shrink-0" style={{ fontFamily: '"JetBrains Mono", monospace' }}>
        {subtotal > 0
          ? <span className="text-sm font-bold text-gray-200">{fmt(subtotal)}</span>
          : <span className="text-xs text-gray-600">—</span>}
      </div>
    </div>
  )
}

function PanelCuadre({ label, contado, sistema, color }: {
  label: string; contado: number; sistema: number; color: 'green' | 'blue'
}) {
  const diff = contado - sistema
  const cuadra = diff === 0

  // Semantic panel bg: green if balanced, red if diff
  const panelStyle = cuadra
    ? {
        background: 'oklch(25% 0.04 155)',
        border: '1.5px solid oklch(35% 0.08 155)',
      }
    : {
        background: 'oklch(25% 0.07 25)',
        border: '1.5px solid oklch(40% 0.14 25)',
      }

  const labelColor = color === 'green'
    ? (cuadra ? 'text-green-400' : 'text-red-400')
    : (cuadra ? 'text-blue-400' : 'text-red-400')

  return (
    <div className="rounded-2xl p-4 space-y-2" style={panelStyle}>
      <p className={`text-xs font-bold uppercase tracking-wide ${labelColor}`}>{label}</p>
      <div className="flex justify-between text-sm text-gray-400">
        <span>Sistema</span>
        <span className="font-semibold text-gray-200 font-mono">{fmt(sistema)}</span>
      </div>
      <div className="flex justify-between text-sm text-gray-400">
        <span>Contado / Bold</span>
        <span className="font-semibold text-gray-200 font-mono">{contado > 0 ? fmt(contado) : '—'}</span>
      </div>
      {contado > 0 && (
        <div className="flex items-center justify-between pt-2 border-t border-gray-700">
          <span className="text-sm text-gray-400">Diferencia</span>
          <div className="flex items-center gap-2">
            {cuadra ? (
              <>
                <CheckCircle2 size={15} className="text-green-400" />
                <span className="font-bold text-sm font-mono" style={{ color: 'oklch(72% 0.14 155)' }}>Cuadra</span>
              </>
            ) : (
              <>
                <XCircle size={15} className="text-red-400" />
                <span className="text-red-400 font-bold text-sm font-mono" style={{ fontSize: 22 }}>
                  {diff > 0 ? '+' : ''}{fmt(diff)}
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
  const { user, logout } = useAuth()
  const { turno, refresh } = useTurno()
  const navigate = useNavigate()

  const [cantidades, setCantidades] = useState<Record<number, number>>({})
  const [showBilletes, setShowBilletes] = useState(true)
  const [showMonedas, setShowMonedas] = useState(false)
  const [datafono, setDatafono] = useState('')
  const [justificacion, setJustificacion] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!turno) { navigate('/hub', { replace: true }); return }
    if (!turno.tiene_conteo_cierre) navigate('/conteo-cierre', { replace: true })
  }, [navigate, turno])

  if (!turno || !turno.tiene_conteo_cierre) return null

  const getCantidad = (valor: number, tipo: string) => {
    const key = tipo === 'moneda' ? valor : valor + 1000000
    return cantidades[key] ?? 0
  }
  const setCantidad = (valor: number, tipo: string, n: number) => {
    const key = tipo === 'moneda' ? valor : valor + 1000000
    setCantidades(prev => ({ ...prev, [key]: n }))
  }

  const totalBilletes = BILLETES.reduce((s, b) => s + b.valor * (cantidades[b.valor + 1000000] ?? 0), 0)
  const totalMonedas  = MONEDAS.reduce((s, m) => s + m.valor * (cantidades[m.valor] ?? 0), 0)
  const totalCaja = totalBilletes + totalMonedas

  const efectivoEsperado = turno.efectivo_esperado_actual
  const diffEfectivo = totalCaja > 0 ? totalCaja - efectivoEsperado : null

  const datafonoNum = Number(datafono) || 0
  const diffTarjeta = datafono.trim() !== '' ? datafonoNum - turno.total_tarjeta : null
  const requiereDatafono = turno.total_tarjeta > 0
  const datafonoDigitado = datafono.trim() !== ''

  const hayDiff = (diffEfectivo !== null && diffEfectivo !== 0) || (diffTarjeta !== null && diffTarjeta !== 0)
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
    <div className="min-h-screen flex flex-col text-white" style={{ background: 'oklch(18% 0.01 55)' }}>
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-4 border-b sticky top-0 z-10"
        style={{ background: 'oklch(18% 0.01 55)', borderColor: 'oklch(32% 0.014 55)' }}>
        <div className="flex items-center gap-2">
          <Lock size={16} className="text-forest-400" />
          <span className="text-sm font-bold" style={{ color: 'oklch(85% 0.005 75)' }}>Cuadre de caja</span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs" style={{ color: 'oklch(45% 0.014 55)' }}>{user?.nombre}</span>
          <button onClick={() => { logout(); navigate('/login') }} className="text-gray-500 hover:text-red-400">
            <LogOut size={15} />
          </button>
        </div>
      </div>

      <div className="flex-1 px-4 pb-12 max-w-md mx-auto w-full space-y-5 pt-5">
        <div>
          <p className="text-xs font-semibold uppercase tracking-widest mb-1 text-forest-400">Paso 5 de 5</p>
          <h1 className="text-xl font-bold text-white">Cuadre de caja</h1>
          <p className="text-sm mt-0.5" style={{ color: 'oklch(45% 0.014 55)' }}>Cuenta el efectivo y revisa el datafono</p>
        </div>

        {/* Ventas del turno */}
        <div className="rounded-2xl p-4" style={{ background: 'oklch(23% 0.012 55)' }}>
          <p className="text-xs font-semibold uppercase tracking-wide mb-3" style={{ color: 'oklch(45% 0.014 55)' }}>
            Sistema — ventas del turno
          </p>
          <div className="grid grid-cols-3 gap-3">
            {[
              { label: 'Total', value: turno.total_ventas, color: 'text-white' },
              { label: 'Efectivo', value: turno.total_efectivo, color: 'text-green-400' },
              { label: 'Tarjeta', value: turno.total_tarjeta, color: 'text-blue-400' },
            ].map(({ label, value, color }) => (
              <div key={label} className="text-center">
                <p className="text-xs mb-1" style={{ color: 'oklch(45% 0.014 55)' }}>{label}</p>
                <p className={`text-sm font-bold font-mono ${color}`}>{fmt(value)}</p>
              </div>
            ))}
          </div>
        </div>

        {(turno.ingresos_movimientos > 0 || turno.egresos_movimientos > 0) && (
          <div className="grid grid-cols-2 gap-2">
            <div className="rounded-xl p-3 text-center" style={{ background: 'oklch(23% 0.012 55)' }}>
              <p className="text-xs mb-1" style={{ color: 'oklch(45% 0.014 55)' }}>Ingresos mov.</p>
              <p className="text-sm font-bold text-green-400 font-mono">{fmt(turno.ingresos_movimientos)}</p>
            </div>
            <div className="rounded-xl p-3 text-center" style={{ background: 'oklch(23% 0.012 55)' }}>
              <p className="text-xs mb-1" style={{ color: 'oklch(45% 0.014 55)' }}>Egresos mov.</p>
              <p className="text-sm font-bold text-red-400 font-mono">{fmt(turno.egresos_movimientos)}</p>
            </div>
          </div>
        )}

        {/* Cash counter */}
        <div className="rounded-2xl overflow-hidden" style={{ background: 'oklch(23% 0.012 55)' }}>
          <div className="flex items-center justify-between px-4 py-3" style={{ borderBottom: '1px solid oklch(32% 0.014 55)' }}>
            <p className="text-sm font-bold text-gray-200">Cuenta el efectivo en caja</p>
            {totalCaja > 0 && (
              <span className="text-sm font-bold font-mono" style={{ color: 'oklch(72% 0.14 155)' }}>{fmt(totalCaja)}</span>
            )}
          </div>

          <div>
            <button
              onClick={() => setShowBilletes(!showBilletes)}
              className="w-full flex items-center justify-between px-4 py-2.5 bg-green-900/40 hover:bg-green-900/60 transition-colors"
            >
              <div className="flex items-center gap-2">
                <span className="text-xs font-bold text-green-400 uppercase tracking-wide">Billetes</span>
                {totalBilletes > 0 && (
                  <span className="text-xs font-bold text-green-300 bg-green-800/60 px-2 py-0.5 rounded-full font-mono">
                    {fmt(totalBilletes)}
                  </span>
                )}
              </div>
              {showBilletes ? <ChevronUp size={14} className="text-green-500" /> : <ChevronDown size={14} className="text-green-500" />}
            </button>
            {showBilletes && (
              <div className="divide-y divide-gray-700/30">
                {BILLETES.map(b => (
                  <FilaDenom key={b.valor} item={b} cantidad={getCantidad(b.valor, 'billete')} onChange={n => setCantidad(b.valor, 'billete', n)} />
                ))}
              </div>
            )}
          </div>

          <div style={{ borderTop: '1px solid oklch(32% 0.014 55)' }}>
            <button
              onClick={() => setShowMonedas(!showMonedas)}
              className="w-full flex items-center justify-between px-4 py-2.5 bg-amber-900/20 hover:bg-amber-900/40 transition-colors"
            >
              <div className="flex items-center gap-2">
                <span className="text-xs font-bold text-amber-400 uppercase tracking-wide">Monedas</span>
                {totalMonedas > 0 && (
                  <span className="text-xs font-bold text-amber-300 bg-amber-800/50 px-2 py-0.5 rounded-full font-mono">
                    {fmt(totalMonedas)}
                  </span>
                )}
              </div>
              {showMonedas ? <ChevronUp size={14} className="text-amber-500" /> : <ChevronDown size={14} className="text-amber-500" />}
            </button>
            {showMonedas && (
              <div className="divide-y divide-gray-700/30">
                {MONEDAS.map(m => (
                  <FilaDenom key={m.valor} item={m} cantidad={getCantidad(m.valor, 'moneda')} onChange={n => setCantidad(m.valor, 'moneda', n)} />
                ))}
              </div>
            )}
          </div>

          {totalCaja > 0 && (
            <div className="px-4 py-3" style={{ borderTop: '1px solid oklch(32% 0.014 55)', background: 'oklch(20% 0.01 55)' }}>
              <div className="flex justify-between items-center mb-1">
                <span className="text-xs text-gray-400">Total en caja</span>
                <span className="text-lg font-bold font-mono text-white">{fmt(totalCaja)}</span>
              </div>
              <div className="flex justify-between text-xs text-gray-500">
                <span>Esperado por sistema</span>
                <span className="font-semibold font-mono text-amber-400">{fmt(efectivoEsperado)}</span>
              </div>
            </div>
          )}
        </div>

        {/* Datafono */}
        <div className="rounded-2xl p-4 space-y-3" style={{ background: 'oklch(23% 0.012 55)' }}>
          <p className="text-sm font-bold text-gray-200">Datafono Bold</p>
          <p className="text-xs text-gray-500">
            {requiereDatafono
              ? 'Ingresa el total que muestra el datafono. Es obligatorio porque hubo ventas con tarjeta.'
              : 'Ingresa el total que muestra el datafono'}
          </p>
          <div className="relative">
            <span className="absolute left-4 top-1/2 -translate-y-1/2 text-xl font-bold text-blue-400">$</span>
            <input
              type="number"
              value={datafono}
              onChange={e => setDatafono(e.target.value)}
              placeholder="0"
              inputMode="numeric"
              className="w-full pl-10 pr-4 py-4 text-3xl font-bold text-blue-300 bg-gray-700 border-2 border-blue-800 rounded-xl focus:outline-none focus:border-blue-500 transition-colors"
              style={{ fontFamily: '"JetBrains Mono", monospace' }}
            />
          </div>
        </div>

        {/* Reconciliation panels */}
        {(totalCaja > 0 || datafonoDigitado) && (
          <div className="space-y-3">
            <p className="text-xs font-semibold uppercase tracking-wide" style={{ color: 'oklch(45% 0.014 55)' }}>
              Resultado del cuadre
            </p>
            {totalCaja > 0 && (
              <PanelCuadre label="Efectivo" contado={totalCaja} sistema={efectivoEsperado} color="green" />
            )}
            {datafonoDigitado && (
              <PanelCuadre label="Tarjeta (Bold)" contado={datafonoNum} sistema={turno.total_tarjeta} color="blue" />
            )}
          </div>
        )}

        {error && (
          <div className="flex items-center gap-2 bg-red-900/50 border border-red-700 text-red-300 text-sm px-4 py-3 rounded-xl">
            <AlertTriangle size={14} /> {error}
          </div>
        )}

        {hayDiff && (
          <div>
            <label className="text-xs font-semibold text-red-400 uppercase tracking-wide block mb-2">
              Justificación de diferencias (obligatoria)
            </label>
            <textarea
              value={justificacion}
              onChange={e => setJustificacion(e.target.value)}
              placeholder="Explica las diferencias encontradas..."
              rows={2}
              className="w-full bg-gray-800 border-2 border-red-700 rounded-xl px-4 py-3 text-sm text-white focus:outline-none focus:border-red-500 resize-none placeholder-gray-600"
            />
          </div>
        )}

        {/* CTA */}
        <button
          onClick={cerrar}
          disabled={!canSubmit || loading}
          className="w-full disabled:opacity-40 disabled:cursor-not-allowed text-white font-bold py-4 rounded-xl text-base flex items-center justify-center gap-2 transition-colors"
          style={{ background: canSubmit ? 'oklch(48% 0.12 155)' : 'oklch(30% 0.05 155)' }}
        >
          <Lock size={18} />
          {loading ? 'Cerrando...' : 'Cerrar turno'}
        </button>

        {requiereDatafono && !datafonoDigitado && (
          <p className="text-center text-xs text-amber-400">
            Debes registrar el total del datafono Bold para cerrar este turno.
          </p>
        )}

        <button
          onClick={() => navigate('/hub')}
          className="w-full text-sm py-2 transition-colors"
          style={{ color: 'oklch(45% 0.014 55)' }}
        >
          ← Volver al hub
        </button>
      </div>
    </div>
  )
}
