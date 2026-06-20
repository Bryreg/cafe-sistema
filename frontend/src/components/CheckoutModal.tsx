import { useState, useEffect, useRef } from 'react'
import { CreditCard, Banknote, CheckCircle2 } from 'lucide-react'
import api from '../api/client'
import { useAuth } from '../contexts/AuthContext'
import TicketRecibo, { type TicketData } from './TicketRecibo'
import Numpad from './Numpad'
import { Sheet, MoneyInput, Toast, SectionLabel, Pill } from './ui'

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
  descuento?: number
}

interface Props {
  items: CartItem[]
  totalEstimado: number
  onClose: () => void
  onSuccess: () => void
}

const fmtCO = (v: number) => `$${v.toLocaleString('es-CO')}`

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
        items: items.map(i => ({ producto_id: i.producto_id, cantidad: i.cantidad, descuento: i.descuento || 0 })),
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
      {/* Sheet maneja: bottom-sheet en mobile, dialog centrado en desktop,
          backdrop, Escape, safe-area. dismissable=false bloquea durante loading. */}
      <Sheet
        open
        onClose={onClose}
        title="Cobrar"
        dismissable={!loading}
      >
        {/* Panel de éxito — visible brevemente antes de que onSuccess cierre el modal */}
        {confirmed && (
          <div className="flex flex-col items-center gap-3 py-8 pb-4">
            <CheckCircle2 size={52} className="text-success-500" />
            <p className="text-lg font-bold text-bark-800">Venta registrada</p>
            {cambioFinal > 0 && (
              <div className="bg-success-50 border border-success-200 rounded-2xl px-6 py-3 text-center w-full">
                <p className="text-[11px] font-bold uppercase tracking-wide text-success-600 mb-0.5">Cambio</p>
                <p className="text-3xl font-bold font-mono tabular-nums text-success-700">{fmtCO(cambioFinal)}</p>
              </div>
            )}
            <p className="text-sm text-warm-400 pb-2">Imprimiendo ticket…</p>
          </div>
        )}

        {/* Formulario de cobro — oculto tras confirmar */}
        {!confirmed && (
          <div className="space-y-4 pb-4">

            {/* Total a cobrar (ya con descuentos por producto aplicados) */}
            <div className="bg-warm-50 rounded-2xl p-4 text-center border border-warm-200">
              <SectionLabel className="mb-1">Total a cobrar</SectionLabel>
              <p className="text-4xl font-bold font-mono tabular-nums text-bark-900">{fmtCO(totalEstimado)}</p>
            </div>

            {/* Método de pago */}
            <div>
              <SectionLabel className="mb-2">Método de pago</SectionLabel>
              <div className="grid grid-cols-3 gap-2">
                {(['efectivo', 'tarjeta', 'mixto'] as Metodo[]).map(m => {
                  const label = m === 'efectivo' ? 'Efectivo' : m === 'tarjeta' ? 'Tarjeta' : 'Mixto'
                  const Icon = m === 'tarjeta' ? CreditCard : Banknote
                  const active = metodo === m
                  return (
                    <button
                      key={m}
                      type="button"
                      onClick={() => { setMetodo(m); setError('') }}
                      className={[
                        'flex flex-col items-center gap-1.5 py-3 rounded-2xl border-2 transition-all font-semibold text-sm',
                        active
                          ? 'border-success-400 bg-success-50 text-success-700'
                          : 'border-warm-200 bg-white text-warm-500 hover:border-warm-300',
                      ].join(' ')}
                    >
                      <Icon size={18} />
                      {label}
                    </button>
                  )
                })}
              </div>
            </div>

            {/* Panel efectivo — input + numpad */}
            {metodo === 'efectivo' && (
              <div className="space-y-3">
                <MoneyInput
                  label="¿Con cuánto paga?"
                  value={recibido}
                  onChange={setRecibido}
                  inputRef={inputRef}
                  size="lg"
                />

                {/* Numpad en pantalla */}
                <Numpad
                  value={recibido}
                  onValue={setRecibido}
                  onQuick={amount => setRecibido(String(amount))}
                  totalEstimado={totalEstimado}
                />

                {/* Cambio en vivo */}
                {numRecibido > 0 && (
                  <div className={`rounded-2xl p-4 flex items-center justify-between border ${cambio < 0 ? 'bg-danger-50 border-danger-200' : 'bg-success-50 border-success-200'}`}>
                    <span className={`text-sm font-semibold ${cambio < 0 ? 'text-danger-700' : 'text-success-700'}`}>
                      {cambio < 0 ? 'Falta' : 'Cambio'}
                    </span>
                    <span className={`text-2xl font-bold font-mono tabular-nums ${cambio < 0 ? 'text-danger-700' : 'text-success-700'}`}>
                      {fmtCO(Math.abs(cambio))}
                    </span>
                  </div>
                )}
              </div>
            )}

            {/* Panel tarjeta */}
            {metodo === 'tarjeta' && (
              <div className="bg-warm-50 border border-warm-200 rounded-2xl p-4 text-center">
                <CreditCard size={28} className="mx-auto text-warm-400 mb-2" />
                <p className="text-sm font-semibold text-bark-700">Pago con datáfono</p>
                <p className="text-xs text-warm-500 mt-1">Confirmá el pago en el dispositivo antes de continuar</p>
              </div>
            )}

            {/* Panel mixto */}
            {metodo === 'mixto' && (
              <div className="space-y-3">
                <p className="text-xs text-warm-500 text-center">
                  Los dos montos deben sumar{' '}
                  <Pill tone="clay" className="font-mono tabular-nums">{fmtCO(totalEstimado)}</Pill>
                </p>
                <div className="grid grid-cols-2 gap-3">
                  <MoneyInput
                    label="Efectivo"
                    size="sm"
                    value={montoEfectivo}
                    onChange={v => {
                      setMontoEfectivo(v)
                      const ef = Number(v) || 0
                      const resta = totalEstimado - ef
                      if (resta >= 0) setMontoTarjeta(String(resta))
                    }}
                  />
                  <MoneyInput
                    label="Tarjeta"
                    size="sm"
                    value={montoTarjeta}
                    onChange={setMontoTarjeta}
                  />
                </div>
                {(() => {
                  const suma = (Number(montoEfectivo) || 0) + (Number(montoTarjeta) || 0)
                  const diff = suma - totalEstimado
                  if (suma === 0) return null
                  return (
                    <div className={`rounded-xl p-3 flex items-center justify-between text-sm font-semibold border ${diff === 0 ? 'bg-success-50 border-success-200 text-success-700' : 'bg-danger-50 border-danger-200 text-danger-700'}`}>
                      <span>{diff === 0 ? 'Suma correcta' : diff > 0 ? 'Suma de más' : 'Falta'}</span>
                      {diff !== 0 && (
                        <span className="font-mono tabular-nums">{fmtCO(Math.abs(diff))}</span>
                      )}
                    </div>
                  )
                })()}
              </div>
            )}

            {/* Error — panel visible, invita a reintentar sin perder el carrito */}
            {error && (
              <div className="space-y-1">
                <Toast tone="danger">{error}</Toast>
                <p className="text-xs text-danger-500 pl-5">
                  Tu cuenta sigue intacta — podés reintentar o cambiar el método de pago.
                </p>
              </div>
            )}

            {/* CTA principal con token clay */}
            <button
              type="button"
              onClick={confirmar}
              disabled={!canConfirm}
              className={[
                'w-full font-bold py-4 rounded-2xl text-base transition-all active:scale-[0.98]',
                'disabled:opacity-40 disabled:cursor-not-allowed',
                canConfirm
                  ? 'bg-clay-500 hover:bg-clay-600 text-white'
                  : 'bg-warm-100 text-warm-400',
              ].join(' ')}
            >
              {loading ? 'Procesando...' : `Confirmar y cobrar ${fmtCO(totalEstimado)}`}
            </button>
          </div>
        )}
      </Sheet>

      {/* Ticket montado en DOM (oculto en pantalla, visible en impresión) */}
      {ticket && <TicketRecibo ticket={ticket} />}
    </>
  )
}
