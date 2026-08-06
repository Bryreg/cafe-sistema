import { useState } from 'react'
import { X } from 'lucide-react'
import api from '../../api/client'
import { conMiles, soloDigitos } from '../../utils/plata'
import { hoyBogota } from '../../utils/fechaLocal'

const METODOS = ['transferencia', 'efectivo', 'tarjeta', 'cheque', 'otro']
const fmt = (v: number) => '$' + Math.round(v || 0).toLocaleString('es-CO')

/**
 * Lo mínimo que hace falta para pagar una obligación. Ni Costos ni el calendario
 * pasan su fila entera: cada uno tiene su propia forma (`Obligacion` trae `saldo`,
 * `AgendaItem` trae `monto`) y el modal no tiene por qué conocer las dos.
 */
export interface ObligacionAPagar {
  id: number
  concepto: string
  saldo: number
  /** Línea de contexto ya armada por quien abre (categoría · sede · beneficiario). */
  detalle?: string
}

/**
 * Registrar el pago de una obligación — UNA sola implementación.
 *
 * Vivía copiado en `pages/Costos.tsx` y en `components/plata/CalendarioView.tsx`:
 * mismo formulario, mismo `POST /costos/pagos`, mismas validaciones. Dos copias de
 * un modal que mueve plata son dos lugares donde arreglar el próximo bug, y en la
 * práctica ya habían empezado a separarse (una tomaba "hoy" del reloj del
 * navegador y la otra del de Colombia).
 *
 * El estado arranca de las props y no se sincroniza después, así que quien lo monta
 * DEBE pasar `key={obligacion.id}` — sin eso, abrir un segundo pago reusaría el
 * monto tecleado para el primero.
 */
export default function ModalRegistrarPago({ obligacion, onCerrar, onPagado }: {
  obligacion: ObligacionAPagar
  onCerrar: () => void
  onPagado: () => void
}) {
  const [monto, setMonto] = useState(String(Math.round(obligacion.saldo)))
  const [fecha, setFecha] = useState(hoyBogota())
  const [metodo, setMetodo] = useState('transferencia')
  const [nota, setNota] = useState('')
  const [error, setError] = useState('')
  const [guardando, setGuardando] = useState(false)

  const registrar = async () => {
    if (!(Number(monto) > 0)) { setError('El monto tiene que ser mayor a 0'); return }
    if (!fecha) { setError('Poné el día en que salió la plata'); return }
    setGuardando(true); setError('')
    try {
      await api.post('/costos/pagos', {
        obligacion_id: obligacion.id,
        monto: Number(monto),
        fecha_pago: fecha,
        metodo,
        nota: nota.trim() || null,
      })
      onPagado()
    } catch (e: any) {
      setError(e.response?.data?.detail || 'No se pudo registrar el pago. Reintentá.')
    } finally { setGuardando(false) }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onCerrar}>
      <div className="bg-white rounded-2xl w-full max-w-sm p-5 space-y-4" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <h2 className="font-bold text-warm-700">Registrar pago</h2>
          <button onClick={onCerrar} aria-label="Cerrar" className="text-warm-400"><X size={18} /></button>
        </div>
        <div className="text-sm text-warm-500">
          <p className="font-semibold text-warm-700">{obligacion.concepto}</p>
          {obligacion.detalle && <p>{obligacion.detalle}</p>}
          <p>Saldo: <span className="font-mono font-bold text-danger-600">{fmt(obligacion.saldo)}</span></p>
        </div>
        <div>
          <label className="text-xs font-semibold text-warm-500 uppercase tracking-wide block mb-1">Monto pagado</label>
          <input type="text" inputMode="numeric" value={conMiles(monto)}
            onChange={e => setMonto(soloDigitos(e.target.value))}
            className="w-full border-2 border-warm-200 rounded-xl px-4 py-2.5 text-lg font-bold font-mono focus:outline-none focus:border-forest" />
        </div>
        <div>
          <label className="text-xs font-semibold text-warm-500 uppercase tracking-wide block mb-1">Día en que salió la plata</label>
          <input type="date" value={fecha} onChange={e => setFecha(e.target.value)}
            className="w-full border-2 border-warm-200 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:border-forest" />
          <p className="text-[11px] text-warm-400 mt-1">
            Puede ser un sábado o cualquier día sin turno abierto — por eso este módulo existe.
          </p>
        </div>
        <div>
          <label className="text-xs font-semibold text-warm-500 uppercase tracking-wide block mb-1">Método</label>
          <select value={metodo} onChange={e => setMetodo(e.target.value)}
            className="w-full border-2 border-warm-200 rounded-xl px-4 py-2.5 text-sm bg-white capitalize">
            {METODOS.map(m => <option key={m} value={m} className="capitalize">{m}</option>)}
          </select>
        </div>
        <div>
          <label className="text-xs font-semibold text-warm-500 uppercase tracking-wide block mb-1">Nota (opcional)</label>
          <input value={nota} onChange={e => setNota(e.target.value)}
            className="w-full border-2 border-warm-200 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:border-forest" />
        </div>
        {error && <p className="text-sm text-danger-700 bg-danger-50 border border-danger-200 rounded-xl px-3 py-2">{error}</p>}
        <button onClick={registrar} disabled={guardando || !fecha || !(Number(monto) > 0)}
          className="w-full bg-forest hover:bg-forest-700 disabled:opacity-40 text-white font-bold py-3 rounded-xl text-sm">
          {guardando ? 'Guardando...' : 'Confirmar pago'}
        </button>
      </div>
    </div>
  )
}
