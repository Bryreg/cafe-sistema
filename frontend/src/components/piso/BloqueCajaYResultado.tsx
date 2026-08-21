import { Landmark, Scale } from 'lucide-react'
import { Dato } from '../../api/dato'
import type { Fuente } from '../../api/useDato'
import { SegunDato, NoSeSabe } from '../ui'
import { plata } from '../plata/banco'
import type { LibroMes } from '../plata/banco'
import type { RentabilidadData } from '../rentabilidad/helpers'

// ═════════════════════════════════════════════════════════════════════════════
// EL MES EN DOS NÚMEROS — la caja y el resultado, rotulados
// ═════════════════════════════════════════════════════════════════════════════
// El dueño pidió «si hay pérdida o ganancia a fin de mes». Su hoja no muestra
// eso: muestra cuánto subió o bajó el banco. En julio el saldo subió $2.378.004
// y eso NO fue la ganancia — adentro estaban la prima de la nómina, los gastos
// de su casa y mercadería comprada sin vender.
//
// Por eso van LOS DOS, uno al lado del otro y cada uno con su nombre:
//   LA CAJA      entró − salió = cuánto se movió el banco (el libro de arriba)
//   EL RESULTADO venta neta − compras − gastos = si el café ganó o perdió
//
// QUE NO COINCIDAN ES LO NORMAL, y el renglón del pie lo dice: si esta pantalla
// los fundiera en uno, volvería el error de leer el banco como la ganancia.

const Celda = ({ rotulo, valor, rojo }: {
  rotulo: string; valor: string; rojo?: boolean
}) => (
  <div className="flex items-baseline justify-between gap-2 text-xs">
    <span className="text-warm-500">{rotulo}</span>
    <span className={`font-mono font-bold tabular-nums ${
      rojo ? 'text-danger-700' : 'text-warm-700'}`}>{valor}</span>
  </div>
)

export default function BloqueCajaYResultado({ libro, rentMes, onRecargarLibro }: {
  /** El libro del MES EN CURSO (la misma lectura del bloque de arriba). */
  libro: Dato<LibroMes>
  /** El P&L del mes, del 1 a hoy. */
  rentMes: Fuente<RentabilidadData>
  onRecargarLibro: () => void
}) {
  return (
    <section className="rounded-2xl border border-warm-200 bg-white overflow-hidden">
      <div className="px-4 py-3 border-b border-warm-100">
        <h2 className="text-sm font-bold text-warm-700">El mes, en dos números</h2>
        <p className="text-[11px] text-warm-400">
          la plata que se movió y si el café ganó — no son lo mismo, y por eso van los dos
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 divide-y sm:divide-y-0 sm:divide-x divide-warm-100">
        {/* ── LA CAJA ─────────────────────────────────────────────────────── */}
        <div className="px-4 py-3 space-y-1.5">
          <p className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wide text-warm-500">
            <Landmark size={12} /> La caja (el banco)
          </p>
          <SegunDato
            dato={libro}
            cargando={<p className="text-[11px] text-warm-400 animate-pulse">Cargando…</p>}
            falla={m => <NoSeSabe onReintentar={onRecargarLibro}
              mensaje={`${m} — no se sabe cuánta plata se movió.`} />}
            listo={l => (<>
              <Celda rotulo="Entró" valor={`+ ${plata(l.totales.entradas)}`} />
              <Celda rotulo="Salió" valor={`− ${plata(l.totales.salidas)}`} />
              {/* null = el último día no tiene saldo: no se sabe en cuánto va,
                  y no se escribe un cierre inventado. */}
              {l.totales.final != null ? (
                <div className="pt-1 border-t border-warm-100">
                  <Celda rotulo="El saldo va en" valor={plata(l.totales.final)}
                    rojo={l.totales.final < 0} />
                </div>
              ) : (
                <p className="text-[11px] text-warm-400 pt-1 border-t border-warm-100">
                  Sin saldo del extracto no se sabe en cuánto va la cuenta.
                </p>
              )}
            </>)}
          />
        </div>

        {/* ── EL RESULTADO ────────────────────────────────────────────────── */}
        <div className="px-4 py-3 space-y-1.5">
          <p className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wide text-warm-500">
            <Scale size={12} /> El resultado (el café)
          </p>
          <SegunDato
            dato={rentMes.dato}
            cargando={<p className="text-[11px] text-warm-400 animate-pulse">Cargando…</p>}
            falla={m => <NoSeSabe onReintentar={rentMes.recargar}
              mensaje={`${m} — no se sabe si el mes va ganando o perdiendo.`} />}
            listo={r => (<>
              <Celda rotulo="Venta neta" valor={`+ ${plata(r.resumen.venta_neta)}`} />
              <Celda rotulo="Compras y gastos"
                valor={`− ${plata(r.resumen.compras + r.resumen.gastos)}`} />
              <div className="pt-1 border-t border-warm-100">
                <Celda rotulo={r.resumen.margen_neto >= 0 ? 'Va ganando' : 'Va perdiendo'}
                  valor={plata(Math.abs(r.resumen.margen_neto))}
                  rojo={r.resumen.margen_neto < 0} />
              </div>
            </>)}
          />
        </div>
      </div>

      <p className="px-4 py-2 border-t border-warm-100 text-[11px] text-warm-500 leading-relaxed">
        <b>Que no coincidan es lo normal.</b> Por la caja pasan cosas que no son costo del mes (la
        prima, el impoconsumo, lo personal) y al resultado entran cosas que todavía no salieron de
        la caja. Leer el banco como la ganancia es el error que este renglón existe para evitar.
      </p>
    </section>
  )
}
