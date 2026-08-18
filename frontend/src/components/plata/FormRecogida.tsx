import { useEffect, useRef, useState } from 'react'
import { HandCoins } from 'lucide-react'
import api from '../../api/client'
import { conMiles, soloDigitos } from '../../utils/plata'
import type { Fuente } from '../../api/useDato'
import { SegunDato, NoSeSabe } from '../ui'
import { detalleDeError, fechaCorta } from './banco'
import { Tienda } from './tipos'
import { Campo, CLS_INPUT, CLS_INPUT_PLATA, CLS_BOTON_GUARDAR, ErrorCampo, teclas } from './campos'

/** El lugar del select mientras el catálogo de sedes no está: gris y mudo, sin
 *  afirmar que no haya sedes. Misma caja para no descuadrar la grilla. */
const CajaSedes = ({ texto }: { texto: string }) => (
  <p className="text-[11px] text-warm-500 bg-warm-100 rounded-xl px-3 py-3 min-h-[44px] flex items-center">
    {texto}
  </p>
)

/**
 * El límite del backend, dicho acá para no ofrecer lo que va a rechazar.
 *
 * Mismo criterio que el `max` de la fecha en el formulario del banco: el campo
 * no ofrece lo inválido en vez de ofrecerlo y fallar después del toque. Y no es
 * cosmético — sin `max_length` el INSERT de Postgres explota, no recorta.
 */
const NOTA_MAX = 300

/**
 * ═════════════════════════════════════════════════════════════════════════════
 * «RECOGÍ PLATA DE UNA SEDE» — el registro que faltaba
 * ═════════════════════════════════════════════════════════════════════════════
 * Hasta julio la plata iba del cajón al banco y el sistema veía las dos puntas:
 * la barista consignaba, la consignación colgaba de su turno y el cajón bajaba.
 * Desde agosto el dueño pasa y RECOGE: con eso paga proveedores en efectivo
 * —plata que nunca toca el banco— y consigna el resto él mismo.
 *
 * Sin este formulario, esa recogida no existe en ninguna parte y el cajón sigue
 * diciendo el número de antes. Medido: venden $1.000.000 en efectivo, el dueño
 * recoge todo, paga $400.000 a un proveedor y consigna $600.000 — el sistema
 * muestra $1.000.000 donde hay $600.000. Sobra exactamente lo pagado en
 * efectivo, y sobra hacia el lado tranquilizador, que es el peor.
 *
 * ── ES UNA FILA, NO UN MODAL ───────────────────────────────────────────────
 * Mismo criterio que `FormMovimiento` y por el mismo pedido textual del dueño
 * («no quiero desplegar pestañas para hacer un movimiento»). Recoger de las dos
 * sedes el mismo día son dos cargas seguidas: guardar limpia el monto y la nota,
 * devuelve el foco al monto y deja la fecha y la sede puestas.
 *
 * ── LA SEDE NO SE LIMPIA, PERO SE DICE ─────────────────────────────────────
 * Al revés que el «¿entró o salió?» del banco, que se limpia por seguridad: acá
 * el select arranca PRESELECCIONADO (sin eso se ve elegido y el submit no
 * guarda) y queda como estaba. El guardarraíl es la confirmación de abajo, que
 * nombra la sede: cargar dos veces sobre la misma sede se ve en el mismo
 * renglón donde se acaba de teclear.
 */
export default function FormRecogida({ tiendas, hoy, pedidoFoco, onGuardado }: {
  tiendas: Fuente<Tienda[]>
  /** Hoy en Colombia. Es el default y el tope: el backend rechaza el futuro (no
   *  se puede haber recogido plata de un día que todavía no llegó). */
  hoy: string
  /** Contador que sube cuando el tile «En tu mano» invita a registrar la primera. */
  pedidoFoco: number
  /** Cambió la plata: hay que repedir la caja y la proyección. */
  onGuardado: () => void
}) {
  /** El catálogo LEÍDO, o `null` mientras no esté en la mano. `null` no es «no
   *  hay sedes»: es «no se sabe». Solo alimenta el default del efecto. */
  const ts = tiendas.dato.estado === 'listo' ? tiendas.dato.valor : null

  const [fecha, setFecha] = useState(hoy)
  const [tiendaId, setTiendaId] = useState(ts?.[0] ? String(ts[0].id) : '')
  const [monto, setMonto] = useState('')
  const [nota, setNota] = useState('')
  const [error, setError] = useState('')
  const [guardando, setGuardando] = useState(false)
  const [ultimo, setUltimo] = useState('')

  const refMonto = useRef<HTMLInputElement>(null)

  // EL DEFAULT SE SINCRONIZA CUANDO LLEGA EL CATÁLOGO. El `useState` corre en el
  // PRIMER render, cuando la lista todavía no llegó porque el fetch vive en un
  // hook de la página. Sin esto el estado queda en '' para siempre —el
  // componente no remonta— y el resultado es el peor posible: el select se ve
  // CON una sede elegida (React marca la primera cuando el value controlado no
  // matchea ninguna opción) y el botón «Guardar» gris, sin explicación. Es un
  // bug ya cazado en este repo, en el formulario del banco de al lado. No pisa
  // lo que ya eligió el dueño: solo llena el hueco.
  useEffect(() => {
    if (!tiendaId && ts && ts.length > 0) setTiendaId(String(ts[0].id))
  }, [ts, tiendaId])

  // El tile de arriba pidió el foco («registrá la primera»). Se ignora el
  // montaje (`pedidoFoco` arranca en 0) para no robarle el foco a nadie al
  // abrir la página.
  useEffect(() => {
    if (pedidoFoco > 0) refMonto.current?.focus()
  }, [pedidoFoco])

  const sede = ts?.find(t => String(t.id) === tiendaId)
  const listo = !!fecha && !!tiendaId && Number(monto) > 0

  const guardar = async () => {
    // GUARDA DE REENTRADA. Enter y el botón llaman a lo mismo, y entre el toque
    // y la respuesta hay una ida y vuelta: dos toques ahí adentro escriben DOS
    // recogidas. En una tablet con la señal del local eso duplica el monto que
    // se le resta al cajón, y el cajón queda diciendo MENOS plata de la que hay.
    if (guardando) return
    if (!listo) return
    setGuardando(true); setError('')
    try {
      // La respuesta NO se lee. Lo que cambia en pantalla se relee del backend
      // con `onGuardado`, que es la única fuente de la caja: reconstruir acá el
      // nuevo «en mano» sumando lo tecleado sería una segunda matemática para
      // el mismo número, y esa es la forma en que dos cifras de la misma
      // pregunta terminan discrepando.
      await api.post('/consignaciones/recogidas', {
        tienda_id: Number(tiendaId),
        fecha,
        monto: Number(monto),
        nota: nota.trim() || null,
      })
      // Confirmación EN LA FILA, y con la SEDE adentro: es el único guardarraíl
      // contra cargar la segunda recogida del día sobre la sede de la primera.
      setUltimo(`Recogiste ${conMiles(monto)} de ${sede?.nombre ?? 'la sede elegida'}`
        + ` el ${fechaCorta(fecha)}`)
      setMonto(''); setNota('')
      refMonto.current?.focus()
      onGuardado()
    } catch (e) {
      setError(detalleDeError(e, 'No se pudo guardar la recogida. Reintentá.'))
    } finally { setGuardando(false) }
  }

  return (
    <div className="px-4 py-3 bg-warm-50 border-t border-warm-100 space-y-2"
      onKeyDown={teclas({ listo, guardar })}>
      <div className="flex items-center gap-1.5">
        <HandCoins size={13} className="text-forest shrink-0" />
        <p className="text-[11px] font-bold uppercase tracking-wide text-warm-500">
          Recogí plata de una sede
        </p>
      </div>

      {/* EL AVISO VA ARRIBA DEL SELECT y el formulario se queda montado: sin sede
          el backend no acepta la recogida, así que decirlo acá —con el botón de
          reintentar— es lo único que evita que el dueño teclee todo contra un
          «Guardar» gris que no explica nada. La regla 5 de la casa: ningún
          formulario adentro de un gate por estado. */}
      <SegunDato
        dato={tiendas.dato}
        cargando={null}
        falla={m => (
          <NoSeSabe onReintentar={tiendas.recargar}
            mensaje={`${m} — sin la sede no se puede guardar la recogida. Podés ir tecleando el `
              + 'resto: el día, el monto y la nota no dependen del catálogo.'} />
        )}
        listo={lista => lista.length === 0 ? (
          <NoSeSabe mensaje="No hay ninguna sede cargada, así que todavía no se puede registrar una recogida." />
        ) : null}
      />

      {/* Mobile-first: una columna doble en celular, la fila entera en tablet. */}
      <div className="grid grid-cols-2 sm:grid-cols-[7.5rem_11rem_9rem_1fr_auto] gap-2 items-end">
        <Campo label="¿Qué día?">
          <input type="date" value={fecha} max={hoy}
            onChange={e => setFecha(e.target.value)} className={CLS_INPUT} />
        </Campo>

        <Campo label="¿De qué sede?">
          {/* «Vacío», «todavía no llegó» y «no volvió» son TRES cosas distintas y
              cada una se dibuja distinta. Con una sola caja para las tres, el
              catálogo caído deja puesto un «Cargando…» que no se va nunca. */}
          <SegunDato
            dato={tiendas.dato}
            cargando={<CajaSedes texto="Cargando las sedes…" />}
            falla={() => <CajaSedes texto="Sin sedes para elegir" />}
            listo={lista => lista.length === 0
              ? <CajaSedes texto="No hay sedes cargadas" />
              : (
                <select value={tiendaId} onChange={e => setTiendaId(e.target.value)}
                  aria-label="Sede de la que recogiste" className={CLS_INPUT}>
                  {lista.map(t => <option key={t.id} value={t.id}>{t.nombre}</option>)}
                </select>
              )}
          />
        </Campo>

        <Campo label="Cuánto">
          <input ref={refMonto} type="text" inputMode="numeric" value={conMiles(monto)}
            onChange={e => setMonto(soloDigitos(e.target.value))} placeholder="0"
            aria-label="Monto que recogiste"
            className={CLS_INPUT_PLATA} />
        </Campo>

        <Campo label="Nota (opcional)" ancho="col-span-2 sm:col-span-1">
          <input value={nota} onChange={e => setNota(e.target.value)} maxLength={NOTA_MAX}
            placeholder="Para qué la recogiste"
            className={CLS_INPUT} />
        </Campo>

        <button type="button" onClick={guardar} disabled={guardando || !listo}
          className={`${CLS_BOTON_GUARDAR} col-span-2 sm:col-span-1`}>
          {guardando ? 'Guardando…' : 'Guardar'}
        </button>
      </div>

      <p className="text-[11px] text-warm-400 leading-snug">
        El monto va en positivo. Guardar <b>baja el cajón</b> de esa sede y <b>sube tu efectivo en
        mano</b>: la plata no desaparece, cambia de lugar. Después, lo que pagues en efectivo y lo
        que consignes vos se le descuenta solo.
      </p>

      <ErrorCampo msg={error} />
      {!error && ultimo && (
        <p className="text-[11px] font-semibold text-success-600">Guardado: {ultimo}</p>
      )}
    </div>
  )
}
