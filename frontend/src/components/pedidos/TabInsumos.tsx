import { useEffect, useMemo, useRef, useState } from 'react'
import api from '../../api/client'
import {
  AlertTriangle, ArrowDown, ArrowUp, Search, ChevronRight,
} from 'lucide-react'
import FichaInsumo, { type Resumen, type ConteoCurva, type PuntoCurva } from './FichaInsumo'
import BarraInsumo, { veredicto, CHIP_VEREDICTO, num, firmado } from './BarraInsumo'

/**
 * «Qué pasó con cada insumo», la tabla que el dueño pidió: en un mismo sitio lo
 * que entró, por dónde salió (venta, merma, traslado, preparación) y qué queda.
 *
 * Todo sale de UNA llamada a `/inventario/movimiento-insumos`, que a su vez
 * reusa la escalera de conciliación: acá no se reparte ningún movimiento por su
 * causa, eso ya está resuelto en el backend y no se puede duplicar sin que las
 * dos cuentas se desincronicen en el primer motivo que alguien renombre.
 *
 * Tres decisiones de la pantalla que NO son cosméticas:
 *  · El ORIGEN («proveedor» vs «comprás vos») cambia cómo se lee la fila. Contra
 *    Cafexcoop hay pedido y precio acordado; en Makro no hay pedido que
 *    incumplir y la resta es, en la práctica, la lista de mercado. Es el 25% de
 *    la plata: filtrar por eso es una de las razones de existir de la tabla.
 *  · «Sin causa» va destacada y ordena la tabla por defecto: es lo único que
 *    merece investigarse, y en pesos, que es como duele.
 *  · «No se mide» se DICE. Un 0 en «vendió» para los vasos no es una buena
 *    noticia: es que la caja no los descuenta. Callarlo sería peor que no
 *    mostrar la fila.
 */

// ─── Types ────────────────────────────────────────────────────────────────────

type Origen = 'proveedor' | 'directa' | 'sin_origen'

/** La fila de la tabla ES la fila de la ficha: la arma la MISMA función del
 *  backend (`_fila_insumo`), compartida entre `/movimiento-insumos` y
 *  `/insumo/{id}/ficha`. El tipo se importa en vez de re-declararse: dos
 *  interfaces para la misma fila es cómo empiezan a divergir dos pantallas que
 *  juraron decir lo mismo. */
type Insumo = Resumen

interface ResumenTabla {
  n_insumos: number
  n_sin_causa: number
  valor_sin_causa: number
  n_no_se_mide: number
  n_compra_directa: number
  n_con_pedido: number
  n_en_negativo: number
}

interface Respuesta {
  insumos: Insumo[]; resumen: ResumenTabla
  /** Arranque del rango en UTC. Los `t` de la curva son segundos desde acá; sin
   *  este ancla no se pueden convertir en una hora que mostrar. */
  desde_utc: string
}

/** Cómo se mira la misma respuesta. La barra contesta CUÁNDO —un insumo que se
 *  agota el miércoles y otro que baja parejo tienen los mismos totales—; la
 *  tabla contesta CUÁNTO y sigue siendo la que se ordena y se compara columna
 *  por columna. No se reemplaza una por otra: son dos preguntas. */
type Vista = 'barras' | 'tabla'

// ─── Helpers ──────────────────────────────────────────────────────────────────

const fmt$ = (v: number) => `$${Math.round(v || 0).toLocaleString('es-CO')}`
// Las cantidades se muestran SIN decimales salvo que el número sea chico: en
// gramos «30.180» se lee, «30.180,25» solo hace ruido; pero «0,5 und» sí importa.
const fmtCant = (v: number) => {
  const n = Number(v || 0)
  if (n === 0) return '—'
  const abs = Math.abs(n)
  return abs < 10 && !Number.isInteger(n)
    ? n.toLocaleString('es-CO', { maximumFractionDigits: 2 })
    : Math.round(n).toLocaleString('es-CO')
}

/** Fecha local Colombia (no toISOString: después de las 19:00 devuelve mañana). */
const iso = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

type PeriodoKey = 'hoy' | 'mes' | 'ocho' | 'anterior'

function rangoDe(k: PeriodoKey): { desde: string; hasta: string } {
  const hoy = new Date()
  // El día corrido. Con este rango «arrancó» es literalmente lo que había al
  // abrir esta mañana, que es como el dueño lee el inventario cuando está en el
  // local: la barra llena al empezar y lo que se fue comiendo desde entonces.
  if (k === 'hoy') return { desde: iso(hoy), hasta: iso(hoy) }
  if (k === 'mes') {
    return { desde: iso(new Date(hoy.getFullYear(), hoy.getMonth(), 1)), hasta: iso(hoy) }
  }
  if (k === 'anterior') {
    const ini = new Date(hoy.getFullYear(), hoy.getMonth() - 1, 1)
    const fin = new Date(hoy.getFullYear(), hoy.getMonth(), 0)
    return { desde: iso(ini), hasta: iso(fin) }
  }
  const ini = new Date(hoy)
  ini.setDate(ini.getDate() - 55)
  return { desde: iso(ini), hasta: iso(hoy) }
}

const PERIODOS: { k: PeriodoKey; label: string }[] = [
  { k: 'hoy', label: 'Hoy' },
  { k: 'mes', label: 'Este mes' },
  { k: 'ocho', label: 'Últimas 8 semanas' },
  { k: 'anterior', label: 'Mes pasado' },
]

type OrdenKey = 'valor_sin_causa' | 'arranco' | 'pedi' | 'entradas' | 'ventas' | 'mermas' | 'traslados'
  | 'preparaciones' | 'otras_salidas' | 'otros' | 'queda' | 'producto'

type FiltroOrigen = 'todos' | 'proveedor' | 'directa'

/** ¿Este insumo se movió en el período? Cualquier cosa que toque el saldo cuenta:
 *  una entrada, una salida o un ajuste. Un insumo con stock pero quieto NO se
 *  movió — y en la vista del día es exactamente el que estorba. */
const seMovio = (it: Insumo) =>
  Math.abs(it.entradas) + Math.abs(it.total_salio) + Math.abs(it.otros) > 0.001

// ─── Piezas ───────────────────────────────────────────────────────────────────

function ChipOrigen({ origen }: { origen: Origen }) {
  if (origen === 'directa') {
    return <span className="text-[10.5px] font-bold px-2 py-0.5 rounded-full bg-gold-50 text-gold-700 whitespace-nowrap">comprás vos</span>
  }
  if (origen === 'proveedor') {
    return <span className="text-[10.5px] font-bold px-2 py-0.5 rounded-full bg-forest-50 text-forest-700 whitespace-nowrap">proveedor</span>
  }
  return <span className="text-[10.5px] font-bold px-2 py-0.5 rounded-full bg-warm-100 text-warm-500 whitespace-nowrap">sin origen</span>
}

function Th({ label, k, orden, dir, onSort, className = '', destacado = false }: {
  label: string; k: OrdenKey; orden: OrdenKey; dir: 'asc' | 'desc'
  onSort: (k: OrdenKey) => void; className?: string; destacado?: boolean
}) {
  const activo = orden === k
  return (
    <button
      onClick={() => onSort(k)}
      className={`flex items-center gap-1 text-[10.5px] font-bold uppercase tracking-wide transition-colors ${
        destacado ? 'text-danger-700' : activo ? 'text-warm-700' : 'text-warm-500 hover:text-warm-700'
      } ${className}`}
    >
      {label}
      {activo && (dir === 'desc' ? <ArrowDown size={10} /> : <ArrowUp size={10} />)}
    </button>
  )
}

// Una celda de cantidad. El cero se pinta como «—» a propósito: una columna de
// ceros compite visualmente con los números que sí importan.
function Celda({ v, tono = 'normal' }: { v: number; tono?: 'normal' | 'alerta' | 'aviso' }) {
  const vacio = !v
  const cls = vacio ? 'text-warm-300'
    : tono === 'alerta' ? 'text-danger-700 font-bold'
    : tono === 'aviso' ? 'text-gold-700 font-bold'
    : 'text-warm-700'
  return <span className={`font-mono text-[12.5px] tabular-nums text-right ${cls}`}>{fmtCant(v)}</span>
}

// ─── Componente ───────────────────────────────────────────────────────────────

/** La hora de un punto, a partir del arranque del rango y sus segundos. */
const horaDe = (desdeUtc: string | undefined, t: number) =>
  !desdeUtc ? '' : new Date(new Date(desdeUtc).getTime() + t * 1000)
    .toLocaleString('es-CO', { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' })

const NOMBRE_CAUSA: Record<string, string> = {
  entradas: 'Llegó con factura', traslados_recibidos: 'Vino de la otra sede',
  preparaciones_producidas: 'Se preparó acá', reversas: 'Se anuló una venta',
  unificaciones: 'Unificación', ventas: 'Se vendió', mermas: 'Merma y consumo',
  traslados: 'Se mandó a la otra sede', preparaciones: 'Se usó para preparar',
  reversas_salida: 'Se anuló una entrada', otras_salidas: 'Sin causa',
  ajustes_conteo: 'Ajuste de conteo', ajustes: 'Ajuste',
}

/** Una fila de la vista de barras. */
function FilaBarra({ it, span, desdeUtc, onAbrir, onGlobo }: {
  it: Insumo; span: number; desdeUtc?: string
  onAbrir: () => void
  onGlobo: (nodo: React.ReactNode | null) => void
}) {
  const ver = veredicto(it.curva?.conteos)
  const delta = it.queda - it.arranco

  const globoPunto = (p: PuntoCurva) => onGlobo(
    <>
      <b>{p.k === 'inicio' ? 'Al arrancar el período'
        : p.k === 'fin' ? 'Al cerrar'
        : p.k === 'entrada' ? `Llegaron ${num(p.c ?? 0)} ${it.unidad}`
        : p.k === 'ajuste' ? `Se aplicó un conteo: el saldo quedó en ${num(p.v)} ${it.unidad}`
        : `Salieron ${num(p.c ?? 0)} ${it.unidad}`}</b>
      {p.k !== 'inicio' && p.k !== 'fin' && <><br />{horaDe(desdeUtc, p.t)}</>}
      {p.causa && <><br /><span className="opacity-70">{NOMBRE_CAUSA[p.causa] ?? p.causa}</span></>}
      <br />Quedan <b>{num(p.v)} {it.unidad}</b>
    </>)

  const globoConteo = (c: ConteoCurva) => onGlobo(
    <>
      <b>Conteo de {c.tipos.join(' + ')}</b>{c.es_atajo && <> · atajo</>}
      <br />{horaDe(desdeUtc, c.t)}
      <br />El sistema decía <b>{num(c.sistema)}</b>
      <br />Contaron <b>{num(c.real)}</b>
      <br /><span className="opacity-75">
        {Math.abs(c.dif) <= 0.001 ? 'Coincidió exacto'
          : c.dif > 0 ? `Sobran ${num(c.dif)} ${it.unidad}`
          : `Faltan ${num(-c.dif)} ${it.unidad}`}
      </span>
    </>)

  return (
    <button
      onClick={onAbrir}
      onMouseLeave={() => onGlobo(null)}
      className="w-full text-left grid grid-cols-[minmax(140px,1.3fr)_minmax(200px,3fr)_minmax(104px,auto)]
        gap-3 items-center px-2 py-3 rounded-xl hover:bg-warm-50 transition-colors
        border-b border-warm-100 last:border-b-0"
    >
      <div className="min-w-0 flex flex-col gap-1">
        <div className="flex items-center gap-1.5 min-w-0">
          <span className="text-[13px] font-semibold text-warm-700 truncate">{it.producto}</span>
          <ChevronRight size={13} className="text-warm-300 shrink-0" />
        </div>
        <div className="flex items-center gap-1.5 flex-wrap">
          <ChipOrigen origen={it.origen} />
          <span className="text-[11px] text-warm-400">{it.unidad}</span>
          {ver && (
            <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full inline-flex items-center gap-1 ${CHIP_VEREDICTO[ver.clave]}`}>
              <i className={`w-1.5 h-1.5 rounded-full ${ver.clave === 'cuadra' ? 'bg-forest-500' : 'bg-warm-700'}`} />
              {ver.texto}
            </span>
          )}
          {it.en_negativo && (
            <span className="text-[10px] font-bold px-1.5 py-0.5 rounded-full bg-danger-100 text-danger-700">bajó de cero</span>
          )}
          {it.no_se_mide && (
            <span className="text-[10px] font-bold px-1.5 py-0.5 rounded-full bg-gold-100 text-gold-700">no se mide</span>
          )}
          {it.curva?.ancla === 'estimado' && (
            <span className="text-[10px] font-bold px-1.5 py-0.5 rounded-full bg-warm-100 text-warm-600"
              title="Antes del ajuste más viejo el libro no registra el saldo previo: ese tramo es una reconstrucción, no un dato.">
              arranque reconstruido
            </span>
          )}
        </div>
      </div>

      <div className="min-w-0">
        {it.curva
          ? <BarraInsumo curva={it.curva} span={span} onPunto={globoPunto} onConteo={globoConteo} />
          : <div className="h-[52px]" />}
      </div>

      <span className="flex flex-col items-end leading-tight">
        <span className={`font-mono text-[15px] font-bold tabular-nums ${it.en_negativo ? 'text-danger-700' : 'text-warm-700'}`}>
          {fmtCant(it.queda)} <span className="text-[10px] text-warm-400">{it.unidad}</span>
        </span>
        <span className="font-mono text-[11px] text-warm-500 tabular-nums">{firmado(delta)} en el período</span>
        {!it.cuadra && <span className="text-[10px] font-bold text-danger-600">no cierra</span>}
      </span>
    </button>
  )
}

export default function TabInsumos({ tiendaId, sedeNombre }: { tiendaId: number | null; sedeNombre: string }) {
  const [vista, setVista] = useState<Vista>('barras')
  const [periodo, setPeriodo] = useState<PeriodoKey>('mes')
  const [data, setData] = useState<Respuesta | null>(null)
  const [cargando, setCargando] = useState(true)
  const [error, setError] = useState('')

  const [q, setQ] = useState('')
  const [filtro, setFiltro] = useState<FiltroOrigen>('todos')
  const [soloMovidos, setSoloMovidos] = useState(true)
  const [orden, setOrden] = useState<OrdenKey>('valor_sin_causa')
  const [dir, setDir] = useState<'asc' | 'desc'>('desc')
  // Qué insumo tiene la ficha abierta. El rango viaja con él: la ficha
  // muestra EL MISMO período que la tabla, o los números no se corresponderían.
  const [fichaDe, setFichaDe] = useState<number | null>(null)
  // El globo del gráfico. Un gráfico en pantalla se toca: sin esto los escalones
  // son sólo una silueta. En la tablet no hay hover y por eso el detalle
  // completo vive en la ficha, no acá.
  const [globoNodo, setGloboNodo] = useState<React.ReactNode | null>(null)
  const lienzo = useRef<HTMLDivElement | null>(null)
  const globoRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    const caja = lienzo.current
    if (!caja) return
    const mover = (e: MouseEvent) => {
      const g = globoRef.current
      if (!g) return
      g.style.left = `${Math.min(e.clientX + 14, window.innerWidth - g.offsetWidth - 10)}px`
      g.style.top = `${Math.max(8, e.clientY - g.offsetHeight - 12)}px`
    }
    caja.addEventListener('mousemove', mover)
    return () => caja.removeEventListener('mousemove', mover)
  }, [vista, cargando])

  useEffect(() => {
    if (!tiendaId) return
    let cancel = false
    setCargando(true); setError('')
    const { desde, hasta } = rangoDe(periodo)
    api.get<Respuesta>('/inventario/movimiento-insumos', {
      params: { tienda_id: tiendaId, desde, hasta, con_curva: vista === 'barras' } })
      .then(r => { if (!cancel) setData(r.data) })
      .catch(() => { if (!cancel) setError('No se pudo cargar el movimiento de los insumos.') })
      .finally(() => { if (!cancel) setCargando(false) })
    return () => { cancel = true }
  }, [tiendaId, periodo, vista])

  const sortear = (k: OrdenKey) => {
    if (k === orden) { setDir(d => (d === 'desc' ? 'asc' : 'desc')); return }
    setOrden(k)
    setDir(k === 'producto' ? 'asc' : 'desc')
  }

  const filas = useMemo(() => {
    const todo = data?.insumos ?? []
    const texto = q.trim().toLowerCase()
    const filtrado = todo.filter(it => {
      if (soloMovidos && !seMovio(it)) return false
      if (filtro !== 'todos' && it.origen !== filtro) return false
      if (!texto) return true
      return it.producto.toLowerCase().includes(texto)
        || (it.proveedor ?? '').toLowerCase().includes(texto)
    })
    const signo = dir === 'desc' ? -1 : 1
    return [...filtrado].sort((a, b) => {
      if (orden === 'producto') return signo * a.producto.localeCompare(b.producto, 'es')
      const va = Number(a[orden] ?? 0), vb = Number(b[orden] ?? 0)
      if (va !== vb) return signo * (va - vb)
      return a.producto.localeCompare(b.producto, 'es')
    })
  }, [data, q, filtro, orden, dir, soloMovidos])

  // El eje horizontal es el MISMO para todas las filas: sin esto cada barra
  // escalaría a su último movimiento y el miércoles de una fila caería en un
  // sitio distinto que el de la de al lado, que es justo lo que se compara.
  const span = useMemo(() => {
    for (const it of data?.insumos ?? []) {
      const fin = it.curva?.puntos[it.curva.puntos.length - 1]
      if (fin) return fin.t
    }
    return 1
  }, [data])
  const desdeUtc = data?.desde_utc

  const r = data?.resumen
  // Cuántos se movieron en el período, del total. En «Hoy» es el número que
  // contesta «¿qué pasó en el local?» de un vistazo.
  const movidos = useMemo(() => (data?.insumos ?? []).filter(seMovio).length, [data])
  const rango = rangoDe(periodo)

  if (!tiendaId) {
    return <p className="text-sm text-warm-400 text-center py-10">Elegí una sede para ver sus insumos.</p>
  }

  return (
    <div className="flex flex-col gap-3">

      {/* ── Barra ── */}
      <div className="bg-white border border-warm-200 rounded-2xl px-4 py-3 flex flex-col gap-3">
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div className="flex flex-col gap-0.5">
            <span className="text-[15px] font-bold text-warm-700">Qué pasó con cada insumo</span>
            <span className="text-[12px] text-warm-500">
              {sedeNombre}
              {r && <> · {r.n_insumos} insumos</>}
              {r && <> · <b className="text-warm-700">{movidos} se movieron</b></>}
              {r && r.n_compra_directa > 0 && (
                <> · <b className="text-gold-700">{r.n_compra_directa} los comprás vos</b></>
              )}
              {r && r.n_en_negativo > 0 && (
                <> · <b className="text-danger-700">{r.n_en_negativo} en negativo</b></>
              )}
            </span>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
          <div className="flex gap-1 bg-warm-100 rounded-xl p-0.5">
            {([['barras', 'Barras'], ['tabla', 'Tabla']] as const).map(([k, label]) => (
              <button key={k} onClick={() => { setVista(k); setSoloMovidos(k === 'barras' || periodo === 'hoy') }} aria-pressed={vista === k}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                  vista === k ? 'bg-white text-warm-700 shadow-sm' : 'text-warm-500 hover:text-warm-700'
                }`}>
                {label}
              </button>
            ))}
          </div>
          <div className="flex gap-1 bg-warm-100 rounded-xl p-0.5">
            {PERIODOS.map(p => (
              <button key={p.k} onClick={() => { setPeriodo(p.k); setSoloMovidos(p.k === 'hoy' || vista === 'barras') }}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                  periodo === p.k ? 'bg-white text-warm-700 shadow-sm' : 'text-warm-500 hover:text-warm-700'
                }`}>
                {p.label}
              </button>
            ))}
          </div>
          </div>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          <div className="flex items-center gap-2 bg-warm-50 border border-warm-200 rounded-xl px-3 py-2 flex-1 min-w-[180px]">
            <Search size={14} className="text-warm-400 shrink-0" />
            <input
              value={q} onChange={e => setQ(e.target.value)}
              placeholder="Buscar insumo o proveedor…"
              className="flex-1 bg-transparent outline-none text-[13px] text-warm-700 placeholder:text-warm-400"
            />
          </div>
          {/* Se enciende solo al pasar a «Hoy» —donde 120 filas de guiones taparían
              las 3 que importan— pero se puede apagar: nunca se esconde una fila
              sin que el botón lo diga. */}
          <button
            onClick={() => setSoloMovidos(v => !v)}
            aria-pressed={soloMovidos}
            className={`text-[11.5px] font-bold px-3 py-2 rounded-xl border transition-colors whitespace-nowrap ${
              soloMovidos
                ? 'bg-forest-50 border-forest-100 text-forest-700'
                : 'bg-white border-warm-200 text-warm-500 hover:text-warm-700'
            }`}>
            Solo los que se movieron
          </button>
          <div className="flex gap-1 bg-warm-100 rounded-xl p-0.5">
            {([['todos', 'Todos'], ['proveedor', 'Con proveedor'], ['directa', 'Compra directa']] as const).map(([k, label]) => (
              <button key={k} onClick={() => setFiltro(k)}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                  filtro === k ? 'bg-white text-warm-700 shadow-sm' : 'text-warm-500 hover:text-warm-700'
                }`}>
                {label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* ── Titular ── */}
      {r && r.valor_sin_causa > 0 && (
        <div className="bg-white border border-warm-200 rounded-2xl px-5 py-4 flex flex-col gap-1">
          <p className="text-[21px] font-extrabold text-warm-700 leading-snug">
            <span className="font-mono text-danger-700">{fmt$(r.valor_sin_causa)}</span> salieron sin explicación
          </p>
          <span className="text-[12.5px] text-warm-500">
            en <b className="text-warm-700">{r.n_sin_causa}</b> de {r.n_insumos} insumos
            {r.n_no_se_mide > 0 && <> · <b className="text-gold-700">{r.n_no_se_mide}</b> no se miden (la caja no los descuenta)</>}
          </span>
        </div>
      )}

      {/* ── Barras ── */}
      {vista === 'barras' && (
        <div className="bg-white border border-warm-200 rounded-2xl px-3 py-2" ref={lienzo}>
          {/* Cómo se lee la barra. Es parte del dato, no decoración: sin esto la
              sombra parece un segundo color y el punto, un adorno. */}
          <div className="flex flex-wrap gap-x-5 gap-y-1.5 px-2 py-2 border-b border-warm-200 mb-1">
            <span className="inline-flex items-center gap-1.5 text-[11px] text-warm-500">
              <i className="w-4 h-2.5 rounded-sm bg-forest-500/10 border-2 border-forest-500" />
              lo que hay
            </span>
            <span className="inline-flex items-center gap-1.5 text-[11px] text-warm-500">
              <i className="w-4 h-2.5 rounded-sm bg-warm-200 border-t-2 border-dashed border-warm-400" />
              lo que se fue
            </span>
            <span className="inline-flex items-center gap-1.5 text-[11px] text-warm-500">
              <i className="w-0.5 h-3 bg-gold-500" />
              llegó mercadería
            </span>
            <span className="inline-flex items-center gap-1.5 text-[11px] text-warm-500">
              <i className="w-[9px] h-[9px] rounded-full bg-warm-700 ring-2 ring-white" />
              lo que contaron · el palito hasta la barra es la diferencia
            </span>
            <span className="inline-flex items-center gap-1.5 text-[11px] text-warm-500">
              <i className="w-4 h-0 border-t-2 border-dashed border-forest-500 opacity-70" />
              tramo reconstruido, no medido
            </span>
          </div>

          {cargando && <p className="text-sm text-warm-400 text-center py-10">Cargando…</p>}
          {!cargando && error && <p className="text-sm text-danger-700 text-center py-10">{error}</p>}
          {!cargando && !error && filas.length === 0 && (
            <p className="text-sm text-warm-400 text-center py-10">
              {periodo === 'hoy' ? 'Todavía no se movió ningún insumo hoy.' : 'Ningún insumo con ese filtro.'}
            </p>
          )}
          {!cargando && !error && filas.map(it => (
            <FilaBarra key={it.producto_id} it={it} span={span} desdeUtc={desdeUtc}
              onAbrir={() => setFichaDe(it.producto_id)} onGlobo={setGloboNodo} />
          ))}
        </div>
      )}

      {/* ── Tabla ── */}
      {vista === 'tabla' && (
      <div className="bg-white border border-warm-200 rounded-2xl px-3 py-2 overflow-x-auto">
        <div className="min-w-[1080px]">
          {/* encabezado */}
          <div className="grid grid-cols-[2fr_0.75fr_0.7fr_0.75fr_0.75fr_0.6fr_0.66fr_0.7fr_0.66fr_0.85fr_0.75fr] gap-2 items-center px-2 py-2.5 border-b-2 border-warm-200">
            <Th label="Insumo · de dónde viene" k="producto" orden={orden} dir={dir} onSort={sortear} />
            <Th label="Arrancó"  k="arranco"       orden={orden} dir={dir} onSort={sortear} className="justify-end" />
            <Th label="Pedí"     k="pedi"          orden={orden} dir={dir} onSort={sortear} className="justify-end" />
            <Th label="Entró"    k="entradas"      orden={orden} dir={dir} onSort={sortear} className="justify-end" />
            <Th label="Vendió"   k="ventas"        orden={orden} dir={dir} onSort={sortear} className="justify-end" />
            <Th label="Merma"    k="mermas"        orden={orden} dir={dir} onSort={sortear} className="justify-end" />
            <Th label="Traslado" k="traslados"     orden={orden} dir={dir} onSort={sortear} className="justify-end" />
            <Th label="Preparó"  k="preparaciones" orden={orden} dir={dir} onSort={sortear} className="justify-end" />
            <Th label="Sin causa" k="otras_salidas" orden={orden} dir={dir} onSort={sortear} className="justify-end" destacado />
            <Th label="Otros ±"  k="otros"         orden={orden} dir={dir} onSort={sortear} className="justify-end" />
            <Th label="Queda"    k="queda"         orden={orden} dir={dir} onSort={sortear} className="justify-end" />
          </div>

          {cargando && <p className="text-sm text-warm-400 text-center py-10">Cargando…</p>}
          {!cargando && error && <p className="text-sm text-danger-700 text-center py-10">{error}</p>}
          {!cargando && !error && filas.length === 0 && (
            <p className="text-sm text-warm-400 text-center py-10">
              {soloMovidos && !q && filtro === 'todos'
                ? (periodo === 'hoy'
                    ? 'Todavía no se movió ningún insumo hoy.'
                    : 'Ningún insumo se movió en este período.')
                : q || filtro !== 'todos' ? 'Ningún insumo con ese filtro.' : 'Sin movimiento en el período.'}
            </p>
          )}

          {!cargando && !error && filas.map(it => {
            const alerta = it.otras_salidas > 0
            return (
              <div key={it.producto_id}>
                <button
                  onClick={() => setFichaDe(it.producto_id)}
                  className={`w-full text-left grid grid-cols-[2fr_0.75fr_0.7fr_0.75fr_0.75fr_0.6fr_0.66fr_0.7fr_0.66fr_0.85fr_0.75fr] gap-2 items-center px-2 py-2.5 rounded-lg transition-colors ${
                    alerta ? 'bg-danger-50/60 hover:bg-danger-50' : it.no_se_mide ? 'bg-gold-50/50 hover:bg-gold-50' : 'hover:bg-warm-50'
                  }`}
                >
                  <div className="min-w-0">
                    <div className="flex items-center gap-1.5">
                      <span className="text-[13px] font-semibold text-warm-700 truncate">{it.producto}</span>
                      <span className="text-[11px] text-warm-400 shrink-0">{it.unidad}</span>
                      <ChevronRight size={13} className="text-warm-300 shrink-0" />
                    </div>
                    <div className="flex items-center gap-1.5 mt-1">
                      <ChipOrigen origen={it.origen} />
                      {it.proveedor && <span className="text-[11px] text-warm-500 truncate">{it.proveedor}</span>}
                    </div>
                  </div>
                  {/* Lo que había al empezar. Es el término que faltaba: sin él,
                      «entró 180, vendió 167, queda 70» no da, y el que hace la
                      resta de cabeza concluye que el sistema está mal. */}
                  <span className="flex flex-col items-end leading-tight">
                    <Celda v={it.arranco} />
                    {it.arranque_estimado && (
                      <span className="text-[10px] text-warm-400">estimado</span>
                    )}
                  </span>
                  {/* Pedí vs. Entró, una al lado de la otra: es la comparación
                      que el dueño vino a buscar. Cuando pidió y llegó de menos,
                      el faltante va abajo en chico — el número solo no dice
                      nada, y hacer la resta de cabeza en una tabla de 120 filas
                      es exactamente lo que la pantalla vino a evitar. */}
                  <span className="flex flex-col items-end leading-tight">
                    <Celda v={it.pedi} />
                    {it.pedi > 0 && it.entradas < it.pedi && (
                      <span className="font-mono text-[10px] text-gold-600 tabular-nums">
                        faltó {fmtCant(it.pedi - it.entradas)}
                      </span>
                    )}
                    {it.pedi === 0 && Object.keys(it.pedi_otras_unidades).length > 0 && (
                      <span className="text-[10px] text-warm-400">otra unidad</span>
                    )}
                  </span>
                  <Celda v={it.entradas} />
                  <span className="flex items-center justify-end gap-1">
                    {it.no_se_mide && <AlertTriangle size={11} className="text-gold-600 shrink-0" />}
                    <Celda v={it.ventas} tono={it.no_se_mide ? 'aviso' : 'normal'} />
                  </span>
                  <Celda v={it.mermas} />
                  <Celda v={it.traslados} />
                  <Celda v={it.preparaciones} />
                  <span className="flex flex-col items-end leading-tight">
                    <Celda v={it.otras_salidas} tono={alerta ? 'alerta' : 'normal'} />
                    {alerta && <span className="font-mono text-[10px] text-danger-500 tabular-nums">{fmt$(it.valor_sin_causa)}</span>}
                  </span>
                  {/* Lo que mueve el saldo sin estar en el arco: traslados recibidos,
                      lo producido acá, anulaciones, unificaciones y ajustes. En una
                      columna y no en cinco, porque son raros; el desglose está en la
                      ficha. Sin esta columna la mezcla de granizado sube 3.400 gr
                      con «entró 0» al lado. */}
                  <span className="flex flex-col items-end leading-tight">
                    <Celda v={it.otros} />
                    {!it.cuadra && (
                      <span className="text-[10px] font-bold text-danger-600">no cierra</span>
                    )}
                  </span>
                  {/* Un «queda» negativo no se pinta como un número más: es el
                      único dato de esta tabla que es imposible, y por lo tanto
                      una certeza de que falta registrar algo. */}
                  <span className="flex flex-col items-end leading-tight">
                    <Celda v={it.queda} tono={it.en_negativo ? 'alerta' : 'normal'} />
                    {it.en_negativo && (
                      <span className="text-[10px] font-bold text-danger-600">menos que cero</span>
                    )}
                  </span>
                </button>
              </div>
            )
          })}
        </div>
      </div>
      )}

      {/* Una columna de ceros sin explicación se lee como un bug, y en los
          períodos anteriores a que «Armar pedido» guardara lo que manda, «Pedí»
          es cero para todo. Se dice por qué, en vez de dejar al dueño
          preguntándose si el sistema perdió sus pedidos. */}
      {!cargando && !error && r && r.n_con_pedido === 0 && filas.length > 0 && (
        <p className="text-[11.5px] text-warm-500 bg-warm-50 border border-warm-200 rounded-xl px-3 py-2 leading-relaxed">
          <b>«Pedí» está en cero en todo el período.</b> Los pedidos quedan escritos desde que se
          mandan con el botón «Pedir a…» de la pestaña <b>Pedido</b>. Lo de antes se iba por
          WhatsApp sin pasar por acá, y no hay forma de recuperarlo.
        </p>
      )}

      {globoNodo && (
        <div ref={globoRef} role="status" aria-live="polite"
          className="fixed z-50 pointer-events-none bg-warm-700 text-warm-50 rounded-lg px-3 py-2
            text-[12px] leading-snug max-w-[270px] shadow-lg">
          {globoNodo}
        </div>
      )}

      {vista === 'barras' && !cargando && !error && filas.length > 0 && (
        <p className="text-[11.5px] text-warm-500 bg-warm-50 border border-warm-200 rounded-xl px-3 py-2 leading-relaxed">
          <b>Cada fila tiene su propia escala vertical.</b> Un insumo se mide en gramos y otro en
          unidades: una escala compartida diría que el café es mil veces más importante que las
          pulpas, y es otra unidad. Lo comparable entre filas es <b>la forma</b> —si baja parejo,
          si se agota, si el conteo se despega siempre para el mismo lado—; las cantidades van
          escritas. Tocá una fila para abrir su ficha.
        </p>
      )}

      {/* La cuenta que la tabla permite hacer, escrita. Antes faltaban «arrancó» y
          «otros», y por eso una fila como «entró 180, vendió 167, queda 70» no
          daba: los 57 de diferencia eran lo que ya había en el estante. */}
      {vista === 'tabla' && (
      <p className="text-[12px] text-warm-600 bg-warm-50 border border-warm-200 rounded-xl px-3 py-2 leading-relaxed">
        <b>Cada fila cierra:</b> <span className="font-mono">arrancó + entró + otros − vendió − merma − traslado − preparó − sin causa = queda</span>.
        <b> «Otros ±»</b> junta lo que mueve el saldo sin ser una compra ni una salida normal —lo que
        vino de la otra sede, lo que se preparó acá, anulaciones y ajustes de conteo—; abrí la ficha
        para ver de qué está hecho.
      </p>
      )}

      {vista === 'tabla' && (
      <p className="text-[11.5px] text-warm-400 leading-relaxed px-1">
        <b>«Pedí»</b> = lo que mandaste por escrito a un proveedor, en la unidad del insumo. Al lado va
        lo que <b>entró</b>: la resta entre las dos es lo que no te trajeron.
        <b> «Comprás vos»</b> = lo traés del supermercado, sin pedido ni precio acordado — ahí lo que salió es tu lista de mercado.
        Tocá una columna para ordenar, una fila para abrir su ficha. Los <b>ajustes de conteo</b> no entran en lo que salió:
        no son una causa, son faltante viejo que apareció al contar.
      </p>
      )}

      {/* La fila viaja con la ficha. No es un caché: es EXACTAMENTE el mismo
          objeto que la ficha va a recibir en `resumen` —la arma la misma función
          del backend— así que abre con sus números puestos y solo espera el
          detalle. Antes tapaba todo con «Cargando…» durante ~2 segundos para
          después mostrar cifras que ya estaban en la pantalla de atrás. */}
      {fichaDe !== null && tiendaId && (
        <FichaInsumo
          productoId={fichaDe} tiendaId={tiendaId}
          desde={rango.desde} hasta={rango.hasta}
          filaPrevia={data?.insumos.find(i => i.producto_id === fichaDe)}
          onClose={() => setFichaDe(null)}
        />
      )}
    </div>
  )
}
