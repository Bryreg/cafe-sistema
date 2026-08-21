import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { ChevronLeft, ChevronRight, Plus, RefreshCw, X } from 'lucide-react'
import { Dato } from '../../api/dato'
import type { Fuente } from '../../api/useDato'
import { SegunDato, NoSeSabe } from '../ui'
import {
  CuentaBanco, DiaLibro, LibroMes,
  MESES, compacto, diaSemana, esFinde, fechaCorta, fechaLarga, plata,
} from './banco'
import { Agenda, Categoria } from './tipos'
import FormMovimiento from './FormMovimiento'

/**
 * ═════════════════════════════════════════════════════════════════════════════
 * EL LIBRO DIARIO — la hoja del dueño, con sus movimientos al lado
 * ═════════════════════════════════════════════════════════════════════════════
 * Dos paneles enlazados: a la izquierda el libro día por día (arranca + entra −
 * sale = queda); a la derecha, los movimientos.
 *
 *  · Con el mouse FUERA del libro, el panel muestra TODOS los movimientos del
 *    mes, con su propio scroll — no una lista de miles de píxeles.
 *  · Con el mouse SOBRE un día (o tocándolo), muestra SOLO los de ese día.
 *
 * EL HOVER QUE FILTRA VIVE SOLO EN EL LIBRO. Si los movimientos también
 * reaccionaran al cursor, apuntar uno filtraría la lista y se quitaría la fila
 * de abajo del puntero — un parpadeo sin fin. Por eso el panel es lista + scroll
 * y no reacciona al hover; el que decide qué se ve es la fila del libro.
 *
 * Las consignaciones ENTRAN SOLAS (llevan la ↻): el sistema ya las conoce. El
 * formulario de «agregar» es para lo que solo sabe el dueño (el Bold, un pago en
 * efectivo) y va montado SIEMPRE, aunque el libro no haya cargado (regla 5 del
 * sistema de diseño: un formulario no se esconde detrás de un gate por estado).
 */

// ── Un movimiento aplanado, listo para pintar en el panel ────────────────────
type Clase = 'consig' | 'banco' | 'personal' | 'cafe' | 'efectivo' | 'cuenta' | 'recogido' | 'deposito'

interface MovFila {
  key: string
  fecha: string
  dia: number
  clase: Clase
  tag: string
  label: string
  monto: number
  entra: boolean
  /** Entró sola desde consignaciones: lleva la ↻. */
  auto: boolean
}

/** El tono del chip por clase. Badge no tiene tono «forest», así que el café y
 *  las cuentas van en warm — el color distingue lo que importa (consignación
 *  verde, personal dorado), no cada categoría. */
const TONO: Record<Clase, 'success' | 'warm' | 'gold'> = {
  consig: 'success', personal: 'gold', recogido: 'success',
  banco: 'warm', cafe: 'warm', cuenta: 'warm', efectivo: 'warm', deposito: 'warm',
}

const claseDeMovimiento = (ambito: string | null | undefined): Clase => {
  if (ambito === 'banco') return 'banco'
  if (ambito === 'personal') return 'personal'
  return 'cafe'
}

/**
 * Aplana los días del libro en una sola lista de movimientos, cada uno con su
 * día. Reúne las tres fuentes que el backend ya manda por día:
 *   · las consignaciones proyectadas (entran solas, ↻)
 *   · los movimientos tecleados (con su categoría si la tienen)
 *   · los pagos en efectivo (informativos: NO tocan el saldo del banco)
 */
function aplanar(dias: DiaLibro[]): MovFila[] {
  const filas: MovFila[] = []
  for (const d of dias) {
    const n = Number(d.fecha.slice(8, 10))
    for (const c of d.consignaciones ?? []) {
      filas.push({
        key: `c-${c.consignacion_id}`, fecha: d.fecha, dia: n, clase: 'consig',
        tag: 'Consignación', label: c.barista_nombre || 'Occidente',
        monto: c.valor, entra: true, auto: true,
      })
    }
    for (const m of d.movimientos) {
      // Un depósito de lo recogido no es plata nueva: es un traspaso de la mano al
      // banco (neutro al total). Se pinta aparte para que no se lea como ingreso.
      const esDeposito = m.desde_mano === true && m.tipo === 'entrada'
      filas.push({
        key: `m-${m.id}`, fecha: d.fecha, dia: n,
        clase: esDeposito ? 'deposito'
          : m.categoria ? claseDeMovimiento(m.categoria_ambito) : 'cuenta',
        tag: esDeposito ? 'Depósito' : (m.categoria || m.cuenta), label: m.concepto,
        monto: m.monto, entra: m.tipo === 'entrada', auto: false,
      })
    }
    for (const p of d.pagos_efectivo ?? []) {
      filas.push({
        key: `e-${p.pago_id}`, fecha: d.fecha, dia: n, clase: 'efectivo',
        tag: 'Efectivo', label: p.detalle || 'Pago en efectivo',
        monto: p.monto, entra: false, auto: false,
      })
    }
    for (const r of d.recogido ?? []) {
      filas.push({
        key: `r-${r.id}`, fecha: d.fecha, dia: n, clase: 'recogido',
        tag: 'Recogí', label: r.nota || 'Efectivo recogido',
        monto: r.monto, entra: true, auto: false,
      })
    }
  }
  return filas
}

export default function LibroDiario({
  libro, anio, mes, hoy, viendoElMesDeHoy,
  cuentas, agenda, categorias,
  onIrAlMes, onIrAHoy, onGuardado, onIrAlAncla,
}: {
  libro: Dato<LibroMes>
  anio: number
  mes: number
  hoy: string
  viendoElMesDeHoy: boolean
  cuentas: Fuente<CuentaBanco[]>
  agenda: Fuente<Agenda>
  categorias?: Fuente<Categoria[]>
  onIrAlMes: (delta: number) => void
  onIrAHoy: () => void
  onGuardado: (fecha: string) => void
  /** Sube al editor del extracto: el hero lo ofrece cuando falta el cierre. */
  onIrAlAncla: () => void
}) {
  // El día señalado (hover) o fijado (toque, para tablet). El fijado sobrevive a
  // que el mouse se vaya; «✕ ver todo» lo suelta.
  const [hover, setHover] = useState<string | null>(null)
  const [fijo, setFijo] = useState<string | null>(null)
  const activo = hover ?? fijo

  // La tasa del GMF viaja con el libro. AUSENTE (servidor viejo o libro caído)
  // es null: la sugerencia del GMF se apaga en vez de inventar una tasa.
  const tasaGmf = libro.estado === 'listo' ? (libro.valor.tasa_gmf ?? null) : null

  return (
    <div className="space-y-3">
      <SegunDato
        dato={libro}
        cargando={
          <div className="rounded-2xl border border-warm-200 bg-white p-8 text-center text-sm text-warm-400 animate-pulse">
            Cargando el libro…
          </div>
        }
        falla={m => (
          <NoSeSabe bloque
            mensaje={`${m} — no se sabe qué se movió este mes ni con cuánto quedó cada día. `
              + 'Que no haya filas acá no quiere decir que no se haya movido plata.'} />
        )}
        listo={l => (
          <LibroListo
            l={l} anio={anio} mes={mes} hoy={hoy} viendoElMesDeHoy={viendoElMesDeHoy}
            activo={activo} fijo={fijo}
            onHover={setHover} onFijar={f => setFijo(x => (x === f ? null : f))}
            onSoltar={() => { setFijo(null); setHover(null) }}
            onIrAlMes={onIrAlMes} onIrAHoy={onIrAHoy} onIrAlAncla={onIrAlAncla} />
        )}
      />

      {/* ── Agregar un movimiento — SIEMPRE montado ─────────────────────────
          Para lo que solo sabe el dueño: el Bold (que liquida con su comisión),
          un pago en efectivo. Las consignaciones entran solas. */}
      <div className="rounded-2xl border border-warm-200 bg-white overflow-hidden">
        <div className="px-4 py-3 border-b border-warm-100">
          <p className="text-sm font-bold text-warm-700">Agregar un movimiento</p>
          <p className="text-[11px] text-warm-500 mt-0.5">
            El Bold, un pago en efectivo — lo que el sistema no sabe solo. Las consignaciones y
            recogidas entran solas, no hace falta cargarlas.
          </p>
        </div>
        <FormMovimiento
          fechaInicial={hoy} cuentas={cuentas} agenda={agenda} maxFecha={hoy}
          categorias={categorias} tasaGmf={tasaGmf}
          onGuardado={m => onGuardado(m.fecha)} />
      </div>
    </div>
  )
}

// ═════════════════════════════════════════════════════════════════════════════
// El libro YA resuelto: hero + los dos paneles.
// ═════════════════════════════════════════════════════════════════════════════
function LibroListo({
  l, anio, mes, hoy, viendoElMesDeHoy, activo, fijo,
  onHover, onFijar, onSoltar, onIrAlMes, onIrAHoy, onIrAlAncla,
}: {
  l: LibroMes
  anio: number
  mes: number
  hoy: string
  viendoElMesDeHoy: boolean
  activo: string | null
  fijo: string | null
  onHover: (f: string | null) => void
  onFijar: (f: string) => void
  onSoltar: () => void
  onIrAlMes: (delta: number) => void
  onIrAHoy: () => void
  onIrAlAncla: () => void
}) {
  const movs = useMemo(() => aplanar(l.dias), [l.dias])
  const mostrados = activo ? movs.filter(m => m.fecha === activo) : movs
  const hayColumnasDeSaldo = l.dias_con_saldo > 0
  const t = l.totales

  // ── EL PANEL DE MOVIMIENTOS SE ALINEA CON EL DÍA SEÑALADO ──────────────────
  // Antes, al señalar un día de abajo (el 22) sus movimientos aparecían arriba
  // del todo, lejos del cursor. Ahora el panel se corre para quedar al lado de la
  // fila señalada. Solo en pantalla ancha (lg+): en celular los paneles van
  // apilados y el de movimientos ya cae debajo del libro, así que no hay nada que
  // alinear. El traslado es visual (transform), no toca el layout: la columna del
  // libro no se mueve y el bloque de abajo tampoco.
  const gridRef = useRef<HTMLDivElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const filasRef = useRef<Map<string, HTMLElement>>(new Map())
  const [esAncho, setEsAncho] = useState(false)
  const [alineado, setAlineado] = useState(0)

  useEffect(() => {
    const mq = window.matchMedia('(min-width: 1024px)')
    const leer = () => setEsAncho(mq.matches)
    leer()
    mq.addEventListener('change', leer)
    return () => mq.removeEventListener('change', leer)
  }, [])

  useLayoutEffect(() => {
    if (!esAncho || !activo || !gridRef.current) { setAlineado(0); return }
    const fila = filasRef.current.get(activo)
    if (!fila) return
    // offsetTop (métrica de LAYOUT) y no getBoundingClientRect: es relativo al
    // grid (que es `relative`), no depende del scroll ni de la transform que el
    // propio panel ya tiene puesta — que era lo que descuadraba la medición.
    const top = fila.offsetTop
    // El panel se ALINEA con la fila (su borde de arriba a la altura del día). Se
    // frena solo para que el encabezado no caiga por debajo del libro: el cuerpo
    // puede pasarse un poco hacia abajo (es flotante, no empuja nada), pero el
    // título «Movimientos · día N» siempre queda dentro del alto del libro.
    setAlineado(Math.max(0, Math.min(top, Math.max(0, gridRef.current.offsetHeight - 64))))
  }, [esAncho, activo, mostrados.length])

  const trasladar = esAncho && !!activo

  return (
    <div className="space-y-3">
      {/* ── HERO: el resultado del mes ─────────────────────────────────────────
          Compacto: la etiqueta y el mes en una línea, y abajo el cierre GRANDE a
          la izquierda con las tres métricas a la derecha, repartidos a lo ancho —
          sin el hueco muerto que dejaba el título solo. */}
      <div className="rounded-2xl bg-forest text-forest-50 p-4 sm:p-5 shadow-lg shadow-forest/20">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-baseline gap-2 flex-wrap">
            <span className="text-[11px] font-bold uppercase tracking-wide text-forest-50/70">La plata</span>
            <h1 className="text-2xl sm:text-3xl font-extrabold text-white leading-none">
              {MESES[mes - 1]} <span className="text-forest-50/90">{anio}</span>
            </h1>
          </div>
          <div className="flex items-center gap-1 shrink-0">
            <button onClick={() => onIrAlMes(-1)} aria-label="Mes anterior"
              className="w-9 h-9 rounded-xl bg-forest-700 text-forest-50 flex items-center justify-center hover:bg-forest-500">
              <ChevronLeft size={18} />
            </button>
            {!viendoElMesDeHoy && (
              <button onClick={onIrAHoy}
                className="h-9 px-3 rounded-xl bg-forest-700 text-forest-50 text-xs font-bold hover:bg-forest-500">
                Hoy
              </button>
            )}
            <button onClick={() => onIrAlMes(1)} aria-label="Mes siguiente"
              className="w-9 h-9 rounded-xl bg-forest-700 text-forest-50 flex items-center justify-center hover:bg-forest-500">
              <ChevronRight size={18} />
            </button>
          </div>
        </div>

        <div className="mt-3 flex flex-wrap items-end justify-between gap-x-8 gap-y-4">
          {/* Con cuánto cerró (o el aviso honesto de que no se sabe). */}
          <div className="flex flex-col gap-1">
            {t.final != null ? (<>
              <span className="text-[11px] font-bold uppercase tracking-wide text-forest-50/70">
                Con lo cargado, el mes cerró con
              </span>
              <span className={`font-mono tabular-nums text-4xl sm:text-5xl font-bold leading-none ${
                t.final < 0 ? 'text-gold-200' : 'text-white'}`}>
                {plata(t.final)}
              </span>
            </>) : (
              <button onClick={onIrAlAncla} className="text-left">
                <span className="block text-[11px] font-bold uppercase tracking-wide text-forest-50/80">
                  El cierre no se sabe todavía
                </span>
                <span className="block text-sm text-forest-50/90 mt-1 max-w-xs leading-snug">
                  Falta el saldo del extracto para saber con cuánto termina. Tocá acá y cargalo.
                </span>
              </button>
            )}
          </div>

          <div className="flex gap-2">
            <div className="rounded-xl bg-forest-700 px-4 py-2.5 flex flex-col gap-0.5 min-w-[7rem]">
              <span className="text-[10px] font-semibold uppercase tracking-wide text-forest-50/70">Entró</span>
              <span className="font-mono tabular-nums text-base font-semibold text-success-200">+ {plata(t.entradas)}</span>
            </div>
            <div className="rounded-xl bg-forest-700 px-4 py-2.5 flex flex-col gap-0.5 min-w-[7rem]">
              <span className="text-[10px] font-semibold uppercase tracking-wide text-forest-50/70">Salió</span>
              <span className="font-mono tabular-nums text-base font-semibold text-gold-200">− {plata(t.salidas)}</span>
            </div>
            {l.dias_con_saldo > 0 && (
              <div className="rounded-xl bg-forest-700 px-4 py-2.5 flex flex-col gap-0.5 min-w-[5.5rem]">
                <span className="text-[10px] font-semibold uppercase tracking-wide text-forest-50/70">Días en rojo</span>
                <span className="text-base font-bold text-gold-200">
                  {t.dias_en_rojo}
                  {t.fecha_dia_mas_bajo && (
                    <span className="ml-1 text-[11px] font-medium text-forest-50/70">
                      · el {Number(t.fecha_dia_mas_bajo.slice(8, 10))}
                    </span>
                  )}
                </span>
              </div>
            )}
          </div>
        </div>

        {/* La mano del dueño y el total (banco + mano) — SOLO cuando hay efectivo
            recogido. Sin recogidas (el caso de hoy) el hero queda igual. Ausente
            (servidor viejo, antes del modelo banco+mano) no dibuja nada. */}
        {typeof t.mano_final === 'number' && t.mano_final !== 0 && (
          <div className="mt-3 pt-3 border-t border-forest-700 flex flex-wrap items-center gap-x-6 gap-y-1">
            <span className="text-sm text-forest-50/80">
              En mano <span className="text-forest-50/60">(efectivo recogido)</span>:{' '}
              <b className="font-mono tabular-nums text-white">{plata(t.mano_final)}</b>
            </span>
            {t.total_final != null && (
              <span className="text-sm text-forest-50/80">
                Toda la plata <span className="text-forest-50/60">(banco + mano)</span>:{' '}
                <b className="font-mono tabular-nums text-white">{plata(t.total_final)}</b>
              </span>
            )}
          </div>
        )}
      </div>

      <p className="text-[13px] text-warm-500 px-1">
        Con el mouse fuera del libro ves <b className="text-warm-600">todos</b> los movimientos, con
        scroll. Poné el cursor sobre un día <span className="text-warm-400">— o tocalo —</span> y el
        panel se corre <b className="text-warm-600">al lado de ese día</b> con solo sus movimientos.
      </p>

      {/* ── LOS DOS PANELES ────────────────────────────────────────────────── */}
      <div ref={gridRef} className="relative grid lg:grid-cols-2 gap-3 items-start">
        {/* Libro */}
        <div className="rounded-2xl border border-warm-200 bg-white overflow-hidden">
          <div className="px-4 py-3 border-b border-warm-100">
            <p className="text-sm font-bold text-warm-700">El libro, día por día</p>
          </div>
          <div className={`grid gap-2 px-4 py-2 bg-warm-50 border-b border-warm-100 text-[9px] font-bold uppercase tracking-wide text-warm-500 ${
            hayColumnasDeSaldo ? 'grid-cols-[3.4rem_1fr_1fr_1fr]' : 'grid-cols-[3.4rem_1fr_1fr]'}`}>
            <span>Día</span>
            <span className="text-right">Entra</span>
            <span className="text-right">Sale</span>
            {hayColumnasDeSaldo && <span className="text-right">Queda</span>}
          </div>
          {l.dias.map(d => (
            <FilaDia key={d.fecha} dia={d} hoy={hoy} columnasDeSaldo={hayColumnasDeSaldo}
              activo={activo === d.fecha}
              innerRef={el => {
                if (el) filasRef.current.set(d.fecha, el)
                else filasRef.current.delete(d.fecha)
              }}
              onEntra={() => onHover(d.fecha)} onSale={() => onHover(null)}
              onTocar={() => onFijar(d.fecha)} />
          ))}
        </div>

        {/* Movimientos — se traslada para quedar al lado del día señalado (lg+). */}
        <div ref={panelRef}
          style={trasladar ? { transform: `translateY(${alineado}px)` } : undefined}
          className={`rounded-2xl border bg-white overflow-hidden flex flex-col self-start ${
            trasladar
              ? 'border-forest-200 shadow-xl shadow-forest/10 ring-1 ring-forest-100 transition-transform duration-150 ease-out'
              : 'border-warm-200'}`}>
          <div className="px-4 py-3 border-b border-warm-100 flex items-center justify-between gap-2">
            <p className="text-sm font-bold text-warm-700">Movimientos</p>
            <div className="flex items-center gap-2">
              <span className="text-[11px] text-warm-400">
                {activo
                  ? `día ${Number(activo.slice(8, 10))} · ${mostrados.length} ${mostrados.length === 1 ? 'mov' : 'movs'}`
                  : `todo el mes · ${movs.length}`}
              </span>
              {fijo && (
                <button onClick={onSoltar}
                  className="inline-flex items-center gap-1 rounded-full border border-warm-200 px-2 py-1 text-[11px] font-bold text-warm-500 hover:bg-warm-50">
                  <X size={12} /> ver todo
                </button>
              )}
            </div>
          </div>
          <div className="p-2 flex flex-col gap-1.5 max-h-[560px] overflow-y-auto">
            {mostrados.length === 0 ? (
              <p className="px-3 py-4 text-[13px] text-warm-500">
                {activo
                  ? `El ${Number(activo.slice(8, 10))} no se movió plata en el banco.`
                  : 'No hay movimientos cargados este mes.'}
              </p>
            ) : mostrados.map(m => <FilaMov key={m.key} m={m} />)}
          </div>
          <div className="flex items-center gap-2 px-4 py-3 border-t border-warm-100 bg-warm-50">
            <RefreshCw size={13} className="shrink-0 text-success-600" />
            <span className="text-[11px] text-warm-500 leading-relaxed">
              Las <b className="text-success-700">consignaciones</b> entran solas desde su módulo: al
              marcarlas «recogí / saldado» aparecen acá y en el libro sin teclear.
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Una fila del libro = un día ──────────────────────────────────────────────
function FilaDia({
  dia, hoy, columnasDeSaldo, activo, innerRef, onEntra, onSale, onTocar,
}: {
  dia: DiaLibro
  hoy: string
  columnasDeSaldo: boolean
  activo: boolean
  /** Para medir la posición de la fila y alinear el panel de movimientos. */
  innerRef?: (el: HTMLButtonElement | null) => void
  onEntra: () => void
  onSale: () => void
  onTocar: () => void
}) {
  const esHoy = dia.fecha === hoy
  const rojo = dia.en_rojo
  const numero = Number(dia.fecha.slice(8, 10))
  const fondo = activo
    ? (rojo ? 'bg-danger-50' : 'bg-forest-50')
    : (rojo ? 'bg-danger-50/60' : esFinde(dia.fecha) ? 'bg-warm-50/60' : '')

  return (
    <button
      ref={innerRef}
      onMouseEnter={onEntra} onMouseLeave={onSale} onClick={onTocar}
      aria-label={`${fechaLarga(dia.fecha)}${dia.cadena ? `, queda ${plata(dia.final)}` : ''}`}
      className={`w-full text-left border-b border-warm-100 transition-colors ${fondo} ${
        activo ? 'shadow-[inset_3px_0_0] ' + (rojo ? 'shadow-danger-500' : 'shadow-forest') : ''}`}>
      <div className={`grid gap-2 items-center px-4 py-3 ${
        columnasDeSaldo ? 'grid-cols-[3.4rem_1fr_1fr_1fr]' : 'grid-cols-[3.4rem_1fr_1fr]'}`}>
        <span className="flex items-baseline gap-1.5">
          <span className={`text-base font-bold ${
            esHoy ? 'text-forest bg-forest-100 rounded-full px-1.5' : rojo ? 'text-danger-700' : 'text-warm-600'}`}>{numero}</span>
          <span className={`text-[10px] ${rojo ? 'text-danger-500' : 'text-warm-400'}`}>{diaSemana(dia.fecha)}</span>
        </span>
        <span className={`text-right font-mono tabular-nums text-[13px] font-semibold ${
          dia.total_entradas > 0 ? 'text-success-600' : 'text-warm-300'}`}>
          {dia.total_entradas > 0 ? `+ ${plata(dia.total_entradas)}` : '—'}
        </span>
        <span className={`text-right font-mono tabular-nums text-[13px] font-semibold ${
          dia.total_salidas > 0 ? 'text-danger-600' : 'text-warm-300'}`}>
          {dia.total_salidas > 0 ? `− ${plata(dia.total_salidas)}` : '—'}
        </span>
        {columnasDeSaldo && (
          <span className={`text-right font-mono tabular-nums text-[13px] font-bold ${
            !dia.cadena ? 'text-warm-300' : rojo ? 'text-danger-700' : 'text-warm-700'}`}>
            {dia.cadena ? plata(dia.final) : '—'}
          </span>
        )}
      </div>
    </button>
  )
}

// ── Una fila del panel de movimientos ────────────────────────────────────────
function FilaMov({ m }: { m: MovFila }) {
  const tono = TONO[m.clase]
  const chip = tono === 'success' ? 'bg-success-50 text-success-700'
    : tono === 'gold' ? 'bg-gold-50 text-gold-700'
    : 'bg-warm-100 text-warm-600'
  return (
    <div className="flex items-center gap-2.5 px-3 py-2.5 rounded-xl border border-warm-100">
      <span className="w-7 shrink-0 text-center text-xs font-bold text-warm-400">{m.dia}</span>
      <span className={`shrink-0 rounded-md px-2 py-1 text-[10px] font-bold uppercase tracking-wide ${chip}`}>
        {m.tag}
      </span>
      {m.auto && (
        <RefreshCw size={13} className="shrink-0 text-success-600" aria-label="Entró sola" />
      )}
      <span className="flex-1 min-w-0 truncate text-sm text-warm-600">
        {m.label}
        {m.clase === 'efectivo' && <span className="ml-1 text-[11px] text-warm-400">· no toca el banco</span>}
        {m.clase === 'deposito' && <span className="ml-1 text-[11px] text-warm-400">· de lo recogido, no suma al total</span>}
      </span>
      {/* El depósito de lo recogido es un traspaso mano→banco: ni + ni − al total.
          Se pinta con «↔» y en gris para que no se lea como un ingreso. */}
      <span className={`shrink-0 font-mono tabular-nums text-sm font-bold ${
        m.clase === 'deposito' ? 'text-warm-400' : m.entra ? 'text-success-600' : 'text-danger-600'}`}>
        {m.clase === 'deposito' ? '↔' : m.entra ? '+' : '−'} {plata(m.monto)}
      </span>
    </div>
  )
}
