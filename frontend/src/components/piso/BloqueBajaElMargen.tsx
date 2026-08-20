import { ReactNode } from 'react'
import { TrendingUp } from 'lucide-react'
import type { Fuente } from '../../api/useDato'
import { SegunDato, NoSeSabe } from '../ui'
import { plata } from '../plata/banco'
import { ComoSeCalcula } from '../plata/campos'
import { fmtTasa, fmtUnit } from '../rentabilidad/helpers'
import type { PalancasData, Piso } from './tipos'

// ═════════════════════════════════════════════════════════════════════════════
// 7 · LO QUE BAJA EL MARGEN — lo de abajo de la división
// ═════════════════════════════════════════════════════════════════════════════
// El denominador del piso, abierto. Cada peso de acá que se recupera baja el
// piso de arriba: es el único bloque de la página donde una decisión de compra
// se ve convertida en la meta de venta del día siguiente.
//
// ── LOS TRES RENGLONES SON MEDIDOS, NO TARIFAS ───────────────────────────
// `impoconsumo` es el impuesto REAL dividido por lo cobrado, no la tarifa ni
// tasa/(1+tasa). `cogs` es el costo teórico sobre lo vendido. `comision` es la
// tasa del contrato por el porcentaje de venta con tarjeta que de verdad hubo.
// Los tres salen del backend ya divididos: acá no se recalcula ninguno.
//
// ── EL IMPOCONSUMO NUNCA FUE PLATA DEL NEGOCIO ───────────────────────────
// De una aromática de $5.900, $437 son de la DIAN. Está adentro del precio de
// la carta, así que se cobra y se gira. Ponerlo en la lista de «lo que baja el
// margen» no es una queja: es lo que hace que el 53% de abajo se entienda.

const porCien = (frac: number) => {
  const v = frac * 100
  const dec = Math.abs(v) < 10 ? 2 : 0
  return '$' + v.toLocaleString('es-CO', { minimumFractionDigits: dec, maximumFractionDigits: dec })
}

/**
 * «sube $X por día» / «baja $X por día» / «no lo mueve».
 *
 * EL VERBO SALE DEL SIGNO, nunca de un supuesto sobre la dirección. Este bloque
 * ya publicó una vez una frase que afirmaba la dirección por su cuenta
 * («recuperar el viejo es esa misma plata de vuelta») y estaba equivocada por un
 * factor de diez. Con un costo fijado a mano cualquiera de los dos movimientos
 * puede darse vuelta: escribir «sube» encima de un número negativo sería la
 * misma promesa, dada vuelta.
 */
function MueveElPiso({ v }: { v: number }) {
  if (v === 0) return <>no se mueve</>
  return <>{v > 0 ? 'sube' : 'baja'}{' '}
    <b className="font-mono tabular-nums">{plata(Math.abs(v))}</b> por día</>
}

/**
 * «va bajando hasta $X por día a medida que se le compre a ese precio».
 *
 * EL MISMO SIGNO QUE `MueveElPiso`, OTRO TIEMPO VERBAL, y esa diferencia es la
 * única que le importa al dueño que está por levantar el teléfono.
 *
 * El renglón de VUELTA decía «el piso baja $X por día» y la frase de abajo
 * remataba con «lo que se recupera HOY yendo a negociar». Los dos números están
 * bien —se verificaron contra el piso real— pero los dos salen de mover
 * `costo_usado` hasta `costo_ref`, y ese movimiento NO ocurre el día que el
 * proveedor acepta: `costo_usado` es el promedio ponderado de TODA la historia
 * de compras, así que baja factura a factura. MEDIDO sobre 10 compras a $2,00 y
 * una a $2,80, con el proveedor aceptando volver a $2,00:
 *
 *     el día del acuerdo, sin comprar todavía   el piso baja      $0,00
 *     con 1 compra al precio acordado           bajó   $658,99   (8,3%)
 *     con 5                                     bajó $2.492,71  (31,2%)
 *     con 20                                    bajó $5.148,76  (64,5%)
 *     con 100                                   bajó $7.189,22  (90,1%)
 *     la promesa publicada                           $7.978,85  (el TOPE)
 *
 * O sea: el número es el LÍMITE al que se llega comprando al precio nuevo, no lo
 * que pasa mañana, y ni siquiera se toca — se le acerca. «Baja $X por día» a
 * secas le pone fecha de mañana a una plata que tarda decenas de facturas, y es
 * la misma familia de error de siempre: un dato CERCA del correcto —el correcto,
 * pero de otro momento— del lado que tranquiliza.
 *
 * Y EL ARREGLO NO PODÍA SER «HASTA». Este renglón decía «el piso va bajando
 * hasta $665 por día»: `hasta` adentro de una construcción de MAGNITUD se lee
 * como DESTINO, o sea «el piso baja hasta quedar en $665 por día» — y el piso de
 * este local no es $665, es $2.682.959,76. El dueño con la tablet a las 7 de la
 * mañana leía que negociar le deja el piso en seiscientos pesos.
 *
 * Ahora dice «baja como mucho $665 por día»: `como mucho` no puede leerse como
 * destino, y el verbo queda en el mismo tiempo que el renglón de IDA («el piso
 * todavía sube $X por día»), que mide exactamente lo mismo para el otro lado.
 * La demora, que era lo único que el gerundio aportaba, pasa a decirse con
 * palabras en vez de con una conjugación: «y no de una, sino factura a factura».
 */
function LlegaAlPiso({ v }: { v: number }) {
  if (v === 0) return <>no se mueve</>
  return <>{v > 0 ? 'sube' : 'baja'} como mucho{' '}
    <b className="font-mono tabular-nums">{plata(Math.abs(v))}</b> por día — y no de una, sino
    factura a factura, a medida que se le compre a ese precio</>
}

function Renglon({ label, valor, nota, fuerte = false }: {
  label: string; valor: string; nota?: ReactNode; fuerte?: boolean
}) {
  return (
    <div className={fuerte ? 'border-t border-warm-200 pt-2 mt-2' : ''}>
      <div className="flex items-baseline justify-between gap-2">
        <p className={`text-xs ${fuerte ? 'font-bold text-warm-700' : 'text-warm-600'}`}>{label}</p>
        <p className={`font-mono tabular-nums shrink-0 ${
          fuerte ? 'text-base font-bold text-warm-700' : 'text-sm text-warm-600'}`}>{valor}</p>
      </div>
      {nota && <p className="text-[11px] text-warm-400 leading-snug mt-0.5">{nota}</p>}
    </div>
  )
}

export default function BloqueBajaElMargen({
  piso, palancas, onCargarComision, children,
}: {
  piso: Fuente<Piso>
  /**
   * `GET /costos/palancas`: las mismas subas que ya mostraba «por producto»,
   * pero con el NOMBRE del que las subió y traducidas a pesos de piso por día.
   * Reemplaza a la lista anónima que salía de `/rentabilidad/por-producto`: dos
   * listas de lo mismo terminan diciendo dos cosas distintas.
   */
  palancas: Fuente<PalancasData>
  onCargarComision: () => void
  /** El bloque de proveedores, montado adentro: es el mismo tema. */
  children?: ReactNode
}) {
  return (
    <section className="rounded-2xl border border-warm-200 bg-white overflow-hidden">
      <div className="px-4 py-3 border-b border-warm-100">
        <h2 className="text-sm font-bold text-warm-700">Lo que baja el margen</h2>
        <p className="text-[11px] text-warm-500 leading-snug">
          Lo de abajo de la división: cada peso que se recupere acá baja el piso de arriba.
        </p>
      </div>

      {/* ── De cada $100 cobrados ──────────────────────────────────────────── */}
      <div className="px-4 py-3">
        <p className="text-[10px] font-bold uppercase tracking-wide text-warm-500 mb-2">
          De cada $100 cobrados
        </p>
        <SegunDato
          dato={piso.dato}
          cargando={<p className="text-sm text-warm-400">Midiendo el margen…</p>}
          falla={m => (
            <NoSeSabe bloque onReintentar={piso.recargar}
              mensaje={`${m} — no se sabe cuánto queda de cada peso cobrado.`} />
          )}
          listo={p => p.razones === null ? (
            /* Sin razones no hay porcentajes que mostrar, y eso NO es un 100%
               limpio: es que no hubo venta con la que medir. El hueco ocupa
               lugar y lo dice. */
            <div className="rounded-xl border border-dashed border-warm-300 bg-warm-50 px-3 py-4">
              <p className="text-xs text-warm-600 leading-relaxed">
                Todavía no se puede decir cuánto queda de cada $100: no hay venta medida ni en este
                mes ni en el anterior. No quiere decir que quede todo.
              </p>
            </div>
          ) : (<>
            <div className="space-y-2">
              <Renglon label="Impoconsumo" valor={`−${porCien(p.razones.impoconsumo)}`}
                nota="Se le gira a la DIAN. No es plata del negocio, nunca: viene adentro del precio de la carta." />
              <Renglon label="Mercadería" valor={`−${porCien(p.razones.cogs)}`}
                nota={<>Lo que costó lo que se vendió
                  {p.razones.cogs_desechables > 0 && <>, con el empaque adentro:{' '}
                    <b className="font-mono tabular-nums">{porCien(p.razones.cogs_desechables)}</b>{' '}
                    de cada $100 son vaso, tapa y servilleta</>}.</>} />
              <Renglon label="Comisión del datáfono" valor={`−${porCien(p.razones.comision)}`}
                nota={p.razones.tasa_comision > 0
                  ? <>{fmtTasa(p.razones.tasa_comision)} sobre el {Math.round(p.razones.pct_tarjeta * 100)}%
                      de la venta que se cobró con tarjeta.</>
                  : <span className="text-gold-700">
                      Sin cargar — el {Math.round(p.razones.pct_tarjeta * 100)}% de la venta se
                      cobra con tarjeta y esa comisión no la está descontando nadie, así que el
                      margen sale <b>alto</b> y el piso <b>bajo</b>.{' '}
                      <button onClick={onCargarComision} className="font-bold underline decoration-dotted">
                        cargarla
                      </button>
                    </span>} />
              <Renglon fuerte label="Quedan"
                valor={p.margen_contribucion === null ? '—' : porCien(p.margen_contribucion)} />
            </div>

            <p className="text-[11px] text-warm-400 leading-relaxed mt-2">
              Medido sobre {plata(p.razones.ventas_medidas)} vendidos entre el {p.razones.desde} y
              el {p.razones.hasta}
              {p.razones.de === 'mes_anterior' && <> — <b>del mes pasado</b>, porque este mes
                todavía no tiene venta con la que medir</>}.
              {p.razones.pct_venta_costeada !== null && p.razones.pct_venta_costeada < 100 && (
                <> Solo el {Math.round(p.razones.pct_venta_costeada)}% de esa venta tiene costo
                  cargado: el resto entra valiendo $0 y sube este «quedan».</>
              )}
            </p>
          </>)} />
      </div>

      {/* ── Lo que subieron, con nombre ────────────────────────────────────── */}
      <div className="px-4 py-3 border-t border-warm-100">
        <p className="text-[10px] font-bold uppercase tracking-wide text-warm-500 mb-2">
          Lo que subieron, con nombre
        </p>
        <SegunDato
          dato={palancas.dato}
          cargando={<p className="text-sm text-warm-400">Comparando precios de compra…</p>}
          falla={m => (
            <NoSeSabe onReintentar={palancas.recargar}
              mensaje={`${m} — no se sabe qué insumos subieron de precio. Que no aparezca ninguno `
                + 'no quiere decir que no haya subido nada.'} />
          )}
          listo={d => {
            if (d.palancas.length === 0) return (
              <p className="text-xs text-warm-600 leading-relaxed">
                Ningún insumo se está facturando más de un 10% arriba de lo más barato que se le
                pagó en los últimos 12 meses.
              </p>
            )
            return (
              <div className="space-y-2.5">
                {d.palancas.slice(0, 5).map(a => (
                  <div key={a.insumo_id} className="flex items-start gap-2">
                    <TrendingUp size={14} className="shrink-0 mt-0.5 text-danger-600" />
                    <div className="min-w-0 flex-1">
                      <p className="text-xs font-semibold text-warm-700 leading-snug">
                        {/* EL SUJETO DE LA FRASE TIENE QUE SER EL DUEÑO DEL
                            PORCENTAJE. Con el proveedor adelante, el «+40%» es
                            una acusación contra él, así que solo puede ir
                            adelante cuando la referencia también es SUYA
                            (`mismo_proveedor`). Si el precio barato lo facturó
                            otro, el sujeto pasa a ser el insumo y los dos nombres
                            van abajo: el dueño llega a la reunión con un número
                            que el proveedor no puede desmentir con su propia
                            factura. `null` cuando la factura vino sin proveedor:
                            se dice, no se inventa un «varios». */}
                        {a.mismo_proveedor && a.proveedor !== null ? (<>
                          {a.proveedor}
                          <span className="font-normal text-warm-600"> subió {a.nombre} </span>
                        </>) : (<>
                          {a.nombre}
                          <span className="font-normal text-warm-600"> subió </span>
                        </>)}
                        <span className="text-danger-700">+{Math.round(a.pct_suba)}%</span>{' '}
                        {/* EL PAR IMPRESO ES EL PAR QUE MIDE ESE PORCENTAJE
                            —referencia → último—, no «lo que se costea →
                            último»: dos cifras que no dan el porcentaje que tienen
                            al lado son una invitación a desconfiar de las dos. Y
                            va con `fmtUnit` porque estos precios viven abajo del
                            peso: `fmt` imprimía «$2 → $3» para $2,00 → $2,80. */}
                        <span className="font-mono tabular-nums font-normal text-warm-400">
                          {fmtUnit(a.costo_ref)} → {fmtUnit(a.costo_ultimo)}
                        </span>
                      </p>
                      <p className="text-[11px] text-warm-500 leading-snug">
                        Toca <b className="font-mono tabular-nums">{plata(a.venta_30d_afectada)}</b>{' '}
                        de venta al mes
                        {a.productos_afectados.length > 0
                          && ` · ${a.productos_afectados.slice(0, 3).join(', ')}`
                            + (a.productos_afectados.length > 3
                              ? ` y ${a.productos_afectados.length - 3} más` : '')}
                      </p>
                      {/* DE DÓNDE SALE LA REFERENCIA. Sin esto el «+40%» es un
                          número que hay que creer; con la fecha y el nombre es una
                          afirmación que se verifica contra el papel antes de
                          discutirla. */}
                      <p className="text-[11px] text-warm-400 leading-snug">
                        Los <span className="font-mono tabular-nums">{fmtUnit(a.costo_ref)}</span>{' '}
                        son lo más barato que se facturó en {a.ref_meses} meses
                        {!a.mismo_proveedor && <>, y los facturó{' '}
                          {a.ref_proveedor ?? 'una factura sin proveedor cargado'}</>}
                        {a.ref_fecha !== null && ` (${a.ref_fecha.slice(0, 10)})`}.
                      </p>
                      {/* ═══ LOS DOS NÚMEROS, Y NINGUNO SE DEDUCE DEL OTRO ═══
                          Acá se publicaba UNO —«el piso sube $8.053 por día»— y
                          debajo decía «recuperar el viejo es esa misma plata de
                          vuelta». No lo era: recuperar el precio viejo devolvía
                          $798 por día. La frase prometía diez veces lo que la
                          decisión devuelve, porque el costo con el que se costea
                          es el promedio de toda la historia y ya tenía la suba
                          absorbida en un 9%.
                          Cuando alguno no se pudo traducir va el porqué del
                          backend en el mismo lugar: un renglón que se evapora se
                          lee como «no importa». */}
                      {a.piso_dia_si_se_queda !== null ? (
                        <p className="text-[11px] text-danger-700 leading-snug mt-0.5">
                          Si ese precio se queda, el piso todavía{' '}
                          <MueveElPiso v={a.piso_dia_si_se_queda} />.
                        </p>
                      ) : (
                        <p className="text-[11px] text-warm-400 leading-snug mt-0.5">
                          {a.sin_impacto_porque ?? 'No se pudo medir cuánto mueve el piso.'}
                        </p>
                      )}
                      {/* EL DE IDA YA TENÍA SU MARCADOR DE ACUMULACIÓN («todavía»);
                          este no tenía ninguno y se leía en presente. Los dos
                          números salen del mismo movimiento de `costo_usado`, así
                          que los dos tardan lo mismo: ver `LlegaAlPiso` para el
                          escalón medido ($0,00 el día del acuerdo). */}
                      {a.piso_dia_si_vuelve !== null && (
                        <p className="text-[11px] text-success-700 leading-snug">
                          Si vuelve a{' '}
                          <span className="font-mono tabular-nums">{fmtUnit(a.costo_ref)}</span>, el
                          piso <LlegaAlPiso v={a.piso_dia_si_vuelve} />
                          {a.pct_absorbido !== null && <>: ese tope es el pedazo de la suba que ya
                            está adentro del costo con el que se costea, el{' '}
                            {Math.round(a.pct_absorbido)}%</>}.
                        </p>
                      )}
                    </div>
                  </div>
                ))}
                {/* ACÁ ESTABA LA PROMESA FUERTE: «lo que se recupera HOY yendo a
                    negociar es el segundo». El número es correcto y es el tope,
                    no el lunes: se llega comprando al precio nuevo, factura a
                    factura, y el día del acuerdo el piso baja $0,00 (medido, ver
                    `LlegaAlPiso`). El primero tiene exactamente la misma demora
                    —es el mismo promedio moviéndose para el otro lado— así que la
                    frase los declara juntos en vez de arreglar uno solo. */}
                <p className="text-[11px] text-warm-400 leading-relaxed">
                  Los dos renglones de cada suba miden cosas distintas y se leen juntos. El costo con
                  el que se calcula la mercadería de arriba es el <b>promedio de todas las compras</b>,
                  así que se mueve de a poco y para los dos lados: lo que <b>todavía va a llegar</b> si
                  el precio nuevo se queda es el primer número, y <b>cuánto puede bajar</b> el
                  piso si el proveedor da marcha atrás es el segundo. Ninguno de los dos pasa mañana:
                  el día que el proveedor acepta, el piso <b>no se mueve</b> — el promedio recién
                  empieza a bajar con la primera factura al precio nuevo y le lleva decenas de
                  compras acercarse a ese tope. Al principio de una suba el primero es grande y el
                  segundo chico; cuando la suba ya llegó entera se dan vuelta.
                </p>
              </div>
            )
          }} />
      </div>

      {/* El bloque de proveedores entero, montado acá adentro: a quién se le
          compra y cuánto se le debe es la misma pregunta que «qué me está
          bajando el margen», y era el ÚNICO camino real para pagarle a un
          proveedor (`PATCH /facturas/{id}/pago`). Se mueve completo, no se
          reescribe. */}
      {children}

      <ComoSeCalcula titulo="¿Por qué el impoconsumo está en esta lista?">
        <p>
          Porque está <b>adentro</b> del precio de la carta. De una aromática de $5.900, unos $437
          son de la DIAN: entran al cajón con la venta y se giran después. Ponerlos acá no es una
          queja — es lo que hace que el «quedan» de abajo se entienda, y es la razón de que el piso
          de arriba esté en pesos <b>cobrados</b> y no en pesos netos.
        </p>
        <p>
          La mercadería es el costo <b>teórico</b> de lo que se vendió: sale de la receta de cada
          producto por las unidades que salieron, no de las facturas del mes. Por eso un mes con
          mucha compra y poca venta no dispara este renglón — la compra está en la bodega, no en el
          margen.
        </p>
      </ComoSeCalcula>
    </section>
  )
}
