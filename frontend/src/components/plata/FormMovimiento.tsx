import { useEffect, useRef, useState } from 'react'
import { ArrowDownLeft, ArrowUpRight, Plus } from 'lucide-react'
import api from '../../api/client'
import { conMiles, soloDigitos } from '../../utils/plata'
import type { Fuente } from '../../api/useDato'
import { SegunDato, NoSeSabe } from '../ui'
import { CuentaBanco, MovimientoBanco, detalleDeError } from './banco'
import { Campo, CLS_INPUT, CLS_INPUT_PLATA, CLS_BOTON_GUARDAR, ErrorCampo, teclas } from './campos'

/** El lugar del select mientras el catálogo no está: gris y mudo, sin afirmar
 *  que no haya cuentas. Misma caja para no descuadrar la grilla. */
const CajaCuentas = ({ texto }: { texto: string }) => (
  <p className="text-[11px] text-warm-500 bg-warm-100 rounded-xl px-3 py-3 min-h-[44px] flex items-center">
    {texto}
  </p>
)

/**
 * Cargar un movimiento del banco — LA FILA, no un modal.
 *
 * ═════════════════════════════════════════════════════════════════════════════
 * POR QUÉ DEJÓ DE SER UN MODAL
 * ═════════════════════════════════════════════════════════════════════════════
 * Pedido textual del dueño: «no quiero desplegar pestañas para hacer un
 * movimiento». Era el formulario MÁS usado del módulo y costaba abrir un modal,
 * llenarlo, guardarlo y verlo cerrarse — y para el siguiente, todo de nuevo.
 * Acá la fila queda montada: guardar limpia los campos y devuelve el foco al
 * primero, así que veinte movimientos seguidos son veinte tabuladas, no veinte
 * aperturas.
 *
 * ═════════════════════════════════════════════════════════════════════════════
 * LO QUE NO SE PUEDE PERDER AL SACARLO DEL MODAL
 * ═════════════════════════════════════════════════════════════════════════════
 *  - EL TIPO ARRANCA SIN ELEGIR. Un default («salida», por ser lo más común) se
 *    guarda sin que nadie lo mire, y el signo equivocado no se nota hasta que el
 *    mes no cuadra contra el extracto. Que el botón no se habilite hasta elegirlo
 *    cuesta un toque y evita el único error caro de este formulario.
 *  - EL MONTO VA SIEMPRE POSITIVO: el signo lo pone «Entró»/«Salió», que es la
 *    regla de `services/banco.py`. Un campo con signo dejaría que una salida de
 *    −$100.000 sumara plata.
 *  - EL TIPO NO SE CONSERVA ENTRE CARGAS. Es la única cosa que NO se limpia por
 *    comodidad sino que se limpia por seguridad: encadenar una entrada después
 *    de otra sin volver a mirar el botón es exactamente cómo se cuela el signo
 *    equivocado en la carga número 14.
 *  - GUARDAR SALTA AL MES DEL MOVIMIENTO GUARDADO, no al que se estaba mirando
 *    (lo hace quien monta esta fila, con la fecha que devuelve el backend): la
 *    fecha es editable, y guardar algo de otro mes sin ver ningún cambio en
 *    pantalla se lee como que no se guardó.
 *  - «CARGANDO» Y «NO HAY NINGUNA» NO SON LA MISMA CAJA. Antes las dos decían
 *    «Cargando las cuentas…» porque el catálogo llegaba como `CuentaBanco[]` y
 *    una lista vacía no se distinguía de una que no volvió. Con el catálogo
 *    caído esa caja se quedaba puesta para siempre y el dueño esperaba un fetch
 *    que ya había fallado.
 */
export default function FormMovimiento({ fechaInicial, cuentas, maxFecha, onGuardado }: {
  /** Con qué día arranca. El libro precarga hoy, o el día de la fila que lo abrió. */
  fechaInicial: string
  cuentas: Fuente<CuentaBanco[]>
  /** Hoy en Colombia: el backend RECHAZA fechas futuras (el libro es plata que ya
   *  se movió), así que el campo no las ofrece en vez de ofrecerlas y fallar. */
  maxFecha: string
  onGuardado: (movimiento: MovimientoBanco) => void
}) {
  /** El catálogo LEÍDO, o `null` mientras no esté en la mano. `null` no es «no
   *  hay cuentas»: es «no se sabe». Solo alimenta el default del efecto. */
  const cs = cuentas.dato.estado === 'listo' ? cuentas.dato.valor : null

  const [fecha, setFecha] = useState(fechaInicial)
  const [cuentaId, setCuentaId] = useState(cs?.[0] ? String(cs[0].id) : '')
  const [tipo, setTipo] = useState<'entrada' | 'salida' | null>(null)
  const [monto, setMonto] = useState('')
  const [concepto, setConcepto] = useState('')
  const [error, setError] = useState('')
  const [guardando, setGuardando] = useState(false)
  const [ultimo, setUltimo] = useState('')

  // El foco vuelve acá después de guardar: es el primer campo que se toca para
  // cargar el siguiente movimiento.
  const refMonto = useRef<HTMLInputElement>(null)

  // EL DEFAULT SE SINCRONIZA CUANDO LLEGA EL CATÁLOGO. El useState corre en el
  // PRIMER render, cuando la lista todavía no llegó porque el fetch va en un
  // hook del padre. Sin esto el estado quedaba en '' para siempre —el componente
  // no remonta— y el resultado era el peor posible: el select se ve CON una
  // opción elegida (React marca la primera cuando el value controlado no matchea
  // ninguna) y el botón «Guardar» gris, sin explicación. El dueño tecleaba todo
  // y no podía guardar. No pisa lo que ya eligió: solo llena el hueco.
  useEffect(() => {
    if (!cuentaId && cs && cs.length > 0) setCuentaId(String(cs[0].id))
  }, [cs, cuentaId])

  const cuenta = cs?.find(c => String(c.id) === cuentaId)
  const listo = !!fecha && !!cuentaId && !!tipo && Number(monto) > 0 && !!concepto.trim()

  const guardar = async () => {
    // GUARDA DE REENTRADA. Enter y el botón llaman a lo mismo, y entre el
    // toque y la respuesta hay una ida y vuelta: dos toques ahí adentro
    // escribían DOS veces. En una tablet con conexión lenta eso duplica un
    // movimiento, un pago o una obligación, y `registrar_pago` del backend
    // ni siquiera valida contra el saldo.
    if (guardando) return
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
      // Confirmación EN LA FILA. Sin el modal que se cerraba, guardar no tenía
      // ningún gesto propio: la grilla de abajo cambia, pero el ojo está acá.
      setUltimo(`${tipo === 'entrada' ? 'Entró' : 'Salió'} ${conMiles(monto)} · ${concepto.trim()}`)
      setMonto(''); setConcepto(''); setTipo(null)
      refMonto.current?.focus()
      onGuardado(r.data)
    } catch (e) {
      setError(detalleDeError(e, 'No se pudo guardar el movimiento. Reintentá.'))
    } finally { setGuardando(false) }
  }

  return (
    <div className="px-3 py-3 bg-warm-50 border-b border-warm-100 space-y-2"
      onKeyDown={teclas({ listo, guardar })}>
      <div className="flex items-center gap-1.5">
        <Plus size={13} className="text-forest shrink-0" />
        <p className="text-[11px] font-bold uppercase tracking-wide text-warm-500">
          Cargar un movimiento del banco
        </p>
      </div>

      {/* EL AVISO VA ARRIBA DEL SELECT y el formulario se queda montado: sin
          cuenta el backend no acepta el movimiento, así que decirlo acá —con el
          botón de reintentar— es lo único que evita que el dueño teclee todo
          contra un «Guardar» gris que no explica nada. */}
      <SegunDato
        dato={cuentas.dato}
        cargando={null}
        falla={m => (
          <NoSeSabe onReintentar={cuentas.recargar}
            mensaje={`${m} — sin la cuenta no se puede guardar el movimiento. Podés ir tecleando `
              + 'el resto: el día, el monto y el concepto no dependen del catálogo.'} />
        )}
        listo={lista => lista.length === 0 ? (
          <NoSeSabe mensaje="No hay ninguna cuenta de banco cargada, así que todavía no se puede cargar un movimiento." />
        ) : null}
      />

      {/* Mobile-first: una columna en celular, la fila entera en tablet. El
          monto va PRIMERO en la grilla ancha porque es el campo que se toca
          siempre; la fecha casi nunca se cambia (viene precargada). */}
      <div className="grid grid-cols-2 sm:grid-cols-[7.5rem_11rem_9rem_9rem_1fr_auto] gap-2 items-end">
        <Campo label="Día">
          <input type="date" value={fecha} max={maxFecha}
            onChange={e => setFecha(e.target.value)} className={CLS_INPUT} />
        </Campo>

        {/* Dos botones grandes y no un select: es lo que decide el SIGNO de la
            plata, y un desplegable de dos opciones esconde justo el dato que más
            caro sale equivocar. */}
        <Campo label="¿Entró o salió?">
          <div className="grid grid-cols-2 gap-1.5">
            <button type="button" onClick={() => setTipo('entrada')}
              aria-pressed={tipo === 'entrada'}
              className={`flex items-center justify-center gap-1 min-h-[44px] rounded-xl border-2 text-xs font-bold transition-colors ${
                tipo === 'entrada'
                  ? 'border-success-500 bg-success-50 text-success-700'
                  : 'border-warm-200 bg-white text-warm-500'}`}>
              <ArrowDownLeft size={14} /> Entró
            </button>
            <button type="button" onClick={() => setTipo('salida')}
              aria-pressed={tipo === 'salida'}
              className={`flex items-center justify-center gap-1 min-h-[44px] rounded-xl border-2 text-xs font-bold transition-colors ${
                tipo === 'salida'
                  ? 'border-danger-500 bg-danger-50 text-danger-700'
                  : 'border-warm-200 bg-white text-warm-500'}`}>
              <ArrowUpRight size={14} /> Salió
            </button>
          </div>
        </Campo>

        <Campo label="Monto">
          <input ref={refMonto} type="text" inputMode="numeric" value={conMiles(monto)}
            onChange={e => setMonto(soloDigitos(e.target.value))} placeholder="0"
            aria-label="Monto del movimiento"
            className={CLS_INPUT_PLATA} />
        </Campo>

        <Campo label="Cuenta">
          {/* «Vacío», «todavía no llegó» y «no volvió» son TRES cosas distintas y
              cada una se dibuja distinta: antes las tres decían «Cargando las
              cuentas…», y con el catálogo caído esa caja no se iba nunca. */}
          <SegunDato
            dato={cuentas.dato}
            cargando={<CajaCuentas texto="Cargando las cuentas…" />}
            falla={() => <CajaCuentas texto="Sin cuentas para elegir" />}
            listo={lista => lista.length === 0
              ? <CajaCuentas texto="No hay cuentas cargadas" />
              : (
                <select value={cuentaId} onChange={e => setCuentaId(e.target.value)} className={CLS_INPUT}>
                  {lista.map(c => <option key={c.id} value={c.id}>{c.nombre}</option>)}
                </select>
              )}
          />
        </Campo>

        <Campo label="Concepto" ancho="col-span-2 sm:col-span-1">
          <input value={concepto} onChange={e => setConcepto(e.target.value)}
            placeholder={tipo === 'entrada' ? 'Consignación del viernes'
              : tipo === 'salida' ? 'Arriendo agosto' : 'Qué fue ese movimiento'}
            className={CLS_INPUT} />
        </Campo>

        <button type="button" onClick={guardar} disabled={guardando || !listo}
          className={`${CLS_BOTON_GUARDAR} col-span-2 sm:col-span-1`}>
          {guardando ? 'Guardando…' : 'Guardar'}
        </button>
      </div>

      {/* La nota del monto y la de la cuenta van juntas y chiquitas: son las dos
          cosas que hay que saber una sola vez, no en cada carga. */}
      <p className="text-[11px] text-warm-400 leading-snug">
        El monto va siempre en positivo: el signo lo pone «Entró» o «Salió». El concepto es lo
        que después te deja conciliar la fila contra el extracto del banco.
        {cuenta?.nota && <> · {cuenta.nota}</>}
      </p>

      <ErrorCampo msg={error} />
      {!error && ultimo && (
        <p className="text-[11px] font-semibold text-success-600">Guardado: {ultimo}</p>
      )}
    </div>
  )
}
