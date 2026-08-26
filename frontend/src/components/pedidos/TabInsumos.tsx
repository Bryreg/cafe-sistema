import { useEffect, useMemo, useState } from 'react'
import api from '../../api/client'
import {
  AlertTriangle, ArrowDown, ArrowUp, Info, Search, Package, ChevronRight,
} from 'lucide-react'

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

interface Insumo {
  producto_id: number
  producto: string
  unidad: string
  categoria: string | null
  proveedor: string | null
  origen: Origen
  entradas: number
  traslados_recibidos: number
  preparaciones_producidas: number
  ventas: number
  mermas: number
  traslados: number
  preparaciones: number
  reversas_salida: number
  otras_salidas: number
  total_salio: number
  ajustes_conteo: number
  ajustes: number
  queda: number
  valor_unitario: number
  valor_sin_causa: number
  arranque_estimado: boolean
  no_se_mide: boolean
}

interface Resumen {
  n_insumos: number
  n_sin_causa: number
  valor_sin_causa: number
  n_no_se_mide: number
  n_compra_directa: number
}

interface Respuesta { insumos: Insumo[]; resumen: Resumen }

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

type PeriodoKey = 'mes' | 'ocho' | 'anterior'

function rangoDe(k: PeriodoKey): { desde: string; hasta: string } {
  const hoy = new Date()
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
  { k: 'mes', label: 'Este mes' },
  { k: 'ocho', label: 'Últimas 8 semanas' },
  { k: 'anterior', label: 'Mes pasado' },
]

type OrdenKey = 'valor_sin_causa' | 'entradas' | 'ventas' | 'mermas' | 'traslados'
  | 'preparaciones' | 'otras_salidas' | 'queda' | 'producto'

type FiltroOrigen = 'todos' | 'proveedor' | 'directa'

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

/** Lo que la fila no muestra en columnas: lo que entró sin comprarse, el ajuste
 *  de conteo (que NO es una salida) y las advertencias de confianza. */
function Detalle({ it }: { it: Insumo }) {
  const nada = !it.traslados_recibidos && !it.preparaciones_producidas
    && !it.ajustes_conteo && !it.ajustes && !it.reversas_salida
  return (
    <div className="col-span-full bg-warm-50 rounded-xl px-4 py-3 mt-1 mb-2 flex flex-col gap-2.5">
      {it.no_se_mide && (
        <div className="flex items-start gap-2 text-[12px] text-gold-700 font-semibold">
          <AlertTriangle size={14} className="shrink-0 mt-px" />
          <span>Este insumo no se descuenta al vender. El <b>0</b> de «vendió» no significa que no se usó — significa que nadie lo está midiendo.</span>
        </div>
      )}
      {it.arranque_estimado && (
        <div className="flex items-start gap-2 text-[12px] text-warm-500">
          <Info size={14} className="shrink-0 mt-px" />
          <span>El arranque del período es un cálculo, no un dato: nadie registró cuánto había antes.</span>
        </div>
      )}

      {!nada && (
        <div className="flex flex-wrap gap-x-8 gap-y-2">
          {(it.traslados_recibidos > 0 || it.preparaciones_producidas > 0) && (
            <div className="flex flex-col gap-1">
              <span className="text-[10px] font-bold uppercase tracking-wide text-warm-400">Entró sin comprarse</span>
              {it.traslados_recibidos > 0 && (
                <span className="text-[12px] text-warm-600">Vino de la otra sede <b className="font-mono">{fmtCant(it.traslados_recibidos)} {it.unidad}</b></span>
              )}
              {it.preparaciones_producidas > 0 && (
                <span className="text-[12px] text-warm-600">Se produjo acá <b className="font-mono">{fmtCant(it.preparaciones_producidas)} {it.unidad}</b></span>
              )}
            </div>
          )}
          {it.reversas_salida > 0 && (
            <div className="flex flex-col gap-1">
              <span className="text-[10px] font-bold uppercase tracking-wide text-warm-400">Correcciones de papeles</span>
              <span className="text-[12px] text-warm-600">No salió mercadería <b className="font-mono">{fmtCant(it.reversas_salida)} {it.unidad}</b></span>
            </div>
          )}
          {(it.ajustes_conteo !== 0 || it.ajustes !== 0) && (
            <div className="flex flex-col gap-1">
              <span className="text-[10px] font-bold uppercase tracking-wide text-warm-400">Aparte · no salió ahora</span>
              {it.ajustes_conteo !== 0 && (
                <span className="text-[12px] text-warm-600">
                  Ajuste de conteo <b className="font-mono">{fmtCant(it.ajustes_conteo)} {it.unidad}</b>
                  <span className="text-warm-400"> · faltante viejo que apareció al contar</span>
                </span>
              )}
              {it.ajustes !== 0 && (
                <span className="text-[12px] text-warm-600">Ajuste manual <b className="font-mono">{fmtCant(it.ajustes)} {it.unidad}</b></span>
              )}
            </div>
          )}
        </div>
      )}

      {nada && !it.no_se_mide && !it.arranque_estimado && (
        <span className="text-[12px] text-warm-400">Sin nada más que contar: todo lo que se movió está en las columnas.</span>
      )}
    </div>
  )
}

// ─── Componente ───────────────────────────────────────────────────────────────

export default function TabInsumos({ tiendaId, sedeNombre }: { tiendaId: number | null; sedeNombre: string }) {
  const [periodo, setPeriodo] = useState<PeriodoKey>('mes')
  const [data, setData] = useState<Respuesta | null>(null)
  const [cargando, setCargando] = useState(true)
  const [error, setError] = useState('')

  const [q, setQ] = useState('')
  const [filtro, setFiltro] = useState<FiltroOrigen>('todos')
  const [orden, setOrden] = useState<OrdenKey>('valor_sin_causa')
  const [dir, setDir] = useState<'asc' | 'desc'>('desc')
  const [abierto, setAbierto] = useState<number | null>(null)

  useEffect(() => {
    if (!tiendaId) return
    let cancel = false
    setCargando(true); setError('')
    const { desde, hasta } = rangoDe(periodo)
    api.get<Respuesta>('/inventario/movimiento-insumos', { params: { tienda_id: tiendaId, desde, hasta } })
      .then(r => { if (!cancel) setData(r.data) })
      .catch(() => { if (!cancel) setError('No se pudo cargar el movimiento de los insumos.') })
      .finally(() => { if (!cancel) setCargando(false) })
    return () => { cancel = true }
  }, [tiendaId, periodo])

  const sortear = (k: OrdenKey) => {
    if (k === orden) { setDir(d => (d === 'desc' ? 'asc' : 'desc')); return }
    setOrden(k)
    setDir(k === 'producto' ? 'asc' : 'desc')
  }

  const filas = useMemo(() => {
    const todo = data?.insumos ?? []
    const texto = q.trim().toLowerCase()
    const filtrado = todo.filter(it => {
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
  }, [data, q, filtro, orden, dir])

  const r = data?.resumen

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
              {r && r.n_compra_directa > 0 && (
                <> · <b className="text-gold-700">{r.n_compra_directa} los comprás vos</b></>
              )}
            </span>
          </div>
          <div className="flex gap-1 bg-warm-100 rounded-xl p-0.5">
            {PERIODOS.map(p => (
              <button key={p.k} onClick={() => setPeriodo(p.k)}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                  periodo === p.k ? 'bg-white text-warm-700 shadow-sm' : 'text-warm-500 hover:text-warm-700'
                }`}>
                {p.label}
              </button>
            ))}
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

      {/* ── Tabla ── */}
      <div className="bg-white border border-warm-200 rounded-2xl px-3 py-2 overflow-x-auto">
        <div className="min-w-[860px]">
          {/* encabezado */}
          <div className="grid grid-cols-[2.4fr_0.8fr_0.8fr_0.62fr_0.7fr_0.75fr_0.9fr_0.8fr] gap-2 items-center px-2 py-2.5 border-b-2 border-warm-200">
            <Th label="Insumo · de dónde viene" k="producto" orden={orden} dir={dir} onSort={sortear} />
            <Th label="Entró"    k="entradas"      orden={orden} dir={dir} onSort={sortear} className="justify-end" />
            <Th label="Vendió"   k="ventas"        orden={orden} dir={dir} onSort={sortear} className="justify-end" />
            <Th label="Merma"    k="mermas"        orden={orden} dir={dir} onSort={sortear} className="justify-end" />
            <Th label="Traslado" k="traslados"     orden={orden} dir={dir} onSort={sortear} className="justify-end" />
            <Th label="Preparó"  k="preparaciones" orden={orden} dir={dir} onSort={sortear} className="justify-end" />
            <Th label="Sin causa" k="otras_salidas" orden={orden} dir={dir} onSort={sortear} className="justify-end" destacado />
            <Th label="Queda"    k="queda"         orden={orden} dir={dir} onSort={sortear} className="justify-end" />
          </div>

          {cargando && <p className="text-sm text-warm-400 text-center py-10">Cargando…</p>}
          {!cargando && error && <p className="text-sm text-danger-700 text-center py-10">{error}</p>}
          {!cargando && !error && filas.length === 0 && (
            <p className="text-sm text-warm-400 text-center py-10">
              {q || filtro !== 'todos' ? 'Ningún insumo con ese filtro.' : 'Sin movimiento en el período.'}
            </p>
          )}

          {!cargando && !error && filas.map(it => {
            const abiertoEsta = abierto === it.producto_id
            const alerta = it.otras_salidas > 0
            return (
              <div key={it.producto_id}>
                <button
                  onClick={() => setAbierto(abiertoEsta ? null : it.producto_id)}
                  className={`w-full text-left grid grid-cols-[2.4fr_0.8fr_0.8fr_0.62fr_0.7fr_0.75fr_0.9fr_0.8fr] gap-2 items-center px-2 py-2.5 rounded-lg transition-colors ${
                    alerta ? 'bg-danger-50/60 hover:bg-danger-50' : it.no_se_mide ? 'bg-gold-50/50 hover:bg-gold-50' : 'hover:bg-warm-50'
                  } ${abiertoEsta ? 'ring-1 ring-warm-200' : ''}`}
                >
                  <div className="min-w-0">
                    <div className="flex items-center gap-1.5">
                      <span className="text-[13px] font-semibold text-warm-700 truncate">{it.producto}</span>
                      <span className="text-[11px] text-warm-400 shrink-0">{it.unidad}</span>
                      <ChevronRight size={13} className={`text-warm-300 shrink-0 transition-transform ${abiertoEsta ? 'rotate-90' : ''}`} />
                    </div>
                    <div className="flex items-center gap-1.5 mt-1">
                      <ChipOrigen origen={it.origen} />
                      {it.proveedor && <span className="text-[11px] text-warm-500 truncate">{it.proveedor}</span>}
                    </div>
                  </div>
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
                  <Celda v={it.queda} />
                </button>
                {abiertoEsta && <Detalle it={it} />}
              </div>
            )
          })}
        </div>
      </div>

      <p className="text-[11.5px] text-warm-400 leading-relaxed px-1">
        <b>«Comprás vos»</b> = lo traés del supermercado, sin pedido ni precio acordado — ahí lo que salió es tu lista de mercado.
        Tocá una columna para ordenar, una fila para ver el detalle. Los <b>ajustes de conteo</b> no entran en lo que salió:
        no son una causa, son faltante viejo que apareció al contar.
      </p>
    </div>
  )
}
