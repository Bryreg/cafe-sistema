import { useState } from 'react'
import { Landmark, Wallet } from 'lucide-react'
import api from '../../api/client'
import { conMiles, soloDigitos } from '../../utils/plata'
import { hoyBogota } from '../../utils/fechaLocal'
import { CuentaBanco, detalleDeError, plata } from './banco'
import { METODOS_DE_BANCO, METODOS_PAGO } from './tipos'
import {
  Campo, CLS_INPUT, CLS_INPUT_PLATA, CLS_BOTON_GUARDAR, CLS_BOTON_SUAVE,
  ErrorCampo, teclas,
} from './campos'

/**
 * Registrar el pago de una obligación — LA FILA, no un modal.
 *
 * Sigue siendo UNA sola implementación para las tres puertas que llevan acá (el
 * banner de vencidos, la fila del día del libro y la lista de obligaciones):
 * dos copias de un formulario que mueve plata son dos lugares donde arreglar el
 * próximo bug, y las copias viejas ya se habían empezado a separar —una tomaba
 * «hoy» del reloj del navegador y la otra del de Colombia—.
 *
 * ═════════════════════════════════════════════════════════════════════════════
 * LA COSTURA QUE ESTE FORMULARIO POR FIN CIERRA
 * ═════════════════════════════════════════════════════════════════════════════
 * Registrar un pago TACHA el vencimiento pero NO mueve el libro del banco: al
 * libro solo entra lo que se teclea. Hasta ahora eso se resolvía con un cartel
 * («cuando la plata salga de la cuenta, cargala como salida»), o sea pidiéndole
 * al dueño que hiciera la misma carga dos veces en dos pantallas — y el que se
 * olvidaba dejaba el saldo del banco alto y la proyección optimista.
 *
 * `POST /banco/movimientos` acepta `obligacion_id` y `nota` desde siempre
 * (routers/banco.py: `MovimientoIn`) y el frontend no mandaba ninguno de los
 * dos. Con eso, el pago puede ofrecer «y descontalo del banco» en el mismo
 * gesto, dejando el movimiento ENLAZADO a la obligación que pagó.
 *
 * TRES GUARDAS, y ninguna es decorativa:
 *  - SOLO CON MÉTODO DE BANCO. El efectivo sale del cajón de la registradora,
 *    no de la cuenta: ofrecerlo ahí metería en el libro una salida que el
 *    extracto nunca va a tener, y el mes dejaría de cuadrar.
 *  - SOLO CON FECHA NO FUTURA. El backend rechaza movimientos futuros a
 *    propósito (el libro es plata que YA se movió). Se apaga la opción en vez
 *    de ofrecerla y que el POST falle.
 *  - EL PAGO Y EL MOVIMIENTO SON DOS ESCRITURAS. Si la segunda falla, la
 *    primera YA pasó: el mensaje lo dice con esas palabras en vez de un «no se
 *    pudo registrar el pago» que mandaría a cargarlo de nuevo y lo duplicaría.
 */
export default function FormPagoObligacion({
  obligacionId, concepto, detalle, saldo, cuentas, onCancelar, onPagado,
}: {
  obligacionId: number
  concepto: string
  /** Línea de contexto ya armada por quien abre (categoría · sede · beneficiario). */
  detalle?: string
  saldo: number
  cuentas: CuentaBanco[]
  onCancelar: () => void
  /** Aviso hacia afuera: cambió la agenda, el resultado y (si se marcó) el libro. */
  /** Se llama SIEMPRE que el pago quedó registrado, con o sin el movimiento del
   *  banco. El `aviso` viaja hacia arriba porque este formulario se DESMONTA al
   *  llamarlo: escribir el error acá y cerrar en el mismo render lo hacía
   *  desaparecer sin que nadie lo leyera, justo en el caso que necesita
   *  explicación (el pago está, el saldo del banco no bajó). */
  onPagado: (aviso?: string) => void
}) {
  const hoy = hoyBogota()
  const [monto, setMonto] = useState(String(Math.round(saldo)))
  const [fecha, setFecha] = useState(hoy)
  const [metodo, setMetodo] = useState('transferencia')
  const [nota, setNota] = useState('')
  /**
   * ARRANCA EN NO, y no por timidez.
   *
   * Marcarlo escribe una salida en el libro del banco. Si el dueño ya la tecleó
   * —cosa que hoy hace, porque hasta ahora era la única forma— un default en «sí»
   * la escribiría DOS VECES: el saldo bajaría el doble y el punto de quiebre
   * saldría antes de lo real. Un default que escribe plata sin que nadie lo mire
   * es exactamente la familia de error que este módulo viene arrastrando.
   *
   * Dejarlo en no es el comportamiento de siempre (el pago tacha el vencimiento
   * y el libro no se toca), y eso está dicho en el propio rótulo.
   */
  const [alBanco, setAlBanco] = useState(false)
  const [cuentaId, setCuentaId] = useState(cuentas[0] ? String(cuentas[0].id) : '')
  const [error, setError] = useState('')
  const [guardando, setGuardando] = useState(false)

  // La opción existe solo cuando las tres condiciones se dan a la vez.
  const puedeIrAlBanco = METODOS_DE_BANCO.includes(metodo) && fecha <= hoy && cuentas.length > 0
  const marcado = alBanco && puedeIrAlBanco
  const listo = Number(monto) > 0 && !!fecha && (!marcado || !!cuentaId)

  const registrar = async () => {
    // GUARDA DE REENTRADA. Enter y el botón llaman a lo mismo, y entre el
    // toque y la respuesta hay una ida y vuelta: dos toques ahí adentro
    // escribían DOS veces. En una tablet con conexión lenta eso duplica un
    // movimiento, un pago o una obligación, y `registrar_pago` del backend
    // ni siquiera valida contra el saldo.
    if (guardando) return
    if (!listo) return
    setGuardando(true); setError('')
    try {
      await api.post('/costos/pagos', {
        obligacion_id: obligacionId,
        monto: Number(monto),
        fecha_pago: fecha,
        metodo,
        nota: nota.trim() || null,
      })
    } catch (e) {
      setError(detalleDeError(e, 'No se pudo registrar el pago. Reintentá.'))
      setGuardando(false)
      return
    }
    // El pago YA está. De acá en adelante, cualquier error habla del libro.
    if (marcado) {
      try {
        await api.post('/banco/movimientos', {
          fecha,
          cuenta_id: Number(cuentaId),
          tipo: 'salida',
          monto: Number(monto),
          // Recortados a los topes del router (160 y 300): un concepto largo
          // haría fallar el movimiento DESPUÉS de que el pago ya se guardó, y
          // ese error no tiene arreglo desde acá — el dueño quedaría con el
          // vencimiento tachado y el saldo del banco sin bajar.
          concepto: concepto.slice(0, 160),
          obligacion_id: obligacionId,
          nota: nota.trim().slice(0, 300) || null,
        })
      } catch (e) {
        setGuardando(false)
        // El mensaje sube: acá abajo no sobrevive al desmontaje.
        onPagado(
          'El pago quedó registrado y el vencimiento ya está tachado. Lo que NO se pudo '
          + 'cargar es la salida del banco: ' + detalleDeError(e, 'reintentá desde el libro.')
          + ' Cargala a mano en el libro para que el saldo baje.')
        return
      }
    }
    setGuardando(false)
    onPagado()
  }

  return (
    <div className="px-3 py-3 bg-forest-50 border-y border-forest-100 space-y-2"
      onKeyDown={teclas({ listo, guardar: registrar, cancelar: onCancelar })}>
      <div className="flex items-baseline gap-2">
        <Wallet size={13} className="text-forest shrink-0 self-center" />
        <p className="text-sm font-bold text-warm-700 min-w-0 truncate">{concepto}</p>
        <span className="ml-auto shrink-0 text-[11px] text-warm-500">
          saldo <b className="font-mono tabular-nums text-danger-700">{plata(saldo)}</b>
        </span>
      </div>
      {detalle && <p className="text-[11px] text-warm-500 -mt-1">{detalle}</p>}

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 items-end">
        {/* Arranca enfocado y con el saldo entero adentro: el caso normal es
            pagar todo, y así el gesto completo es abrir y confirmar. */}
        <Campo label="Monto pagado">
          <input type="text" inputMode="numeric" value={conMiles(monto)} autoFocus
            onChange={e => setMonto(soloDigitos(e.target.value))}
            aria-label="Monto pagado" className={CLS_INPUT_PLATA} />
        </Campo>
        <Campo label="Día en que salió">
          <input type="date" value={fecha} onChange={e => setFecha(e.target.value)}
            className={CLS_INPUT} />
        </Campo>
        <Campo label="Método">
          <select value={metodo} onChange={e => setMetodo(e.target.value)}
            className={`${CLS_INPUT} capitalize`}>
            {METODOS_PAGO.map(m => <option key={m} value={m} className="capitalize">{m}</option>)}
          </select>
        </Campo>
        <Campo label="Nota (opcional)">
          <input value={nota} onChange={e => setNota(e.target.value)} className={CLS_INPUT} />
        </Campo>
      </div>

      {/* «Y descontalo del banco»: el gesto que evita cargar lo mismo dos veces. */}
      {puedeIrAlBanco && (
        <div className="rounded-xl border border-warm-200 bg-white px-3 py-2.5">
          <label className="flex items-start gap-2 cursor-pointer">
            <input type="checkbox" checked={alBanco} onChange={e => setAlBanco(e.target.checked)}
              className="mt-0.5 h-4 w-4 shrink-0 accent-forest" />
            <span className="min-w-0 flex-1">
              <span className="block text-xs font-bold text-warm-700 flex items-center gap-1">
                <Landmark size={12} /> Y descontalo del banco
              </span>
              <span className="block text-[11px] text-warm-500 leading-snug">
                Carga también la salida en el libro, enlazada a esta obligación. Sin marcarlo el
                vencimiento queda tachado igual, pero <b>el saldo del banco no baja</b> hasta que
                cargues la salida a mano. <b>No lo marques si ya la tecleaste</b> en el libro: se
                cargaría dos veces.
              </span>
            </span>
          </label>
          {alBanco && (
            <div className="mt-2 max-w-[16rem]">
              <Campo label="¿De qué cuenta salió?">
                <select value={cuentaId} onChange={e => setCuentaId(e.target.value)} className={CLS_INPUT}>
                  {cuentas.map(c => <option key={c.id} value={c.id}>{c.nombre}</option>)}
                </select>
              </Campo>
            </div>
          )}
        </div>
      )}
      {!puedeIrAlBanco && (
        <p className="text-[11px] text-warm-400 leading-snug">
          {metodo === 'efectivo'
            ? 'En efectivo la plata sale del cajón, no de la cuenta: el libro del banco no se toca.'
            : fecha > hoy
              ? 'Con fecha futura no se puede cargar la salida del banco: el libro es plata que ya se movió.'
              : cuentas.length === 0
                ? 'No hay cuentas de banco cargadas, así que la salida del libro hay que cargarla aparte.'
                : 'Con este método la salida del banco se carga aparte, en el libro.'}
        </p>
      )}

      <div className="flex gap-2">
        <button type="button" onClick={onCancelar} className={CLS_BOTON_SUAVE}>Cancelar</button>
        <button type="button" onClick={registrar} disabled={guardando || !listo}
          className={`${CLS_BOTON_GUARDAR} flex-1`}>
          {guardando ? 'Guardando…' : marcado ? 'Pagar y descontar del banco' : 'Confirmar pago'}
        </button>
      </div>

      <ErrorCampo msg={error} />
    </div>
  )
}
