import { ReactNode, useMemo, useState } from 'react'
import { AlertTriangle, Plus } from 'lucide-react'
import { Dato, mapDato } from '../../api/dato'
import type { Fuente } from '../../api/useDato'
import { SegunDato, NoSeSabe } from '../ui'
import { plata } from '../plata/banco'
import { Bandeja, Listado } from '../plata/tipos'
import { CLS_BOTON_SUAVE } from '../plata/campos'
import type { Piso } from './tipos'
import LaNominaAbierta from './LaNominaAbierta'

// ═════════════════════════════════════════════════════════════════════════════
// 6 · LO QUE SUBE EL PISO — lo de arriba de la división
// ═════════════════════════════════════════════════════════════════════════════
// El numerador del piso, abierto. No es «los gastos del mes»: es exactamente la
// plata que hay que pagar venda lo que venda, que es la que se divide por el
// margen para sacar la meta de venta.
//
// ── LA VENTANA ES EL MES COMPLETO ────────────────────────────────────────
// Y no «del 1 a hoy». El arriendo y la nómina se devengan a fin de mes: con la
// ventana recortada, el piso del día 2 salía ridículamente bajo — justo el día
// en que más se mira. El backend ya manda `costos_fijos.desde/hasta` para que
// esto se pueda decir en pantalla en vez de suponerlo.
//
// ── «SOLO ESTE MES» TAMBIÉN CUENTA ───────────────────────────────────────
// El arreglo del molino no se repite, pero este mes hay que pagarlo: entra al
// piso igual. Separarlos sirve para saber cuánto del piso es estructural, no
// para descontar el otro.
//
// ── LO SIN CLASIFICAR NO ENTRA AL PISO, Y ESO ES UNA MALA NOTICIA ────────
// Plata que ya salió de la caja y que el piso no está mirando: mientras esté
// así, el piso es MÁS BAJO que el real. Por eso el renglón es ámbar y no gris.

interface Split { fijos: number; unaVez: number; nFijos: number; nUnaVez: number }

/**
 * Cuánto del costo del mes se repite y cuánto es de una vez.
 *
 * Se decide por `plantilla_id`, que es la llave de la serie mensual que escribe
 * «Repetir». No se adivina por el nombre de la categoría: el arriendo de una
 * sede nueva cargado a mano todavía no tiene serie, y llamarlo «todos los
 * meses» sería afirmar una recurrencia que nadie declaró.
 *
 * Solo mira las obligaciones DEVENGADAS EN EL MES DEL PISO. Las del mes que
 * viene viajan en la misma lectura (para saber qué falta armar) y contarlas acá
 * duplicaría el arriendo.
 */
function partir(l: Listado, anio: number, mes: number): Split {
  const clave = `${anio}-${String(mes).padStart(2, '0')}`
  const delMes = l.obligaciones.filter(
    o => o.estado !== 'anulada' && o.fecha_devengo.slice(0, 7) === clave)
  const repite = delMes.filter(o => o.plantilla_id !== null)
  const unaVez = delMes.filter(o => o.plantilla_id === null)
  return {
    fijos: repite.reduce((s, o) => s + o.monto, 0),
    unaVez: unaVez.reduce((s, o) => s + o.monto, 0),
    nFijos: repite.length,
    nUnaVez: unaVez.length,
  }
}

export default function BloqueSubeElPiso({
  piso, obligaciones, egresos, anio, mes, onClasificar, elGestor, id,
}: {
  piso: Fuente<Piso>
  /** Las obligaciones del mes del piso Y del que viene, en una sola lectura. */
  obligaciones: Fuente<Listado>
  egresos: Fuente<Bandeja>
  anio: number
  mes: number
  /** Al detalle del mes, donde vive el adoptador de egresos sueltos. */
  onClasificar: () => void
  /** El gestor de obligaciones entero, montado plegado. */
  elGestor: ReactNode
  id?: string
}) {
  const [gestor, setGestor] = useState(false)

  const split = useMemo<Dato<Split>>(
    () => mapDato(obligaciones.dato, l => partir(l, anio, mes)), [obligaciones.dato, anio, mes])

  return (
    <section id={id} className="rounded-2xl border border-warm-200 bg-white overflow-hidden">
      <div className="px-4 py-3 border-b border-warm-100">
        <h2 className="text-sm font-bold text-warm-700">Lo que sube el piso</h2>
        <p className="text-[11px] text-warm-500 leading-snug">
          Lo de arriba de la división: lo que hay que pagar venda lo que venda.
        </p>
      </div>

      {/* ── El total y las categorías, tal como los cuenta el piso ─────────
          Sale de `/costos/piso`, no de una suma propia: es LITERALMENTE el
          numerador que se usó para calcular el número de arriba de la página.
          Sumar las obligaciones acá con otro criterio daría un total que no
          cierra contra el piso, y ahí no habría forma de saber cuál miente. */}
      <SegunDato
        dato={piso.dato}
        cargando={<p className="px-4 py-6 text-sm text-warm-400">Leyendo los costos del mes…</p>}
        falla={m => (
          <div className="p-3">
            <NoSeSabe bloque onReintentar={piso.recargar}
              mensaje={`${m} — no se sabe qué costos fijos tiene el mes. Que no aparezca la lista `
                + 'no quiere decir que no haya nada cargado.'} />
          </div>
        )}
        listo={p => {
          const cf = p.costos_fijos
          return (<>
            <div className="flex items-baseline gap-2 px-4 py-2.5 bg-warm-50 border-b border-warm-100">
              <p className="text-[11px] font-bold uppercase tracking-wide text-warm-600 flex-1">
                Costos fijos del mes <span className="opacity-60">({cf.n})</span>
              </p>
              <p className="font-mono font-bold text-sm tabular-nums text-warm-700 shrink-0">
                {plata(cf.total)}
              </p>
            </div>

            {cf.por_categoria.length === 0 ? (
              <p className="px-4 py-5 text-sm text-warm-500 leading-relaxed">
                No hay ningún costo fijo cargado en este mes. Sin el arriendo y la nómina, el piso
                de venta de arriba no se puede calcular — y cualquier número que apareciera sería
                más bajo que el real.
              </p>
            ) : (
              <div className="divide-y divide-warm-100">
                {cf.por_categoria.map(c => (
                  <div key={c.clave} className="flex items-baseline gap-2 px-4 py-2">
                    <p className="text-sm text-warm-700 flex-1 min-w-0 truncate">
                      {c.nombre}{' '}
                      <span className="text-[11px] text-warm-400">
                        ({c.n} {c.n === 1 ? 'cuenta' : 'cuentas'})
                      </span>
                    </p>
                    <p className="font-mono text-sm tabular-nums text-warm-600 shrink-0">
                      {plata(c.monto)}
                    </p>
                  </div>
                ))}
              </div>
            )}

            <p className="px-4 py-2 text-[11px] text-warm-400 leading-relaxed border-t border-warm-100">
              Del {cf.desde} al {cf.hasta}: <b>el mes entero</b>, no lo que va corrido. El arriendo
              y la nómina se deben completos aunque estemos a mitad de mes, y por eso el piso de
              arriba no baja a principios de mes.
            </p>

            {/* La nómina sin contrato es plata laboral que el consolidado NO
                cuenta: decirlo acá es lo que impide que el total pase por
                completo. */}
            {cf.nomina_sin_contrato > 0 && (
              <p className="px-4 pb-2 text-[11px] text-gold-700 leading-relaxed">
                Hay {plata(cf.nomina_sin_contrato)} de nómina de gente sin contrato cargado: no
                entra a este total, así que el piso está <b>por debajo</b> del real.
              </p>
            )}
          </>)
        }} />

      {/* ── Cuánto se repite y cuánto es de una vez ───────────────────────── */}
      <SegunDato
        dato={split}
        cargando={null}
        falla={m => (
          <div className="px-3 py-2 border-t border-warm-100">
            <NoSeSabe onReintentar={obligaciones.recargar}
              mensaje={`${m} — no se pudo separar lo que se repite todos los meses de lo que es `
                + 'solo de este mes. El total de arriba no depende de esta lectura.'} />
          </div>
        )}
        listo={s => (
          <div className="grid grid-cols-2 divide-x divide-warm-100 border-t border-warm-100">
            <div className="px-4 py-2.5">
              <p className="text-[10px] font-bold uppercase tracking-wide text-warm-500">
                Todos los meses
              </p>
              <p className="text-base font-bold font-mono tabular-nums text-warm-700">
                {plata(s.fijos)}
              </p>
              <p className="text-[11px] text-warm-400">
                {s.nFijos} {s.nFijos === 1 ? 'cuenta de la serie mensual' : 'cuentas de la serie mensual'}
              </p>
            </div>
            <div className="px-4 py-2.5">
              <p className="text-[10px] font-bold uppercase tracking-wide text-warm-500">
                Solo este mes
              </p>
              <p className="text-base font-bold font-mono tabular-nums text-warm-700">
                {plata(s.unaVez)}
              </p>
              <p className="text-[11px] text-warm-400 leading-snug">
                No se repite, pero este mes hay que pagarlo: <b>sí</b> cuenta en el piso.
              </p>
            </div>
          </div>
        )} />

      {/* ── Lo que salió de caja y el piso todavía no mira ────────────────── */}
      <SegunDato
        dato={egresos.dato}
        cargando={null}
        falla={m => (
          <div className="px-3 py-2 border-t border-warm-100">
            <NoSeSabe onReintentar={egresos.recargar}
              mensaje={`${m} — no se sabe si hay plata que salió de caja sin categoría. Que no `
                + 'aparezca el aviso no quiere decir que esté todo clasificado.'} />
          </div>
        )}
        listo={b => b.totales.n === 0 ? null : (
          <div className="flex items-start gap-2 px-4 py-2.5 border-t border-gold-200 bg-gold-50">
            <AlertTriangle size={15} className="shrink-0 mt-0.5 text-gold-700" />
            <div className="flex-1 min-w-0">
              <p className="text-xs font-bold text-gold-700 leading-snug">
                Sin clasificar: {plata(b.totales.monto)} — esta plata NO entra al piso
              </p>
              <p className="text-[11px] text-gold-700/80 leading-snug">
                Ya salió de la caja, pero como no tiene categoría el piso no la está mirando:
                mientras esté así, el piso de arriba es <b>más bajo</b> que el real.
              </p>
            </div>
            <button onClick={onClasificar}
              className="shrink-0 min-h-[46px] px-3 rounded-xl text-[11px] font-bold text-gold-700
                         hover:bg-gold-100">
              Clasificar {b.totales.n} →
            </button>
          </div>
        )} />

      {/* ── Las cuentas una por una ────────────────────────────────────────
          El gestor entero, plegado. Adentro vive TODO lo que se puede hacer con
          un costo fijo y que no vive en ningún otro lado de la página: cargar
          uno nuevo (el formulario está montado arriba de su lista), corregirlo,
          anularlo, anular un pago mal registrado, repetirlo al mes siguiente y
          los cuatro filtros — entre ellos «anuladas», que es el ÚNICO camino a
          una obligación dada de baja por error.

          Plegado y no borrado: nada de esto se toca todos los días, pero el día
          que hace falta no hay otra puerta.

          NO hay un segundo formulario de alta acá afuera. Tener dos altas para
          la misma tabla es cómo se termina con dos defaults distintos de
          categoría y dos criterios de devengo. El botón abre ESTE. */}
      <div className="border-t border-warm-100">
        <div className="px-4 py-2.5">
          <button onClick={() => setGestor(v => !v)}
            className={`${CLS_BOTON_SUAVE} flex items-center gap-1.5`}>
            <Plus size={14} />
            {gestor ? 'Cerrar las cuentas' : 'Cargar un costo · ver y corregir las cuentas'}
          </button>
        </div>
        {gestor && <div className="border-t border-warm-100">{elGestor}</div>}
      </div>

      <LaNominaAbierta anio={anio} mes={mes} id="la-nomina" />
    </section>
  )
}
