import { useState } from 'react'
import { Scale } from 'lucide-react'
import type { Fuente } from '../../api/useDato'
import { SegunDato, NoSeSabe } from '../ui'
import { plata } from '../plata/banco'
import type { EquilibrioSede, Piso } from './tipos'

// ═════════════════════════════════════════════════════════════════════════════
// EL PUNTO DE EQUILIBRIO — descriptivo, nunca un veredicto del día
// ═════════════════════════════════════════════════════════════════════════════
// Reemplaza al bloque de «El Piso» por decisión del dueño, con sus palabras:
// «no quiero manejar más el piso; solo quiero saber el punto de equilibrio
// para cada sede, pero que no me amarre las ventas a un número, que se venda
// lo que más se pueda».
//
// LA FÓRMULA SOBREVIVE ENTERA (get_piso: costos fijos / margen de
// contribución); lo que se retira es el INSTRUMENTO DIARIO. El piso era
// PRESCRIPTIVO —«hoy tenés que vender $2.340.000», un veredicto cada mañana, y
// con 61 de 212 días por debajo de $2M ese veredicto era rojo casi siempre; un
// número así ANCLA: si el equipo llega, afloja—. El equilibrio es DESCRIPTIVO:
// «el mes necesita $X; va en 62% y quedan 10 días». La misma información, sin
// sentencia. Por eso acá NO hay «piso de hoy», ni racha, ni «te falta vender
// hoy»: solo el mes, su avance y sus tres partes.
//
// ── LOS TRES NÚMEROS: POR SEDE SE EXPONE, NO SE PRORRATEA ────────────────
// Vida necesita $X para lo suyo, Palmetto $Y, y lo CORPORATIVO son $Z que las
// dos cubren entre las dos — pesa más que las dos juntas y no cuelga de
// ninguna. Si cada sede mirara solo lo suyo, las dos «pasarían» y el negocio
// igual perdería plata; repartirlo sería inventar. Con el mismo divisor, la
// suma de las tres partes ES el total del mes: se puede verificar a ojo.

const Rotulo = ({ children }: { children: React.ReactNode }) => (
  <p className="text-[10px] font-bold uppercase tracking-wide text-warm-400">
    {children}
  </p>
)

/** El avance como barra chiquita + texto. Descriptivo: sin colores de veredicto
 *  (un 40% a mitad de mes no es un fracaso, es un dato). */
function Avance({ pct }: { pct: number }) {
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 flex-1 rounded-full bg-warm-100 overflow-hidden">
        <div className="h-full rounded-full bg-forest"
          style={{ width: `${Math.max(0, Math.min(100, pct))}%` }} />
      </div>
      <span className="text-[11px] font-mono tabular-nums font-bold text-warm-600 shrink-0">
        {Math.round(pct)}%
      </span>
    </div>
  )
}

function FilaParte({ p, esCorporativo }: { p: EquilibrioSede; esCorporativo?: boolean }) {
  return (
    <div className="px-4 py-2.5">
      <div className="flex items-baseline justify-between gap-2">
        <p className="text-xs font-bold text-warm-700">
          {p.nombre}
          {esCorporativo && (
            <span className="ml-1.5 font-normal text-[10px] text-warm-400">
              lo cubren las dos entre las dos
            </span>
          )}
        </p>
        <p className="text-sm font-mono font-bold tabular-nums text-warm-700 shrink-0">
          {p.venta_necesaria != null ? plata(p.venta_necesaria) : plata(p.costos_fijos)}
          {p.venta_necesaria == null && (
            <span className="ml-1 text-[10px] font-sans font-normal text-warm-400">en costos</span>
          )}
        </p>
      </div>
      {/* El corporativo no vende: su avance NO EXISTE, y no se dibuja una barra
          en cero que se leería como «no avanzó nada». */}
      {p.avance_pct != null && <Avance pct={p.avance_pct} />}
    </div>
  )
}

export default function BloqueEquilibrio({ piso, onCargarCosto }: {
  piso: Fuente<Piso>
  /** Sin costos fijos cargados no hay equilibrio que calcular: el hueco lleva
   *  al lugar donde se cargan. */
  onCargarCosto: () => void
}) {
  const [abierto, setAbierto] = useState(false)

  return (
    <section className="rounded-2xl border border-warm-200 bg-white overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-3 border-b border-warm-100">
        <Scale size={15} className="text-forest" />
        <h2 className="text-sm font-bold text-warm-700">El punto de equilibrio</h2>
        <span className="ml-auto text-[10px] text-warm-400">informa, no sentencia</span>
      </div>

      <SegunDato
        dato={piso.dato}
        cargando={<p className="px-4 py-6 text-center text-sm text-warm-400 animate-pulse">Calculando…</p>}
        falla={m => (
          <div className="px-4 py-4">
            <NoSeSabe bloque onReintentar={piso.recargar}
              mensaje={`${m} — no se sabe cuánto necesita el mes para cubrir sus costos.`} />
          </div>
        )}
        listo={d => {
          // ── Puerta 1: sin costos fijos no hay equilibrio, y el hueco lo dice ──
          if (d.puerta === 'sin_costos_fijos') {
            return (
              <div className="px-4 py-4 space-y-2">
                <p className="text-sm text-warm-600 leading-relaxed">
                  Todavía no hay <b>costos fijos cargados</b> en {mesDe(d)}: sin el arriendo, la
                  nómina y los servicios no se puede decir cuánto necesita el mes.
                </p>
                <button onClick={onCargarCosto}
                  className="min-h-[42px] px-4 rounded-xl bg-forest text-white text-xs font-bold">
                  Cargar el arriendo →
                </button>
              </div>
            )
          }

          // ── Puerta 3: margen no positivo es un VEREDICTO del negocio, no un
          //    dato que falta — y se dice plano, como siempre. ──
          if (d.puerta === 'margen_no_positivo') {
            return (
              <p className="px-4 py-4 text-sm text-danger-700 font-semibold leading-relaxed">
                Con estos costos, cada venta pierde plata: el margen de contribución del mes es
                {' '}{d.margen_contribucion != null ? `${Math.round(d.margen_contribucion * 100)}%` : 'negativo'}.
                No hay venta que cubra los costos fijos — lo que hay que mover es el costo, no la venta.
              </p>
            )
          }

          const conNumero = d.piso_mes != null
          const pct = conNumero && d.piso_mes! > 0
            ? (d.ventas_mes / d.piso_mes!) * 100 : null
          const retenciones = d.sesgos.find(s => s.clave === 'retenciones_fuera_del_gasto')

          return (<>
            {/* ── El mes, en una frase descriptiva ──────────────────────────── */}
            <div className="px-4 py-3 space-y-1.5 border-b border-warm-100">
              {conNumero ? (<>
                <Rotulo>Para cubrir sus costos, {mesDe(d)} necesita</Rotulo>
                <p className="text-2xl font-mono font-bold tabular-nums text-warm-700">
                  {plata(d.piso_mes!)}
                  <span className="ml-2 text-xs font-sans font-normal text-warm-400">
                    en ventas, al menos
                  </span>
                </p>
                {pct != null && (<>
                  <Avance pct={pct} />
                  <p className="text-[11px] text-warm-500">
                    Van {plata(d.ventas_mes)}
                    {d.cubierto
                      ? <> — el mes ya cubre sus costos{d.falta != null && d.falta < 0 && (
                        <>, con {plata(-d.falta)} por encima</>)}.</>
                      : <> · quedan {d.dias.quedan} {d.dias.quedan === 1 ? 'día' : 'días'} de
                        apertura{d.razones?.de === 'mes_anterior' && (
                          <> · margen medido con el mes anterior</>
                        )}.</>}
                  </p>
                </>)}
              </>) : (<>
                {/* Puerta 2 con costos fijos: la mitad que SÍ se sabe, en plata. */}
                <Rotulo>Los costos fijos de {mesDe(d)}</Rotulo>
                <p className="text-2xl font-mono font-bold tabular-nums text-warm-700">
                  {plata(d.costos_fijos.total)}
                </p>
                <p className="text-[11px] text-warm-500 leading-relaxed">
                  Todavía no hay venta medida que dé el margen del mes, así que no se puede
                  traducir a venta necesaria — la plata que hay que cubrir es esta.
                </p>
              </>)}
            </div>

            {/* ── Los tres números ──────────────────────────────────────────── */}
            {d.por_sede ? (
              <div className="divide-y divide-warm-100 border-b border-warm-100">
                {d.por_sede.sedes.map(s => <FilaParte key={s.nombre} p={s} />)}
                <FilaParte p={d.por_sede.corporativo} esCorporativo />
              </div>
            ) : (
              // AUSENTE, no vacío: un servidor de antes del desglose no manda
              // `por_sede`, y acá no se inventan tres ceros.
              <p className="px-4 py-2 border-b border-warm-100 text-[11px] text-warm-400">
                Esta versión del servidor no desglosa el equilibrio por sede — recargá la página
                en unos minutos.
              </p>
            )}

            {/* ── La banda del contador ─────────────────────────────────────── */}
            {retenciones?.activo && (
              <p className="px-4 py-2 border-b border-warm-100 bg-gold-50 text-[11px] text-gold-700 leading-relaxed">
                {/* El monto solo se escribe si vino como número: un `?? 0` acá
                    pintaría «$0 fuera del costo», que afirma lo que no se midió
                    (regla 1 del README de ui/). */}
                Retefuente y reteica
                {typeof retenciones.detalle?.monto_mes === 'number' && (
                  <> ({plata(retenciones.detalle.monto_mes)} este mes)</>
                )} están
                <b> fuera del costo del mes</b> — la clasificación vigente, pendiente de confirmar
                con el contador. Si él dice que son gasto, el equilibrio sube
                {typeof retenciones.detalle?.subiria_piso === 'number'
                  ? <> {plata(retenciones.detalle.subiria_piso)}</>
                  : <> esa plata dividida por el margen</>}.
              </p>
            )}

            {/* ── De dónde sale el número, plegado ──────────────────────────── */}
            <button onClick={() => setAbierto(a => !a)} aria-expanded={abierto}
              className="w-full px-4 py-2.5 text-left text-[11px] font-bold text-forest hover:bg-warm-50">
              {abierto ? '▾' : '▸'} De dónde sale este número
            </button>
            {abierto && (
              <div className="px-4 pb-3 space-y-1.5 text-[11px] text-warm-600 leading-relaxed">
                <p>
                  <b>Arriba:</b> los costos fijos del mes completo, {plata(d.costos_fijos.total)}
                  {' '}({d.costos_fijos.n} cuentas
                  {d.costos_fijos.nomina_calculada != null && d.costos_fijos.nomina_calculada > 0 && (
                    <> + nómina calculada {plata(d.costos_fijos.nomina_calculada)}</>
                  )}).
                </p>
                {d.razones && d.margen_contribucion != null && (
                  <p>
                    <b>Abajo:</b> de cada $100 vendidos quedan
                    {' '}${Math.round(d.margen_contribucion * 100)} después del impoconsumo
                    (${Math.round(d.razones.impoconsumo * 100)}), la mercadería
                    (${Math.round(d.razones.cogs * 100)}) y la comisión del datáfono
                    (${Math.round(d.razones.comision * 100)})
                    {d.razones.de === 'mes_anterior' && <> — medidos con el mes anterior</>}.
                  </p>
                )}
                <p>
                  La división de esos dos es la venta que cubre los costos. Es el mismo cálculo
                  del piso de siempre; lo que se retiró es el veredicto diario.
                </p>
              </div>
            )}
          </>)
        }}
      />
    </section>
  )
}

const MESES_LARGOS = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio',
  'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']

const mesDe = (d: Piso) => MESES_LARGOS[d.mes - 1] ?? `el mes ${d.mes}`
