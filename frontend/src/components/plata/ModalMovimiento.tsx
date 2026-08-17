import { useState } from 'react'
import { ArrowDownLeft, ArrowUpRight, X } from 'lucide-react'
import api from '../../api/client'
import { conMiles, soloDigitos } from '../../utils/plata'
import { CuentaBanco, MovimientoBanco, detalleDeError } from './banco'

/**
 * Cargar UN movimiento del banco: fecha, cuenta, entra o sale, monto, concepto.
 *
 * Es el formulario más importante del módulo porque es la ÚNICA forma en que el
 * libro se llena: el sistema no deduce lo que entró al banco (el datáfono liquida
 * con rezago y con la comisión ya descontada, así que el número deducido nunca
 * coincidiría con el extracto). Lo que no se teclee acá, no existe en el saldo.
 *
 * EL SIGNO NO SE TECLEA. El monto va siempre positivo y el signo lo decide
 * "Entró"/"Salió", que es la regla de `services/banco.py`. Un campo con signo
 * dejaría que una salida de −$100.000 sumara plata, y ese error no se ve hasta
 * que el mes no cuadra contra el extracto — por eso el formulario no ofrece la
 * posibilidad en vez de ofrecerla y después rechazarla.
 *
 * El estado arranca de las props y no se sincroniza, así que quien lo monta debe
 * pasar `key` cuando cambie la fecha inicial.
 */
export default function ModalMovimiento({ fechaInicial, cuentas, onCerrar, onGuardado }: {
  fechaInicial: string
  cuentas: CuentaBanco[]
  onCerrar: () => void
  /** Recibe el movimiento creado: su fecha puede ser de OTRO mes que el visible. */
  onGuardado: (movimiento: MovimientoBanco) => void
}) {
  const [fecha, setFecha] = useState(fechaInicial)
  const [cuentaId, setCuentaId] = useState(cuentas[0] ? String(cuentas[0].id) : '')
  // ARRANCA SIN ELEGIR, y no en «salida» por comodidad: un tipo por defecto se
  // guarda sin que nadie lo mire, y el signo equivocado no se nota hasta que el
  // mes no cuadra contra el extracto. Que el botón de guardar no se habilite
  // hasta elegirlo cuesta un toque y evita el único error caro de este formulario.
  const [tipo, setTipo] = useState<'entrada' | 'salida' | null>(null)
  const [monto, setMonto] = useState('')
  const [concepto, setConcepto] = useState('')
  const [error, setError] = useState('')
  const [guardando, setGuardando] = useState(false)

  const cuenta = cuentas.find(c => String(c.id) === cuentaId)
  const listo = !!fecha && !!cuentaId && !!tipo && Number(monto) > 0 && !!concepto.trim()

  const guardar = async () => {
    if (!listo || !tipo) return
    setGuardando(true); setError('')
    try {
      const r = await api.post<MovimientoBanco>('/banco/movimientos', {
        fecha,
        cuenta_id: Number(cuentaId),
        tipo,
        monto: Number(monto),
        concepto: concepto.trim(),
      })
      // El movimiento que vuelve NO se usa para parchear la fila en pantalla: un
      // movimiento mueve el saldo de TODOS los días siguientes (la cadena se
      // deriva, no se guarda), así que quien monta el modal recarga el mes. Se
      // pasa por su FECHA, que puede no ser la del mes que se estaba mirando.
      onGuardado(r.data)
    } catch (e) {
      setError(detalleDeError(e, 'No se pudo guardar el movimiento. Reintentá.'))
    } finally { setGuardando(false) }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onCerrar}>
      <div className="bg-white rounded-2xl w-full max-w-sm p-5 space-y-4 max-h-[92vh] overflow-y-auto"
        onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <h2 className="font-bold text-warm-700">Movimiento del banco</h2>
          <button onClick={onCerrar} aria-label="Cerrar" className="text-warm-400"><X size={18} /></button>
        </div>

        <div>
          <label className="text-xs font-semibold text-warm-500 uppercase tracking-wide block mb-1">Día</label>
          <input type="date" value={fecha} onChange={e => setFecha(e.target.value)}
            className="w-full border-2 border-warm-200 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:border-forest" />
        </div>

        {/* Entró / Salió: dos botones grandes y no un select, porque es lo que
            decide el signo de la plata. Un desplegable de dos opciones esconde
            justo el dato que más caro sale equivocar. */}
        <div>
          <label className="text-xs font-semibold text-warm-500 uppercase tracking-wide block mb-1">¿Entró o salió?</label>
          <div className="grid grid-cols-2 gap-2">
            <button onClick={() => setTipo('entrada')}
              className={`flex items-center justify-center gap-1.5 min-h-[46px] rounded-xl border-2 text-sm font-bold transition-colors ${
                tipo === 'entrada'
                  ? 'border-success-500 bg-success-50 text-success-700'
                  : 'border-warm-200 text-warm-500'}`}>
              <ArrowDownLeft size={15} /> Entró
            </button>
            <button onClick={() => setTipo('salida')}
              className={`flex items-center justify-center gap-1.5 min-h-[46px] rounded-xl border-2 text-sm font-bold transition-colors ${
                tipo === 'salida'
                  ? 'border-danger-500 bg-danger-50 text-danger-700'
                  : 'border-warm-200 text-warm-500'}`}>
              <ArrowUpRight size={15} /> Salió
            </button>
          </div>
        </div>

        <div>
          <label className="text-xs font-semibold text-warm-500 uppercase tracking-wide block mb-1">Monto</label>
          <input type="text" inputMode="numeric" value={conMiles(monto)}
            onChange={e => setMonto(soloDigitos(e.target.value))}
            placeholder="0"
            className="w-full border-2 border-warm-200 rounded-xl px-4 py-2.5 text-lg font-bold font-mono tabular-nums focus:outline-none focus:border-forest" />
          <p className="text-[11px] text-warm-400 mt-1">
            Siempre en positivo: el signo lo pone «Entró» o «Salió».
          </p>
        </div>

        <div>
          <label className="text-xs font-semibold text-warm-500 uppercase tracking-wide block mb-1">Cuenta</label>
          {cuentas.length > 0 ? (
            <select value={cuentaId} onChange={e => setCuentaId(e.target.value)}
              className="w-full border-2 border-warm-200 rounded-xl px-4 py-2.5 text-sm bg-white focus:outline-none focus:border-forest">
              {cuentas.map(c => <option key={c.id} value={c.id}>{c.nombre}</option>)}
            </select>
          ) : (
            <p className="text-sm text-warm-500 bg-warm-100 rounded-xl px-3 py-2">
              No hay cuentas cargadas todavía.
            </p>
          )}
          {cuenta?.nota && (
            <p className="text-[11px] text-warm-400 mt-1 leading-snug">{cuenta.nota}</p>
          )}
        </div>

        <div>
          <label className="text-xs font-semibold text-warm-500 uppercase tracking-wide block mb-1">Concepto</label>
          <input value={concepto} onChange={e => setConcepto(e.target.value)}
            placeholder={tipo === 'entrada' ? 'Consignación del viernes'
              : tipo === 'salida' ? 'Arriendo agosto' : 'Qué fue ese movimiento'}
            className="w-full border-2 border-warm-200 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:border-forest" />
          <p className="text-[11px] text-warm-400 mt-1">
            Es lo que después te deja conciliar la fila contra el extracto del banco.
          </p>
        </div>

        {error && (
          <p className="text-sm text-danger-700 bg-danger-50 border border-danger-200 rounded-xl px-3 py-2">{error}</p>
        )}

        <button onClick={guardar} disabled={guardando || !listo}
          className="w-full bg-forest hover:bg-forest-700 disabled:opacity-40 text-white font-bold py-3 rounded-xl text-sm">
          {guardando ? 'Guardando...' : 'Guardar movimiento'}
        </button>
      </div>
    </div>
  )
}
