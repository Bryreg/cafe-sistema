import { ReactNode, useMemo, useState } from 'react'
import { ChevronRight } from 'lucide-react'
import api from '../../api/client'
import { soloDigitos } from '../../utils/plata'
import { Dato, mapDato } from '../../api/dato'
import type { Fuente } from '../../api/useDato'
import { SegunDato, NoSeSabe } from '../ui'
import { MESES, detalleDeError, plata } from '../plata/banco'
import { Agenda, Categoria, Flujo, Listado } from '../plata/tipos'
import { CLS_INPUT, CLS_INPUT_PLATA, CLS_BOTON_GUARDAR, CLS_BOTON_SUAVE, ErrorCampo, teclas } from '../plata/campos'
import { entraAlPiso } from './calculo'
import type { ArmadoDelMes, CuentaSuelta, Impoconsumo, Piso } from './tipos'

// ═════════════════════════════════════════════════════════════════════════════
// UNA VEZ AL MES — de acá salen el piso de hoy y el «¿llego a fin de mes?»
// ═════════════════════════════════════════════════════════════════════════════
// Todo lo de este bloque se toca una vez al mes o menos, así que vive plegado y
// al pie. Pero no es «configuración»: son los seis números que gobiernan la
// página entera. La reserva mínima decide el colchón, la comisión del datáfono
// decide el margen, la nómina agendada decide si el bloque 5 puede mostrar
// algún número.
//
// ── EL DÍA 1 SE DIBUJA ARRIBA DE TODO ────────────────────────────────────
// Es el único día del mes en que la página cambia de forma. `arriba` lo decide
// la página; acá solo cambia el título y el marco.
//
// ── SE ABRE EN EL MISMO SCROLL, NO NAVEGA ────────────────────────────────
// Cada una de estas cosas es un campo y un botón. Mandarlas a otra pantalla es
// lo que hizo que ninguna se cargara nunca.

interface Props {
  piso: Fuente<Piso>
  flujo: Fuente<Flujo>
  agenda: Fuente<Agenda>
  obligaciones: Fuente<Listado>
  categorias: Fuente<Categoria[]>
  impoconsumo: Fuente<Impoconsumo>
  anio: number
  mes: number
  anioSiguiente: number
  mesSiguiente: number
  /** true = hoy es día 1 (o quedan cosas del arranque): sube al tope. */
  arriba: boolean
  onCambio: () => void
  onVerElMesEnDetalle: () => void
  id?: string
}

const nombreMes = (m: number) => MESES[m - 1] ?? `mes ${m}`

/** Un renglón del bloque: rótulo, estado actual y el control que lo cambia. */
function Item({ titulo, estado, children }: {
  titulo: string; estado: ReactNode; children?: ReactNode
}) {
  return (
    <div className="px-4 py-2.5 border-t border-warm-100 first:border-t-0">
      <div className="flex items-baseline justify-between gap-2">
        <p className="text-xs font-semibold text-warm-700 flex-1 min-w-0">{titulo}</p>
        <div className="shrink-0 text-right">{estado}</div>
      </div>
      {children && <div className="mt-1.5">{children}</div>}
    </div>
  )
}

/**
 * LA OFERTA: las cuentas vivas que todavía no son serie, para elegir cuáles van.
 *
 * Existe porque el lote nacía inerte. Solo se copian solas las cuentas que
 * alguien ya declaró repetibles apretando «Repetir mes que viene», y en esta
 * cafetería los costos fijos se cargan a mano todos los meses y ese botón no se
 * apretó nunca: cero series, nada que copiar, y la pantalla diciendo que estaba
 * todo bien mientras el mes siguiente arrancaba con el piso en $0.
 *
 * NO SE TILDA NADA POR DEFECTO, y es la decisión de diseño de este bloque.
 * Copiar todo automáticamente arrastraría la reparación del molino y el anticipo
 * al mes que viene, y un costo inventado INFLA el piso — el mismo error, mirado
 * del otro lado. El sistema no puede distinguir un arriendo de una reparación
 * (las dos son categoría de grupo "fijo"); el dueño sí, y le toma un tap.
 *
 * Con la plata al lado de cada renglón, porque la pregunta real no es «¿esta se
 * repite?» sino «¿estos $8.500.000 se pagan otra vez el mes que viene?».
 */
function Elegir({ candidatas, deMes, aMes, elegidas, onMarcar }: {
  candidatas: CuentaSuelta[]
  /** De qué mes salen las cuentas ofrecidas. */
  deMes: string
  /** A qué mes irían. Se nombra porque el aviso de `parecidas` habla de ÉL. */
  aMes: string
  elegidas: Set<number>
  onMarcar: (id: number) => void
}) {
  const tildadas = candidatas.filter(c => elegidas.has(c.obligacion_id))
  const total = tildadas.reduce((s, c) => s + c.monto, 0)
  return (
    <div className="rounded-lg border border-warm-200 bg-white p-2 space-y-1">
      <p className="text-[11px] font-bold text-warm-700">
        {candidatas.length} {candidatas.length === 1 ? 'cuenta' : 'cuentas'} de{' '}
        {deMes} sin marcar para repetir
      </p>
      <p className="text-[11px] text-warm-400 leading-snug">
        Tildá las que se pagan todos los meses. Las de una sola vez —un arreglo,
        un anticipo, una compra suelta— dejalas sin tildar: copiarlas inventaría
        un costo que nadie va a pagar y subiría el piso de más. Lo que tildes
        queda marcado, y de acá en más se copia solo.
      </p>
      {/* CÓMO SE SALE, DICHO ANTES DE ENTRAR. «Queda marcado» es una decisión
          que se toma con un tap y hasta acá no tenía vuelta: tildar por error la
          reparación del molino la volvía un costo fijo mensual y el piso subía
          todos los meses. Decirlo acá le baja el costo al tilde — y a un dueño
          que no tilda nada por miedo el mes que viene le arranca en cero. */}
      <p className="text-[11px] text-warm-400 leading-snug">
        Si te equivocás no queda para siempre: el mes que viene la vas a ver en
        la lista de lo que se va a copiar, con un «esta no se repite» al lado que
        la saca sin borrar nada de lo ya cargado.
      </p>
      <ul className="divide-y divide-warm-100">
        {candidatas.map(c => (
          <li key={c.obligacion_id}>
            <label className="flex items-center gap-2 py-2 min-h-[40px] cursor-pointer">
              <input type="checkbox" className="shrink-0 w-4 h-4 accent-clay-500"
                checked={elegidas.has(c.obligacion_id)}
                onChange={() => onMarcar(c.obligacion_id)} />
              <span className="flex-1 min-w-0 text-[11px] text-warm-600 truncate">
                {c.concepto}
                {c.tienda_nombre && (
                  <span className="text-warm-400"> · {c.tienda_nombre}</span>
                )}
                <span className="text-warm-400"> · {c.categoria_nombre}</span>
              </span>
              <span className="shrink-0 font-mono tabular-nums text-[11px] text-warm-700">
                {plata(c.monto)}
              </span>
            </label>
            {/* EL AVISO VA EN EL RENGLÓN, ANTES DEL TILDE Y NO DESPUÉS.
                El server tapa lo que reconoce por concepto + sede, y eso es una
                igualdad: «Arriendo Vida» y «Arriendo local Vida» no matchean, así
                que esta cuenta se ofrece igual y tildarla duplicaría el arriendo.
                Aflojar el matcheo para que las agarrara escondería costos reales
                —el mes destino quedaría corto y el piso BAJO—, así que la cuenta
                se ofrece y el aviso viaja pegado a ella.

                `?? []` NO viola la regla 2 de `ui/README.md`: acá no se saca
                ninguna conclusión de que esté vacío. Con el backend viejo (la
                ventana del deploy de la PWA) el campo llega `undefined` y no se
                dibuja aviso, que es lo mismo que dibuja hoy. */}
            {(c.parecidas ?? []).length > 0 && (
              <div className="pb-2 pl-6">
                {(c.parecidas ?? []).map(p => (
                  <p key={p.obligacion_id}
                    className="text-[11px] text-gold-700 leading-snug">
                    Ojo: {aMes} ya tiene <b>{p.concepto}</b> por{' '}
                    <span className="font-mono tabular-nums">{plata(p.monto)}</span>
                    {' '}en {p.categoria_nombre}. Si es la misma, no la tildes.
                  </p>
                ))}
              </div>
            )}
          </li>
        ))}
      </ul>
      <p className="text-[11px] font-bold text-warm-700">
        {tildadas.length === 0
          ? 'Ninguna tildada todavía.'
          : `${tildadas.length} ${tildadas.length === 1 ? 'tildada' : 'tildadas'} · `
            + `${plata(total)} que se le suman a cada mes`}
      </p>
    </div>
  )
}

/** Un campo de plata con su botón, para los tres números que se declaran. */
function CampoPlata({ valor, onGuardar, sufijo, ayuda, etiqueta }: {
  valor: string
  onGuardar: (v: string) => Promise<void>
  sufijo?: string
  ayuda?: ReactNode
  etiqueta: string
}) {
  const [v, setV] = useState(valor)
  const [error, setError] = useState('')
  const [guardando, setGuardando] = useState(false)
  const [ok, setOk] = useState(false)

  const guardar = async () => {
    if (guardando || !v) return
    setGuardando(true); setError(''); setOk(false)
    try { await onGuardar(v); setOk(true) }
    catch (e) { setError(detalleDeError(e, 'No se pudo guardar.')) }
    finally { setGuardando(false) }
  }

  return (
    <div className="space-y-1.5" onKeyDown={teclas({ listo: !!v, guardar })}>
      <div className="flex items-center gap-2">
        <input type="text" inputMode="decimal" value={v} aria-label={etiqueta}
          onChange={e => { setOk(false); setV(sufijo === '%' ? e.target.value : soloDigitos(e.target.value)) }}
          className={`${CLS_INPUT_PLATA} max-w-[180px]`} />
        {sufijo && <span className="text-sm font-bold text-warm-500">{sufijo}</span>}
        <button onClick={guardar} disabled={guardando || !v} className={CLS_BOTON_GUARDAR}>
          {guardando ? 'Guardando…' : 'Guardar'}
        </button>
      </div>
      {ayuda && <p className="text-[11px] text-warm-400 leading-snug">{ayuda}</p>}
      {ok && <p className="text-[11px] font-bold text-success-700">Guardado.</p>}
      <ErrorCampo msg={error} />
    </div>
  )
}

export default function UnaVezAlMes({
  piso, flujo, agenda, obligaciones, categorias, impoconsumo,
  anio, mes, anioSiguiente, mesSiguiente, arriba, onCambio, onVerElMesEnDetalle, id,
}: Props) {
  const [abierto, setAbierto] = useState(arriba)
  const [error, setError] = useState('')
  const [aviso, setAviso] = useState('')
  const [armando, setArmando] = useState(false)
  const [agendando, setAgendando] = useState(false)
  const [agendandoImpo, setAgendandoImpo] = useState(false)
  /** La lista que devolvió la vista previa. `null` = todavía no se pidió. */
  const [previa, setPrevia] = useState<ArmadoDelMes | null>(null)
  /** Las cuentas sueltas tildadas ahora mismo, sin mandar todavía. */
  const [elegidas, setElegidas] = useState<Set<number>>(new Set())
  /**
   * Con QUÉ elección se pidió la `previa` que está en pantalla.
   *
   * No es lo mismo que `elegidas`: apenas el dueño tilda una más, lo que se ve
   * deja de ser la lista de lo que se va a crear. Mientras las dos no coincidan
   * el botón de crear no aparece — la promesa de este bloque es que se confirma
   * EXACTAMENTE la lista que se miró, y el commit manda esta y no la tildada.
   */
  const [previaCon, setPreviaCon] = useState<number[]>([])
  const [declarando, setDeclarando] = useState(false)

  /**
   * La reserva YA CARGADA, como texto para precargar el campo.
   *
   * `''` cuando el flujo no volvió o cuando la reserva es el default: el 0 del
   * default no es una decisión de nadie, así que precargarlo lo haría guardable
   * de un toque y un cero sin decidir pasaría por un cero decidido.
   */
  const reservaCargada = flujo.dato.estado === 'listo' && !flujo.dato.valor.reserva_es_default
    ? String(Math.round(flujo.dato.valor.reserva_minima_caja))
    : ''

  /**
   * EL VISTAZO LOCAL, Y POR QUÉ SON TRES NÚMEROS Y NO UNO.
   *
   * Antes acá había un solo conteo —las series sin copiar— y la pantalla lo
   * publicaba como «al día» cuando daba cero. En este negocio los costos fijos
   * se cargan a mano todos los meses y nadie apretó nunca «Repetir mes que
   * viene», así que NINGUNA cuenta es serie: el conteo daba cero porque no había
   * series, y la pantalla lo leía como que ya estaba todo copiado. Dos ceros
   * distintos con la misma cara, y del lado tranquilizador — el 1 de septiembre
   * el piso decía $0,00 con $27,6M de fijos por aparecer.
   *
   * `haySerie` es el que los separa, y por eso viaja al lado del conteo y no
   * derivado de él.
   */
  const vistazo = useMemo<Dato<{
    /** Series mensuales que todavía no tienen su copia del mes que viene. */
    sinCopiar: number
    /** ¿Hay al menos UNA cuenta marcada como repetible? */
    haySerie: boolean
    /** Cuentas vivas de este mes que nadie marcó como repetibles. */
    sueltas: number
    /**
     * CUÁNTOS COSTOS FIJOS Y CUÁNTA PLATA TIENE YA EL MES QUE VIENE.
     *
     * EL NÚMERO QUE FALTABA CONTAR, y por no contarlo esta pantalla escribía
     * «arrancaría sin costos fijos y el piso en cero» sobre un mes que ya tenía
     * $27.620.000 cargados a mano — y salía del MISMO array. El dueño tildaba
     * los cinco de la oferta y el mes destino pasaba a $55.240.000, con el piso
     * en $59.659.195,23 contra los $29.829.597,61 que necesita.
     *
     * SE CUENTAN CON `entraAlPiso` Y NO TODAS LAS VIVAS, porque la frase que
     * este número gobierna habla del PISO. Contar todas daba un número CERCA del
     * correcto y del lado tranquilizador: una declaración del impoconsumo sola
     * en el mes apagaba el aviso de un mes sin un peso de costos fijos.
     *
     * Viven adentro del `Dato` y no como locales: `cero` acá tiene que
     * significar «lo miré y está vacío», y eso solo se puede afirmar en la rama
     * `listo`.
     */
    yaEnElMesQueViene: number
    platEnElMesQueViene: number
  }>>(
    () => mapDato(obligaciones.dato, l => {
      const clave = `${anioSiguiente}-${String(mesSiguiente).padStart(2, '0')}`
      const vivas = l.obligaciones.filter(o => o.estado !== 'anulada')
      const enElMes = vivas.filter(o => o.fecha_devengo.slice(0, 7) === clave)
      const ya = new Set(enElMes
        .map(o => o.plantilla_id)
        .filter((x): x is number => x !== null))
      const fuera = vivas.filter(o => o.fecha_devengo.slice(0, 7) !== clave)
      // Para «¿falta la copia?» valen TODAS las del mes, no solo las del piso:
      // una copia ya hecha en categoría variable existe igual, y volver a
      // crearla sería duplicarla.
      const fijosEnElMes = enElMes.filter(entraAlPiso)
      return {
        sinCopiar: fuera.filter(o =>
          o.plantilla_id !== null && !ya.has(o.plantilla_id)).length,
        haySerie: vivas.some(o => o.plantilla_id !== null),
        sueltas: fuera.filter(o => o.plantilla_id === null).length,
        yaEnElMesQueViene: fijosEnElMes.length,
        platEnElMesQueViene: fijosEnElMes.reduce((s, o) => s + o.monto, 0),
      }
    }),
    [obligaciones.dato, anioSiguiente, mesSiguiente])

  /**
   * Lo que se ve DESDE ACÁ. `null` = no se pudo mirar, que no es cero. Solo
   * ROTULA el botón: nunca decide si se puede tocar, porque la pregunta que el
   * botón hace no depende de esta lectura.
   */
  const nSinCopiar = vistazo.estado === 'listo' ? vistazo.valor.sinCopiar : null
  const haySerie = vistazo.estado === 'listo' ? vistazo.valor.haySerie : null
  const nSueltas = vistazo.estado === 'listo' ? vistazo.valor.sueltas : null
  const nYaEnElMes = vistazo.estado === 'listo' ? vistazo.valor.yaEnElMesQueViene : null
  const platYaEnElMes = vistazo.estado === 'listo' ? vistazo.valor.platEnElMesQueViene : null
  /**
   * Cero series y cuentas vivas sin marcar Y EL MES QUE VIENE EN BLANCO: recién
   * ahí el mes que viene arranca en cero.
   *
   * LA TERCERA CONDICIÓN ES EL ARREGLO DE ESTA RONDA. Sin ella esto valía `true`
   * con el mes que viene ya cargado a mano —que es lo que pasa TODOS los meses
   * en este negocio— y de ahí salía la frase «arrancaría sin costos fijos y el
   * piso en cero» sobre un mes que tenía sus $27.620.000 adentro.
   *
   * SE LEE DEL `Dato`, NO DE LOS LOCALES DE ARRIBA. `(nSueltas ?? 0) > 0` daba
   * este mismo valor —`haySerie === false` ya implica `listo`, porque el `null`
   * de las otras ramas nunca es `false`— pero el que lo garantizaba era el orden
   * de los operandos y no el compilador. Es el `?? 0` sobre un dato que pudo no
   * volver que prohibe la regla 1 de `ui/README.md`, y el candado que esa regla
   * compra es justamente que no dependa de quien edite acá en seis meses.
   * Adentro de la rama `listo` los números existen de verdad.
   */
  const nadaMarcado = vistazo.estado === 'listo'
    && !vistazo.valor.haySerie && vistazo.valor.sueltas > 0
    && vistazo.valor.yaEnElMesQueViene === 0
  /**
   * Nada marcado PERO el mes que viene ya está cubierto. El estado que antes no
   * existía y que se contaba como el de arriba: no urge —la plata está— pero el
   * dueño los sigue cargando a mano todos los meses y marcar una vez lo corta.
   */
  const nadaMarcadoPeroCubierto = vistazo.estado === 'listo'
    && !vistazo.valor.haySerie && vistazo.valor.sueltas > 0
    && vistazo.valor.yaEnElMesQueViene > 0

  /**
   * LA VISTA PREVIA: qué se va a crear, con sus montos, ANTES de crearlo.
   *
   * Antes esto eran N requests en un `for`, una por obligación. Es idempotente,
   * así que reintentar no duplicaba nada — pero si la tablet perdía señal en la
   * séptima de catorce, el mes quedaba armado A LA MITAD y la proyección del mes
   * siguiente salía con la mitad de los costos, o sea TRANQUILIZADORA.
   *
   * Ahora son dos toques y un solo commit del lado del server: `confirmar:false`
   * no escribe nada y devuelve la lista exacta; `confirmar:true` las crea todas
   * o ninguna. El paso de por medio no es burocracia: los montos se copian del
   * mes pasado, y verlos antes es la única oportunidad de decir «ese arriendo
   * subió» sin tener que ir a corregir catorce filas después.
   */
  const verLaPrevia = async (incluir: number[]) => {
    if (armando) return
    setArmando(true); setError(''); setAviso('')
    try {
      const { data } = await api.post<ArmadoDelMes>('/costos/obligaciones/armar-mes',
        { anio: anioSiguiente, mes: mesSiguiente, confirmar: false, incluir })
      setPrevia(data)
      // Se guarda CON QUÉ se pidió, y el commit manda esta lista y no la que
      // esté tildada en ese momento: si el dueño destilda una después de mirar,
      // lo que se crea tiene que seguir siendo lo que aprobó.
      setPreviaCon(incluir)
    } catch (e) {
      setError(detalleDeError(e, 'No se pudo ver qué cuentas hay que armar.'))
    } finally { setArmando(false) }
  }

  /** Vuelve al botón de arranque y suelta lo tildado. */
  const cancelar = () => { setPrevia(null); setPreviaCon([]); setElegidas(new Set()) }

  /**
   * DESHACER QUE UNA CUENTA SEA SERIE. La vuelta del tilde.
   *
   * Tildar una cuenta en la oferta la marca PARA SIEMPRE, y hasta acá no había
   * cómo salir: el dueño tilda una vez la «Reparación del molino» de $3.000.000
   * y desde ese mes se copia sola, inflando el piso con plata que se pagó una
   * sola vez. Está medido que anular la copia del mes NO alcanza —la del mes
   * anterior sigue marcada y al siguiente vuelve a copiar— y que anular la
   * original tampoco: había que anularlas todas, sabiendo cuáles son.
   *
   * NO BORRA NI ANULA NADA: las cuentas ya creadas siguen ahí con su plata,
   * porque se deben igual. Lo único que cambia es que dejan de copiarse solas.
   *
   * DESPUÉS DE DESMARCAR SE VUELVE A PEDIR LA PREVIA, y no se toca la que está
   * en pantalla: lo que se está mirando dejó de ser lo que el server haría, y
   * editarlo acá sería inventar una lista que nadie calculó. Es la misma regla
   * que sostiene `sinMirar`.
   */
  const noRepetirMas = async (obligacionId: number, concepto: string) => {
    if (armando) return
    setArmando(true); setError(''); setAviso('')
    try {
      await api.post(`/costos/obligaciones/${obligacionId}/no-repetir`)
      onCambio()
    } catch (e) {
      setError(detalleDeError(e, 'No se pudo sacar esa cuenta de las que se repiten.'))
      setArmando(false)
      return
    }
    setArmando(false)
    // La lista de arriba ya no vale: se vuelve a preguntar con la MISMA
    // elección con la que se pidió, para no perderle los tildes al dueño.
    await verLaPrevia(previaCon)
    // EL AVISO VA DESPUÉS DE LA PREVIA, y no antes: `verLaPrevia` limpia el
    // aviso al arrancar (para que un cartel viejo no quede pegado a una lista
    // nueva), así que ponerlo primero lo borraba y el dueño no se enteraba de
    // que su toque hizo algo.
    setAviso(`«${concepto}» ya no se copia sola. Las que ya se crearon siguen `
      + 'cargadas: esto no borra ninguna. Si querés que vuelva a repetirse, '
      + 'tildala de nuevo en la lista de elegir.')
  }

  /** Tilda o destilda una cuenta suelta de la oferta. */
  const marcar = (id: number) => setElegidas(previas => {
    const s = new Set(previas)
    if (s.has(id)) s.delete(id)
    else s.add(id)
    return s
  })

  /**
   * ¿Lo tildado dejó de coincidir con lo que se está mirando?
   *
   * Mientras sea `true` no se puede crear nada: hay que volver a pedir la previa
   * con la elección nueva. Es lo que sostiene la promesa del bloque —se confirma
   * EXACTAMENTE la lista que se miró, con sus montos y sus fechas— cuando la
   * lista dejó de estar fija y ahora la arma el dueño tildando.
   */
  const sinMirar = previa !== null
    && (elegidas.size !== previaCon.length || previaCon.some(x => !elegidas.has(x)))

  /** Confirma la lista que el dueño acaba de ver. Un viaje, un commit. */
  const confirmarElMes = async () => {
    if (armando) return
    setArmando(true); setError(''); setAviso('')
    try {
      const { data } = await api.post<ArmadoDelMes>('/costos/obligaciones/armar-mes',
        { anio: anioSiguiente, mes: mesSiguiente, confirmar: true,
          incluir: previaCon })
      cancelar()
      onCambio()
      // NO se dice «listo» a secas: lo que no se pudo copiar se nombra. Un
      // «listo» sobre catorce con dos afuera deja al dueño creyendo que el mes
      // que viene está armado, y esas dos no están en ninguna proyección.
      setAviso(
        `Se armaron ${data.n_creadas} ${data.n_creadas === 1 ? 'cuenta' : 'cuentas'} `
        + `de ${nombreMes(mesSiguiente)}.`
        // Que ahora sean serie es la mitad del valor de haber elegido, y si no
        // se dice el dueño va a creer que el mes que viene le toca elegir otra vez.
        //
        // Y CÓMO SE DESHACE VA EN LA MISMA FRASE. «Quedan marcadas» sin la
        // vuelta es una puerta de una sola dirección sobre el número más caro de
        // la pantalla: tildar por error la reparación del molino la convierte en
        // un costo fijo mensual y el piso sube todos los meses. El botón está en
        // la lista de «lo que se va a copiar», que es donde se la vuelve a ver.
        + (data.n_elegidas > 0
          ? ` Las ${data.n_elegidas} que elegiste quedan marcadas: el mes que `
            + 'viene se copian solas. Si alguna era de una sola vez, el mes que '
            + 'viene te va a aparecer en la lista de lo que se va a copiar y ahí '
            + 'mismo la sacás con «esta no se repite» — no borra nada de lo ya '
            + 'cargado.'
          : '')
        + (data.no_se_pueden.length > 0
          ? ` ${data.no_se_pueden.length} quedaron afuera: ${
            data.no_se_pueden.map(x => x.concepto).join(', ')}.`
          : ''))
    } catch (e) {
      // Es atómico: si falló, NO se creó ninguna. Decirlo evita que el dueño
      // salga a revisar cuáles entraron.
      setError(detalleDeError(e, 'No se pudo armar el mes. No se creó ninguna: '
        + 'o entran todas o no entra ninguna.'))
    } finally { setArmando(false) }
  }

  const agendarNomina = async () => {
    if (agendando) return
    setAgendando(true); setError(''); setAviso('')
    try {
      const { data } = await api.post<{ ya_existia?: boolean }>(
        '/costos/nomina/agendar', { anio: anioSiguiente, mes: mesSiguiente })
      setAviso(data.ya_existia
        ? `La nómina de ${nombreMes(mesSiguiente)} ya estaba agendada.`
        : `La nómina de ${nombreMes(mesSiguiente)} quedó en lo que hay que pagar.`)
      onCambio()
    } catch (e) {
      setError(detalleDeError(e, 'No se pudo agendar la nómina.'))
    } finally { setAgendando(false) }
  }

  /**
   * Mete la declaración del bimestre en la agenda y en el flujo.
   *
   * Recibe el bimestre que el dueño TIENE EN PANTALLA y no «el último»: puede
   * tener la tablet abierta desde ayer, y dejar que el server lo deduzca podría
   * agendar uno distinto del que vio. Es el mismo criterio del botón de al lado.
   */
  const agendarImpoconsumo = async (i: Impoconsumo) => {
    if (agendandoImpo) return
    setAgendandoImpo(true); setError(''); setAviso('')
    try {
      const { data } = await api.post<{ ya_existia?: boolean }>(
        '/costos/impoconsumo/agendar',
        { anio: i.bimestre.anio, bimestre: i.bimestre.numero })
      setAviso(data.ya_existia
        ? `El impoconsumo de ${i.bimestre.nombre} ya estaba en lo que hay que pagar.`
        : `El impoconsumo de ${i.bimestre.nombre} quedó en lo que hay que pagar: `
          + 'ahora la proyección de caja lo descuenta.')
      onCambio()
    } catch (e) {
      setError(detalleDeError(e, 'No se pudo agendar el impoconsumo.'))
    } finally { setAgendandoImpo(false) }
  }

  const marco = arriba
    ? 'border-clay-200 bg-clay-50'
    : 'border-warm-200 bg-white'

  return (
    <section id={id} className={`rounded-2xl border overflow-hidden ${marco}`}>
      <button onClick={() => setAbierto(v => !v)}
        className="w-full flex items-center gap-2 px-4 py-3 text-left min-h-[46px] hover:bg-black/[0.02]">
        <div className="flex-1 min-w-0">
          <h2 className={`text-sm font-bold ${arriba ? 'text-clay-600' : 'text-warm-700'}`}>
            {arriba
              ? `Arrancó ${nombreMes(mes)}: cosas para dejar listas`
              : 'Una vez al mes'}
          </h2>
          <p className={`text-[11px] leading-snug ${arriba ? 'text-clay-600/80' : 'text-warm-500'}`}>
            De acá salen el piso de hoy y el «¿llego a fin de mes?» de arriba.
          </p>
        </div>
        <span className="shrink-0 text-xs font-bold text-warm-500">{abierto ? '▾' : '▸'}</span>
      </button>

      {abierto && (
        <div className="border-t border-warm-100 bg-white">
          {aviso && (
            <p className="px-4 py-2 text-[11px] font-bold text-success-700 bg-success-50">{aviso}</p>
          )}
          <div className="px-4 py-1"><ErrorCampo msg={error} /></div>

          {/* ── Armar el mes que viene ────────────────────────────────────── */}
          <Item titulo={`Armar los costos de ${nombreMes(mesSiguiente)}`}
            estado={
              <SegunDato dato={vistazo}
                cargando={<span className="text-[11px] text-warm-400">…</span>}
                falla={() => <span className="text-[11px] text-warm-400">—</span>}
                listo={v => (
                  <span className="text-[11px] font-mono text-warm-500">
                    {/* LOS DOS CEROS NO COMPARTEN RÓTULO, Y ES EL ARREGLO
                        ENTERO EN UN RENGLÓN. Sin una sola serie marcada, «al
                        día» sería una afirmación sobre un mes que arranca sin
                        un peso de costos fijos — el cero de «no falta ninguna
                        copia» y el de «no hay ninguna copia posible» son
                        opuestos y acá decían lo mismo. */}
                    {/* Y CON EL MES QUE VIENE YA CARGADO NO DICE NINGUNA DE
                        LAS DOS: «5 sin marcar» sobre un mes cubierto empuja al
                        tilde, que es exactamente el tap que duplicaba el piso.
                        Lo que se publica ahí es la plata que YA está. */}
                    {!v.haySerie
                      ? (v.yaEnElMesQueViene > 0
                        ? `${nombreMes(mesSiguiente)}: ${plata(v.platEnElMesQueViene)}`
                        : v.sueltas > 0 ? `${v.sueltas} sin marcar` : 'sin cuentas')
                      : v.sinCopiar === 0 ? `${nombreMes(mes)}, al día`
                        : `${v.sinCopiar} sin copiar`}
                  </span>
                )} />
            }>
            {/* EL BOTÓN VIVE AFUERA DEL GATE — regla 5 de `ui/README.md`.
                `verLaPrevia()` no mira el vistazo ni una vez: manda anio/mes y
                el que revisa de verdad es el server. Montado adentro de la rama
                `listo` desaparecía justo cuando la lectura de obligaciones no
                volvía —o sea cuando MÁS falta preguntarle al server— y dejaba
                como única salida el Reintentar de OTRA lectura. El aviso va
                arriba; el botón sigue montado y el conteo solo lo ROTULA. */}
            <SegunDato dato={vistazo}
              cargando={null}
              falla={m => (
                <NoSeSabe onReintentar={obligaciones.recargar}
                  mensaje={`${m} — no se sabe cuántas cuentas de la serie faltan copiar. `
                    + 'El botón de acá abajo se lo pregunta al server igual.'} />
              )}
              listo={() => null} />

            {/* ── PASO 1: ver qué se va a crear ─────────────────────────── */}
            {/* EL BOTÓN SIGUE ESTANDO CON CERO, Y NO ES UN DETALLE. Este conteo
                sale de las obligaciones de ESTE mes y el que viene, que es lo
                único que la página trae; una serie a la que se le saltó un mes
                queda fuera de esa ventana. Decir «ya está» y esconder el botón
                sería afirmar sobre lo que no se miró, y del lado tranquilizador.
                El que revisa de verdad es el server, y este botón es la única
                forma de preguntarle. */}
            {previa === null && (<>
              <button onClick={() => verLaPrevia([])} disabled={armando}
                className={nSinCopiar || nadaMarcado ? CLS_BOTON_GUARDAR : CLS_BOTON_SUAVE}>
                {armando ? 'Mirando…'
                  : nSinCopiar === null ? `Ver qué falta de ${nombreMes(mesSiguiente)}`
                    : nadaMarcado ? `Elegir qué va a ${nombreMes(mesSiguiente)}`
                      : nadaMarcadoPeroCubierto
                        ? `Marcar las que se repiten`
                        : nSinCopiar === 0 ? `Ver si falta algo de ${nombreMes(mesSiguiente)}`
                          : `Ver las ${nSinCopiar} de ${nombreMes(mesSiguiente)}`}
              </button>
              <p className="text-[11px] text-warm-400 leading-snug mt-1">
                {/* EL ORDEN DE LAS RAMAS ES EL ARREGLO DE DOS RONDAS SEGUIDAS.
                    `nadaMarcado` va antes que `nSinCopiar === 0` porque sin
                    ninguna serie el conteo TAMBIÉN da cero, y con la rama vieja
                    primero la pantalla escribía «ya tienen su copia» sobre un
                    mes que iba a arrancar en $0. Y ahora `nadaMarcado` exige
                    además que el mes que viene esté VACÍO: sin esa condición
                    escribía «arrancaría sin costos fijos y el piso en cero»
                    sobre un mes que ya tenía sus $27.620.000 cargados a mano —
                    y el tilde que seguía dejaba el piso en $59.659.195,23
                    cuando el mes necesitaba $29.829.597,61.

                    Las dos veces la frase era una afirmación sobre algo que no
                    se había mirado, y las dos veces del lado del miedo. */}
                {nSinCopiar === null
                  ? <>Desde acá no se pudo contar cuántas faltan — el botón se lo pregunta al
                    server igual. Nada se guarda hasta que confirmes.</>
                  : nadaMarcado
                    ? <><b className="text-warm-600">Ninguna de las {nSueltas} cuentas
                      de {nombreMes(mes)} está marcada para repetirse</b>, y{' '}
                      {nombreMes(mesSiguiente)} no tiene todavía un peso de costos fijos:
                      arrancaría con el piso en cero. Acá elegís cuáles se pagan todos los
                      meses; de ahí en más se copian solas.</>
                    : nadaMarcadoPeroCubierto
                      ? <><b className="text-warm-600">{nombreMes(mesSiguiente)} ya tiene{' '}
                        {nYaEnElMes} {nYaEnElMes === 1 ? 'costo fijo' : 'costos fijos'} por{' '}
                        {platYaEnElMes === null ? '—' : plata(platYaEnElMes)}</b>, así que esto
                        no urge y no hace falta tildar nada hoy. Marcar las que se pagan todos
                        los meses es lo que evita volver a cargarlas a mano el mes que viene.
                        Lo que ya esté cargado no se va a duplicar: el server no lo ofrece.</>
                      : nSinCopiar === 0
                        ? <>Las cuentas de {nombreMes(mes)} ya tienen su copia de{' '}
                          {nombreMes(mesSiguiente)}. Si alguna serie se salteó un mes, desde acá no
                          se ve: el botón la busca.</>
                        : <>Primero te muestra qué cuentas va a crear y por cuánta plata. Nada se
                          guarda hasta que confirmes.</>}
              </p>
            </>)}

            {/* ── PASO 2: la lista exacta, y el botón que la crea ───── */}
            {previa !== null && (
              <div className="mt-1.5 rounded-xl border border-clay-200 bg-clay-50/60 p-2.5 space-y-2">
                {/* LO QUE EL MES DESTINO YA TIENE, ARRIBA DE TODO Y ANTES DE
                    CUALQUIER TILDE. Es el número sobre el que esta pantalla
                    venía afirmando sin haberlo pedido, y el que contesta la
                    única pregunta que importa antes de tildar: «¿esto ya está?».
                    `undefined` = backend viejo (ventana del deploy de la PWA):
                    no se dibuja, porque no se puede afirmar. */}
                {previa.mes_destino && (
                  <p className="text-[11px] text-warm-600 leading-snug">
                    {/* SE PUBLICA `fijos` Y NO `total`: la frase habla del piso,
                        y el total incluye lo que el piso NO cuenta (la
                        declaración del impoconsumo, las viejas de proveedores).
                        Con `total` acá, un mes sin un peso de costos fijos se
                        habría leído como cubierto. */}
                    {previa.mes_destino.n_fijos === 0
                      ? <>{nombreMes(mesSiguiente)} <b>todavía no tiene un peso de costos
                        fijos</b> cargado
                        {previa.mes_destino.n > 0
                          ? <> ({previa.mes_destino.n}{' '}
                            {previa.mes_destino.n === 1 ? 'cuenta' : 'cuentas'} de otras
                            categorías, que no entran al piso).</>
                          : <>.</>}</>
                      : <>{nombreMes(mesSiguiente)} <b>ya tiene {previa.mes_destino.n_fijos}{' '}
                        {previa.mes_destino.n_fijos === 1 ? 'costo fijo' : 'costos fijos'} por{' '}
                        {plata(previa.mes_destino.fijos)}</b> cargados.</>}
                  </p>
                )}

                {previa.van_a_crearse.length === 0 ? (
                  <p className="text-[11px] text-warm-600 leading-snug">
                    {/* LA FRASE QUE NO SE PUEDE VOLVER A DECIR. «Ya tienen su
                        copia» solo es cierto cuando HAY series; con
                        `series_repetibles === 0` lo que pasa es que no hay
                        ninguna cuenta marcada para repetirse, que es lo
                        contrario de estar al día. El server manda los dos
                        números justamente para que acá no se deduzca.

                        Y LA OFERTA VACÍA TIENE AHORA DOS CAUSAS OPUESTAS, que
                        es el mismo pecado un nivel más abajo: «no hay costos
                        cargados en ningún lado» y «el mes destino ya las tiene
                        todas». Decirle «cargá los costos de agosto» a alguien
                        que acaba de cargar septiembre entero lo manda a cargar
                        de nuevo lo que ya está. `ya_en_el_mes` las separa. */}
                    {previa.series_repetibles === 0
                      ? <>No hay <b>ninguna cuenta marcada para repetirse</b>, así que no hay
                        nada que copiar solo a {nombreMes(mesSiguiente)}
                        {previa.candidatas.length > 0
                          ? <> — elegí abajo cuáles se pagan todos los meses.</>
                          : (previa.ya_en_el_mes ?? []).length > 0
                            ? <> — y no hace falta: {nombreMes(mesSiguiente)} ya tiene todas
                              las cuentas de {nombreMes(mes)}, cargadas a mano.</>
                            : <>. Cargá los costos de {nombreMes(mes)} y volvé acá.</>}</>
                      : previa.ya_estaban.length > 0
                        ? <>Las {previa.ya_estaban.length} cuentas de la serie ya tienen su
                          copia de {nombreMes(mesSiguiente)}.</>
                        : (previa.ya_en_el_mes ?? []).length > 0
                          ? <>No hay nada para crear: {nombreMes(mesSiguiente)} ya tiene esas
                            cuentas.</>
                          : <>No hay nada para crear en {nombreMes(mesSiguiente)}.</>}
                  </p>
                ) : (<>
                  <p className="text-[11px] font-bold text-warm-700">
                    {previa.van_a_crearse.length}{' '}
                    {previa.van_a_crearse.length === 1 ? 'cuenta' : 'cuentas'} ·{' '}
                    {plata(previa.total)} que se le suman a {nombreMes(mesSiguiente)}
                  </p>
                  <ul className="space-y-0.5">
                    {previa.van_a_crearse.map(v => (
                      <li key={v.serie_id} className="text-[11px]">
                        <div className="flex items-baseline justify-between gap-2">
                          <span className="text-warm-600 truncate">
                            {v.concepto}
                            {v.tienda_nombre && (
                              <span className="text-warm-400"> · {v.tienda_nombre}</span>
                            )}
                          </span>
                          <span className="shrink-0 font-mono text-warm-700">
                            {plata(v.monto)}
                            <span className="text-warm-400"> · {v.fecha_devengo.slice(8)}/{v.fecha_devengo.slice(5, 7)}</span>
                          </span>
                        </div>
                        {/* LA VUELTA DEL TILDE, Y ESTE ES EL MOMENTO EXACTO EN
                            QUE HACE FALTA. Tildar una cuenta la vuelve serie
                            para siempre: el dueño tilda una vez la «Reparación
                            del molino» de $3.000.000 y desde ahí se copia sola
                            todos los meses, inflando el piso con una plata que
                            se pagó una sola vez. Está medido que anular la copia
                            del mes NO alcanza (la del mes anterior sigue
                            marcada) y que anular la original tampoco.

                            Va acá y no en Obligaciones porque acá es donde la
                            está VIENDO: el renglón dice «esto se va a copiar» y
                            al lado está el botón que dice «esta no». */}
                        <button onClick={() => noRepetirMas(v.origen_id, v.concepto)}
                          disabled={armando}
                          className="text-[11px] text-warm-400 underline underline-offset-2
                                     min-h-[32px] disabled:opacity-50">
                          Esta no se repite — sacarla de las que se copian solas
                        </button>
                      </li>
                    ))}
                  </ul>
                  <p className="text-[11px] text-warm-400 leading-snug">
                    Los montos salen del mes anterior. Si alguno cambió, creá el mes igual y
                    corregilo después: la copia queda editable.
                  </p>
                </>)}

                {/* LO QUE EL MES DESTINO YA TIENE Y POR ESO NO VA, CON LAS DOS
                    FILAS. Que el server decida no copiar algo, callado, se lee
                    como «no había nada» — y esa es la familia de error de este
                    módulo entero. Se nombra el concepto y la plata de las dos
                    para que el dueño pueda decir «esa no es la misma».

                    `automatica` NO es un detalle técnico: separa «esta se te
                    habría copiado sola» de «esta ni te la ofrecí», y son dos
                    cosas distintas de saber. */}
                {(previa.ya_en_el_mes ?? []).length > 0 && (
                  <div className="rounded-lg border border-warm-200 bg-white px-2 py-1.5">
                    <p className="text-[11px] font-bold text-warm-700">
                      {(previa.ya_en_el_mes ?? []).length}{' '}
                      {(previa.ya_en_el_mes ?? []).length === 1
                        ? 'cuenta ya está' : 'cuentas ya están'} en {nombreMes(mesSiguiente)}
                    </p>
                    <p className="text-[11px] text-warm-400 leading-snug">
                      No se copian ni se ofrecen: {nombreMes(mesSiguiente)} ya las tiene. Si
                      alguna de estas NO es la misma cuenta, cargala a mano desde Obligaciones.
                    </p>
                    <ul className="mt-1 space-y-0.5">
                      {(previa.ya_en_el_mes ?? []).map(x => (
                        <li key={x.obligacion_id}
                          className="text-[11px] text-warm-600 leading-snug">
                          <b>{x.concepto}</b>
                          {x.tienda_nombre && (
                            <span className="text-warm-400"> · {x.tienda_nombre}</span>
                          )}
                          {x.automatica && (
                            <span className="text-warm-400"> · se copiaba sola</span>
                          )}
                          <span className="block text-warm-400">
                            en {nombreMes(mesSiguiente)} ya está «{x.ya.concepto}» por{' '}
                            <span className="font-mono tabular-nums">{plata(x.ya.monto)}</span>
                            {' '}del {x.ya.fecha_devengo.slice(8)}/{x.ya.fecha_devengo.slice(5, 7)}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {/* LA OFERTA VA SIEMPRE QUE HAYA ALGO QUE OFRECER, y no solo
                    cuando la lista de arriba está vacía: un negocio puede tener
                    tres series sanas y dos costos nuevos cargados a mano este
                    mes, y esos dos no pueden quedar invisibles porque las otras
                    tres estén bien. */}
                {previa.candidatas.length > 0 && (
                  <Elegir candidatas={previa.candidatas}
                    deMes={previa.candidatas_de
                      ? nombreMes(Number(previa.candidatas_de.slice(5, 7)))
                      : nombreMes(mes)}
                    aMes={nombreMes(mesSiguiente)}
                    elegidas={elegidas} onMarcar={marcar} />
                )}

                {/* LO QUE NO SE PUEDE COPIAR SE NOMBRA. Una fila legacy no
                    puede dejar el mes sin armar sin que nadie lo diga. */}
                {previa.no_se_pueden.length > 0 && (
                  <div className="rounded-lg bg-gold-50 border border-gold-200 px-2 py-1.5">
                    <p className="text-[11px] font-bold text-gold-700">
                      {previa.no_se_pueden.length}{' '}
                      {previa.no_se_pueden.length === 1 ? 'no se puede' : 'no se pueden'} copiar
                    </p>
                    {previa.no_se_pueden.map(x => (
                      <p key={x.serie_id} className="text-[11px] text-gold-700/90 leading-snug">
                        <b>{x.concepto}</b>: {x.porque}
                      </p>
                    ))}
                  </div>
                )}

                <div className="flex flex-wrap items-center gap-2">
                  {/* MIENTRAS LO TILDADO NO COINCIDA CON LO MIRADO, NO HAY BOTÓN
                      DE CREAR. Es la misma promesa de siempre —se confirma la
                      lista que se vio, con sus montos y sus fechas— sostenida
                      ahora que la lista la arma el dueño tildando. */}
                  {sinMirar ? (
                    <button onClick={() => verLaPrevia([...elegidas])} disabled={armando}
                      className={CLS_BOTON_GUARDAR}>
                      {armando ? 'Mirando…'
                        : elegidas.size === 0 ? 'Ver qué queda'
                          : `Ver las ${elegidas.size} que elegí`}
                    </button>
                  ) : previa.van_a_crearse.length > 0 ? (
                    <button onClick={confirmarElMes} disabled={armando}
                      className={CLS_BOTON_GUARDAR}>
                      {armando ? 'Armando…' : `Crear las ${previa.van_a_crearse.length}`}
                    </button>
                  ) : null}
                  <button onClick={cancelar} disabled={armando}
                    className={CLS_BOTON_SUAVE}>
                    Cancelar
                  </button>
                </div>
                <p className="text-[11px] text-warm-400 leading-snug">
                  Entran todas o no entra ninguna, y tocarlo dos veces no duplica nada.
                </p>
              </div>
            )}
          </Item>

          {/* ── La declaración del impoconsumo ────────────────────────────── */}
          {/* EL ÚNICO GASTO GRANDE QUE NO SE VEÍA COMO GASTO. 7,41% de cada peso
              facturado es de la DIAN. El sistema ya lo descuenta del margen y
              del piso; lo que faltaba era verlo como plata a pagar en una fecha.

              ACÁ HAY DOS BOTONES Y HACEN COSAS DISTINTAS:
                · «Meterla en lo que hay que pagar» crea la obligación, que es lo
                  que la mete en la agenda y en la proyección de caja. Va a una
                  categoría dedicada que el P&L no mira, así que el piso y el
                  margen no se mueven ni un peso — el porqué, medido, está en
                  `services/costos.py`.
                · «Ya declaré …» APAGA el recordatorio. No paga nada: si la
                  obligación está creada, sigue en la agenda hasta que se pague.

              EL MONTO SE VE ANTES DE CREAR NADA, igual que en «armar el mes»:
              es plata grande y el número es MEDIDO, no declarado. */}
          <Item titulo="La declaración del impoconsumo"
            estado={
              <SegunDato dato={impoconsumo.dato}
                cargando={<span className="text-[11px] text-warm-400">…</span>}
                falla={() => <span className="text-[11px] text-warm-400">—</span>}
                listo={i => {
                  // «AL DÍA» PIDE LOS DOS HECHOS, no solo el trámite. Declarada y
                  // sin agendar, la plata sigue sin estar en ninguna proyección:
                  // pintar verde ahí es el mismo error tranquilizador que el
                  // backend acaba de sacar de `_cobertura_impoconsumo`.
                  const alDia = !i.hay_que_declarar && !!i.agendada
                  return (
                    <span className={`text-[11px] font-bold ${
                      alDia ? 'text-success-700'
                        : i.hay_que_declarar && i.vencido ? 'text-danger-700' : 'text-gold-700'}`}>
                      {alDia ? 'al día'
                        : !i.hay_que_declarar ? 'sin reservar'
                          : i.vencido ? 'atrasada' : 'pendiente'}
                      {i.agendada && <span className="text-warm-400 font-normal"> · agendada</span>}
                    </span>
                  )
                }} />
            }>
            <SegunDato dato={impoconsumo.dato}
              cargando={<p className="text-[11px] text-warm-400">Mirando el bimestre…</p>}
              falla={m => (
                <NoSeSabe onReintentar={impoconsumo.recargar}
                  mensaje={`${m} — no se sabe si hay una declaración pendiente ni de cuánto.`} />
              )}
              listo={i => !i.hay_que_declarar ? (<>
                <p className="text-[11px] text-warm-500">
                  Marcaste como declarado hasta{' '}
                  <b>{i.declarado_hasta?.nombre ?? i.bimestre.nombre}</b>. El bimestre que corre se
                  declara cuando cierre.
                </p>
                {/* MARCARLA NO LA PAGA. Si la obligación existe y sigue con saldo,
                    esa plata sigue saliendo — y el dueño tiene que verlo, o el
                    «al día» de arriba se lee como «no debo nada». */}
                {i.agendada ? (
                  <p className="text-[11px] text-warm-400 leading-snug mt-1">
                    Los <b>{plata(i.agendada.monto)}</b> siguen en lo que hay que pagar hasta que
                    registres el pago: marcarla como declarada apaga este aviso, no la paga.
                  </p>
                ) : (<>
                  {/* DECLARADA PERO SIN RESERVAR: EL AGUJERO, DICHO ACÁ.
                      Declarar es un TRÁMITE ante la DIAN; reservar es plata que
                      sale. Antes el tap de «ya declaré» apagaba de paso el aviso
                      de la caja: la proyección dejaba de avisar por el impoconsumo
                      sin que se moviera un peso de la agenda. Ahora el aviso sigue
                      prendido allá, así que el botón que lo tapa tiene que estar
                      ACÁ — si no, el «Agendarlo» de esa pantalla aterrizaba en un
                      renglón que decía «al día» y no ofrecía nada que hacer. */}
                  <p className="text-[11px] text-gold-700 leading-snug mt-1">
                    Pero <b>esa plata no está en lo que hay que pagar</b>: declararla es el
                    trámite, no la reserva. Mientras no esté acá adentro, el «¿llego a fin de
                    mes?» de arriba se ve mejor de lo que está.
                  </p>
                  <button onClick={() => agendarImpoconsumo(i)}
                    disabled={agendandoImpo}
                    className={`${i.monto_medido === null ? CLS_BOTON_SUAVE : CLS_BOTON_GUARDAR} mt-1.5`}>
                    {agendandoImpo ? 'Agendando…'
                      : i.monto_medido === null
                        ? 'Meterla en lo que hay que pagar'
                        : `Meter los ${plata(i.monto_medido)} en lo que hay que pagar`}
                  </button>
                  <p className="text-[11px] text-warm-400 leading-snug mt-1">
                    {i.monto_medido === null
                      ? <>El sistema no la pudo medir: {i.sin_monto_porque}. Tocá igual: si tenés
                        la cifra de tu contador, te lo va a decir.</>
                      : <>No te sube el piso ni te baja el margen — el impuesto ya está descontado
                        de cada venta, y esta cuenta va en una categoría aparte justamente para no
                        contarlo dos veces.</>}
                  </p>
                </>)}
              </>) : (<>
                <p className="text-[11px] text-warm-600 leading-snug">
                  <b>{i.bimestre.nombre}</b> ya cerró.{' '}
                  {i.monto_medido === null
                    ? <>El sistema no puede decir de cuánto: {i.sin_monto_porque}.</>
                    : <>De lo que facturaste en esos dos meses, <b>{plata(i.monto_medido)}</b> son
                      de la DIAN — no eran plata del negocio en ningún momento.</>}
                </p>
                <p className="text-[11px] text-warm-400 leading-snug mt-1">
                  Se declara en <b>{i.declara_en.nombre}</b>. El día exacto lo fija la DIAN según el
                  último dígito del NIT, así que el sistema no lo inventa
                  {i.vencido && <> — y ese mes ya pasó</>}.{' '}
                  {i.monto_medido !== null && (
                    <>Es lo que el sistema <b>midió cobrado</b>, no la declaración: esa la arma tu
                      contador.</>
                  )}
                </p>

                {/* ── PASO 1: meterla en lo que hay que pagar ───────────── */}
                {/* EL TEXTO YA NO DICE «no la cargues» A SECAS. Antes decía eso y
                    nada más, y para el dueño se leía «no la cargues», punto: la
                    salida más grande del bimestre quedaba fuera de la proyección
                    de caja porque no había dónde ponerla. Ahora hay dónde, y lo
                    que se explica es POR QUÉ el piso no se mueve al hacerlo. */}
                {i.agendada ? (
                  <p className="text-[11px] font-bold text-success-700 leading-snug mt-1.5">
                    Ya está en lo que hay que pagar: {plata(i.agendada.monto)}
                    {i.agendada.fecha_vencimiento && <> · vence el{' '}
                      {i.agendada.fecha_vencimiento.slice(8)}/{i.agendada.fecha_vencimiento.slice(5, 7)}</>}.
                    <span className="font-normal text-warm-400"> La proyección de caja ya lo
                      descuenta.</span>
                  </p>
                ) : (<>
                  {/* EL BOTÓN VIVE AFUERA DE TODO GATE DE MONTO (regla 5): con
                      `monto_medido` en null el server igual puede tener razones
                      para aceptar una cifra escrita a mano, y esconderlo dejaría
                      al dueño sin forma de preguntar. Lo que cambia es el rótulo. */}
                  <button onClick={() => agendarImpoconsumo(i)}
                    disabled={agendandoImpo}
                    className={`${i.monto_medido === null ? CLS_BOTON_SUAVE : CLS_BOTON_GUARDAR} mt-1.5`}>
                    {agendandoImpo ? 'Agendando…'
                      : i.monto_medido === null
                        ? 'Meterla en lo que hay que pagar'
                        : `Meter los ${plata(i.monto_medido)} en lo que hay que pagar`}
                  </button>
                  <p className="text-[11px] text-warm-400 leading-snug mt-1">
                    {i.monto_medido === null
                      ? <>El sistema no la pudo medir, así que no va a poder crearla con un monto
                        propio. Tocá igual: si tenés la cifra de tu contador, te lo va a decir.</>
                      : <>Sin esto, esta plata no está en la agenda ni le baja la proyección de
                        caja: el «¿llego a fin de mes?» de arriba se ve mejor de lo que está.{' '}
                        <b>No te sube el piso ni te baja el margen</b> — el impuesto ya está
                        descontado de cada venta, y esta cuenta va en una categoría aparte
                        justamente para no contarlo dos veces.</>}
                  </p>
                </>)}

                {/* ── PASO 2 (independiente): apagar el recordatorio ────── */}
                <button
                  onClick={async () => {
                    if (declarando) return
                    setDeclarando(true); setError(''); setAviso('')
                    try {
                      await api.post('/costos/impoconsumo/declarado',
                        { anio: i.bimestre.anio, bimestre: i.bimestre.numero })
                      setAviso(`El impoconsumo de ${i.bimestre.nombre} quedó marcado como declarado.`)
                      onCambio()
                    } catch (e) {
                      setError(detalleDeError(e, 'No se pudo marcar como declarado.'))
                    } finally { setDeclarando(false) }
                  }}
                  disabled={declarando} className={`${CLS_BOTON_SUAVE} mt-1.5`}>
                  {declarando ? 'Marcando…' : `Ya declaré ${i.bimestre.nombre}`}
                </button>
                <p className="text-[11px] text-warm-400 leading-snug mt-1">
                  Eso apaga este aviso. No registra el pago: si la agendaste, sigue en lo que hay
                  que pagar hasta que la pagues.
                </p>
              </>)} />
          </Item>

          {/* ── La nómina del mes que viene ───────────────────────────────── */}
          <Item titulo={`La nómina de ${nombreMes(mesSiguiente)}`}
            estado={
              <SegunDato dato={agenda.dato}
                cargando={<span className="text-[11px] text-warm-400">…</span>}
                falla={() => <span className="text-[11px] text-warm-400">—</span>}
                listo={a => {
                  const clave = `${anioSiguiente}-${String(mesSiguiente).padStart(2, '0')}`
                  const hay = a.items.some(i => i.categoria === 'nomina' && i.fecha.startsWith(clave))
                  return (
                    <span className={`text-[11px] font-bold ${hay ? 'text-success-700' : 'text-gold-700'}`}>
                      {hay ? 'agendada' : 'sin agendar'}
                    </span>
                  )
                }} />
            }>
            <button onClick={agendarNomina} disabled={agendando} className={CLS_BOTON_SUAVE}>
              {agendando ? 'Agendando…' : `Agendar la nómina de ${nombreMes(mesSiguiente)}`}
            </button>
            <p className="text-[11px] text-warm-400 leading-snug mt-1">
              Un mes que todavía no ocurrió no tiene horas marcadas, así que el monto sale del{' '}
              <b>contrato</b> de cada persona. Sin esto, la nómina no está en la agenda, no baja la
              proyección y no tiene botón de pagar.
            </p>
          </Item>

          {/* ── La reserva mínima ─────────────────────────────────────────── */}
          <Item titulo="Cuánto no querés que la caja baje nunca"
            estado={
              <SegunDato dato={flujo.dato}
                cargando={<span className="text-[11px] text-warm-400">…</span>}
                falla={() => <span className="text-[11px] text-warm-400">—</span>}
                listo={f => (
                  <span className={`text-[11px] font-mono ${
                    f.reserva_es_default ? 'text-gold-700 font-bold' : 'text-warm-500'}`}>
                    {plata(f.reserva_minima_caja)}{f.reserva_es_default && ' (sin decidir)'}
                  </span>
                )} />
            }>
            {/* EL AVISO ARRIBA, EL CAMPO SIEMPRE MONTADO (regla 5).
                La reserva es un número que el dueño tiene decidido en la cabeza:
                no depende de este fetch. Meter el campo adentro de la rama
                `listo` lo hacía desaparecer justo cuando la proyección no
                volvía — que es cuando más falta hace poder declararla. */}
            <SegunDato dato={flujo.dato}
              cargando={null}
              falla={() => (
                <NoSeSabe onReintentar={flujo.recargar}
                  mensaje="No se pudo leer la reserva que ya estaba cargada, así que el campo abre
                    en blanco. Lo que escribas se guarda igual." />
              )}
              listo={() => null} />
            <CampoPlata etiqueta="Reserva mínima de caja"
              /* `key` remonta el campo cuando llega el valor leído: `CampoPlata`
                 guarda su propio estado y sin esto el default nunca entraría. Y
                 remonta solo cuando el número CAMBIA, así que no le pisa lo que
                 el dueño esté tecleando. */
              key={reservaCargada}
              valor={reservaCargada}
              ayuda={<>Es lo que convierte «cuánto puedo gastar» en una decisión de negocio en
                vez de «cuánto puedo gastar hasta quedar en cero». El colchón del bloque de
                arriba se mide contra este número.</>}
              onGuardar={async v => {
                await api.post('/costos/reserva-minima', { reserva: Number(v) })
                onCambio()
              }} />
          </Item>

          {/* ── La comisión del datáfono ──────────────────────────────────── */}
          <Item titulo="Cuánto cobra el datáfono por cada venta con tarjeta"
            estado={
              <SegunDato dato={piso.dato}
                cargando={<span className="text-[11px] text-warm-400">…</span>}
                falla={() => <span className="text-[11px] text-warm-400">—</span>}
                listo={p => p.razones === null ? (
                  <span className="text-[11px] text-warm-400">—</span>
                ) : (
                  <span className={`text-[11px] font-mono ${
                    p.razones.tasa_comision > 0 ? 'text-warm-500' : 'text-gold-700 font-bold'}`}>
                    {p.razones.tasa_comision > 0
                      ? `${(p.razones.tasa_comision * 100).toLocaleString('es-CO')}%`
                      : 'sin cargar'}
                  </span>
                )} />
            }>
            <CampoPlata etiqueta="Comisión del datáfono en porcentaje" valor="" sufijo="%"
              ayuda={<>Se escribe en porcentaje, como viene en el contrato del adquirente: <b>2.5</b>{' '}
                para 2,5%. Sin este número el piso de venta sale corto — la comisión se paga de
                cada venta y hoy no la descuenta nadie.</>}
              onGuardar={async v => {
                await api.post('/costos/comision-datafono', { porcentaje: Number(v.replace(',', '.')) })
                onCambio()
              }} />
          </Item>

          {/* ── Las categorías ────────────────────────────────────────────── */}
          <Item titulo="Mis categorías de costo"
            estado={
              <SegunDato dato={categorias.dato}
                cargando={<span className="text-[11px] text-warm-400">…</span>}
                falla={() => <span className="text-[11px] text-warm-400">—</span>}
                listo={cs => <span className="text-[11px] font-mono text-warm-500">{cs.length}</span>} />
            }>
            <MisCategorias categorias={categorias} onCambio={onCambio} />
          </Item>

          {/* ── El link al detalle ────────────────────────────────────────── */}
          <div className="px-4 py-3 border-t border-warm-100">
            <button onClick={onVerElMesEnDetalle}
              className="flex items-center gap-1 min-h-[46px] text-xs font-bold text-forest hover:underline">
              El mes en detalle: margen por producto, sede contra sede, la escalera del resultado
              <ChevronRight size={14} />
            </button>
            <p className="text-[11px] text-warm-400 leading-snug">
              Todo eso es para <b>interpretar</b>, no para decidir hoy. Por eso está acá y no
              arriba: el piso de arriba es el mismo hecho, ya convertido en una decisión.
            </p>
          </div>
        </div>
      )}
    </section>
  )
}

/**
 * El catálogo que el dueño decide.
 *
 * `grupo` es lo único que importa río abajo: el grupo `fijo` es el que arma el
 * numerador del piso. Por eso el alta lo pide explícitamente en vez de elegirlo
 * por él — una categoría nueva en el grupo equivocado le cambia el piso a todo
 * el negocio sin que nadie lo haya pedido.
 */
function MisCategorias({ categorias, onCambio }: {
  categorias: Fuente<Categoria[]>; onCambio: () => void
}) {
  const [abierto, setAbierto] = useState(false)
  const [nombre, setNombre] = useState('')
  const [grupo, setGrupo] = useState<'fijo' | 'variable'>('fijo')
  const [error, setError] = useState('')
  const [guardando, setGuardando] = useState(false)

  const guardar = async () => {
    if (guardando || !nombre.trim()) return
    setGuardando(true); setError('')
    try {
      await api.post('/costos/categorias', { nombre: nombre.trim(), grupo })
      setNombre('')
      onCambio()
    } catch (e) {
      setError(detalleDeError(e, 'No se pudo crear la categoría.'))
    } finally { setGuardando(false) }
  }

  return (<>
    <button onClick={() => setAbierto(v => !v)}
      className="text-[11px] font-bold text-forest underline decoration-dotted min-h-[44px]">
      {abierto ? 'cerrar' : 'ver y agregar categorías'}
    </button>

    {abierto && (
      <div className="mt-1.5 space-y-2" onKeyDown={teclas({ listo: !!nombre.trim(), guardar })}>
        <SegunDato
          dato={categorias.dato}
          cargando={<p className="text-[11px] text-warm-400">Leyendo el catálogo…</p>}
          falla={m => (
            <NoSeSabe onReintentar={categorias.recargar}
              mensaje={`${m} — no se pudo leer qué categorías hay. Podés crear una igual: el `
                + 'campo de abajo no depende de esta lectura.'} />
          )}
          listo={cs => cs.length === 0 ? (
            <p className="text-[11px] text-warm-500">Todavía no hay ninguna categoría cargada.</p>
          ) : (
            <div className="flex flex-wrap gap-1">
              {cs.map(c => (
                <span key={c.id}
                  className={`text-[10px] font-bold px-2 py-1 rounded-lg border ${
                    c.grupo === 'fijo'
                      ? 'bg-gold-50 text-gold-700 border-gold-200'
                      : 'bg-warm-50 text-warm-600 border-warm-200'}`}>
                  {c.nombre}
                </span>
              ))}
            </div>
          )} />

        <p className="text-[11px] text-warm-400 leading-snug">
          Las <b>fijas</b> (en dorado) son las que arman el piso: se pagan venda lo que venda. Las
          variables suben con la venta y no entran al numerador.
        </p>

        {/* El formulario NO se esconde cuando el catálogo no volvió (regla 5). */}
        <div className="flex flex-wrap items-center gap-2">
          <input type="text" value={nombre} onChange={e => setNombre(e.target.value)}
            placeholder="Nombre de la categoría" aria-label="Nombre de la categoría"
            className={`${CLS_INPUT} max-w-[220px]`} />
          <select value={grupo} onChange={e => setGrupo(e.target.value as 'fijo' | 'variable')}
            aria-label="Grupo" className={`${CLS_INPUT} max-w-[140px]`}>
            <option value="fijo">Fija (sube el piso)</option>
            <option value="variable">Variable</option>
          </select>
          <button onClick={guardar} disabled={guardando || !nombre.trim()} className={CLS_BOTON_GUARDAR}>
            {guardando ? 'Creando…' : 'Crear'}
          </button>
        </div>
        <ErrorCampo msg={error} />
      </div>
    )}
  </>)
}
