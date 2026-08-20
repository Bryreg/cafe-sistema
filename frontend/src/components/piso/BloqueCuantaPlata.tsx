import { ReactNode, useMemo, useState } from 'react'
import { HandCoins, Landmark, Store } from 'lucide-react'
import { Dato, ambos, mapDato } from '../../api/dato'
import type { Fuente } from '../../api/useDato'
import { SegunDato, NoSeSabe } from '../ui'
import { fechaCorta, plata } from '../plata/banco'
import { Agenda, CajaHoy, Flujo, ORIGEN_CAJA, Tienda } from '../plata/tipos'
import { ComoSeCalcula } from '../plata/campos'
import FormRecogida from '../plata/FormRecogida'

// ═════════════════════════════════════════════════════════════════════════════
// 3 · CUÁNTA PLATA HAY
// ═════════════════════════════════════════════════════════════════════════════
// Tres números arriba —lo que hay, lo que ya está debido, lo que queda libre— y
// abajo el desglose de dónde sale cada peso.
//
// ── «QUEDA LIBRE» NECESITA LOS DOS LADOS ─────────────────────────────────
// Es una RESTA entre dos fetches que se caen por separado. Con `ambos`, la
// falla de cualquiera gana sobre el cargando del otro: no hay forma de restar
// una deuda que no volvió y publicar el resultado como plata disponible. Ese
// número, hacia el lado optimista, es el que hace gastar plata comprometida.
//
// ── LA PLATA VIVE EN TRES LUGARES, NO EN DOS ─────────────────────────────
// Hasta julio eran el cajón y el banco, y el sistema los conocía a los dos: la
// barista vendía en efectivo y ella misma iba a consignar. Desde agosto el
// DUEÑO pasa y recoge, le paga a proveedores en efectivo —plata que nunca toca
// el banco— y consigna el resto. El tercer lugar es SU MANO.
//
// ── UNA BOLSA QUE NUNCA SE REGISTRÓ DICE «SIN REGISTRAR», NUNCA $0 ───────
// `efectivo_en_mano === null` significa que el bucket no existe: no hay ninguna
// recogida, así que no hay desde cuándo contar. Un cero ahí AFIRMA que no hay
// plata, y no es lo mismo que no saber. Y cuando ese bucket falta, el total de
// arriba está incompleto por una cantidad desconocida — la línea lo dice ahí
// mismo, porque el backend manda `efectivo_en_mano_incluido` justamente para
// que la pantalla no tenga que deducirlo.

function Cifra({ valor, apagado = false, rojo = false, grande = false }: {
  valor: ReactNode; apagado?: boolean; rojo?: boolean; grande?: boolean
}) {
  return (
    <p className={`font-bold font-mono tabular-nums leading-tight mt-0.5 ${
      grande ? 'text-2xl' : 'text-xl'} ${
      apagado ? 'text-warm-400' : rojo ? 'text-danger-700' : 'text-warm-700'}`}>
      {valor}
    </p>
  )
}

const Nota = ({ children }: { children: ReactNode }) => (
  <p className="text-[11px] text-warm-500 leading-snug">{children}</p>
)

const Rotulo = ({ children }: { children: ReactNode }) => (
  <p className="text-[10px] font-bold uppercase tracking-wide text-warm-500 flex items-center gap-1">
    {children}
  </p>
)

export default function BloqueCuantaPlata({
  flujo, agenda, tiendas, hoy, onVerDondeEsta, onVerLaLista,
}: {
  flujo: Fuente<Flujo>
  agenda: Fuente<Agenda>
  /** Para el select de la fila de recogida: de qué sede se recogió la plata. */
  tiendas: Fuente<Tienda[]>
  hoy: string
  onVerDondeEsta: () => void
  onVerLaLista: () => void
}) {
  /** Sube cuando el tile «en tu mano» invita a registrar la primera recogida. */
  const [pedidoRecogida, setPedidoRecogida] = useState(0)

  // El total sale del backend (`caja_hoy.total`), no de sumar acá: con filtro de
  // sede el banco no entra, y esa decisión ya está tomada allá.
  const caja = useMemo<Dato<CajaHoy>>(() => mapDato(flujo.dato, f => f.caja_hoy), [flujo.dato])

  /** Lo que queda libre. Los DOS lados o ninguno. */
  const libre = useMemo(
    () => mapDato(ambos(caja, agenda.dato),
      ([c, a]) => ({ valor: c.total - a.totales.monto, debido: a.totales.monto })),
    [caja, agenda.dato])

  return (
    <section className="rounded-2xl border border-warm-200 bg-white overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-3 border-b border-warm-100">
        <h2 className="text-sm font-bold text-warm-700">Cuánta plata hay</h2>
      </div>

      {/* ── Los tres números de la decisión ────────────────────────────────── */}
      <div className="grid grid-cols-1 sm:grid-cols-3 divide-y sm:divide-y-0 sm:divide-x divide-warm-100
                      border-b border-warm-100">
        <div className="px-4 py-3">
          <Rotulo>Hay ahora</Rotulo>
          <SegunDato
            dato={caja}
            cargando={<Cifra valor="…" apagado grande />}
            falla={m => (<>
              <Cifra valor="—" apagado grande />
              <NoSeSabe onReintentar={flujo.recargar}
                mensaje={`${m} — no se sabe cuánta plata hay.`} />
            </>)}
            listo={c => (<>
              <Cifra valor={plata(c.total)} rojo={c.total < 0} grande />
              <button onClick={onVerDondeEsta}
                className="text-[11px] font-bold text-forest underline decoration-dotted">
                ver dónde está
              </button>
            </>)} />
        </div>

        <div className="px-4 py-3">
          <Rotulo>Ya está debido</Rotulo>
          <SegunDato
            dato={agenda.dato}
            cargando={<Cifra valor="…" apagado grande />}
            falla={m => (<>
              <Cifra valor="—" apagado grande />
              <NoSeSabe onReintentar={agenda.recargar}
                mensaje={`${m} — no se sabe cuánto se debe. Que no haya cifra no quiere decir `
                  + 'que no se deba nada.'} />
            </>)}
            listo={a => (<>
              <Cifra valor={plata(a.totales.monto)} grande />
              <button onClick={onVerLaLista}
                className="text-[11px] font-bold text-forest underline decoration-dotted">
                ver la lista
              </button>
              {/* La plata sin fecha NO está adentro de ese total (el backend la
                  manda aparte). Callarlo dejaría un total que se lee como «todo
                  lo que se debe» siendo menos. */}
              {a.totales.sin_fecha > 0 && (
                <Nota>
                  Y hay {plata(a.totales.sin_fecha)} más sin fecha de pago, que no entran
                  a este total ni a ninguna proyección.
                </Nota>
              )}
            </>)} />
        </div>

        <div className="px-4 py-3">
          <Rotulo>Queda libre</Rotulo>
          <SegunDato
            dato={libre}
            cargando={<Cifra valor="…" apagado grande />}
            falla={m => (<>
              <Cifra valor="—" apagado grande />
              <NoSeSabe
                onReintentar={() => { flujo.recargar(); agenda.recargar() }}
                mensaje={`${m} — para restar hacen falta los dos lados: la plata que hay y la `
                  + 'que se debe. Con uno solo, el resultado sobraría siempre para el mismo lado.'} />
            </>)}
            listo={l => (<>
              <Cifra valor={plata(l.valor)} rojo={l.valor < 0} grande />
              <Nota>
                {l.valor < 0
                  ? 'Se debe más de lo que hay. La diferencia tiene que salir de la venta de los días que quedan.'
                  : 'Lo que hay menos lo que ya está debido con fecha.'}
              </Nota>
            </>)} />
        </div>
      </div>

      {/* ── De dónde sale cada peso ────────────────────────────────────────── */}
      <div className="grid grid-cols-1 sm:grid-cols-3 divide-y sm:divide-y-0 sm:divide-x divide-warm-100">
        <div className="px-4 py-3">
          <Rotulo><Store size={11} /> En las registradoras</Rotulo>
          <SegunDato
            dato={caja}
            cargando={<Cifra valor="…" apagado />}
            falla={() => (<>
              <Cifra valor="—" apagado />
              {/* El desglose por sede desaparecía entero y sin decir nada: dos
                  sedes que no se muestran se leen como dos cajones vacíos. */}
              <Nota>No se pudo leer el efectivo de las registradoras.</Nota>
            </>)}
            listo={c => (<>
              <Cifra valor={plata(c.efectivo_registradora)} rojo={c.efectivo_registradora < 0} />
              <div className="space-y-0.5 mt-0.5">
                {c.por_tienda.map(t => (
                  <div key={t.tienda_id} className="flex items-center justify-between gap-2 text-[11px]">
                    <span className="text-warm-500 truncate">{t.tienda_nombre}</span>
                    <span className={`font-mono tabular-nums shrink-0 ${
                      t.efectivo < 0 ? 'text-danger-700 font-bold' : 'text-warm-600'}`}>
                      {plata(t.efectivo)}{' '}
                      <span className="text-warm-400">· {ORIGEN_CAJA[t.origen] ?? t.origen}</span>
                    </span>
                  </div>
                ))}
              </div>
              {/* Un cajón en negativo es físicamente imposible: no es un saldo,
                  es un dato mal cargado (casi siempre una recogida por más plata
                  de la que había). Sin este aviso se pinta del mismo gris que un
                  cajón sano y no hay cómo distinguirlos. */}
              {c.efectivo_registradora < 0 && (
                <Nota>
                  <b>Un cajón no puede tener menos de cero.</b> Revisá si registraste una recogida
                  por más plata de la que había.
                </Nota>
              )}
            </>)} />
        </div>

        <div className="px-4 py-3">
          <Rotulo><HandCoins size={11} /> En tu mano</Rotulo>
          <SegunDato
            dato={caja}
            cargando={<Cifra valor="…" apagado />}
            falla={() => (<>
              <Cifra valor="—" apagado />
              <Nota>No se pudo leer el efectivo que recogiste de las sedes.</Nota>
            </>)}
            listo={c => c.efectivo_en_mano === null ? (<>
              {/* EL BUCKET NO EXISTE — NO ES CERO. Nunca se registró una
                  recogida, así que no hay desde cuándo contar. Un «$0» acá
                  afirmaría que no lleva plata encima, hacia el lado
                  tranquilizador. Va el «—» y la invitación a llenarlo. */}
              <Cifra valor="sin registrar" apagado />
              <Nota>
                Todavía no registraste ninguna recogida, así que <b>no se sabe</b> cuánta plata
                tenés encima. No es cero.{' '}
                <button onClick={() => setPedidoRecogida(n => n + 1)}
                  className="font-bold text-forest underline decoration-dotted">
                  Registrá la primera
                </button>
              </Nota>
            </>) : (<>
              <Cifra valor={plata(c.efectivo_en_mano)} rojo={c.efectivo_en_mano < 0} />
              <Nota>
                {c.efectivo_en_mano < 0
                  ? <>Salió más de lo que aparece recogido: falta registrar alguna recogida.</>
                  : c.efectivo_en_mano_desde
                    ? <>Desde el {fechaCorta(c.efectivo_en_mano_desde)}, menos lo que pagaste en
                        efectivo y lo que consignaste vos.</>
                    : <>Lo que recogiste, menos lo que pagaste en efectivo y lo que
                        consignaste vos.</>}
              </Nota>
            </>)} />
        </div>

        <div className="px-4 py-3">
          <Rotulo><Landmark size={11} /> En el banco</Rotulo>
          <SegunDato
            dato={caja}
            cargando={<Cifra valor="…" apagado />}
            falla={() => (<>
              <Cifra valor="—" apagado />
              <Nota>No se pudo leer el saldo del banco.</Nota>
            </>)}
            listo={c => (<>
              <Cifra valor={plata(c.saldo_banco)} rojo={c.saldo_banco < 0} />
              <Nota>
                {c.saldo_banco_fecha
                  ? <>Extracto del {fechaCorta(c.saldo_banco_fecha)}
                      {c.saldo_banco_origen === 'libro'
                        ? ', más lo que tecleaste después.'
                        : ' — la cadena no encadena, así que los movimientos que tecleaste '
                          + 'después no se le están sumando.'}</>
                  : 'Todavía no cargaste ningún extracto.'}
              </Nota>
              {/* Qué entró al total lo dice el BACKEND. Escribir la condición
                  acá daría lo mismo hoy, y esa es la trampa: el día que allá
                  cambie, este rótulo seguiría enumerando un sumando que ya no
                  se suma. */}
              {!c.efectivo_en_mano_incluido && (
                <Nota>
                  <b>Ojo:</b> la plata de tu mano no entró al total de arriba, así que «hay ahora»
                  es <b>menos</b> de lo que de verdad hay.
                </Nota>
              )}
              {!c.saldo_banco_incluido && (
                <Nota>
                  Filtrando por sede el banco no suma: la cuenta es de la empresa, no de la sede.
                </Nota>
              )}
            </>)} />
        </div>
      </div>

      {/* La fila que llena el bucket de la mano, PEGADA a los tres números: es la
          acción que los mueve, y cada click de distancia es un día más de cajón
          mintiendo. Refresca `flujo` y nada más: una recogida no toca el banco,
          ni la agenda, ni el resultado del mes — solo mueve plata de un bucket
          al otro, y los dos viven adentro de ese mismo recurso. */}
      <FormRecogida tiendas={tiendas} hoy={hoy}
        pedidoFoco={pedidoRecogida} onGuardado={flujo.recargar} />

      <ComoSeCalcula titulo="¿De dónde sale cada uno de estos números?">
        <p>
          El sistema <b>no puede saber</b> cuánta plata hay en la cuenta: registra las
          consignaciones que hacen las baristas, pero nunca ve el extracto. Por eso el saldo
          arranca del número que copiás arriba y de ahí para adelante el libro suma lo que entra
          y resta lo que sale, movimiento por movimiento. Que el libro esté al día <b>no</b> es
          haberlo comparado contra el banco: lo que nunca tecleaste —un débito automático, una
          comisión— no está en ninguna parte.
        </p>
        <p>
          «En las registradoras» es efectivo físico y sale de cada sede por separado: un turno
          abierto es el conteo vivo, «conteo del cierre» es el de la última vez que cerraron y
          «último cuadre» es el respaldo cuando cerraron sin contar.
        </p>
        <p>
          <b>«En tu mano»</b> es la plata que recogiste de las sedes y que todavía no salió. Cada
          recogida <b>baja el cajón</b> de esa sede y <b>sube tu efectivo en mano</b>: la plata no
          desaparece, cambia de lugar. De ahí se descuenta solo lo que pagás en efectivo y las
          consignaciones que hacés <b>vos</b> — las de las baristas no, porque esas ya salieron
          del cajón y restarlas de nuevo sería restar la misma plata dos veces.
        </p>
        <p>
          «Ya está debido» es todo lo que tiene fecha de pago, lo vencido incluido. La plata sin
          fecha se cuenta aparte a propósito: no entra a ninguna proyección, así que mientras esté
          así la caja se ve mejor de lo que está.
        </p>
      </ComoSeCalcula>
    </section>
  )
}
