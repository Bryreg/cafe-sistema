import { ReactNode, useMemo, useRef, useState } from 'react'
import { AlertCircle, CalendarClock, ChevronLeft, ChevronRight, Plus, Trash2 } from 'lucide-react'
import api from '../../api/client'
import { Dato, mapDato } from '../../api/dato'
import type { Fuente } from '../../api/useDato'
import { SegunDato, NoSeSabe } from '../ui'
import {
  CuentaBanco, DiaLibro, LibroMes, MovimientoBanco, SerieAnual,
  MESES, MESES_CORTOS, compacto, detalleDeError, diaSemana, esFinde, fechaCorta, fechaLarga, plata,
} from './banco'
import { Agenda, AgendaItem } from './tipos'
import { Banner, ComoSeCalcula, ErrorCampo } from './campos'
import FormMovimiento from './FormMovimiento'
import FilaVencimiento from './FilaVencimiento'

/**
 * ═════════════════════════════════════════════════════════════════════════════
 * EL LIBRO DEL BANCO — plata que YA se movió
 * ═════════════════════════════════════════════════════════════════════════════
 * Una fila por día: arranca + entra − sale = queda. Es la fórmula de la hoja del
 * dueño, y la pantalla existe para que se pueda verificar a ojo.
 *
 * NO se mezcla con la proyección a propósito. El banner de arriba estima lo que
 * va a pasar; esto es lo que pasó. Cuando el saldo proyectado se pintaba encima
 * de esta grilla, dos números que no significan lo mismo se leían igual.
 *
 * ── LO QUE LA PANTALLA NO PUEDE CONTRADECIR (services/banco.py) ────────────
 *  · LA CADENA SE DECIDE POR DÍA. Cada fila trae su `cadena`: los días
 *    anteriores al ancla vienen con `inicial`/`final` en null y son los únicos
 *    que se pintan «—». Del ancla en adelante el saldo es EXACTO.
 *  · `cadena_completa` es false casi siempre (el ancla cae a mitad de mes) y NO
 *    sirve para decidir si se pintan saldos.
 *  · El ancla es un saldo de APERTURA: «con cuánta plata arranco ese día».
 *  · Los días sin movimiento también van: son los que dejan ver que el saldo se
 *    quedó abajo cuatro días seguidos.
 *  · `en_rojo` lo calcula el backend y ya viene en false cuando la fila no tiene
 *    cadena: un saldo que no se conoce no puede estar en negativo.
 *
 * ── LA AGENDA ES OTRO FETCH, Y SE NOTA POR DÍA ─────────────────────────────
 * La línea «Vence $X» de cada fila sale de la agenda, no del libro. Con la
 * agenda caída no aparecía en ninguna fila — y eso se lee exactamente igual que
 * un mes sin un solo vencimiento. Por eso ahora, cuando la agenda no volvió, hay
 * un renglón que lo dice arriba de la grilla: las filas de abajo hablan solo de
 * plata movida.
 */
export default function BannerLibro({
  libro, serie, anio, mes, hoy, viendoElMesDeHoy,
  cuentas, agenda, onIrAlMes, onIrAHoy, onVerMes, onCambiarAnio,
  onGuardado, onBorrado, onIrAlAncla, onPagar, itemPagando, renderPago, onRecargarLibro,
}: {
  libro: Dato<LibroMes>
  serie: Dato<SerieAnual>
  anio: number
  mes: number
  hoy: string
  viendoElMesDeHoy: boolean
  cuentas: Fuente<CuentaBanco[]>
  /** Los vencimientos NO están en el libro: son compromisos, no plata movida. */
  agenda: Fuente<Agenda>
  onIrAlMes: (delta: number) => void
  onIrAHoy: () => void
  onVerMes: (m: number) => void
  onCambiarAnio: (delta: number) => void
  onGuardado: (m: MovimientoBanco) => void
  onBorrado: () => void
  /** Sube hasta el editor del extracto (el único que queda). */
  onIrAlAncla: () => void
  /** Repide el libro y la serie sin desmontar lo que se esté tecleando. */
  onRecargarLibro: () => void
  onPagar: (i: AgendaItem) => void
  /** `tipo-id` del vencimiento con el pago abierto, para teñir su fila. */
  itemPagando: string | null
  /**
   * El formulario de pago, montado JUSTO DEBAJO de la fila que lo pidió.
   *
   * Llega como render-prop y no se construye acá porque el estado de «a quién le
   * estoy pagando» es de la PÁGINA: el mismo vencimiento puede tocarse desde el
   * banner de vencidos o desde su día en el libro, y tener dos formularios
   * abiertos con el mismo saldo sería la forma más fácil de pagar dos veces.
   */
  renderPago: (i: AgendaItem) => ReactNode
}) {
  const [diaAbierto, setDiaAbierto] = useState<string | null>(hoy)
  const [borrandoId, setBorrandoId] = useState<number | null>(null)
  const [error, setError] = useState('')
  // Con qué fecha arranca la fila de carga. Tocar «cargar con esta fecha» dentro
  // de un día la cambia: es la segunda puerta al MISMO formulario, no otro.
  const [fechaCarga, setFechaCarga] = useState(hoy)
  const refForm = useRef<HTMLDivElement>(null)

  /**
   * La agenda indexada por día, para fusionarla adentro del libro.
   *
   * LO VENCIDO NO ENTRA ACÁ: ya tiene su banner rojo arriba. Indexándolo también
   * por día, un vencimiento atrasado cuya fecha cae en el mes que se está mirando
   * aparecía en las DOS listas, y con el día desplegado tocar «Pagar» abría el
   * formulario arriba y abajo: dos «Confirmar pago» vivos con el saldo entero
   * precargado. La primera respuesta desmonta los dos, así que hace falta tocar
   * dos veces antes de que vuelva — en tablet con conexión lenta es un camino
   * real, y toca plata. Es la misma decisión que ya tomó el banner rojo: lo
   * atrasado se paga en un solo lugar.
   */
  const vencePorDia = useMemo(() => mapDato(agenda.dato, a => {
    const m = new Map<string, AgendaItem[]>()
    for (const i of a.items) {
      if (i.vencida) continue
      const arr = m.get(i.fecha)
      if (arr) arr.push(i); else m.set(i.fecha, [i])
    }
    return m
  }), [agenda.dato])

  const sabeVencimientos = vencePorDia.estado === 'listo'
  const delDia = (fecha: string): AgendaItem[] =>
    vencePorDia.estado === 'listo' ? (vencePorDia.valor.get(fecha) ?? []) : []

  /**
   * La segunda puerta tiene que LLEVAR a la fila de carga, no solo prepararla.
   *
   * La fila vive arriba del banner y el día que se tocó está treinta filas más
   * abajo: cambiarle la fecha sin subir el foco dejaría al dueño esperando un
   * formulario que sí se abrió, pero fuera de la pantalla — el mismo síntoma que
   * tenía el modal («no pasó nada») con otra causa.
   */
  const cargarConFecha = (fecha: string) => {
    setFechaCarga(fecha)
    refForm.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }

  const borrar = async (id: number) => {
    setError('')
    try {
      await api.delete(`/banco/movimientos/${id}`)
      setBorrandoId(null)
      // Avisa hacia afuera: borrar un movimiento mueve el saldo y con él el
      // punto de quiebre. Sin esto, la proyección de arriba sigue con la plata
      // vieja y quedan dos números para la misma pregunta.
      onBorrado()
    } catch (e) {
      setBorrandoId(null)
      setError(detalleDeError(e, 'No se pudo borrar el movimiento.'))
    }
  }

  return (
    <Banner
      titulo="El libro del banco — lo que ya se movió"
      sub={<>{MESES[mes - 1]} {anio} · cada fila es un día: arranca + entra − sale = queda</>}
      accion={
        <div className="flex items-center gap-0.5">
          <button onClick={() => onIrAlMes(-1)} aria-label="Mes anterior"
            className="p-2 rounded-xl text-warm-500 hover:bg-warm-100"><ChevronLeft size={17} /></button>
          {!viendoElMesDeHoy && (
            <button onClick={() => { onIrAHoy(); setDiaAbierto(hoy); setFechaCarga(hoy) }}
              className="text-[11px] font-bold text-forest px-2 min-h-[38px]">Volver a hoy</button>
          )}
          <button onClick={() => onIrAlMes(1)} aria-label="Mes siguiente"
            className="p-2 rounded-xl text-warm-500 hover:bg-warm-100"><ChevronRight size={17} /></button>
        </div>
      }
    >
      {/* ── La carga, SIEMPRE montada ─────────────────────────────────────── */}
      <div ref={refForm}>
        {/* La agenda baja también al formulario: ahí es de dónde salen las
            obligaciones que una salida puede tachar. Es LA MISMA fuente que
            alimenta las líneas «Vence» de la grilla —una sola lectura, y
            `onGuardado` la repide— así que enlazar una obligación la saca de las
            opciones en la carga siguiente, que es la señal de que el enlace pegó. */}
        <FormMovimiento key={fechaCarga} fechaInicial={fechaCarga} cuentas={cuentas}
          agenda={agenda} maxFecha={hoy}
          onGuardado={m => { setDiaAbierto(m.fecha); onGuardado(m) }} />
      </div>

      {/* La agenda no volvió: las filas de abajo van a mostrar plata movida y
          NADA de lo que vence. Sin este renglón, treinta días sin una sola línea
          «Vence» se leen como un mes sin un solo pago programado. */}
      <SegunDato
        dato={agenda.dato}
        cargando={null}
        falla={m => (
          <div className="px-3 py-2 border-b border-warm-100">
            <NoSeSabe onReintentar={agenda.recargar}
              mensaje={`${m} — las filas de abajo muestran solo la plata que ya se movió: no se `
                + 'sabe qué vence cada día.'} />
          </div>
        )}
        listo={() => null}
      />

      {error && <div className="px-3 py-2"><ErrorCampo msg={error} /></div>}

      <SegunDato
        dato={libro}
        cargando={<p className="px-4 py-8 text-center text-sm text-warm-400 animate-pulse">Cargando…</p>}
        falla={m => (
          <div className="px-4 py-4">
            <NoSeSabe bloque onReintentar={onRecargarLibro}
              mensaje={`${m} — no se sabe qué se movió este mes ni con cuánto quedó cada día. `
                + 'Que no haya filas acá abajo no quiere decir que no se haya movido plata.'} />
          </div>
        )}
        listo={l => {
          // Las dos columnas de saldo existen si hay AL MENOS UN día que mostrar.
          // Con cero se apagan porque no habría nada que poner ahí, no porque el
          // mes esté «incompleto»: un mes a medias muestra sus días buenos y
          // pinta «—» en los otros, que es la verdad parcial.
          const hayColumnasDeSaldo = l.dias_con_saldo > 0
          const aviso = avisoDeCadena(l)
          return (<>
            {/* La verdad PARCIAL: desde cuándo hay saldo. Solo cuando no hay
                ningún día con saldo esto dice «este mes no tiene saldos». */}
            {aviso && (
              <button onClick={onIrAlAncla}
                className="w-full flex items-start gap-2 px-4 py-2.5 border-b border-gold-200 bg-gold-50 text-left">
                <AlertCircle size={15} className="text-gold-700 mt-0.5 shrink-0" />
                <span className="min-w-0 flex-1">
                  <span className="block text-xs font-bold text-gold-700">{aviso.titulo}</span>
                  <span className="block text-[11px] text-gold-700/90 leading-relaxed mt-0.5">
                    {aviso.texto}
                  </span>
                </span>
              </button>
            )}

            {/* Encabezado de columnas: es la fórmula, y se deja leer a ojo. */}
            <div className={`grid gap-1 px-2 py-1.5 bg-warm-50 border-b border-warm-100 text-[9px] font-bold uppercase tracking-wide text-warm-500 ${
              hayColumnasDeSaldo ? 'grid-cols-[2.9rem_1fr_1fr_1fr_1fr]' : 'grid-cols-[2.9rem_1fr_1fr]'}`}>
              <span>Día</span>
              {hayColumnasDeSaldo && <span className="text-right">Arranca</span>}
              <span className="text-right">Entra</span>
              <span className="text-right">Sale</span>
              {hayColumnasDeSaldo && <span className="text-right">Queda</span>}
            </div>

            {l.dias.map(d => (
              <FilaDia key={d.fecha} dia={d} hoy={hoy} columnasDeSaldo={hayColumnasDeSaldo}
                abierto={diaAbierto === d.fecha}
                vencimientos={delDia(d.fecha)} sabeVencimientos={sabeVencimientos}
                itemPagando={itemPagando} renderPago={renderPago}
                onAbrir={() => setDiaAbierto(x => (x === d.fecha ? null : d.fecha))}
                onPagar={onPagar}
                onCargarAcá={() => cargarConFecha(d.fecha)}
                borrandoId={borrandoId}
                onPedirBorrar={setBorrandoId}
                onBorrar={borrar} />
            ))}

            {/* Pie del mes: los números que el dueño busca cuando ya vio las filas. */}
            <div className="px-4 py-3 border-t border-warm-200 bg-warm-50 space-y-1">
              <div className="flex items-center justify-between gap-2 text-xs">
                <span className="text-warm-500">Entró en el mes</span>
                <span className="font-mono font-bold tabular-nums text-success-600">+ {plata(l.totales.entradas)}</span>
              </div>
              <div className="flex items-center justify-between gap-2 text-xs">
                <span className="text-warm-500">Salió en el mes</span>
                <span className="font-mono font-bold tabular-nums text-danger-600">− {plata(l.totales.salidas)}</span>
              </div>
              {/* `totales.final` viene en null cuando el ÚLTIMO día del mes no tiene
                  saldo: ahí no hay con cuánto termina y no se escribe la línea. No es
                  lo mismo que terminar en cero. */}
              {l.totales.final != null && (
                <div className="flex items-center justify-between gap-2 text-xs pt-1 border-t border-warm-200">
                  <span className="font-bold text-warm-600">Con lo cargado, el mes termina en</span>
                  <span className={`font-mono font-bold tabular-nums ${
                    l.totales.final < 0 ? 'text-danger-700' : 'text-warm-700'}`}>
                    {plata(l.totales.final)}
                  </span>
                </div>
              )}
              {/* El conteo de rojos se calcula SOLO sobre los días con saldo, así que
                  la frase se ACOTA cuando el mes no está entero: decir «ningún día
                  cerró en rojo» de un mes al que le faltan quince días sin saldo
                  sería afirmar de más justo en el renglón que tranquiliza. */}
              {l.dias_con_saldo > 0 && (
                <p className={`text-[11px] leading-relaxed pt-0.5 ${
                  l.totales.dias_en_rojo > 0 ? 'text-danger-700 font-semibold' : 'text-warm-500'}`}>
                  {l.totales.dias_en_rojo > 0
                    ? `${l.totales.dias_en_rojo} ${l.totales.dias_en_rojo === 1 ? 'día cerró' : 'días cerraron'} en rojo.`
                    : l.cadena_completa
                      ? 'Ningún día cerró en rojo.'
                      : 'Ninguno de los días con saldo cerró en rojo.'}
                  {l.totales.fecha_dia_mas_bajo && l.totales.dia_mas_bajo != null && (
                    <> El más bajo fue el <b>{fechaCorta(l.totales.fecha_dia_mas_bajo)}</b>,
                      {' '}con {plata(l.totales.dia_mas_bajo)}.</>
                  )}
                </p>
              )}
            </div>
          </>)
        }}
      />

      {/* ── LOS DOCE MESES ──────────────────────────────────────────────────
          El mismo libro, resumido. Va plegado porque la pregunta de todos los
          días es la del mes de arriba. El desplegable EXISTE siempre: que se
          evaporara cuando la serie no volvía dejaba al dueño sin saber que ese
          resumen existe. */}
      <ComoSeCalcula titulo={`Ver el año ${anio} entero`}>
        <div className="flex items-center gap-1 -mt-1">
          <button onClick={() => onCambiarAnio(-1)} aria-label="Año anterior"
            className="p-2 rounded-xl text-warm-500 hover:bg-warm-100"><ChevronLeft size={15} /></button>
          <p className="flex-1 text-center text-xs font-bold text-warm-700">
            Cuánto entró, cuánto salió y con cuánto cerró cada mes de {anio}
          </p>
          <button onClick={() => onCambiarAnio(1)} aria-label="Año siguiente"
            className="p-2 rounded-xl text-warm-500 hover:bg-warm-100"><ChevronRight size={15} /></button>
        </div>

        <SegunDato
          dato={serie}
          cargando={<p className="text-warm-400 animate-pulse">Cargando el año…</p>}
          falla={m => (
            <NoSeSabe onReintentar={onRecargarLibro}
              mensaje={`${m} — no se sabe cuánto entró ni cuánto salió en los otros meses.`} />
          )}
          listo={s => {
            // Cuántos meses del año no tienen cierre. Se cuenta para no escribir
            // la explicación del «—» cuando no hay ningún «—» que explicar.
            const mesesSinCierre = s.meses.filter(m => m.cierre == null).length
            return (<>
              <div className="rounded-xl border border-warm-200 overflow-hidden bg-white">
                <div className="grid grid-cols-[2.6rem_1fr_1fr_1fr] gap-1 px-3 py-1.5 bg-warm-50 border-b border-warm-100 text-[9px] font-bold uppercase tracking-wide text-warm-500">
                  <span>Mes</span>
                  <span className="text-right">Entra</span>
                  <span className="text-right">Sale</span>
                  <span className="text-right">Cierra</span>
                </div>
                {s.meses.map(m => {
                  // Condicionado por MONTO, no por la forma del dato: un mes sin
                  // plata movida se apaga; uno con plata se lee aunque el cierre
                  // no exista.
                  const conMovimiento = m.entradas > 0 || m.salidas > 0
                  return (
                    <button key={m.mes} onClick={() => onVerMes(m.mes)}
                      className={`w-full grid grid-cols-[2.6rem_1fr_1fr_1fr] gap-1 items-center px-3 py-2 border-b border-warm-100 last:border-0 text-right transition-colors ${
                        m.mes === mes ? 'bg-forest-50' : 'hover:bg-warm-50'
                      } ${conMovimiento ? '' : 'opacity-45'}`}>
                      <span className="text-left text-[11px] font-bold text-warm-600 capitalize">{MESES_CORTOS[m.mes - 1]}</span>
                      <span className="text-[11px] font-mono tabular-nums text-success-600">
                        {m.entradas > 0 ? compacto(m.entradas) : '—'}
                      </span>
                      <span className="text-[11px] font-mono tabular-nums text-danger-600">
                        {m.salidas > 0 ? compacto(m.salidas) : '—'}
                      </span>
                      <span className={`text-[11px] font-mono font-bold tabular-nums ${
                        m.cierre == null ? 'text-warm-300' : m.cierre < 0 ? 'text-danger-700' : 'text-warm-700'}`}>
                        {m.cierre == null ? '—' : compacto(m.cierre)}
                      </span>
                    </button>
                  )
                })}
              </div>

              <p>
                Tocá un mes para abrirlo arriba.
                {/* La explicación del «—» solo se escribe si hay alguno, y dice el
                    motivo REAL de este año.

                    EL CRITERIO ES QUE EL MES TERMINA ANTES, NO QUE ARRANCA ANTES:
                    `serie_mensual` pide el saldo al cierre con el ÚLTIMO día del
                    mes, así que el cierre falta solo cuando ese último día queda
                    antes del ancla. El mes que CONTIENE al ancla también arranca
                    antes y sí trae cierre.

                    Y EL MOTIVO SE ESCRIBE SOLO CON EL LIBRO EN LA MANO: la fecha
                    del extracto sale de él. Sin libro se dice qué falta, no una
                    causa que nadie leyó. */}
                {mesesSinCierre > 0 && (<>
                  {' '}{mesesSinCierre === 1
                    ? <>El mes con <b>cierre en «—»</b> es uno al que la cadena no llega</>
                    : <>Los meses con <b>cierre en «—»</b> son los que la cadena no alcanza</>}
                  {libro.estado !== 'listo'
                    ? '. No se pudo leer el libro de este mes, así que acá no se puede decir desde qué fecha corre la cadena.'
                    : libro.valor.ancla.fecha
                      ? `: el cierre se mide el último día del mes, y ${mesesSinCierre === 1
                          ? 'ese mes termina' : 'esos meses terminan'} antes del `
                        + `${fechaCorta(libro.valor.ancla.fecha)}, que es la fecha del saldo del extracto.`
                      : ': todavía no cargaste ningún saldo del extracto.'}
                  {mesesSinCierre === 1
                    ? ' No cerró en cero: no se sabe con cuánto cerró.'
                    : ' No cerraron en cero: no se sabe con cuánto cerraron.'}
                </>)}
              </p>
            </>)
          }}
        />
      </ComoSeCalcula>
    </Banner>
  )
}

/**
 * Qué le falta a la cadena EN ESTE MES, dicho con los datos del backend.
 * Tres estados, y ninguno se infiere de la forma del rango.
 *
 * Recibe el libro YA resuelto: acá no hay ninguna decisión sobre datos ausentes.
 */
function avisoDeCadena(libro: LibroMes): { titulo: string; texto: string } | null {
  if (libro.cadena_completa) return null
  const anclaFecha = libro.ancla.fecha
  const desde = libro.primer_dia_con_saldo
  if (desde) {
    // Que el primer día con saldo SEA el del extracto se COMPARA, no se deduce
    // del caso: es el motivo que se le está por afirmar al dueño.
    const arrancaEnElExtracto = anclaFecha != null && anclaFecha === desde
    return {
      titulo: `Los saldos arrancan el ${fechaCorta(desde)}`,
      texto: 'Antes de esa fecha no se sabe cuánta plata había, así que esos días van con «—» '
        + 'en «arranca» y «queda»; lo que entró y lo que salió sí es real. Del '
        + `${fechaCorta(desde)} en adelante el saldo es exacto.`
        + (arrancaEnElExtracto
          ? ' Arranca ahí porque esa es la fecha del saldo del extracto: si tenés uno más '
            + 'viejo, tocá acá y cambiale la fecha.'
          : ''),
    }
  }
  return {
    titulo: 'Este mes no tiene saldos',
    texto: anclaFecha
      ? `El saldo del extracto es del ${fechaCorta(anclaFecha)} y este mes termina el `
        + `${fechaCorta(libro.hasta)}: la cadena arranca en esa fecha y no corre para atrás. `
        + 'Lo que entró y lo que salió sí es real; con cuánto arrancaste y con cuánto quedaste, '
        + 'no. Si tenés el extracto de esos días, tocá acá y cambiale la fecha.'
      : 'Nunca cargaste el saldo del extracto, así que la cadena no tiene de dónde arrancar. '
        + 'Lo que entró y lo que salió sí es real; con cuánto arrancaste y con cuánto quedaste, '
        + 'no. Cargá el saldo del extracto y aparecen.',
  }
}

/**
 * Una fila del libro = un día, y se despliega.
 *
 * INVARIANTE: ninguna fila es inerte. Un día sin movimientos y sin vencimientos
 * abre igual, porque tiene algo que decir (con cuánto arrancó, con cuánto quedó
 * y que no se movió nada) y una acción que ofrecer (cargar el movimiento que
 * falta, con esa fecha).
 *
 * `columnasDeSaldo` decide si la GRILLA tiene las dos columnas de saldo (es del
 * mes: o están para todas las filas o el ancho se descuadra). Lo que va DENTRO
 * de esas columnas lo decide `dia.cadena`, que es de esta fila.
 *
 * `sabeVencimientos` es lo que separa «este día no vence nada» de «no se pudo
 * leer la agenda». Sin él, una lista vacía contestaba las dos preguntas igual.
 */
function FilaDia({
  dia, hoy, columnasDeSaldo, abierto, vencimientos, sabeVencimientos, itemPagando, renderPago,
  onAbrir, onPagar, onCargarAcá, borrandoId, onPedirBorrar, onBorrar,
}: {
  dia: DiaLibro
  hoy: string
  columnasDeSaldo: boolean
  abierto: boolean
  vencimientos: AgendaItem[]
  sabeVencimientos: boolean
  itemPagando: string | null
  renderPago: (i: AgendaItem) => ReactNode
  onAbrir: () => void
  onPagar: (i: AgendaItem) => void
  onCargarAcá: () => void
  borrandoId: number | null
  onPedirBorrar: (id: number | null) => void
  onBorrar: (id: number) => void
}) {
  const esHoy = dia.fecha === hoy
  const rojo = dia.en_rojo
  const totalVence = vencimientos.reduce((s, i) => s + i.monto, 0)
  const numero = Number(dia.fecha.slice(8, 10))

  return (
    <div className={rojo ? 'bg-danger-50/70' : esFinde(dia.fecha) ? 'bg-warm-50/60' : ''}>
      <button onClick={onAbrir} aria-expanded={abierto}
        aria-label={`${fechaLarga(dia.fecha)}${
          dia.total_entradas > 0 ? `, entró ${plata(dia.total_entradas)}` : ''}${
          dia.total_salidas > 0 ? `, salió ${plata(dia.total_salidas)}` : ''}${
          dia.cadena ? `, queda ${plata(dia.final)}` : ''}${
          totalVence > 0 ? `, vence ${plata(totalVence)}` : ''}`}
        className={`w-full px-2 py-2 border-b text-left transition-colors ${
          abierto ? 'border-forest bg-forest-50' : 'border-warm-100 hover:bg-warm-50'}`}>
        <div className={`grid gap-1 items-center ${
          columnasDeSaldo ? 'grid-cols-[2.9rem_1fr_1fr_1fr_1fr]' : 'grid-cols-[2.9rem_1fr_1fr]'}`}>
          <span className="flex items-baseline gap-1">
            <span className={`text-xs font-bold ${
              esHoy ? 'text-forest bg-forest-100 rounded-full px-1.5' : 'text-warm-600'}`}>{numero}</span>
            <span className="text-[9px] text-warm-400">{diaSemana(dia.fecha)}</span>
          </span>
          {columnasDeSaldo && (
            <span className={`text-[11px] font-mono tabular-nums text-right ${
              dia.cadena ? 'text-warm-400' : 'text-warm-300'}`}>
              {dia.cadena ? compacto(dia.inicial) : '—'}
            </span>
          )}
          <span className={`text-[11px] font-mono tabular-nums text-right ${
            dia.total_entradas > 0 ? 'text-success-600 font-bold' : 'text-warm-300'}`}>
            {dia.total_entradas > 0 ? compacto(dia.total_entradas) : '—'}
          </span>
          <span className={`text-[11px] font-mono tabular-nums text-right ${
            dia.total_salidas > 0 ? 'text-danger-600 font-bold' : 'text-warm-300'}`}>
            {dia.total_salidas > 0 ? compacto(dia.total_salidas) : '—'}
          </span>
          {columnasDeSaldo && (
            <span className={`text-[11px] font-mono font-bold tabular-nums text-right ${
              !dia.cadena ? 'text-warm-300' : rojo ? 'text-danger-700' : 'text-warm-700'}`}>
              {dia.cadena ? compacto(dia.final) : '—'}
            </span>
          )}
        </div>

        {/* Lo que VENCE ese día no es plata que ya se movió: es un compromiso, y
            por eso va en su propia línea y NO adentro de la columna «Sale».
            Meterlo ahí restaría del saldo una plata que todavía está en la cuenta. */}
        {totalVence > 0 && (
          <div className="flex items-center gap-1.5 mt-1 pl-1">
            <CalendarClock size={11} className="text-gold-700 shrink-0" />
            <span className="text-[10px] text-gold-700 font-semibold">Vence {plata(totalVence)}</span>
            <span className="text-[10px] text-warm-400">
              · {vencimientos.length} {vencimientos.length === 1 ? 'pago' : 'pagos'}
            </span>
          </div>
        )}
      </button>

      {abierto && (
        <div className="border-b border-warm-200 bg-white px-3 py-3 space-y-3">
          <div className="flex items-baseline justify-between gap-2">
            <p className="text-xs font-bold text-warm-700 first-letter:uppercase">{fechaLarga(dia.fecha)}</p>
            {dia.cadena ? (
              <p className="text-[11px] text-warm-500 shrink-0 font-mono tabular-nums">
                {plata(dia.inicial)} → <b className={rojo ? 'text-danger-700' : 'text-warm-700'}>{plata(dia.final)}</b>
              </p>
            ) : (
              <p className="text-[11px] text-warm-400 shrink-0">Sin saldo: es anterior al extracto</p>
            )}
          </div>

          {dia.movimientos.length > 0 ? (
            <div className="divide-y divide-warm-100 border border-warm-200 rounded-xl overflow-hidden">
              {dia.movimientos.map(m => (
                <div key={m.id} className="flex items-center gap-2 px-3 py-2">
                  <span className="shrink-0 text-[10px] font-bold uppercase tracking-wide px-2 py-1 rounded-lg bg-warm-100 text-warm-600">
                    {m.cuenta}
                  </span>
                  <p className="min-w-0 flex-1 text-sm text-warm-700 truncate">{m.concepto}</p>
                  <span className={`shrink-0 font-mono font-bold text-sm tabular-nums ${
                    m.tipo === 'entrada' ? 'text-success-600' : 'text-danger-600'}`}>
                    {m.tipo === 'entrada' ? '+' : '−'} {plata(m.monto)}
                  </span>
                  {borrandoId === m.id ? (
                    <span className="shrink-0 flex items-center gap-1">
                      <button onClick={() => onBorrar(m.id)}
                        className="text-[11px] font-bold text-white bg-danger-500 px-2 py-1.5 rounded-lg">Borrar</button>
                      <button onClick={() => onPedirBorrar(null)}
                        className="text-[11px] font-bold text-warm-500 px-1.5 py-1.5">No</button>
                    </span>
                  ) : (
                    <button onClick={() => onPedirBorrar(m.id)} aria-label={`Borrar ${m.concepto}`}
                      className="shrink-0 p-2 rounded-lg text-warm-400 hover:text-danger-600 hover:bg-danger-50">
                      <Trash2 size={13} />
                    </button>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <p className="text-[11px] text-warm-500 leading-relaxed">
              No se movió plata en el banco este día
              {dia.cadena && <>: quedó igual que como arrancó</>}.
            </p>
          )}

          {/* La segunda puerta al MISMO formulario de arriba: no abre otro, le
              cambia la fecha y sube el foco. */}
          <button onClick={onCargarAcá}
            className="w-full flex items-center justify-center gap-1.5 min-h-[40px] rounded-xl border border-forest text-forest text-xs font-bold hover:bg-forest-50">
            <Plus size={14} /> Cargar un movimiento con esta fecha
          </button>

          {/* La agenda de ese día, con su acción. Es la mitad que al libro le
              falta: el libro dice qué se movió, la agenda qué hay que mover. */}
          {!sabeVencimientos ? (
            <p className="text-[11px] text-warm-400 leading-relaxed">
              No se pudo leer la agenda de pagos, así que de este día solo se sabe la plata que ya
              se movió: si vence algo, acá no aparece.
            </p>
          ) : vencimientos.length > 0 && (
            <div>
              <p className="text-xs font-bold text-warm-600 mb-1">Vence este día</p>
              <div className="divide-y divide-warm-100 border border-warm-200 rounded-xl overflow-hidden">
                {vencimientos.map(i => (
                  <div key={`d-${i.tipo}-${i.id}`}>
                    <FilaVencimiento item={i} onPagar={onPagar}
                      activo={itemPagando === `${i.tipo}-${i.id}`} />
                    {renderPago(i)}
                  </div>
                ))}
              </div>
              {/* Sin esta línea el dueño paga, ve el vencimiento tachado y espera
                  que el saldo baje solo. No baja: al libro solo entra lo tecleado
                  — salvo que marque «y descontalo del banco» al pagar. */}
              <p className="text-[11px] text-warm-500 leading-relaxed mt-1.5">
                Registrar el pago tacha el vencimiento, pero <b>no mueve el libro del banco</b> por
                sí solo: acá solo entra lo que se teclea. El formulario de pago te ofrece cargar la
                salida en el mismo gesto cuando la plata sale de la cuenta.
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
