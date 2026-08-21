import { ReactNode, useState } from 'react'
import { ChevronRight, ListChecks } from 'lucide-react'
import { Dato } from '../../api/dato'
import type { Fuente } from '../../api/useDato'
import { SegunDato, NoSeSabe } from '../ui'
import { CuentaBanco, LibroMes, MovimientoBanco } from '../plata/banco'
import { Agenda, Categoria } from '../plata/tipos'
import FormMovimiento from '../plata/FormMovimiento'
import ExtractoDelBanco from './ExtractoDelBanco'
import type { Pendiente, Revision } from './pendientes'

// ═════════════════════════════════════════════════════════════════════════════
// 2 · HOY — lo único que se toca todos los días
// ═════════════════════════════════════════════════════════════════════════════
// Dos columnas: a la izquierda lo que el dueño TECLEA contra el extracto, a la
// derecha lo que tiene que HACER. Nada más. Todo lo que se consulta está abajo.
//
// ── LOS DOS FORMULARIOS QUEDAN MONTADOS SIEMPRE (regla 5) ─────────────────
// Ni el extracto ni el movimiento se esconden detrás de un estado de carga. Si
// el catálogo de cuentas no cargó, ese campo queda con su aviso arriba y el
// resto se sigue tecleando: el día, el monto y el concepto no dependen de él.
// Esconderlos le rompe el trabajo de las siete de la mañana.
//
// ── VEINTE MOVIMIENTOS SON VEINTE TABULADAS ──────────────────────────────
// `FormMovimiento` ya limpia los campos y devuelve el foco al monto después de
// guardar, y `teclas()` hace que Enter guarde. Eso es lo que convierte una hoja
// de cálculo en una pantalla: sin ello son veinte viajes con el dedo.
//
// ── EL CONTADOR DE ARRIBA NO PUEDE MENTIR ────────────────────────────────
// «Hay 7 cosas que hacer» solo se puede escribir cuando las siete preguntas se
// pudieron hacer. Con una fuente caída dice «al menos 5», y las que no se
// pudieron mirar dibujan su propio renglón con su Reintentar. Un «no tenés nada
// pendiente» sobre una pregunta que nunca se hizo es la mentira que esta página
// existe para no volver a decir.

/** Una tarea. El botón es siempre táctil: 46px es el mínimo real en la tablet. */
function Fila({ n, p, onHacer }: { n: number; p: Pendiente; onHacer: () => void }) {
  return (
    <div className={`flex items-start gap-2.5 px-3 py-2.5 ${p.urgente ? 'bg-danger-50' : ''}`}>
      <span className={`shrink-0 mt-0.5 w-5 h-5 rounded-full grid place-items-center text-[10px]
        font-bold ${p.urgente ? 'bg-danger-500 text-white' : 'bg-warm-200 text-warm-600'}`}>
        {n}
      </span>
      <div className="min-w-0 flex-1">
        <p className={`text-sm font-semibold leading-snug ${
          p.urgente ? 'text-danger-700' : 'text-warm-700'}`}>
          {p.titulo}
        </p>
        <p className={`text-[11px] leading-snug ${
          p.urgente ? 'text-danger-700/80' : 'text-warm-500'}`}>
          {p.detalle}
        </p>
      </div>
      <button onClick={onHacer}
        className={`shrink-0 flex items-center gap-0.5 min-h-[46px] px-2.5 rounded-xl text-[11px]
          font-bold ${p.urgente
            ? 'text-danger-700 hover:bg-danger-100'
            : 'text-forest hover:bg-warm-100'}`}>
        {p.cta} <ChevronRight size={13} />
      </button>
    </div>
  )
}

/** El renglón de una revisión que no se pudo hacer. Ocupa lugar a propósito. */
function NoSePudoMirar({ r }: { r: Revision }) {
  return (
    <div className="px-3 py-2">
      <NoSeSabe onReintentar={r.recargar}
        mensaje={`No se pudo mirar ${r.nombre}, así que esta lista puede estar incompleta.`} />
    </div>
  )
}

export default function BloqueHoy({
  libro, hoy, cuentas, agenda, categorias, onCategoriaCreada, revisiones,
  pedidoFocoExtracto, onAnclaGuardada, onMovimientoGuardado, onRecargarLibro,
  elLibro, id,
}: {
  libro: Dato<LibroMes>
  hoy: string
  cuentas: Fuente<CuentaBanco[]>
  /** Para el select de «enlazar a una obligación» del formulario de movimiento. */
  agenda: Fuente<Agenda>
  /** El catálogo COMPLETO (café + personal + banco) para rotular movimientos. */
  categorias?: Fuente<Categoria[]>
  onCategoriaCreada?: () => void
  revisiones: Revision[]
  pedidoFocoExtracto: number
  onAnclaGuardada: () => void
  onMovimientoGuardado: (m: MovimientoBanco) => void
  onRecargarLibro: () => void
  /**
   * EL LIBRO DEL BANCO, PLEGADO ADENTRO DE ESTE MISMO BLOQUE.
   *
   * Es la historia de lo que se teclea acá arriba, así que vive al lado del
   * formulario y no en un banner propio: en el día normal ocupa un renglón, y
   * el día que hay que corregir un movimiento mal cargado —el único camino a
   * `DELETE /banco/movimientos/{id}`— está a un toque del campo donde se
   * escribió.
   */
  elLibro: ReactNode
  id?: string
}) {
  const [verTodas, setVerTodas] = useState(false)
  // ABIERTO por defecto: el libro día a día ES la pantalla — la hoja del dueño
  // que se va llenando. Plegado, la página volvía a ser un tablero de números
  // con la hoja escondida atrás de un toque que nadie daba.
  const [verLibro, setVerLibro] = useState(true)

  /**
   * Las tres cuentas de la lista, cada una honesta sobre lo que sabe.
   *
   * `hechas` son las revisiones que devolvieron una tarea; `mudas` son las que
   * no se pudieron hacer. Se cuentan por separado porque el rótulo de arriba
   * cambia: con `mudas.length > 0` no se puede decir un total, solo un mínimo.
   */
  const hechas: { r: Revision; p: Pendiente }[] = []
  const mudas: Revision[] = []
  let cargando = false
  for (const r of revisiones) {
    switch (r.dato.estado) {
      case 'listo': if (r.dato.valor) hechas.push({ r, p: r.dato.valor }); break
      case 'cargando': cargando = true; break
      case 'falla':
      case 'sinBase': mudas.push(r); break
    }
  }

  // Lo urgente primero, y adentro de cada grupo el orden en que se armaron
  // (que ya va de la plata atrasada al mantenimiento).
  const orden = [...hechas].sort((a, b) => Number(!!b.p.urgente) - Number(!!a.p.urgente))
  const VISIBLES = 3
  const visibles = verTodas ? orden : orden.slice(0, VISIBLES)
  const ocultas = orden.length - visibles.length

  return (
    <section id={id} className="rounded-2xl border border-warm-200 bg-white overflow-hidden">
      <div className="grid grid-cols-1 lg:grid-cols-2 divide-y lg:divide-y-0 lg:divide-x divide-warm-100">

        {/* ── Izquierda: lo que se teclea ─────────────────────────────────── */}
        <div className="divide-y divide-warm-100">
          <ExtractoDelBanco libro={libro} hoy={hoy} pedidoFoco={pedidoFocoExtracto}
            onGuardado={onAnclaGuardada} onRecargarLibro={onRecargarLibro} />

          <FormMovimiento fechaInicial={hoy} cuentas={cuentas} agenda={agenda}
            maxFecha={hoy} onGuardado={onMovimientoGuardado}
            categorias={categorias} onCategoriaCreada={onCategoriaCreada}
            tasaGmf={libro.estado === 'listo' ? (libro.valor.tasa_gmf ?? null) : null} />

          <div className="px-4 py-2.5">
            <button onClick={() => setVerLibro(v => !v)}
              className="min-h-[44px] text-xs font-bold text-forest hover:underline flex items-center gap-1">
              {verLibro ? '▾ Ocultar el libro del banco' : '▸ Ver el libro del banco'}
            </button>
          </div>
        </div>

        {/* ── Derecha: lo que hay que hacer ───────────────────────────────── */}
        <div>
          <div className="flex items-center gap-2 px-4 py-3 border-b border-warm-100">
            <ListChecks size={15} className="shrink-0 text-forest" />
            <h2 className="text-sm font-bold text-warm-700 flex-1 min-w-0">
              <Rotulo n={orden.length} incompleta={mudas.length > 0} cargando={cargando} />
            </h2>
          </div>

          <div className="divide-y divide-warm-100">
            {/* Lo que no se pudo mirar va ARRIBA de las tareas: enterrarlo abajo
                es lo que convierte un «no sé» en un «no hay nada». */}
            {mudas.map(r => <NoSePudoMirar key={r.clave} r={r} />)}

            {visibles.map(({ r, p }, i) => (
              <Fila key={r.clave} n={i + 1} p={p} onHacer={r.hacer} />
            ))}

            {/* EL «NADA PENDIENTE» VIVE SOLO ACÁ: con todas las revisiones
                hechas, sin ninguna caída y sin ninguna en curso. Es la única
                combinación en la que la frase es cierta. */}
            {orden.length === 0 && mudas.length === 0 && !cargando && (
              <p className="px-4 py-6 text-center text-sm text-success-700 font-semibold">
                No hay nada pendiente. Las {revisiones.length} revisiones se hicieron y todas
                dieron bien.
              </p>
            )}

            {orden.length === 0 && cargando && (
              <p className="px-4 py-6 text-center text-sm text-warm-400">Revisando…</p>
            )}
          </div>

          {ocultas > 0 && (
            <button onClick={() => setVerTodas(true)}
              className="w-full min-h-[46px] px-4 text-left text-[11px] font-bold text-forest
                         hover:bg-warm-50 border-t border-warm-100">
              ▸ ver las otras {ocultas}
            </button>
          )}
          {verTodas && orden.length > VISIBLES && (
            <button onClick={() => setVerTodas(false)}
              className="w-full min-h-[46px] px-4 text-left text-[11px] font-bold text-warm-500
                         hover:bg-warm-50 border-t border-warm-100">
              ▾ ver menos
            </button>
          )}
        </div>
      </div>

      {/* El libro entero, plegado. Ocupa un renglón hasta que se pide. */}
      {verLibro && <div className="border-t border-warm-100">{elLibro}</div>}
    </section>
  )
}

/**
 * El rótulo del contador.
 *
 * `parcial` junta las dos formas de no saber —una revisión caída y una todavía
 * en curso— porque para el rótulo son lo mismo: el número que se puede escribir
 * es un MÍNIMO, no un total. «Hay 5 cosas que hacer» dicho sobre seis preguntas
 * hechas de siete es una afirmación falsa hacia el lado tranquilizador, y da
 * igual si la séptima falló o si todavía viaja.
 *
 * Lo que NO son lo mismo es el mensaje: una falla se arregla reintentando y una
 * carga se arregla esperando, así que solo la falla dibuja su renglón con botón.
 */
function Rotulo({ n, incompleta, cargando }: {
  n: number; incompleta: boolean; cargando: boolean
}): ReactNode {
  const parcial = incompleta || cargando
  if (parcial) {
    if (n > 0) return <>Hay <b>al menos {n}</b> {n === 1 ? 'cosa' : 'cosas'} que hacer</>
    return cargando && !incompleta
      ? <>Revisando qué hay que hacer…</>
      : <>Hay cosas que hacer que no se pudieron mirar</>
  }
  if (n === 0) return <>No hay nada que hacer</>
  return <>Hay <b>{n}</b> {n === 1 ? 'cosa' : 'cosas'} que hacer</>
}
