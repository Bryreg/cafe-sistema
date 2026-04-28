import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useTurno } from '../contexts/TurnoContext'
import api from '../api/client'
import { Coffee, LogOut, ArrowRight, AlertTriangle, Plus, Minus, ChevronDown, ChevronUp, Coins } from 'lucide-react'

const fmt = (v: number) => `$${v.toLocaleString('es-CO')}`

const MONEDAS = [
  { valor: 50,    label: '$50',    tipo: 'moneda' },
  { valor: 100,   label: '$100',   tipo: 'moneda' },
  { valor: 200,   label: '$200',   tipo: 'moneda' },
  { valor: 500,   label: '$500',   tipo: 'moneda' },
  { valor: 1000,  label: '$1.000', tipo: 'moneda' },
]
const BILLETES = [
  { valor: 2000,   label: '$2.000',   tipo: 'billete' },
  { valor: 5000,   label: '$5.000',   tipo: 'billete' },
  { valor: 10000,  label: '$10.000',  tipo: 'billete' },
  { valor: 20000,  label: '$20.000',  tipo: 'billete' },
  { valor: 50000,  label: '$50.000',  tipo: 'billete' },
  { valor: 100000, label: '$100.000', tipo: 'billete' },
]

function FilaDenom({
  item, cantidad, onChange,
}: {
  item: { valor: number; label: string; tipo: string }
  cantidad: number
  onChange: (n: number) => void
}) {
  const subtotal = item.valor * cantidad
  const esBillete = item.tipo === 'billete'

  return (
    <div
      className="flex items-center gap-3 px-4 py-2.5 transition-colors"
      style={{
        background: cantidad > 0
          ? (esBillete ? 'oklch(95% 0.02 155)' : 'oklch(96% 0.008 75)')
          : 'transparent',
      }}
    >
      {/* Denomination badge */}
      <div
        className="w-[72px] shrink-0 text-center py-1 rounded-md text-xs font-bold"
        style={{
          background: esBillete ? 'oklch(90% 0.025 155)' : 'oklch(96% 0.008 75)',
          color: esBillete ? 'oklch(35% 0.05 155)' : 'oklch(40% 0.01 60)',
          border: esBillete ? '1px solid oklch(82% 0.07 155)' : '1px solid oklch(85% 0.008 75)',
        }}
      >
        {item.label}
      </div>

      {/* Controls */}
      <div className="flex items-center gap-2 flex-1 justify-center">
        <button
          onClick={() => onChange(Math.max(0, cantidad - 1))}
          disabled={cantidad === 0}
          className="w-9 h-9 rounded-lg bg-warm-100 hover:bg-warm-200 disabled:opacity-30 flex items-center justify-center transition-colors active:scale-95"
        >
          <Minus size={13} className="text-warm-600" />
        </button>

        <input
          type="number"
          value={cantidad === 0 ? '' : cantidad}
          onChange={e => onChange(Math.max(0, parseInt(e.target.value) || 0))}
          placeholder="0"
          className="w-14 text-center border-2 border-warm-200 rounded-lg py-1.5 text-base font-bold text-warm-700
                     focus:outline-none transition-colors"
          style={{ fontFamily: '"JetBrains Mono", monospace' }}
          onFocus={e => (e.target.style.borderColor = 'oklch(48% 0.12 155)')}
          onBlur={e => (e.target.style.borderColor = '')}
          inputMode="numeric"
        />

        <button
          onClick={() => onChange(cantidad + 1)}
          className="w-9 h-9 rounded-lg flex items-center justify-center transition-colors active:scale-95 text-white"
          style={{ background: 'oklch(35% 0.05 155)' }}
        >
          <Plus size={13} />
        </button>
      </div>

      {/* Subtotal */}
      <div className="w-[88px] text-right shrink-0" style={{ fontFamily: '"JetBrains Mono", monospace' }}>
        {subtotal > 0
          ? <span className="text-sm font-semibold text-warm-700">{fmt(subtotal)}</span>
          : <span className="text-xs text-warm-300">—</span>
        }
      </div>
    </div>
  )
}

function ContadorEfectivo({ onTotal }: { onTotal: (total: number) => void }) {
  const [cantidades, setCantidades] = useState<Record<number, number>>({})
  const [showMonedas, setShowMonedas] = useState(true)
  const [showBilletes, setShowBilletes] = useState(true)

  const setCantidad = (valor: number, tipo: string, n: number) => {
    const key = tipo === 'moneda' ? valor : valor + 1000000
    const nuevo = { ...cantidades, [key]: n }
    setCantidades(nuevo)
    onTotal(calcTotal(nuevo))
  }

  const getCantidad = (valor: number, tipo: string) => {
    const key = tipo === 'moneda' ? valor : valor + 1000000
    return cantidades[key] ?? 0
  }

  const calcTotal = (c: Record<number, number>) => {
    let t = 0
    MONEDAS.forEach(m => { t += m.valor * (c[m.valor] ?? 0) })
    BILLETES.forEach(b => { t += b.valor * (c[b.valor + 1000000] ?? 0) })
    return t
  }

  const total = calcTotal(cantidades)
  const totalMonedas = MONEDAS.reduce((s, m) => s + m.valor * (cantidades[m.valor] ?? 0), 0)
  const totalBilletes = BILLETES.reduce((s, b) => s + b.valor * (cantidades[b.valor + 1000000] ?? 0), 0)
  const hayAlgo = total > 0

  return (
    <div className="bg-white rounded-2xl border border-warm-200 overflow-hidden shadow-sm">
      <div className="flex items-center justify-between px-4 py-3 border-b border-warm-100 bg-warm-50">
        <div className="flex items-center gap-2">
          <Coins size={15} className="text-forest" />
          <span className="text-sm font-bold text-warm-700">Contador de efectivo</span>
        </div>
        {hayAlgo && (
          <button onClick={() => { setCantidades({}); onTotal(0) }} className="text-xs text-warm-400 hover:text-red-500 transition-colors">
            Limpiar
          </button>
        )}
      </div>

      {/* Billetes */}
      <div>
        <button
          onClick={() => setShowBilletes(!showBilletes)}
          className="w-full flex items-center justify-between px-4 py-2.5 bg-forest-50 hover:bg-forest-100 transition-colors"
        >
          <div className="flex items-center gap-2">
            <span className="text-xs font-bold text-forest uppercase tracking-wide">Billetes</span>
            {totalBilletes > 0 && (
              <span className="text-xs font-bold text-forest bg-forest-100 px-2 py-0.5 rounded-full font-mono">
                {fmt(totalBilletes)}
              </span>
            )}
          </div>
          {showBilletes ? <ChevronUp size={14} className="text-forest" /> : <ChevronDown size={14} className="text-forest" />}
        </button>
        {showBilletes && (
          <div className="divide-y divide-warm-100">
            {BILLETES.map(b => (
              <FilaDenom key={`b-${b.valor}`} item={b} cantidad={getCantidad(b.valor, 'billete')} onChange={n => setCantidad(b.valor, 'billete', n)} />
            ))}
          </div>
        )}
      </div>

      {/* Monedas */}
      <div className="border-t border-warm-100">
        <button
          onClick={() => setShowMonedas(!showMonedas)}
          className="w-full flex items-center justify-between px-4 py-2.5 bg-warm-50 hover:bg-warm-100 transition-colors"
        >
          <div className="flex items-center gap-2">
            <span className="text-xs font-bold text-warm-600 uppercase tracking-wide">Monedas</span>
            {totalMonedas > 0 && (
              <span className="text-xs font-bold text-warm-700 bg-warm-200 px-2 py-0.5 rounded-full font-mono">
                {fmt(totalMonedas)}
              </span>
            )}
          </div>
          {showMonedas ? <ChevronUp size={14} className="text-warm-500" /> : <ChevronDown size={14} className="text-warm-500" />}
        </button>
        {showMonedas && (
          <div className="divide-y divide-warm-100">
            {MONEDAS.map(m => (
              <FilaDenom key={`m-${m.valor}`} item={m} cantidad={getCantidad(m.valor, 'moneda')} onChange={n => setCantidad(m.valor, 'moneda', n)} />
            ))}
          </div>
        )}
      </div>

      {/* Total */}
      <div className={`px-4 py-4 border-t-2 ${hayAlgo ? 'border-forest-100' : 'border-warm-100'}`}
        style={{ background: hayAlgo ? 'oklch(95% 0.015 155)' : undefined }}>
        <div className="flex items-center justify-between">
          <span className="text-sm font-semibold text-warm-600">Total contado</span>
          <span className="text-2xl font-bold font-mono" style={{ color: hayAlgo ? 'oklch(35% 0.05 155)' : 'oklch(85% 0.008 75)' }}>
            {hayAlgo ? fmt(total) : '$0'}
          </span>
        </div>
        {hayAlgo && (
          <p className="text-xs text-forest mt-1 text-right font-mono">
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

  useEffect(() => {
    if (!turnoLoading && turno) navigate('/hub', { replace: true })
  }, [turno, turnoLoading])

  useEffect(() => {
    if (!user?.tienda_id) return
    api.get(`/caja/historial/${user.tienda_id}`).then(({ data }) => {
      if (data.length > 0 && data[0].efectivo_final_real != null) {
        setBaseSistema(data[0].efectivo_final_real)
      }
    }).catch(() => {})
  }, [user?.tienda_id])

  if (turnoLoading) return (
    <div className="min-h-screen bg-warm-50 flex items-center justify-center">
      <p className="text-sm text-warm-400 animate-pulse">Consultando turno...</p>
    </div>
  )

  const diff = Number(baseReal) - baseSistema
  const hayDiff = Number(baseReal) > 0 && diff !== 0
  const canSubmit = Number(baseReal) > 0 && (!hayDiff || justificacion.trim())

  const abrir = async () => {
    setError('')
    setLoading(true)
    try {
      await api.post('/caja/abrir', {
        tienda_id: user?.tienda_id,
        base_real: Number(baseReal),
        justificacion_apertura: justificacion || null,
      })
      await refresh()
      navigate('/conteo-apertura')
    } catch (e: any) {
      const detail = e.response?.data?.detail || ''
      if (detail.toLowerCase().includes('ya existe un turno')) {
        await refresh()
        navigate('/')
        return
      }
      setError(detail || 'Error al abrir caja')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-warm-50 flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-4 bg-white sticky top-0 z-10 border-b border-warm-200">
        <div className="flex items-center gap-2">
          <Coffee size={18} className="text-forest" />
          <span className="text-sm font-bold text-warm-700">Sistema Café</span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-warm-500">{user?.nombre}</span>
          <button
            onClick={() => { logout(); navigate('/login') }}
            className="text-xs text-warm-400 hover:text-red-500 flex items-center gap-1 transition-colors"
          >
            <LogOut size={13} /> Salir
          </button>
        </div>
      </div>

      {/* Step indicator (5 segments, step 1 active) */}
      <div className="flex gap-1 px-5 pt-4 max-w-md mx-auto w-full">
        {[0,1,2,3,4].map(i => (
          <div key={i} className="flex-1 h-1 rounded-full"
            style={{
              background: i === 0 ? 'oklch(68% 0.14 65)' : 'oklch(92% 0.006 75)',
            }}
          />
        ))}
      </div>

      <div className="flex-1 px-4 pb-10 max-w-md mx-auto w-full space-y-5 pt-4">
        {/* Title */}
        <div>
          <p className="text-xs font-semibold text-forest uppercase tracking-widest mb-1">Paso 1 de 5</p>
          <h1 className="text-2xl font-bold text-warm-700">Apertura de caja</h1>
          <p className="text-sm text-warm-500 mt-0.5">
            {new Date().toLocaleDateString('es-CO', { weekday: 'long', day: 'numeric', month: 'long' })}
          </p>
        </div>

        {error && (
          <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 text-sm px-4 py-3 rounded-xl">
            <AlertTriangle size={14} /> {error}
          </div>
        )}

        {/* Toggle contador */}
        <button
          onClick={() => setShowContador(!showContador)}
          className="w-full flex items-center justify-between px-4 py-3 bg-white rounded-xl border-2 border-dashed border-warm-200 hover:border-forest transition-colors"
        >
          <div className="flex items-center gap-2">
            <Coins size={16} className="text-forest" />
            <span className="text-sm font-semibold text-warm-700">
              {showContador ? 'Ocultar contador de billetes/monedas' : 'Contar billetes y monedas'}
            </span>
          </div>
          {showContador ? <ChevronUp size={16} className="text-warm-400" /> : <ChevronDown size={16} className="text-warm-400" />}
        </button>

        {showContador && <ContadorEfectivo onTotal={total => { if (total > 0) setBaseReal(String(total)) }} />}

        {/* Confirmation panel */}
        <div className="bg-white rounded-2xl border border-warm-200 p-5 shadow-sm space-y-4">
          <div>
            <label className="text-xs font-semibold text-warm-500 uppercase tracking-wide block mb-2">
              Total en caja
            </label>
            <div className="relative">
              <span className="absolute left-4 top-1/2 -translate-y-1/2 text-xl font-bold text-warm-400">$</span>
              <input
                type="number"
                value={baseReal}
                onChange={e => setBaseReal(e.target.value)}
                placeholder="0"
                className="w-full pl-10 pr-4 py-4 text-3xl font-bold text-warm-700 border-2 border-warm-200 rounded-xl focus:outline-none transition-colors"
                style={{ fontFamily: '"JetBrains Mono", monospace' }}
                onFocus={e => (e.target.style.borderColor = 'oklch(35% 0.05 155)')}
                onBlur={e => (e.target.style.borderColor = '')}
              />
            </div>
            {baseSistema > 0 && (
              <p className="text-xs text-warm-400 mt-1.5">
                Base esperada del sistema: <span className="font-mono font-semibold">{fmt(baseSistema)}</span>
              </p>
            )}
          </div>

          {/* Difference panel */}
          {hayDiff && (
            <div
              className="flex items-center justify-between p-3 rounded-xl"
              style={{
                background: 'linear-gradient(180deg, oklch(98% 0.01 25), oklch(96% 0.02 25))',
                border: '1.5px solid oklch(88% 0.06 25)',
              }}
            >
              <span className="text-sm font-medium text-red-700">Diferencia vs sistema</span>
              <span className="text-lg font-bold text-red-700 font-mono">
                {diff > 0 ? '+' : ''}{fmt(diff)}
              </span>
            </div>
          )}

          {hayDiff && (
            <div>
              <label className="text-xs font-semibold text-red-500 uppercase tracking-wide block mb-2">
                Justificación obligatoria
              </label>
              <textarea
                value={justificacion}
                onChange={e => setJustificacion(e.target.value)}
                placeholder="Explica la diferencia..."
                rows={2}
                className="w-full border-2 border-red-200 rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-red-400 resize-none"
              />
            </div>
          )}

          <button
            onClick={abrir}
            disabled={!canSubmit || loading}
            className="w-full disabled:opacity-40 disabled:cursor-not-allowed text-white font-bold py-4 rounded-xl text-base flex items-center justify-center gap-2 transition-colors"
            style={{ background: 'oklch(35% 0.05 155)' }}
            onMouseEnter={e => { if (canSubmit && !loading) (e.target as HTMLElement).style.background = 'oklch(30% 0.05 155)' }}
            onMouseLeave={e => { (e.target as HTMLElement).style.background = 'oklch(35% 0.05 155)' }}
          >
            {loading ? 'Abriendo...' : <>Abrir turno <ArrowRight size={18} /></>}
          </button>
        </div>
      </div>
    </div>
  )
}
