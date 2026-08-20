import { ReactNode, useMemo } from 'react'
import { AlertTriangle, TrendingDown } from 'lucide-react'
import { Dato, ambos, mapDato } from '../../api/dato'
import type { Fuente } from '../../api/useDato'
import { SegunDato, NoSeSabe } from '../ui'
import { fechaCorta, plata } from '../plata/banco'
import { Agenda, Flujo } from '../plata/tipos'
import { ComoSeCalcula } from '../plata/campos'
import type { PulsoData } from '../rentabilidad/helpers'
import type { Piso } from './tipos'
import { indiceDeSemana, pisoParejoDelMes, sumarDias } from './calculo'

// ═════════════════════════════════════════════════════════════════════════════
// 5 · ¿LLEGA A FIN DE MES? — la caja más peligrosa de la página
// ═════════════════════════════════════════════════════════════════════════════
// Un número optimista acá hace gastar plata que ya está comprometida. Por eso
// es el único bloque que se APAGA: cuando la nómina no está agendada o hay
// cuentas sin fecha, el colchón no se publica — se dice qué falta y el botón
// que lo arregla.
//
// ── EL HORIZONTE TIENE FECHA DE CIERRE ───────────────────────────────────
// Hasta fin de mes, no 30 días que se corren. La pregunta del dueño tiene una
// fecha («¿llego al 31?») y una ventana que se desliza nunca la contesta: cada
// día que pasa mueve la meta. El backend ancla la serie a fin de mes cuando se
// le pide sin `dias`, y manda `horizonte_es_fin_de_mes` para que esta pantalla
// pueda decir cuál está mirando en vez de suponerlo.
//
// ── EL COLCHÓN SE MIDE CONTRA EL MÍNIMO, NO CONTRA EL FINAL ──────────────
// Un mes que termina bien pero pasa por un lunes en rojo no tiene colchón: el
// proveedor rebota igual. `saldo_minimo` es el punto más bajo de la serie.
//
// ── Y NO SE RECORTA EN CERO ──────────────────────────────────────────────
// `colchon` puede venir negativo, y así se muestra: es exactamente el dato que
// hay que ver antes de gastar. Lo que se recorta es «cuánto se puede sacar»,
// que no puede ser negativo — pero el déficit queda escrito arriba.

interface Bloqueo { titulo: string; detalle: string; cta?: string; hacer?: () => void }

/**
 * Lo que hace que este bloque NO pueda publicar un colchón.
 *
 * Se arma en UN solo lugar porque la misma lista gobierna si hay número y qué
 * se dice en su lugar: dos listas separadas terminan con un colchón publicado
 * bajo un cartel que dice que falta información.
 */
function bloqueosDe(a: Agenda, f: Flujo, irAlMensual: () => void, irASinFecha: () => void): Bloqueo[] {
  const out: Bloqueo[] = []

  // ── LO QUE FALTA, POR CONCEPTO, DICHO POR EL BACKEND ──────────────────────
  // Esta lista NO se calcula acá y esa es la decisión. Antes esta función miraba
  // `a.items` para adivinar si la nómina estaba agendada, y era la única
  // cobertura por concepto que existía: la declaración del impoconsumo —$11,5M
  // en un bimestre— no la miraba nadie, porque desde el navegador no hay forma de
  // MEDIRLA. El server sí puede (sale de la venta real del bimestre y de los
  // contratos), así que manda nombre, plata y fecha, y acá solo se dibuja.
  //
  // Una segunda regla local se desincronizaría de la del server en el primer
  // concepto que se agregue, y las dos estarían en la misma pantalla.
  for (const c of f.advertencias.conceptos_sin_cargar) {
    out.push({
      titulo: `${c.nombre} no está en lo que hay que pagar`,
      detalle: (c.monto === null
        ? `El sistema no puede decir de cuánto: ${c.sin_monto_porque ?? 'no se pudo medir'}. `
        : `${plata(c.monto)} que esta proyección no está restando. `)
        + (c.vencido
          ? 'Ya pasó la fecha en que se pagaba, así que es plata que se debe AHORA.'
          : 'Sin eso adentro, la caja se ve mejor de lo que está — y es justo la '
            + 'plata que se gastaría.'),
      cta: 'Agendarlo',
      hacer: irAlMensual,
    })
  }

  if (a.sin_fecha.length > 0) out.push({
    titulo: `Hay ${a.sin_fecha.length} cuenta${a.sin_fecha.length === 1 ? '' : 's'} sin fecha de pago`,
    detalle: `${plata(a.totales.sin_fecha)} que se deben y que esta proyección no mira, porque no `
      + 'sabe qué día restarlos. La caja se ve mejor de lo que está.',
    cta: 'Ponerles fecha',
    hacer: irASinFecha,
  })

  // `sin_salidas_cargadas` lo decide el BACKEND: ni una sola salida en el
  // horizonte casi siempre significa que nadie cargó las cuentas por pagar, no
  // que no haya nada que pagar. SIGUE ACÁ pero ya no es la señal principal: se
  // apaga con una sola obligación cargada, y ese era el agujero — con el
  // arriendo adentro el colchón se publicaba igual faltando los millones de la
  // DIAN. Lo de arriba es lo que cierra ese caso.
  if (f.advertencias.sin_salidas_cargadas) out.push({
    titulo: 'No hay ningún pago cargado en lo que queda del mes',
    detalle: 'Como está, la proyección solo sabe de la plata que entra. Un saldo que nunca baja '
      + 'no es una buena noticia: es una pregunta que no se hizo.',
  })

  return out
}

/**
 * Una barra del gráfico. La altura es relativa al máximo de TODO el mes.
 *
 * `alto === null` = ese día no tiene número. Va una ranura vacía con un punto
 * al pie, no una barra de altura cero: una barra en cero es una afirmación («no
 * entra nada ese día») y acá lo que pasa es que no se proyectó.
 */
function Barra({ alto, tono, titulo }: {
  alto: number | null
  /** `sin_vara` NO es `flojo`: es un día que vendió y con el que no hay contra
   *  qué compararlo. Pintarlos igual afirma que no pasó una vara que no existe. */
  tono: 'pasado' | 'flojo' | 'esperado' | 'rojo' | 'sin_dato' | 'sin_vara'
  titulo: string
}) {
  if (alto === null || tono === 'sin_dato') {
    return (
      <div className="flex-1 min-w-[3px] flex items-end justify-center h-full" title={titulo}>
        <div className="w-full h-[3px] rounded-sm bg-warm-200 opacity-70" />
      </div>
    )
  }
  const color = tono === 'pasado' ? 'bg-success-500'
    : tono === 'flojo' ? 'bg-warm-300'
    : tono === 'sin_vara' ? 'bg-forest/30'
    : tono === 'rojo' ? 'bg-danger-500'
    : 'bg-warm-200'
  return (
    <div className="flex-1 min-w-[3px] flex items-end h-full" title={titulo}>
      <div className={`w-full rounded-sm ${color} ${tono === 'esperado' ? 'opacity-60' : ''}`}
        style={{ height: `${Math.max(2, Math.min(100, alto))}%` }} />
    </div>
  )
}

interface Dia {
  fecha: string
  /**
   * Vendido (pasado) o esperado (futuro).
   *
   * `null` SOLO en el futuro, y significa que ese día no está en la serie que
   * mandó el backend — o sea que la proyección no llega hasta ahí. Un 0 en su
   * lugar diría «ese día no entra un peso», que es una afirmación sobre un día
   * que nadie proyectó, y hacia el lado alarmista o el tranquilizador según lo
   * que se esté mirando. La barra no se dibuja y la leyenda lo explica.
   *
   * En el PASADO no hay `null`: los tickets del mes llegaron enteros, así que un
   * día que abre y no aparece en `ventas_diarias` es un día que no facturó. Eso
   * es un cero MEDIDO y se puede afirmar.
   */
  monto: number | null
  futuro: boolean
  /** Solo para días pasados: si llegó a la vara pareja. `null` = no hay vara. */
  paso: boolean | null
  quiebre: boolean
}

/**
 * Los días del mes, en una sola serie.
 *
 * Los pasados salen de `ventas_diarias` (tickets ya emitidos) y los futuros de
 * `flujo.serie[].entradas` (la mediana del mismo día de semana). Son dos cosas
 * distintas y por eso se pintan distinto: mezclarlas en un solo color diría que
 * la mitad derecha ya pasó.
 */
function armarDias(p: Piso, f: Flujo, ventasDiarias: { dia: string; ventas: number }[]): Dia[] {
  const parejo = pisoParejoDelMes(p)
  const abre = new Set(p.dias.dias_semana)
  const vendido = new Map(ventasDiarias.map(v => [v.dia, v.ventas]))
  const esperado = new Map(f.serie.map(s => [s.fecha, s.entradas]))

  /**
   * `dias_semana: []` NO significa «no abre ningún día».
   *
   * Con `derivados: false` significa que no había historia de ventas con la que
   * derivar QUÉ días abre, y el backend ya resolvió ese caso contando el
   * calendario entero (`dias = len(calendario)`). Filtrar por el set vacío tira
   * los treinta días del mes y deja la serie en cero — y el bloque de arriba, en
   * la misma pantalla, ya le está diciendo al dueño que se contaron los días de
   * calendario. Dos pantallas contradiciéndose sobre el mismo mes.
   */
  const abreEseDia = (d: string) => !p.dias.derivados || abre.has(indiceDeSemana(d))

  const out: Dia[] = []
  for (let d = p.desde; d <= p.hasta; d = sumarDias(d, 1)) {
    if (!abreEseDia(d)) continue
    const futuro = d > p.hoy
    // Ver el comentario de `Dia.monto`: en el futuro la ausencia es «no
    // proyectado» y en el pasado es «no facturó». Son cosas distintas y por eso
    // solo una de las dos cae a cero.
    //
    // La ausencia se lee del `undefined` que devuelve el `Map`, no de un `has()`
    // seguido de un cast: el cast le prometía al compilador un número que el
    // `Map` no garantiza, y esa promesa es exactamente lo que después deja pasar
    // un `undefined` impreso en pantalla.
    const proyectado = esperado.get(d)
    const monto = futuro
      ? (proyectado === undefined ? null : proyectado)
      : (vendido.get(d) ?? 0)
    out.push({
      fecha: d,
      monto,
      futuro,
      paso: futuro || parejo === null || monto === null ? null : monto >= parejo,
      quiebre: f.punto_de_quiebre === d,
    })
  }
  return out
}

export default function BloqueFinDeMes({
  flujo, agenda, piso, pulso, onCambiarReserva, onAlMensual, onASinFecha,
}: {
  flujo: Fuente<Flujo>
  agenda: Fuente<Agenda>
  piso: Fuente<Piso>
  pulso: Fuente<PulsoData>
  onCambiarReserva: () => void
  /** Al pliegue «una vez al mes», donde viven los botones que agendan la nómina
   *  Y la declaración del impoconsumo. Antes se llamaba `onANomina`, cuando la
   *  nómina era el único concepto que esta pantalla sabía echar en falta. */
  onAlMensual: () => void
  onASinFecha: () => void
}) {
  /** El gráfico necesita los TRES. Con `ambos` encadenado, una falla gana. */
  // `desde`/`hasta` viajan al lado de los días porque son del PISO, no del
  // flujo: son la ventana que se intentó dibujar, y hace falta poder nombrarla
  // justamente en el caso en que no quedó ni un día adentro.
  const grafico = useMemo<Dato<{ dias: Dia[]; f: Flujo; desde: string; hasta: string }>>(
    () => mapDato(ambos(ambos(piso.dato, flujo.dato), pulso.dato),
      ([[p, f], pu]) => ({ dias: armarDias(p, f, pu.ventas_diarias), f, desde: p.desde, hasta: p.hasta })),
    [piso.dato, flujo.dato, pulso.dato])

  /** El colchón necesita el flujo Y la agenda: la agenda es la que puede vetarlo. */
  const colchon = useMemo(
    () => mapDato(ambos(flujo.dato, agenda.dato),
      ([f, a]) => ({ f, bloqueos: bloqueosDe(a, f, onAlMensual, onASinFecha) })),
    [flujo.dato, agenda.dato, onAlMensual, onASinFecha])

  return (
    <section className="rounded-2xl border border-warm-200 bg-white overflow-hidden">
      <div className="px-4 py-3 border-b border-warm-100">
        <h2 className="text-sm font-bold text-warm-700">¿Llega a fin de mes?</h2>
        <SegunDato
          dato={flujo.dato}
          cargando={<p className="text-[11px] text-warm-400">Proyectando…</p>}
          falla={() => (
            <p className="text-[11px] text-warm-500">
              El horizonte llega hasta fin de mes: la pregunta tiene fecha de cierre.
            </p>
          )}
          listo={f => (
            <p className="text-[11px] text-warm-500 leading-snug">
              {f.horizonte_es_fin_de_mes
                ? <>Hasta fin de mes: quedan {f.dias_hasta_fin_de_mes} día
                    {f.dias_hasta_fin_de_mes === 1 ? '' : 's'} de calendario. La pregunta tiene
                    fecha de cierre, no son 30 días que se corren.</>
                : <>Ojo: esta proyección mira {f.dias} días y no hasta fin de mes, así que el
                    colchón de abajo <b>no</b> habla de la misma ventana que el piso de venta.</>}
            </p>
          )} />
      </div>

      {/* ── El mes, día por día ───────────────────────────────────────────── */}
      <div className="px-4 py-3 border-b border-warm-100">
        <SegunDato
          dato={grafico}
          cargando={<div className="h-24 grid place-items-center text-sm text-warm-400">…</div>}
          falla={m => (
            <NoSeSabe bloque
              onReintentar={() => { piso.recargar(); flujo.recargar(); pulso.recargar() }}
              mensaje={`${m} — no se puede dibujar el mes día por día. El hueco está acá a `
                + 'propósito: sin el gráfico no se sabe cómo viene el mes, no que venga bien.'} />
          )}
          listo={({ dias, f, desde, hasta }) => {
            // NINGÚN DÍA QUE DIBUJAR. Los renglones de abajo indexan `dias[0]` y
            // `dias[dias.length - 1]` para rotular los extremos del eje, y sobre
            // una lista vacía eso no dibuja un gráfico pobre: revienta la página
            // entera con un `undefined.fecha`. Es alcanzable de verdad —un mes
            // cuyo rango no tiene un solo día adentro— y acá va el hueco que lo
            // dice, que es lo que la sección debe cuando no tiene qué mostrar.
            if (dias.length === 0) return (
              <p className="text-sm text-warm-500 leading-relaxed py-3">
                No hay ningún día que dibujar entre el {fechaCorta(desde)} y el {fechaCorta(hasta)}.
                No quiere decir que el mes venga bien: quiere decir que no hay mes que mirar.
              </p>
            )
            // La escala sale solo de los días que TIENEN número. Meter los
            // `null` como ceros no cambiaría el máximo, pero sí el criterio, y
            // el criterio es lo que se copia mal la próxima vez.
            const conNumero = dias.filter((d): d is Dia & { monto: number } => d.monto !== null)
            const max = Math.max(...conNumero.map(d => d.monto), 1)
            const pasados = dias.filter(d => !d.futuro)
            // ¿Hay vara? Sin historia para derivar qué días abre el local no hay
            // piso parejo, y entonces no hay aprobado ni reprobado que mostrar:
            // solo alturas. La leyenda cambia con esto, no solo los colores.
            const hayVara = pasados.some(d => d.paso !== null)
            const sinProyectar = dias.filter(d => d.futuro && d.monto === null).length
            return (<>
              <div className="flex items-end gap-[2px] h-24">
                {dias.map(d => (
                  <Barra key={d.fecha}
                    alto={d.monto === null ? null : (d.monto / max) * 100}
                    tono={d.monto === null ? 'sin_dato'
                      : d.quiebre ? 'rojo'
                      : d.futuro ? 'esperado'
                      // `paso` en null quiere decir que NO HAY VARA —sin
                      // historia para derivar qué días abre el local, no hay
                      // piso parejo contra el que medir—. Colapsarlo en 'flojo'
                      // pintaba el mes entero de gris «no la pasó», que es
                      // afirmar exactamente lo que no se midió. El bloque 1 ya
                      // trata este mismo null como ausencia; acá también.
                      : d.paso === null ? 'sin_vara'
                      : d.paso ? 'pasado' : 'flojo'}
                    titulo={d.monto === null
                      ? `${fechaCorta(d.fecha)} · la proyección no llega hasta este día`
                      : `${fechaCorta(d.fecha)} · ${plata(d.monto)}`
                        + (d.futuro ? ' (esperado)' : '')} />
                ))}
              </div>
              <div className="flex items-baseline justify-between gap-2 mt-1.5 text-[10px] text-warm-400">
                <span>{pasados.length > 0 ? fechaCorta(dias[0].fecha) : ''}</span>
                <span>hoy</span>
                <span>{fechaCorta(dias[dias.length - 1].fecha)}</span>
              </div>
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-2 text-[10px] text-warm-500">
                {hayVara && <Leyenda color="bg-success-500" texto="pasó la vara del mes" />}
                {hayVara && <Leyenda color="bg-warm-300" texto="no la pasó" />}
                {!hayVara && <Leyenda color="bg-forest/30" texto="vendió (sin vara con la que medir)" />}
                <Leyenda color="bg-warm-200" texto="esperado (mediana del mismo día)" />
                {f.punto_de_quiebre && <Leyenda color="bg-danger-500" texto="se acaba la plata" />}
              </div>

              {sinProyectar > 0 && (
                <p className="mt-1.5 text-[11px] text-gold-700 leading-snug">
                  {sinProyectar} día{sinProyectar === 1 ? '' : 's'} del mes quedan sin barra: la
                  proyección no llega hasta ahí. No es que no se espere venta — es que no se
                  proyectó.
                </p>
              )}

              {f.punto_de_quiebre && (
                <p className="mt-2 flex items-start gap-1.5 text-xs text-danger-700 font-semibold leading-snug">
                  <TrendingDown size={14} className="shrink-0 mt-0.5" />
                  Te quedás sin plata el {fechaCorta(f.punto_de_quiebre)}
                  {f.dias_hasta_quiebre != null && <> — en {f.dias_hasta_quiebre} día
                    {f.dias_hasta_quiebre === 1 ? '' : 's'}</>}.
                </p>
              )}

              <p className="mt-1.5 text-[11px] text-warm-500 leading-snug">
                Lo más bajo que llega la caja: <b className="font-mono tabular-nums">
                  {plata(f.saldo_minimo)}</b>.
              </p>

              {f.advertencias.sin_historia_ventas && (
                <p className="mt-1 text-[11px] text-gold-700 leading-snug">
                  No hay ventas de las últimas 8 semanas para estimar lo que entra: las barras
                  grises de la derecha están asumiendo que no entra un peso.
                </p>
              )}
            </>)
          }} />
      </div>

      {/* ── ¿Se puede gastar en una activación? ───────────────────────────── */}
      <div className="px-4 py-3">
        <p className="text-[11px] font-bold uppercase tracking-wide text-warm-500">
          ¿Se puede gastar en una activación?
        </p>
        <SegunDato
          dato={colchon}
          cargando={<p className="mt-2 text-sm text-warm-400">Calculando el colchón…</p>}
          falla={m => (
            <div className="mt-2">
              <NoSeSabe bloque
                onReintentar={() => { flujo.recargar(); agenda.recargar() }}
                mensaje={`${m} — no se sabe cuánto se puede sacar. Este es el número más caro de `
                  + 'equivocar de la página, así que sin los dos lados no se publica ninguno.'} />
            </div>
          )}
          listo={({ f, bloqueos }) => bloqueos.length > 0 ? (
            /* ── APAGADO A PROPÓSITO ─────────────────────────────────────
               No hay número. Un colchón calculado sin la nómina adentro es
               exactamente la plata que ya está comprometida, presentada como
               disponible. Se dice qué falta y el botón que lo arregla. */
            <div className="mt-2 rounded-xl border-2 border-dashed border-gold-300 bg-gold-50 px-3 py-3">
              <p className="flex items-start gap-1.5 text-xs font-bold text-gold-700 leading-snug">
                <AlertTriangle size={14} className="shrink-0 mt-0.5" />
                Acá no va ningún número todavía
              </p>
              <p className="text-[11px] text-gold-700/90 leading-relaxed mt-1">
                Falta plata que esta proyección no está mirando, así que cualquier colchón que
                mostrara sería más alto que el real — y es el que se gastaría.
              </p>
              <ul className="mt-2 space-y-2">
                {bloqueos.map(b => (
                  <li key={b.titulo} className="flex items-start gap-2">
                    <div className="min-w-0 flex-1">
                      <p className="text-xs font-semibold text-gold-700 leading-snug">{b.titulo}</p>
                      <p className="text-[11px] text-gold-700/80 leading-snug">{b.detalle}</p>
                    </div>
                    {b.cta && b.hacer && (
                      <button onClick={b.hacer}
                        className="shrink-0 min-h-[46px] px-3 rounded-xl text-[11px] font-bold
                                   text-gold-700 hover:bg-gold-100">
                        {b.cta} →
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ) : (<>
            <div className="mt-2 space-y-1">
              <Renglon label="Lo más bajo que llega la caja" valor={plata(f.saldo_minimo)}
                rojo={f.saldo_minimo < 0} />
              <Renglon label="Reserva mínima" valor={plata(f.reserva_minima_caja)} />
              <div className="flex items-baseline justify-between gap-2 border-t border-warm-200 pt-1.5">
                <p className="text-xs font-bold uppercase tracking-wide text-warm-600">
                  Se puede sacar hoy
                </p>
                <p className={`text-lg font-bold font-mono tabular-nums shrink-0 ${
                  f.colchon > 0 ? 'text-success-700' : 'text-warm-700'}`}>
                  {/* El colchón NO se recorta en cero (arriba se ve entero); lo
                      que se recorta es «cuánto se puede sacar», que no puede ser
                      negativo. El déficit queda escrito abajo, con su cifra. */}
                  {plata(Math.max(0, f.colchon))}
                </p>
              </div>
            </div>

            {f.colchon <= 0 ? (
              <p className="mt-2 text-xs text-danger-700 font-semibold leading-relaxed">
                NO HAY COLCHÓN
                {f.colchon < 0 && <>: faltan <span className="font-mono tabular-nums">
                  {plata(-f.colchon)}</span> para sostener la reserva</>}. Antes de pensar en una
                activación hay que mover una fecha de pago o conseguir plata.
              </p>
            ) : (
              <p className="mt-2 text-xs text-warm-500 leading-relaxed">
                Esa plata se puede sacar sin que la caja baje de la reserva en ningún día del mes.
              </p>
            )}

            {/* Un cero sin decidir no puede pasar por una decisión tomada. */}
            {f.reserva_es_default && (
              <p className="mt-1.5 text-[11px] text-gold-700 leading-relaxed">
                La reserva mínima está en $0, que es el default y no una decisión: con ella en cero,
                «se puede sacar» significa «hasta quedar sin un peso».{' '}
                <button onClick={onCambiarReserva}
                  className="font-bold underline decoration-dotted">
                  poner una reserva
                </button>
              </p>
            )}
            {!f.reserva_es_default && (
              <button onClick={onCambiarReserva}
                className="mt-1.5 text-[11px] font-bold text-forest underline decoration-dotted">
                cambiar la reserva
              </button>
            )}
          </>)} />
      </div>

      <ComoSeCalcula titulo="¿Cómo se arma esta proyección?">
        <p>
          Cada día suma la venta esperada y resta lo que hay que pagar ese día, arrancando de la
          plata que hay hoy. La venta esperada es la <b>mediana del mismo día de la semana</b> de
          las últimas 8 semanas: no es un promedio, así que un sábado excepcional no arrastra a
          todos los sábados.
        </p>
        <p>
          Las dos mitades de la cuenta no se ganan igual: lo que <b>entra</b> se deriva solo de
          cada ticket, pero lo que <b>sale</b> existe únicamente si alguien lo tecleó. Por eso la
          presencia de un día en rojo significa algo, y su ausencia sola no significa nada.
        </p>
        <p>
          El colchón se mide contra el punto <b>más bajo</b> del mes y no contra el saldo final: un
          mes que termina bien pero pasa por un lunes en rojo no tiene colchón — el proveedor
          rebota igual.
        </p>
      </ComoSeCalcula>
    </section>
  )
}

const Leyenda = ({ color, texto }: { color: string; texto: string }) => (
  <span className="flex items-center gap-1">
    <span className={`w-2.5 h-2.5 rounded-sm ${color}`} /> {texto}
  </span>
)

const Renglon = ({ label, valor, rojo = false }: {
  label: ReactNode; valor: string; rojo?: boolean
}) => (
  <div className="flex items-baseline justify-between gap-2">
    <p className="text-xs text-warm-500">{label}</p>
    <p className={`text-sm font-mono tabular-nums shrink-0 ${
      rojo ? 'text-danger-700 font-bold' : 'text-warm-600'}`}>{valor}</p>
  </div>
)
