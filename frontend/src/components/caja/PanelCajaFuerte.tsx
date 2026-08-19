import { useEffect, useRef, useState } from 'react'
import { ArrowDownToLine, ArrowUpFromLine, Lock, Trash2 } from 'lucide-react'
import api from '../../api/client'
import { conMiles, soloDigitos } from '../../utils/plata'
import { detalleDeError } from '../../api/errores'
import { useDato } from '../../api/useDato'
import type { Fuente } from '../../api/useDato'
import { hoyBogota } from '../../utils/fechaLocal'
import { SegunDato, NoSeSabe } from '../ui'
import { plata } from '../plata/banco'
// Los ladrillos de las filas de carga viven en `plata/campos` porque ese módulo
// fue el primero en necesitarlos, pero no son de plata: son las cuatro reglas de
// digitación (44px, teclado numérico, Enter guarda, el foco vuelve) que TODOS
// los formularios de la casa cumplen igual. Copiarlas acá dejaría dos alturas de
// input distintas en la misma pantalla el día que alguien toque una sola.
import {
  Campo, CLS_INPUT, CLS_INPUT_PLATA, CLS_BOTON_GUARDAR,
  ComoSeCalcula, ErrorCampo, teclas,
} from '../plata/campos'

export interface Sede { id: number; nombre: string }

/** Un traslado entre la caja fuerte y el cajón. El monto SIEMPRE es positivo:
 *  el signo lo pone `sentido`, igual que en `MovimientoBanco`. */
export interface TrasladoCajaFuerte {
  id: number
  tienda_id: number
  caja_turno_id: number | null
  /** El momento del traslado (UTC-naive, como todo el resto de caja). */
  fecha: string
  sentido: 'saca' | 'devuelve'
  monto: number
  motivo: string | null
  usuario_id: number
  usuario_nombre?: string | null
  creado_en: string
}

export interface EstadoCajaFuerte {
  /**
   * El saldo VIGENTE de la sede: Σ 'saca' − Σ 'devuelve'.
   *
   * Puede venir negativo y eso NO se corrige acá (ver el banner de abajo): un
   * `max(0, …)` de este lado taparía un traslado mal cargado justo cuando hay
   * que verlo.
   */
  prestado_caja_fuerte: number
  /** Desde cuándo está prestada esa plata. `null` cuando el saldo es cero. */
  prestado_desde: string | null
  traslados: TrasladoCajaFuerte[]
}

/** El tope del backend, dicho acá para no ofrecer lo que va a rechazar. */
const MONTO_MAX = 1e8
/** `motivo` es String(200) en la base: sin el `maxLength` el INSERT explota, no recorta. */
const MOTIVO_MAX = 200

const OPTS_DIA: Intl.DateTimeFormatOptions = { day: 'numeric', month: 'short', year: 'numeric' }

/**
 * El día de un traslado, en castellano corto.
 *
 * Dos formas posibles y una trampa de un día entre las dos. Un instante
 * (`2026-08-15T14:30:00`) se almacena UTC-naive en todo este backend, así que se
 * lee como UTC y el navegador lo baja a la hora de Colombia — que es la misma
 * cuenta que hace `dia_col()` allá. Una fecha sola (`2026-08-15`) NO es un
 * instante: pasarla por UTC la clava a medianoche y en Colombia (UTC-5) la corre
 * al día ANTERIOR, así que el traslado del sábado aparecería el viernes. Es el
 * error que `utils/fechaLocal.ts` documenta al revés, y acá entra por las dos
 * puntas porque este componente lee `fecha` (instante) y `prestado_desde`, que
 * el backend puede fijar como día.
 */
const dia = (iso: string) => {
  if (/^\d{4}-\d{2}-\d{2}$/.test(iso)) {
    return new Date(iso + 'T00:00:00').toLocaleDateString('es-CO', OPTS_DIA)
  }
  const s = iso.replace(' ', 'T').replace('+00:00', 'Z')
  return new Date(s.endsWith('Z') ? s : s + 'Z').toLocaleDateString('es-CO', OPTS_DIA)
}

/** El lugar del select mientras el catálogo de sedes no está: gris y mudo, sin
 *  afirmar que no haya sedes. Misma caja para no descuadrar la grilla. */
const CajaSedes = ({ texto }: { texto: string }) => (
  <p className="text-[11px] text-warm-500 bg-warm-100 rounded-xl px-3 py-3 min-h-[44px] flex items-center">
    {texto}
  </p>
)

/**
 * ═════════════════════════════════════════════════════════════════════════════
 * LA BASE DE LA CAJA FUERTE SALIÓ A TRABAJAR — el hecho que no se podía registrar
 * ═════════════════════════════════════════════════════════════════════════════
 * Cada sede guarda $500.000 en la caja fuerte para emergencias. Cuando en el día
 * los pagos a proveedores en efectivo se comen la venta en efectivo, sacan esa
 * plata y la meten al cajón para poder seguir operando; cuando la venta se
 * normaliza, la vuelven a guardar. Pasa a CUALQUIER HORA, no al abrir.
 *
 * El sistema ya guardaba CUÁNTO hay en la caja fuerte (`CajaTurno.caja_fuerte`)
 * pero no tenía forma de decir que esa plata SE MOVIÓ al cajón. Entonces el
 * cuadre veía efectivo de más en la registradora y concluía lo único que sabía
 * concluir: «sobró plata, hay que bancarla». El sábado 15 de agosto en Palmetto
 * eso convirtió $197.900 a consignar en $697.900 — los $500.000 de la base
 * facturados como sobrante.
 *
 * ── ESTO REGISTRA UN HECHO, NO AGREGA UN MECANISMO ─────────────────────────
 * El módulo ya tiene TRES cosas que mueven plata entre días (la cascada FIFO, el
 * `sobrante_consignable` de la apertura y el ajuste de apertura) y ninguna sabe
 * de las otras. Un cuarto ajuste manual del esperado fue descartado a propósito.
 * Acá se anota que la plata cambió de lugar; el `efectivo_esperado` del cuadre
 * suma ese término y las cuentas que ya existían dan bien solas. La fórmula del
 * consignable no se toca.
 *
 * ── SOLO ADMIN, Y NO ES EL GATE QUE LA CASA PROHÍBE ────────────────────────
 * Los tres endpoints son `require_admin` y esta pantalla la abren también las
 * baristas. El gate de la regla 5 —«ningún formulario adentro de un gate por
 * ESTADO»— es sobre datos que no llegaron: ahí el formulario se queda montado
 * con su aviso. Este es un gate por ROL, y montar la fila para alguien que va a
 * comer un 403 en cada guardado no le sirve a nadie.
 */
export default function PanelCajaFuerte({ tiendaId, sedes, onGuardado }: {
  /** La sede que el admin está mirando arriba: gobierna el saldo Y el default
   *  del select de la fila. */
  tiendaId: number
  sedes: Fuente<Sede[]>
  /** Un traslado cambia el esperado de los cuadres: la lista de turnos se repide. */
  onGuardado: () => void
}) {
  const estado = useDato<EstadoCajaFuerte>(
    () => api.get('/caja/prestamos-caja-fuerte', { params: { tienda_id: tiendaId } }),
    'los traslados de la caja fuerte',
    'No se pudo leer si hay plata de la caja fuerte prestada al cajón.',
    [tiendaId],
  )

  return (
    <section className="bg-white rounded-2xl border border-warm-200 overflow-hidden mb-2">
      <div className="flex items-center gap-1.5 px-4 pt-3 pb-2">
        <Lock size={13} className="text-warm-500 shrink-0" />
        <p className="text-[11px] font-bold uppercase tracking-wide text-warm-500">
          Caja fuerte de la sede
        </p>
      </div>

      {/* SIN PADDING VERTICAL ACÁ. Cada rama pone el suyo, y así el día normal
          —saldo en cero, `SaldoPrestado` devuelve `null`— este contenedor mide
          cero de alto en vez de dejar una banda vacía abajo del título. */}
      <div className="px-4">
        <SegunDato
          dato={estado.dato}
          // `cargando` no es `falla`: un renglón mudo, nunca un aviso de error.
          cargando={<p className="text-[11px] text-warm-400 pb-2">Leyendo la caja fuerte…</p>}
          // EL HUECO OCUPA LUGAR A PROPÓSITO (regla 4). Si esto se evaporara con
          // el fetch caído, un saldo de $500.000 prestados se leería exactamente
          // igual que un día normal — que es la mentira que este panel vino a
          // matar, entrando por la otra puerta.
          falla={m => (
            <div className="pb-2">
              <NoSeSabe onReintentar={estado.recargar}
                mensaje={`${m} — no se sabe si hay plata de la caja fuerte adentro del cajón, así que `
                  + 'el efectivo que cuenten hoy puede no cuadrar con el sistema.'} />
            </div>
          )}
          listo={e => <SaldoPrestado estado={e} />}
        />
      </div>

      <FormTraslado tiendaId={tiendaId} sedes={sedes}
        onGuardado={() => { estado.recargar(); onGuardado() }} />

      <SegunDato
        dato={estado.dato}
        cargando={null}
        // El aviso de arriba ya dijo que no se pudo leer; repetirlo acá sería
        // dos huecos para el mismo fetch.
        falla={() => null}
        listo={e => (
          <ListaTraslados traslados={e.traslados}
            onBorrado={() => { estado.recargar(); onGuardado() }} />
        )}
      />

      <ComoSeCalcula titulo="¿Qué hace registrar un traslado?">
        <p>
          {/* El monto de la base NO se escribe acá: el sistema no lo conoce (vive
              en la caja fuerte de cada sede) y una cifra puesta a mano en este
              párrafo envejece sin que nadie se entere. */}
          La base de la caja fuerte <b>no está en la registradora</b>: es plata guardada aparte
          para emergencias. Cuando los pagos a proveedores en efectivo se comen la venta en
          efectivo del día y hay que sacarla al cajón para poder seguir operando, registralo acá.
        </p>
        <p>
          Guardar un <b>«Saca»</b> le avisa al cuadre que esa plata está adentro del cajón: el
          efectivo que se espera contar sube por el mismo monto, así que el conteo cuadra y{' '}
          <b>no se dispara ningún sobrante</b>. Sin esto, el sistema ve plata de más, la toma como
          sobrante y te la manda a consignar — el sábado 15 de agosto pidió consignar $697.900
          donde iban $197.900.
        </p>
        <p>
          Guardar un <b>«Devuelve»</b> cuando la plata vuelve a la caja fuerte baja el saldo otra
          vez. Con el saldo en cero, este panel desaparece del renglón de arriba y todo sigue como
          siempre. <b>Lo que se consigna no cambia por esto</b>: sigue siendo la venta en efectivo
          más los ingresos menos los egresos.
        </p>
      </ComoSeCalcula>
    </section>
  )
}

/**
 * El saldo vigente, y solo cuando hay algo que decir.
 *
 * EN CERO NO OCUPA LUGAR. El día normal es el día en que la base está guardada,
 * y un renglón que dice «$0 prestados» todos los días es ruido que después nadie
 * lee — justo el renglón que tiene que saltar a la vista el día que no es cero.
 */
function SaldoPrestado({ estado }: { estado: EstadoCajaFuerte }) {
  const p = estado.prestado_caja_fuerte

  if (Math.round(p) === 0) return null

  /**
   * NEGATIVO ES IMPOSIBLE, ASÍ QUE NO ES UN SALDO: ES UN AVISO.
   *
   * Devolver más plata de la que salió no puede pasar en la vida real, o sea que
   * hay un traslado mal cargado (casi siempre un «Devuelve» tecleado dos veces, o
   * un «Saca» que nunca se registró). Mismo trato que ya tiene un cajón en
   * negativo en `BannerSaldos`: rojo, y con la frase que dice dónde buscar. El
   * backend tampoco lo pisa a cero — taparlo con un `max(0, …)` de cualquiera de
   * los dos lados es exactamente el tipo de mentira que este módulo viene matando.
   */
  if (p < 0) {
    return (
      <div className="mb-2 rounded-xl border border-danger-200 bg-danger-50 px-3 py-2.5">
        <p className="text-sm font-bold text-danger-700 font-mono tabular-nums">{plata(p)}</p>
        <p className="text-[11px] text-danger-700 leading-snug mt-0.5">
          <b>Volvió más plata a la caja fuerte de la que salió, y eso no puede pasar.</b> Hay un
          traslado mal cargado: revisá la lista de abajo y borrá el que sobra. Mientras esté así,
          el efectivo que se espera contar en la registradora está <b>por debajo</b> del real.
        </p>
      </div>
    )
  }

  return (
    <div className="mb-2 rounded-xl border border-gold-200 bg-gold-50 px-3 py-2.5">
      <p className="text-sm font-bold text-gold-700">
        De la caja fuerte hay{' '}
        <span className="font-mono tabular-nums">{plata(p)}</span> prestados al cajón
      </p>
      <p className="text-[11px] text-gold-700 leading-snug mt-0.5">
        {/* La fecha se dice SOLO si el backend la mandó. Un «desde hoy» inventado
            acá sería un dato de la nada justo en el renglón que explica el número. */}
        {estado.prestado_desde
          ? <>Salieron el {dia(estado.prestado_desde)}. </>
          : null}
        El cuadre ya los cuenta, así que el conteo de la registradora tiene que dar{' '}
        <b>{plata(p)} más</b> de lo normal y no se dispara ningún sobrante. Cuando vuelvan a la
        caja fuerte, registrá el «Devuelve».
      </p>
    </div>
  )
}

/**
 * ═════════════════════════════════════════════════════════════════════════════
 * LA FILA — siempre montada, nunca un modal
 * ═════════════════════════════════════════════════════════════════════════════
 * Pedido textual del dueño («no quiero desplegar pestañas»), el mismo criterio
 * que `FormMovimiento` y `FormRecogida`. Sacar la base de las dos sedes el mismo
 * día son dos cargas seguidas: guardar limpia el monto y el motivo, devuelve el
 * foco al monto y deja la fecha y la sede puestas.
 *
 * ── EL SENTIDO ARRANCA SIN ELEGIR ──────────────────────────────────────────
 * Es lo único que NO se conserva entre cargas, y no se limpia por comodidad sino
 * por seguridad: es lo que decide el SIGNO. Un default («saca», por ser lo más
 * común) se guarda sin que nadie lo mire, y un «devuelve» cargado como «saca»
 * mueve un millón de pesos de esperado en la dirección equivocada. Encadenar dos
 * cargas sin volver a mirar el botón es exactamente cómo se cuela.
 *
 * ── Y SON DOS BOTONES, NO UN SELECT ────────────────────────────────────────
 * Son dos y hay que verlos. Un desplegable de dos opciones esconde justo el dato
 * que más caro sale equivocar.
 */
function FormTraslado({ tiendaId, sedes, onGuardado }: {
  tiendaId: number
  sedes: Fuente<Sede[]>
  onGuardado: () => void
}) {
  /** El catálogo LEÍDO, o `null` mientras no esté en la mano. `null` no es «no
   *  hay sedes»: es «no se sabe». Solo alimenta el default del select. */
  const ts = sedes.dato.estado === 'listo' ? sedes.dato.valor : null

  const hoy = hoyBogota()

  const [sedeId, setSedeId] = useState(String(tiendaId))
  const [sentido, setSentido] = useState<'saca' | 'devuelve' | null>(null)
  const [monto, setMonto] = useState('')
  const [fecha, setFecha] = useState(hoy)
  const [motivo, setMotivo] = useState('')
  const [error, setError] = useState('')
  const [guardando, setGuardando] = useState(false)
  const [ultimo, setUltimo] = useState('')

  const refMonto = useRef<HTMLInputElement>(null)

  // LA FILA SIGUE A LA SEDE QUE SE ESTÁ MIRANDO. El saldo de arriba y la lista de
  // abajo son de `tiendaId`; que el select apunte a otra sede dejaría cargar un
  // traslado de Vida con el cajón de Palmetto en pantalla. No es el efecto de
  // preselección de `FormRecogida` —allá no hay sede en la página— pero cubre lo
  // mismo: sin un valor que matchee una opción, el navegador dibuja la PRIMERA
  // como si estuviera elegida y el submit guarda contra otra sede (o no guarda).
  useEffect(() => { setSedeId(String(tiendaId)) }, [tiendaId])

  // Y SI ESA SEDE NO ESTÁ EN EL CATÁLOGO, CAE EN LA PRIMERA. Pasa cuando la sede
  // del usuario quedó inactiva, o en el parpadeo entre que el catálogo llega y la
  // pantalla de arriba salta a su primera sede. Es el bug ya cazado dos veces en
  // este repo visto del otro lado: con un `value` que no matchea ninguna opción,
  // el navegador dibuja la PRIMERA como si estuviera elegida y el traslado se
  // guarda contra una sede que nadie eligió. No pisa una elección válida.
  useEffect(() => {
    if (ts && ts.length > 0 && !ts.some(t => String(t.id) === sedeId)) {
      setSedeId(String(ts[0].id))
    }
  }, [ts, sedeId])

  const sede = ts?.find(t => String(t.id) === sedeId)
  const excede = Number(monto) > MONTO_MAX
  const listo = !!fecha && !!sedeId && !!sentido && Number(monto) > 0 && !excede

  const guardar = async () => {
    // GUARDA DE REENTRADA. Enter y el botón llaman a lo mismo y en el medio hay
    // una ida y vuelta: dos toques ahí adentro escriben DOS traslados. En la
    // tablet del local eso duplica el término del cuadre, y el esperado queda
    // $500.000 arriba del real — el mismo error de siempre, con el signo dado
    // vuelta.
    if (guardando) return
    if (!listo || !sentido) return
    setGuardando(true); setError('')
    try {
      // La respuesta NO se lee para pintar el saldo nuevo: eso se relee del
      // backend con `onGuardado`. Sumar acá lo tecleado sería una segunda
      // matemática para el mismo número, y así es como dos cifras de la misma
      // pregunta terminan discrepando.
      await api.post('/caja/prestamos-caja-fuerte', {
        tienda_id: Number(sedeId),
        sentido,
        monto: Number(monto),
        motivo: motivo.trim() || null,
        fecha,
      })
      // Confirmación EN LA FILA y CON LA SEDE ADENTRO: es el único guardarraíl
      // contra cargar el segundo traslado del día sobre la sede del primero.
      setUltimo(
        `${sentido === 'saca' ? 'Salieron' : 'Volvieron'} ${conMiles(monto)} `
        + `${sentido === 'saca' ? 'de' : 'a'} la caja fuerte de ${sede?.nombre ?? 'la sede elegida'}`
        + ` · ${dia(fecha)}`)
      setMonto(''); setMotivo(''); setSentido(null)
      refMonto.current?.focus()
      onGuardado()
    } catch (e) {
      setError(detalleDeError(e, 'No se pudo guardar el traslado. Reintentá.'))
    } finally { setGuardando(false) }
  }

  return (
    <div className="px-4 py-3 bg-warm-50 border-t border-warm-100 space-y-2"
      onKeyDown={teclas({ listo, guardar })}>
      <p className="text-[11px] font-bold uppercase tracking-wide text-warm-500">
        Registrá un traslado
      </p>

      {/* EL AVISO VA ARRIBA DEL SELECT y la fila se queda montada (regla 5): sin
          sede el backend no acepta el traslado, así que decirlo acá —con el
          botón de reintentar— es lo único que evita que el dueño teclee todo
          contra un «Guardar» gris que no explica nada. */}
      <SegunDato
        dato={sedes.dato}
        cargando={null}
        falla={m => (
          <NoSeSabe onReintentar={sedes.recargar}
            mensaje={`${m} — sin la sede no se puede guardar el traslado. Podés ir tecleando el `
              + 'resto: el monto, el día y el motivo no dependen del catálogo.'} />
        )}
        listo={lista => lista.length === 0 ? (
          <NoSeSabe mensaje="No hay ninguna sede cargada, así que todavía no se puede registrar un traslado." />
        ) : null}
      />

      {/* Mobile-first: dos columnas en celular, la fila entera en tablet. */}
      <div className="grid grid-cols-2 sm:grid-cols-[11rem_14rem_9rem_8.5rem_1fr_auto] gap-2 items-end">
        <Campo label="¿Qué sede?" ancho="col-span-2 sm:col-span-1">
          {/* «Vacío», «todavía no llegó» y «no volvió» son TRES cosas distintas y
              cada una se dibuja distinta. Con una sola caja para las tres, el
              catálogo caído deja puesto un «Cargando…» que no se va nunca. */}
          <SegunDato
            dato={sedes.dato}
            cargando={<CajaSedes texto="Cargando las sedes…" />}
            falla={() => <CajaSedes texto="Sin sedes para elegir" />}
            listo={lista => lista.length === 0
              ? <CajaSedes texto="No hay sedes cargadas" />
              : (
                <select value={sedeId} onChange={e => setSedeId(e.target.value)}
                  aria-label="Sede del traslado" className={CLS_INPUT}>
                  {lista.map(t => <option key={t.id} value={t.id}>{t.nombre}</option>)}
                </select>
              )}
          />
        </Campo>

        <Campo label="¿Para dónde va la plata?" ancho="col-span-2 sm:col-span-1">
          <div className="grid grid-cols-2 gap-1.5">
            <button type="button" onClick={() => setSentido('saca')}
              aria-pressed={sentido === 'saca'}
              className={`flex items-center justify-center gap-1 min-h-[44px] rounded-xl border-2 px-1 text-xs font-bold text-center leading-tight transition-colors ${
                sentido === 'saca'
                  ? 'border-gold-500 bg-gold-50 text-gold-700'
                  : 'border-warm-200 bg-white text-warm-500'}`}>
              <ArrowUpFromLine size={14} className="shrink-0" /> Saca de la caja fuerte
            </button>
            <button type="button" onClick={() => setSentido('devuelve')}
              aria-pressed={sentido === 'devuelve'}
              className={`flex items-center justify-center gap-1 min-h-[44px] rounded-xl border-2 px-1 text-xs font-bold text-center leading-tight transition-colors ${
                sentido === 'devuelve'
                  ? 'border-success-500 bg-success-50 text-success-700'
                  : 'border-warm-200 bg-white text-warm-500'}`}>
              <ArrowDownToLine size={14} className="shrink-0" /> Devuelve a la caja fuerte
            </button>
          </div>
        </Campo>

        <Campo label="Cuánto">
          <input ref={refMonto} type="text" inputMode="numeric" value={conMiles(monto)}
            onChange={e => setMonto(soloDigitos(e.target.value))} placeholder="0"
            aria-label="Monto del traslado"
            className={CLS_INPUT_PLATA} />
        </Campo>

        <Campo label="¿Qué día?">
          {/* El backend rechaza el futuro (no se puede haber movido plata de un
              día que todavía no llegó): el campo no lo ofrece en vez de ofrecerlo
              y fallar después del toque. */}
          <input type="date" value={fecha} max={hoy}
            onChange={e => setFecha(e.target.value)} className={CLS_INPUT} />
        </Campo>

        <Campo label="Motivo (opcional)" ancho="col-span-2 sm:col-span-1">
          <input value={motivo} onChange={e => setMotivo(e.target.value)} maxLength={MOTIVO_MAX}
            placeholder="Para qué hizo falta"
            className={CLS_INPUT} />
        </Campo>

        <button type="button" onClick={guardar} disabled={guardando || !listo}
          className={`${CLS_BOTON_GUARDAR} col-span-2 sm:col-span-1`}>
          {guardando ? 'Guardando…' : 'Guardar'}
        </button>
      </div>

      {/* EL BOTÓN GRIS SIEMPRE SE EXPLICA. Un «Guardar» apagado sin decir por qué
          es el bug que este repo ya cazó dos veces: el dueño teclea todo, toca, y
          no pasa nada. El tope no es una regla inventada — la columna es
          Numeric(12,2) y un monto más grande revienta el INSERT con un error que
          no dice nada. */}
      {excede && (
        <p className="text-[11px] font-semibold text-danger-700">
          El tope de un traslado es {plata(MONTO_MAX)}. Revisá si sobra un cero.
        </p>
      )}
      {!excede && !sentido && Number(monto) > 0 && (
        <p className="text-[11px] text-warm-500">
          Falta elegir si la plata <b>sale</b> de la caja fuerte o <b>vuelve</b> a ella.
        </p>
      )}

      <p className="text-[11px] text-warm-400 leading-snug">
        El monto va siempre en positivo: el sentido dice si sale o vuelve. Esto <b>no</b> es una
        venta ni un gasto — la plata no aparece ni desaparece, cambia de lugar.
      </p>

      <ErrorCampo msg={error} />
      {!error && ultimo && (
        <p className="text-[11px] font-semibold text-success-600">Guardado: {ultimo}</p>
      )}
    </div>
  )
}

/**
 * Los traslados cargados, del más nuevo al más viejo.
 *
 * No es un lujo de auditoría: el banner rojo manda a buscar «el traslado que
 * sobra», y sin esta lista esa instrucción no tiene dónde ejecutarse. Es la
 * única puerta al borrado.
 */
function ListaTraslados({ traslados, onBorrado }: {
  traslados: TrasladoCajaFuerte[]
  onBorrado: () => void
}) {
  const [borrando, setBorrando] = useState<number | null>(null)
  const [error, setError] = useState('')

  // Ordenar es presentación, no una segunda cuenta: el saldo lo sigue diciendo
  // el backend. Se ordena acá para no depender del orden en que vengan.
  const filas = [...traslados].sort((a, b) => (b.fecha || '').localeCompare(a.fecha || ''))

  if (filas.length === 0) return null

  const borrar = async (t: TrasladoCajaFuerte) => {
    if (!window.confirm(
      `¿Borrar el traslado de ${plata(t.monto)} del ${dia(t.fecha)}?\n\n`
      + 'El saldo prestado y el efectivo que se espera en la registradora se recalculan.')) return
    setBorrando(t.id); setError('')
    try {
      await api.delete(`/caja/prestamos-caja-fuerte/${t.id}`)
      onBorrado()
    } catch (e) {
      setError(detalleDeError(e, 'No se pudo borrar el traslado. Reintentá.'))
    } finally { setBorrando(null) }
  }

  return (
    <div className="border-t border-warm-100">
      <p className="px-4 pt-2.5 text-[10px] font-bold uppercase tracking-wide text-warm-500">
        Traslados cargados ({filas.length})
      </p>
      <div className="divide-y divide-warm-100">
        {filas.map(t => (
          <div key={t.id} className="flex items-center gap-2 px-4 py-2">
            <span className={`text-[10px] font-bold uppercase tracking-wide px-2 py-0.5 rounded-full shrink-0 ${
              t.sentido === 'saca' ? 'bg-gold-100 text-gold-700' : 'bg-success-50 text-success-700'}`}>
              {t.sentido === 'saca' ? 'Salió' : 'Volvió'}
            </span>
            <span className="text-xs font-bold font-mono tabular-nums text-warm-700 shrink-0">
              {plata(t.monto)}
            </span>
            <span className="text-[11px] text-warm-500 truncate flex-1 min-w-0">
              {dia(t.fecha)}
              {t.motivo && <> · {t.motivo}</>}
              {t.usuario_nombre && <> · {t.usuario_nombre}</>}
            </span>
            <button type="button" onClick={() => borrar(t)} disabled={borrando === t.id}
              title="Borrar este traslado (se cargó por error)"
              aria-label={`Borrar el traslado de ${plata(t.monto)}`}
              className="shrink-0 min-h-[32px] px-2 rounded-lg text-danger-500 hover:bg-danger-50 disabled:opacity-40">
              <Trash2 size={13} />
            </button>
          </div>
        ))}
      </div>
      {error && <div className="px-4 pb-2"><ErrorCampo msg={error} /></div>}
    </div>
  )
}
