import { useEffect, useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'
import { Send, AlertTriangle, Check, ChevronDown, ChevronUp } from 'lucide-react'
import BaristaLayout from '../components/BaristaLayout'

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

const fmt = (v: number) => `$${v.toLocaleString('es-CO')}`

interface Sencilla {
  id: number
  monto_solicitado: number
  motivo: string
  detalle: string | null
  estado: string
  fecha_solicitud: string
}

// ─── Fila: input en pesos → calcula cantidad ──────────────────────────────────
function FilaDenom({
  item, monto, onChange,
}: {
  item: { valor: number; label: string; tipo: string }
  monto: string
  onChange: (v: string) => void
}) {
  const montoNum = Number(monto) || 0
  const esMultiplo = montoNum > 0 && montoNum % item.valor === 0
  const esError    = montoNum > 0 && montoNum % item.valor !== 0
  const cantidad   = esMultiplo ? montoNum / item.valor : null
  const esBillete  = item.tipo === 'billete'

  return (
    <div className={`px-4 py-3 ${montoNum > 0 ? (esBillete ? 'bg-green-50' : 'bg-amber-50') : ''} transition-colors`}>
      <div className="flex items-center gap-3">
        {/* Etiqueta denominación */}
        <div className={`w-16 shrink-0 text-center py-1 rounded-lg text-xs font-bold ${
          esBillete
            ? 'bg-green-100 text-green-800 border border-green-200'
            : 'bg-amber-100 text-amber-800 border border-amber-200'
        }`}>
          {item.label}
        </div>

        {/* Input: monto en pesos */}
        <div className="flex-1 relative">
          <span className="absolute left-3 top-1/2 -translate-y-1/2 text-sm font-bold text-gray-400">$</span>
          <input
            type="number"
            value={monto}
            onChange={e => onChange(e.target.value)}
            placeholder="0"
            step={item.valor}
            inputMode="numeric"
            className={`w-full pl-7 pr-3 py-2 text-base font-bold border-2 rounded-xl focus:outline-none transition-colors ${
              esError
                ? 'border-red-300 text-red-700 focus:border-red-400 bg-red-50'
                : 'border-gray-200 focus:border-amber-400'
            }`}
          />
        </div>

        {/* Resultado: cuántos billetes/monedas */}
        <div className="w-24 text-right shrink-0 text-xs">
          {esMultiplo ? (
            <span className="font-semibold text-gray-700">
              {cantidad} {item.tipo}{cantidad !== 1 ? 's' : ''}
            </span>
          ) : esError ? (
            <span className="text-red-500 font-semibold">no válido</span>
          ) : (
            <span className="text-gray-300">—</span>
          )}
        </div>
      </div>

      {esError && (
        <p className="text-xs text-red-500 mt-1 pl-19">
          Debe ser múltiplo de {fmt(item.valor)}
        </p>
      )}
    </div>
  )
}

// ─── Historial ────────────────────────────────────────────────────────────────
function DetalleHistorial({ detalle }: { detalle: string | null }) {
  if (!detalle) return null
  try {
    const items: { label: string; tipo: string; monto: number; cantidad: number }[] = JSON.parse(detalle)
    return (
      <div className="mt-2 space-y-1">
        {items.map((item, i) => (
          <div key={i} className="flex items-center justify-between text-xs">
            <div className="flex items-center gap-1.5">
              <span className={`px-1.5 py-0.5 rounded font-bold ${
                item.tipo === 'billete' ? 'bg-green-100 text-green-700' : 'bg-amber-100 text-amber-700'
              }`}>{item.label}</span>
              <span className="text-gray-500">× {item.cantidad}</span>
            </div>
            <span className="font-semibold text-gray-700">{fmt(item.monto)}</span>
          </div>
        ))}
      </div>
    )
  } catch { return null }
}

// ─── Página principal ─────────────────────────────────────────────────────────
export default function SolicitudSencilla() {
  const { user } = useAuth()
  const [lista, setLista] = useState<Sencilla[]>([])
  // montos['b-2000'] = '100000', montos['m-100'] = '5000', etc.
  const [montos, setMontos] = useState<Record<string, string>>({})
  const [showBilletes, setShowBilletes] = useState(true)
  const [showMonedas, setShowMonedas]   = useState(true)
  const [motivo, setMotivo] = useState('')
  const [error, setError]   = useState('')
  const [saved, setSaved]   = useState(false)
  const [saving, setSaving] = useState(false)

  const load = async () => {
    if (!user?.tienda_id) return
    const { data } = await api.get(`/solicitudes/sencilla/tienda/${user.tienda_id}`)
    setLista(data)
  }

  useEffect(() => { load() }, [user])

  const key = (tipo: string, valor: number) => `${tipo[0]}-${valor}`

  const getMonto = (tipo: string, valor: number) => montos[key(tipo, valor)] ?? ''
  const setMonto = (tipo: string, valor: number, v: string) =>
    setMontos(prev => ({ ...prev, [key(tipo, valor)]: v }))

  const totalBilletes = BILLETES.reduce((s, b) => {
    const m = Number(montos[key('billete', b.valor)]) || 0
    return s + (m % b.valor === 0 ? m : 0)
  }, 0)
  const totalMonedas = MONEDAS.reduce((s, m) => {
    const v = Number(montos[key('moneda', m.valor)]) || 0
    return s + (v % m.valor === 0 ? v : 0)
  }, 0)
  const total = totalBilletes + totalMonedas

  const hayErrores = [
    ...BILLETES.map(b => { const m = Number(montos[key('billete', b.valor)]) || 0; return m > 0 && m % b.valor !== 0 }),
    ...MONEDAS.map(m => { const v = Number(montos[key('moneda', m.valor)]) || 0; return v > 0 && v % m.valor !== 0 }),
  ].some(Boolean)

  const limpiar = () => setMontos({})

  const detalleItems = [
    ...BILLETES.filter(b => {
      const m = Number(montos[key('billete', b.valor)]) || 0
      return m > 0 && m % b.valor === 0
    }).map(b => {
      const m = Number(montos[key('billete', b.valor)])
      return { label: b.label, tipo: b.tipo, valor: b.valor, monto: m, cantidad: m / b.valor }
    }),
    ...MONEDAS.filter(m => {
      const v = Number(montos[key('moneda', m.valor)]) || 0
      return v > 0 && v % m.valor === 0
    }).map(m => {
      const v = Number(montos[key('moneda', m.valor)])
      return { label: m.label, tipo: m.tipo, valor: m.valor, monto: v, cantidad: v / m.valor }
    }),
  ]

  const canSend = total > 0 && !hayErrores && motivo.trim()

  const enviar = async () => {
    setError(''); setSaving(true)
    try {
      await api.post('/solicitudes/sencilla', {
        tienda_id: user?.tienda_id,
        monto_solicitado: total,
        motivo,
        detalle: JSON.stringify(detalleItems),
      })
      limpiar(); setMotivo('')
      setSaved(true); setTimeout(() => setSaved(false), 2500)
      load()
    } catch (e: any) { setError(e.response?.data?.detail || 'Error') }
    finally { setSaving(false) }
  }

  const estadoBadge = (estado: string) => (
    <span className={`text-xs px-2 py-0.5 rounded-full font-semibold ${
      estado === 'pendiente' ? 'bg-amber-100 text-amber-700' :
      estado === 'aprobada'  ? 'bg-green-100 text-green-700' :
                               'bg-red-100 text-red-700'
    }`}>{estado}</span>
  )

  return (
    <BaristaLayout title="Solicitar sencilla">
      <div className="space-y-5">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Solicitar sencilla</h1>
          <p className="text-sm text-gray-500 mt-0.5">Escribe cuánto necesitas en cada denominación.</p>
        </div>

        {error && (
          <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 text-sm px-4 py-3 rounded-xl">
            <AlertTriangle size={14} /> {error}
          </div>
        )}
        {saved && (
          <div className="flex items-center gap-2 bg-green-50 border border-green-200 text-green-700 text-sm px-4 py-3 rounded-xl">
            <Check size={14} /> Solicitud enviada al administrador
          </div>
        )}

        {/* Contador */}
        <div className="bg-white rounded-2xl border border-gray-200 overflow-hidden shadow-sm">

          {/* Billetes */}
          <div>
            <button onClick={() => setShowBilletes(!showBilletes)}
              className="w-full flex items-center justify-between px-4 py-2.5 bg-green-50 hover:bg-green-100 transition-colors">
              <div className="flex items-center gap-2">
                <span className="text-xs font-bold text-green-700 uppercase tracking-wide">Billetes</span>
                {totalBilletes > 0 && (
                  <span className="text-xs font-bold text-green-800 bg-green-200 px-2 py-0.5 rounded-full">{fmt(totalBilletes)}</span>
                )}
              </div>
              {showBilletes ? <ChevronUp size={14} className="text-green-600" /> : <ChevronDown size={14} className="text-green-600" />}
            </button>
            {showBilletes && (
              <div className="divide-y divide-gray-50">
                {BILLETES.map(b => (
                  <FilaDenom key={b.valor} item={b}
                    monto={getMonto('billete', b.valor)}
                    onChange={v => setMonto('billete', b.valor, v)} />
                ))}
              </div>
            )}
          </div>

          {/* Monedas */}
          <div className="border-t border-gray-100">
            <button onClick={() => setShowMonedas(!showMonedas)}
              className="w-full flex items-center justify-between px-4 py-2.5 bg-amber-50 hover:bg-amber-100 transition-colors">
              <div className="flex items-center gap-2">
                <span className="text-xs font-bold text-amber-700 uppercase tracking-wide">Monedas</span>
                {totalMonedas > 0 && (
                  <span className="text-xs font-bold text-amber-800 bg-amber-200 px-2 py-0.5 rounded-full">{fmt(totalMonedas)}</span>
                )}
              </div>
              {showMonedas ? <ChevronUp size={14} className="text-amber-600" /> : <ChevronDown size={14} className="text-amber-600" />}
            </button>
            {showMonedas && (
              <div className="divide-y divide-gray-50">
                {MONEDAS.map(m => (
                  <FilaDenom key={m.valor} item={m}
                    monto={getMonto('moneda', m.valor)}
                    onChange={v => setMonto('moneda', m.valor, v)} />
                ))}
              </div>
            )}
          </div>

          {/* Total */}
          <div className={`px-4 py-4 border-t-2 ${total > 0 ? 'border-amber-300 bg-amber-50' : 'border-gray-100'}`}>
            <div className="flex items-center justify-between">
              <span className="text-sm font-semibold text-gray-600">Total a cambiar</span>
              <span className={`text-2xl font-bold ${total > 0 ? 'text-amber-700' : 'text-gray-300'}`}>
                {total > 0 ? fmt(total) : '$0'}
              </span>
            </div>
            {total > 0 && (
              <p className="text-xs text-amber-600 mt-1 text-right">
                {fmt(totalBilletes)} en billetes · {fmt(totalMonedas)} en monedas
              </p>
            )}
            {hayErrores && (
              <p className="text-xs text-red-500 mt-1 text-right">Corrige los montos marcados en rojo</p>
            )}
          </div>
        </div>

        {/* Motivo + enviar */}
        {total > 0 && (
          <div className="bg-white rounded-2xl border border-gray-200 p-5 space-y-4">
            <div>
              <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-1.5">
                Motivo / nota para el admin
              </label>
              <input
                value={motivo}
                onChange={e => setMotivo(e.target.value)}
                placeholder="Ej: cambio para el turno de la tarde"
                className="w-full border-2 border-gray-200 rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-amber-400 transition-colors"
              />
            </div>
            <div className="flex gap-3">
              <button onClick={limpiar}
                className="px-4 py-3 rounded-xl border-2 border-gray-200 text-sm font-semibold text-gray-500 hover:border-gray-300 transition-colors">
                Limpiar
              </button>
              <button onClick={enviar} disabled={!canSend || saving}
                className="flex-1 bg-amber-600 hover:bg-amber-700 disabled:opacity-40 disabled:cursor-not-allowed text-white font-bold py-3 rounded-xl text-sm flex items-center justify-center gap-2 transition-colors">
                <Send size={15} />
                {saving ? 'Enviando...' : 'Enviar solicitud'}
              </button>
            </div>
          </div>
        )}

        {total === 0 && !hayErrores && (
          <div className="bg-gray-50 border border-dashed border-gray-300 rounded-2xl px-4 py-8 text-center">
            <p className="text-sm text-gray-400">Escribe el monto que necesitas en cada denominación.</p>
          </div>
        )}

        {/* Historial */}
        {lista.length > 0 && (
          <div className="bg-white rounded-2xl border border-gray-200 overflow-hidden">
            <div className="px-4 py-2.5 border-b border-gray-100">
              <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Historial</p>
            </div>
            <div className="divide-y divide-gray-50">
              {lista.map(s => (
                <div key={s.id} className="px-4 py-3">
                  <div className="flex items-start justify-between">
                    <div className="flex-1">
                      <p className="text-sm font-bold text-gray-800">{fmt(s.monto_solicitado)}</p>
                      <p className="text-xs text-gray-500">{s.motivo}</p>
                      <DetalleHistorial detalle={s.detalle} />
                    </div>
                    <div className="ml-3 shrink-0">{estadoBadge(s.estado)}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </BaristaLayout>
  )
}
