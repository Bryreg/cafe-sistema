import { useState, useEffect, useRef } from 'react'
import { X, CreditCard, Banknote, AlertTriangle, CheckCircle2 } from 'lucide-react'
import api from '../api/client'
import { useAuth } from '../contexts/AuthContext'
import TicketRecibo, { type TicketData } from './TicketRecibo'

// Extrae un mensaje de error legible. El backend puede devolver `detail` como
// string (errores de negocio) o como array de objetos (errores de validación
// 422 de FastAPI: [{type, loc, msg, input}]). Nunca devolver un objeto: si se
// pasa a setError y se renderiza en JSX, React lanza el error #31 y la app
// queda en blanco.
function extractError(e: any): string {
  const d = e?.response?.data?.detail
  if (typeof d === 'string') return d
  if (Array.isArray(d)) {
    const msg = d.map((x: any) => x?.msg).filter(Boolean).join(', ')
    return msg || 'Datos inválidos en el cobro'
  }
  if (d && typeof d === 'object' && typeof d.msg === 'string') return d.msg
  return 'Error al procesar el cobro'
}

interface CartItem {
  producto_id: number
  nombre: string
  cantidad: number
  precio_venta: number
}

interface Props {
  items: CartItem[]
  totalEstimado: number
  onClose: () => void
  onSuccess: () => void
}

const fmtCO = (v: number) => `$${v.toLocaleString('es-CO')}`

const MONTOS_RAPIDOS = [10_000, 20_000, 50_000, 100_000]

type Metodo = 'efectivo' | 'tarjeta' | 'mixto'

export default function CheckoutModal({ items, totalEstimado, onClose, onSuccess }: Props) {
  const { user } = useAuth()
  const [metodo, setMetodo] = useState<Metodo>('efectivo')
  const [recibido, setRecibido] = useState('')
  const [montoEfectivo, setMontoEfectivo] = useState('')
  const [montoTarjeta, setMontoTarjeta] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [ticket, setTicket] = useState<TicketData | null>(null)
  const [confirmed, setConfirmed] = useState(false)
  const [cambioFinal, setCambioFinal] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (metodo === 'efectivo') setTimeout(() => inputRef.current?.focus(), 100)
  }, [metodo])

  const numRecibido = Number(recibido) || 0
  const cambio = metodo === 'efectivo' ? numRecibido - totalEstimado : 0
  const canConfirm = (() => {
    if (loading) return false
    if (metodo === 'efectivo') return numRecibido >= totalEstimado
    if (metodo === 'tarjeta') return true
    // mixto: los dos montos deben sumar el total
    const ef = Number(montoEfectivo) || 0
    const tar = Number(montoTarjeta) || 0
    return ef + tar === totalEstimado && ef > 0 && tar > 0
  })()

  const confirmar = async () => {
    setError('')
    setLoading(true)
    try {
      const body: Record<string, unknown> = {
        tienda_id: user?.tienda_id,
        items: items.map(i => ({ producto_id: i.producto_id, cantidad: i.cantidad })),
        metodo_pago: metodo,
      }
      if (metodo === 'efectivo') body.efectivo_recibido = numRecibido
      if (metodo === 'mixto') {
        body.monto_efectivo = Number(montoEfectivo)
        body.monto_tarjeta = Number(montoTarjeta)
      }

      const { data } = await api.post<TicketData>('/pos/ticket', body)
      setTicket(data)
      setConfirmed(true)
      setCambioFinal(metodo === 'efectivo' ? numRecibido - totalEstimado : 0)

      // Pequeño delay para que el DOM del ticket monte antes de imprimir
      setTimeout(() => {
        window.print()
        onSuccess()
      }, 150)
    } catch (e: any) {
      setError(extractError(e))
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      {/* Backdrop — bloqueado durante el procesamiento para evitar cierre accidental */}
      <div
        className="fixed inset-0 z-50 bg-black/60 flex items-end justify-center"
        onClick={loading ? undefined : onClose}
      >
        <div
          className="w-full max-w-lg bg-white rounded-t-3xl"
          style={{ paddingBottom: 'calc(env(safe-area-inset-bottom, 0px) + 1.5rem)' }}
          onClick={e => e.stopPropagation()}
        >
          {/* Drag handle */}
          <div className="flex justify-center pt-3 pb-1">
            <div className="w-10 h-1 rounded-full bg-warm-200" />
          </div>

          {/* Header */}
          <div className="flex items-center justify-between px-5 pt-2 pb-4 border-b border-warm-100">
            <p className="text-base font-bold text-gray-800">Cobrar</p>
            <button
              onClick={onClose}
              disabled={loading}
              className="p-1.5 rounded-lg text-warm-400 hover:text-warm-600 hover:bg-warm-100 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
            >
              <X size={18} />
            </button>
          </div>

          <div className="px-5 pt-4 space-y-4">
            {/* Estado de éxito — se muestra brevemente antes de que onSuccess cierre el modal */}
            {confirmed && (
              <div className="flex flex-col items-center gap-3 py-6">
                <CheckCircle2 size={52} className="text-green-500" />
                <p className="text-lg font-bold text-gray-800">Venta registrada</p>
                {cambioFinal > 0 && (
                  <div className="bg-green-50 border border-green-200 rounded-2xl px-6 py-3 text-center">
                    <p className="text-xs font-semibold text-green-600 uppercase tracking-wide mb-0.5">Cambio</p>
                    <p className="text-3xl font-bold text-green-700">{fmtCO(cambioFinal)}</p>
                  </div>
                )}
                <p className="text-sm text-gray-400">Imprimiendo ticket…</p>
              </div>
            )}

            {/* Formulario de cobro — oculto tras confirmar */}
            {!confirmed && (
            <>
            {/* Total */}
            <div className="bg-gray-50 rounded-2xl p-4 text-center border border-gray-100">
              <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">Total a cobrar</p>
              <p className="text-4xl font-bold text-gray-900">{fmtCO(totalEstimado)}</p>
            </div>

            {/* Método de pago */}
            <div>
              <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">Método de pago</p>
              <div className="grid grid-cols-3 gap-2">
                {(['efectivo', 'tarjeta', 'mixto'] as Metodo[]).map(m => {
                  const label = m === 'efectivo' ? 'Efectivo' : m === 'tarjeta' ? 'Tarjeta' : 'Mixto'
                  const Icon = m === 'tarjeta' ? CreditCard : Banknote
                  const active = metodo === m
                  return (
                    <button
                      key={m}
                      onClick={() => { setMetodo(m); setError('') }}
                      className="flex flex-col items-center gap-1.5 py-3 rounded-2xl border-2 transition-all font-semibold text-sm"
                      style={active ? {
                        borderColor: 'oklch(48% 0.12 155)',
                        background: 'oklch(96% 0.015 155)',
                        color: 'oklch(30% 0.10 155)',
                      } : {
                        borderColor: 'oklch(88% 0.006 75)',
                        background: '#fff',
                        color: 'oklch(55% 0.01 60)',
                      }}
                    >
                      <Icon size={18} />
                      {label}
                    </button>
                  )
                })}
              </div>
            </div>

            {/* Panel efectivo */}
            {metodo === 'efectivo' && (
              <div className="space-y-3">
                <div>
                  <label className="text-xs font-semibold text-gray-500 block mb-1.5">
                    ¿Con cuánto paga?
                  </label>
                  <div className="relative">
                    <span className="absolute left-4 top-1/2 -translate-y-1/2 text-xl font-bold text-gray-300">$</span>
                    <input
                      ref={inputRef}
                      type="number"
                      inputMode="numeric"
                      value={recibido}
                      onChange={e => setRecibido(e.target.value)}
                      placeholder="0"
                      className="w-full pl-10 pr-4 py-3.5 text-3xl font-bold text-gray-900 border-2 border-gray-200 rounded-xl focus:outline-none focus:border-amber-400 transition-colors"
                    />
                  </div>
                </div>

                {/* Montos rápidos */}
                <div className="grid grid-cols-4 gap-2">
                  <button
                    onClick={() => setRecibido(String(totalEstimado))}
                    className="py-2 rounded-xl border-2 border-gray-200 text-xs font-bold text-gray-600 hover:border-amber-400 hover:text-amber-700 transition-colors"
                  >
                    Exacto
                  </button>
                  {MONTOS_RAPIDOS.filter(m => m >= totalEstimado).slice(0, 3).map(m => (
                    <button
                      key={m}
                      onClick={() => setRecibido(String(m))}
                      className="py-2 rounded-xl border-2 border-gray-200 text-xs font-bold text-gray-600 hover:border-amber-400 hover:text-amber-700 transition-colors"
                    >
                      {fmtCO(m)}
                    </button>
                  ))}
                </div>

                {/* Cambio en vivo */}
                {numRecibido > 0 && (
                  <div className={`rounded-2xl p-4 flex items-center justify-between ${cambio < 0 ? 'bg-red-50 border border-red-200' : 'bg-green-50 border border-green-200'}`}>
                    <span className={`text-sm font-semibold ${cambio < 0 ? 'text-red-700' : 'text-green-700'}`}>
                      {cambio < 0 ? 'Falta' : 'Cambio'}
                    </span>
                    <span className={`text-2xl font-bold ${cambio < 0 ? 'text-red-700' : 'text-green-700'}`}>
                      {fmtCO(Math.abs(cambio))}
                    </span>
                  </div>
                )}
              </div>
            )}

            {/* Panel tarjeta */}
            {metodo === 'tarjeta' && (
              <div className="bg-blue-50 border border-blue-200 rounded-2xl p-4 text-center">
                <CreditCard size={28} className="mx-auto text-blue-400 mb-2" />
                <p className="text-sm font-semibold text-blue-800">Pago con datáfono</p>
                <p className="text-xs text-blue-600 mt-1">Confirmá el pago en el dispositivo antes de continuar</p>
              </div>
            )}

            {/* Panel mixto */}
            {metodo === 'mixto' && (
              <div className="space-y-3">
                <p className="text-xs text-gray-400 text-center">
                  Los dos montos deben sumar <strong>{fmtCO(totalEstimado)}</strong>
                </p>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-xs font-semibold text-gray-500 block mb-1">Efectivo</label>
                    <div className="relative">
                      <span className="absolute left-3 top-1/2 -translate-y-1/2 text-sm font-bold text-gray-300">$</span>
                      <input
                        type="number"
                        inputMode="numeric"
                        value={montoEfectivo}
                        onChange={e => {
                          setMontoEfectivo(e.target.value)
                          const ef = Number(e.target.value) || 0
                          const resta = totalEstimado - ef
                          if (resta >= 0) setMontoTarjeta(String(resta))
                        }}
                        placeholder="0"
                        className="w-full pl-8 pr-3 py-3 text-lg font-bold border-2 border-gray-200 rounded-xl focus:outline-none focus:border-amber-400"
                      />
                    </div>
                  </div>
                  <div>
                    <label className="text-xs font-semibold text-gray-500 block mb-1">Tarjeta</label>
                    <div className="relative">
                      <span className="absolute left-3 top-1/2 -translate-y-1/2 text-sm font-bold text-gray-300">$</span>
                      <input
                        type="number"
                        inputMode="numeric"
                        value={montoTarjeta}
                        onChange={e => setMontoTarjeta(e.target.value)}
                        placeholder="0"
                        className="w-full pl-8 pr-3 py-3 text-lg font-bold border-2 border-gray-200 rounded-xl focus:outline-none focus:border-blue-400"
                      />
                    </div>
                  </div>
                </div>
                {(() => {
                  const suma = (Number(montoEfectivo) || 0) + (Number(montoTarjeta) || 0)
                  const diff = suma - totalEstimado
                  if (suma === 0) return null
                  return (
                    <div className={`rounded-xl p-3 flex items-center justify-between text-sm font-semibold ${diff === 0 ? 'bg-green-50 border border-green-200 text-green-700' : 'bg-red-50 border border-red-200 text-red-700'}`}>
                      <span>{diff === 0 ? 'Suma correcta' : diff > 0 ? 'Suma de más' : 'Falta'}</span>
                      {diff !== 0 && <span>{fmtCO(Math.abs(diff))}</span>}
                    </div>
                  )
                })()}
              </div>
            )}

            {/* Error — panel visible, invita a reintentar sin perder el carrito */}
            {error && (
              <div className="bg-red-50 border border-red-200 rounded-xl px-4 py-3 space-y-1.5">
                <div className="flex items-center gap-2 text-red-700 text-sm font-semibold">
                  <AlertTriangle size={14} className="shrink-0" />
                  {error}
                </div>
                <p className="text-xs text-red-500 pl-5">
                  Tu cuenta sigue intacta — podés reintentar o cambiar el método de pago.
                </p>
              </div>
            )}

            {/* CTA */}
            <button
              onClick={confirmar}
              disabled={!canConfirm}
              className="w-full font-bold py-4 rounded-2xl text-base transition-all active:scale-[0.98] disabled:opacity-40 disabled:cursor-not-allowed"
              style={{
                background: canConfirm ? 'linear-gradient(135deg, oklch(48% 0.12 155), oklch(40% 0.12 155))' : 'oklch(88% 0.006 75)',
                color: canConfirm ? '#fff' : 'oklch(55% 0.01 60)',
              }}
            >
              {loading ? 'Procesando...' : `Confirmar y cobrar ${fmtCO(totalEstimado)}`}
            </button>
            </>
            )}
          </div>
        </div>
      </div>

      {/* Ticket montado en DOM (oculto en pantalla, visible en impresión) */}
      {ticket && <TicketRecibo ticket={ticket} />}
    </>
  )
}
