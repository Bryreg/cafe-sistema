import { ReactNode } from 'react'
import { TrendingUp } from 'lucide-react'
import type { Fuente } from '../../api/useDato'
import { SegunDato, NoSeSabe } from '../ui'
import { plata } from '../plata/banco'
import { ComoSeCalcula } from '../plata/campos'
import type { PorProductoData } from '../rentabilidad/helpers'
import { fmt, fmtTasa } from '../rentabilidad/helpers'
import type { Piso } from './tipos'

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
  piso, productos, onCargarComision, children,
}: {
  piso: Fuente<Piso>
  productos: Fuente<PorProductoData>
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
                nota="Lo que costó lo que se vendió." />
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
          dato={productos.dato}
          cargando={<p className="text-sm text-warm-400">Comparando precios de compra…</p>}
          falla={m => (
            <NoSeSabe onReintentar={productos.recargar}
              mensaje={`${m} — no se sabe qué insumos subieron de precio. Que no aparezca ninguno `
                + 'no quiere decir que no haya subido nada.'} />
          )}
          listo={d => {
            // `alertas_costo` es OPCIONAL en la respuesta. `undefined` no es una
            // lista vacía: es un backend que no mandó el campo, y afirmar «no
            // subió nada» sobre eso sería el verde de siempre sobre una
            // medición que no corrió.
            if (d.alertas_costo === undefined) return (
              <p className="text-xs text-warm-500 leading-relaxed">
                Esta versión del backend no está mandando la comparación de precios de compra, así
                que no se sabe qué subió.
              </p>
            )
            if (d.alertas_costo.length === 0) return (
              <p className="text-xs text-warm-600 leading-relaxed">
                Ningún insumo subió de precio respecto de lo que se está usando para costear.
              </p>
            )
            return (
              <div className="space-y-2">
                {d.alertas_costo.slice(0, 5).map(a => (
                  <div key={a.insumo_id} className="flex items-start gap-2">
                    <TrendingUp size={14} className="shrink-0 mt-0.5 text-danger-600" />
                    <div className="min-w-0 flex-1">
                      <p className="text-xs font-semibold text-warm-700 leading-snug">
                        {a.nombre}{' '}
                        <span className="font-mono tabular-nums font-normal text-warm-500">
                          {fmt(a.costo_usado)} → {fmt(a.costo_ultimo)}
                        </span>{' '}
                        <span className="text-danger-700 font-bold">
                          (+{Math.round(a.pct_suba)}%)
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
                    </div>
                  </div>
                ))}
                <p className="text-[11px] text-warm-400 leading-relaxed">
                  Cada uno de estos sube la mercadería del renglón de arriba, y con ella el piso de
                  venta del día. Recuperar el precio viejo lo baja.
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
