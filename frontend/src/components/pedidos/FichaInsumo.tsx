import { useEffect, useState } from 'react'
import api from '../../api/client'
import { AlertTriangle, Info, X, FileText, ArrowDown, ArrowUp, Clock } from 'lucide-react'

/**
 * La ficha de UN insumo: qué hacía falta, qué llegó, por dónde salió y qué
 * queda, más los movimientos uno por uno.
 *
 * Los totales NO se calculan acá: vienen de `/inventario/insumo/{id}/ficha`, que
 * los arma con la misma función que la tabla. Esta pantalla solo los ordena y
 * los pone en castellano.
 *
 * Tres cosas que la ficha DICE en vez de dejar un número mudo, y que son la
 * razón de que tenga tanto texto:
 *  · «Pedí vs. llegó» solo cuenta lo que el DUEÑO pidió por escrito y en la
 *    unidad del insumo. Lo que la barista pide por el kiosko va aparte, en la
 *    bitácora: viene en unidades que cambian semana a semana para el mismo
 *    producto (el azúcar aparece como «2 bolsa», «2 unidad» y «5000 gr»), y
 *    sumarlo daría un número falso con toda la pinta de ser cierto.
 *  · «Hacía falta» convive con «pedí» y no lo reemplaza. Uno es el cálculo del
 *    sistema y el otro la decisión del dueño; la diferencia entre los dos es su
 *    criterio de compra, y aplanarla en una sola cifra lo escondería.
 *  · Un 0 en «se vendió» puede significar dos cosas opuestas —no se vendió, o
 *    nadie lo está midiendo—, así que cuando es lo segundo se dice con todas
 *    las letras.
 */

// ─── Types ────────────────────────────────────────────────────────────────────

/** UNA fila de «qué pasó con este insumo».
 *
 *  Se exporta y la tabla la reusa (`TabInsumos`) porque las dos pantallas leen
 *  literalmente la misma fila: el backend la arma en `_fila_insumo`, compartida
 *  entre `/movimiento-insumos` y `/insumo/{id}/ficha`. Dos interfaces separadas
 *  para la misma fila es cómo empiezan a divergir dos pantallas que juraron
 *  decir lo mismo. */
export interface Resumen {
  producto_id: number
  producto: string; unidad: string; categoria: string | null
  proveedor: string | null
  origen: 'proveedor' | 'directa' | 'sin_origen'
  pedi: number; pedi_n_pedidos: number; pedi_proveedores: string[]
  pedi_otras_unidades: Record<string, number>
  entradas: number; traslados_recibidos: number; preparaciones_producidas: number
  ventas: number; mermas: number; traslados: number; preparaciones: number
  reversas_salida: number; otras_salidas: number; total_salio: number
  ajustes_conteo: number; ajustes: number; queda: number
  valor_unitario: number; valor_origen: string | null
  valor_sin_causa: number; valor_total_salio: number
  arranque_estimado: boolean; no_se_mide: boolean
  /** El stock quedó por debajo de cero. No es «se acabó»: es imposible, y por
   *  eso es una certeza y no una sospecha — falta registrar algo. */
  en_negativo: boolean
}
interface HaciaFalta {
  para_reponer: number; se_compro: number; hoy_hay_que_pedir: number | null
  empaques_sugeridos: number | null; contenido_por_empaque: number | null
  consumo_diario: number | null; estado: string | null; accion: string | null
  tandas_sugeridas: number | null; stock_minimo: number | null
}
interface FacturaLinea {
  factura_id: number; fecha: string | null; proveedor: string | null
  numero_factura: string | null; cantidad: number
  precio_unitario: number | null; total: number | null
}
interface Llego {
  facturas: FacturaLinea[]; con_factura: number; sin_papel: number
  vino_de_la_otra_sede: number; se_produjo_aca: number
}
interface PedidoEscrito {
  solicitud_id: number; fecha: string | null; cantidad: number
  unidad: string; estado: string
  origen: 'kiosko' | 'admin'
  proveedor: string | null
}
interface PediLlego {
  pedi: number; n_pedidos: number; proveedores: string[]
  en_otra_unidad: Record<string, number>
  llego_con_factura: number
  /** Positivo = trajeron de menos. Contra lo que entró CON FACTURA: la
   *  mercadería cargada a mano no respalda ningún pedido. */
  diferencia: number
}
interface Movimiento {
  id: number; fecha: string | null; tipo: string; cantidad: number
  motivo: string | null; causa: string; barista: string | null
}
interface Ficha {
  producto: { id: number; nombre: string; unidad: string; proveedor: string | null; origen: string; contenido_por_empaque: number | null }
  periodo: { desde: string; hasta: string }
  resumen: Resumen
  hacia_falta: HaciaFalta
  pedi_llego: PediLlego
  llego: Llego
  pedido_escrito: PedidoEscrito[]
  movimientos: Movimiento[]
  movimientos_total: number
  movimientos_truncados: boolean
  causas: Record<string, number>
  causa_filtrada: string | null
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

const fmt$ = (v: number) => `$${Math.round(v || 0).toLocaleString('es-CO')}`
const fmtC = (v: number) => {
  const n = Number(v || 0)
  const abs = Math.abs(n)
  return abs < 10 && !Number.isInteger(n)
    ? n.toLocaleString('es-CO', { maximumFractionDigits: 2 })
    : Math.round(n).toLocaleString('es-CO')
}
const fmtFecha = (s: string | null) => {
  if (!s) return '—'
  const [a, m, d] = s.slice(0, 10).split('-')
  const MES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic']
  return `${d} ${MES[Number(m) - 1] ?? m}${a ? '' : ''}`
}

/** Los renglones de «salió», en el idioma del dueño. «Sin causa» va primero
 *  porque es lo único que merece investigarse; el resto solo si es distinto de
 *  cero (una lista de ceros compite con lo que sí pasó). */
const RENGLONES: { k: keyof Resumen; label: string; siempre?: boolean; alerta?: boolean }[] = [
  { k: 'otras_salidas',   label: 'Salió sin causa registrada', alerta: true },
  { k: 'ventas',          label: 'Se vendió', siempre: true },
  { k: 'preparaciones',   label: 'Se usó para preparar' },
  { k: 'mermas',          label: 'Se lo tomó el personal o se dañó' },
  { k: 'traslados',       label: 'Se mandó a la otra sede' },
  { k: 'reversas_salida', label: 'Correcciones de papeles (no salió mercadería)' },
]

const CAUSA_LABEL: Record<string, string> = {
  ventas: 'Venta', mermas: 'Merma o consumo', traslados: 'Traslado',
  preparaciones: 'Preparación', otras_salidas: 'Sin causa',
  reversas_salida: 'Corrección', entradas: 'Compra',
  traslados_recibidos: 'Recibo de traslado', preparaciones_producidas: 'Se produjo',
  ajustes_conteo: 'Ajuste de conteo', ajustes: 'Ajuste manual',
  reversas: 'Reversa', unificaciones: 'Unificación',
}

function Bloque({ titulo, children }: { titulo: string; children: React.ReactNode }) {
  return (
    <div className="bg-white border border-warm-200 rounded-2xl px-4 py-3.5 flex flex-col gap-2.5">
      <span className="text-[10.5px] font-bold uppercase tracking-wider text-warm-500">{titulo}</span>
      {children}
    </div>
  )
}

// ─── Componente ───────────────────────────────────────────────────────────────

export default function FichaInsumo({
  productoId, tiendaId, desde, hasta, onClose, filaPrevia,
}: {
  productoId: number; tiendaId: number; desde: string; hasta: string
  onClose: () => void
  /** La fila de la tabla desde la que se abrió esta ficha, si vino de ahí.
   *
   *  No es un caché ni un adelanto aproximado: es EXACTAMENTE el mismo objeto
   *  que va a llegar en `resumen` —lo arma la misma función del backend, y hay
   *  un test que lo compara clave por clave—. Sirve para que la ficha abra con
   *  sus números puestos en vez de un cartel de «Cargando…» sobre el vacío: el
   *  detalle (facturas, movimientos, pedidos) es lo único que hay que esperar.
   *
   *  Cuando llega la respuesta, MANDA la respuesta. La fila previa es del
   *  instante del clic; si algo cambió mientras tanto, lo que vale es lo que
   *  acaba de contestar el servidor. */
  filaPrevia?: Resumen
}) {
  const [d, setD] = useState<Ficha | null>(null)
  const [cargando, setCargando] = useState(true)
  const [error, setError] = useState('')
  // Filtro de la lista de movimientos. Existe porque un insumo de alta rotación
  // tiene miles y casi todos son ventas de a 10 gr: sin esto, los más recientes
  // TAPAN lo que se vino a mirar (el café real tiene 2.561 en dos meses, y sus
  // 250 últimos son 239 ventas).
  const [causa, setCausa] = useState<string | null>(null)

  useEffect(() => {
    let cancel = false
    setCargando(true); setError('')
    api.get<Ficha>(`/inventario/insumo/${productoId}/ficha`, {
      params: { tienda_id: tiendaId, desde, hasta, ...(causa ? { causa } : {}) },
    })
      .then(r => { if (!cancel) setD(r.data) })
      .catch(() => { if (!cancel) setError('No se pudo cargar la ficha de este insumo.') })
      .finally(() => { if (!cancel) setCargando(false) })
    return () => { cancel = true }
  }, [productoId, tiendaId, desde, hasta, causa])

  // Escape cierra: el panel tapa la tabla y quedarse encerrado es peor en tablet.
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [onClose])

  // La respuesta manda; la fila del clic solo cubre el hueco mientras llega.
  const r = d?.resumen ?? filaPrevia
  const pl = d?.pedi_llego
  const u = r?.unidad ?? ''
  const nombre = d?.producto.nombre ?? filaPrevia?.producto
  // Nunca hubo nada que mostrar: se abrió sin fila previa y todavía no llegó.
  const enBlanco = !r

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/25 px-2 py-4 sm:px-4 sm:py-8"
         onClick={onClose}>
      <div className="w-full max-w-[880px] flex flex-col gap-3" onClick={e => e.stopPropagation()}>

        {/* ── Cabecera ── */}
        <div className="bg-white border border-warm-200 rounded-2xl px-4 py-3 flex items-start justify-between gap-3 sticky top-0 z-10">
          <div className="flex flex-col gap-1 min-w-0">
            <span className="text-[16px] font-bold text-warm-700 truncate">{nombre ?? 'Cargando…'}</span>
            <div className="flex items-center gap-2 flex-wrap">
              {r && (
                <span className={`text-[10.5px] font-bold px-2 py-0.5 rounded-full ${
                  r.origen === 'directa' ? 'bg-gold-50 text-gold-700'
                  : r.origen === 'proveedor' ? 'bg-forest-50 text-forest-700'
                  : 'bg-warm-100 text-warm-500'}`}>
                  {r.origen === 'directa' ? 'comprás vos' : r.origen === 'proveedor' ? 'proveedor' : 'sin origen'}
                </span>
              )}
              {r?.proveedor && <span className="text-[11.5px] text-warm-500">{r.proveedor}</span>}
              {r && <span className="text-[11.5px] text-warm-400">· se mide en {u}</span>}
            </div>
          </div>
          <button onClick={onClose} aria-label="Cerrar"
            className="shrink-0 w-9 h-9 rounded-full bg-warm-50 border border-warm-200 flex items-center justify-center text-warm-500 hover:bg-warm-100 transition-colors">
            <X size={16} />
          </button>
        </div>

        {/* El cartel de carga a pantalla completa queda SOLO para el caso en que
            de verdad no hay nada que mostrar (una ficha abierta sin venir de la
            tabla). Cuando se abrió desde una fila, sus números ya están acá y
            taparlos con «Cargando…» era esconder lo que el dueño vino a ver. */}
        {cargando && enBlanco && <div className="bg-white border border-warm-200 rounded-2xl py-14 text-center text-sm text-warm-400">Cargando…</div>}
        {!cargando && error && <div className="bg-white border border-warm-200 rounded-2xl py-14 text-center text-sm text-danger-700">{error}</div>}

        {r && !error && (
          <>
            {/* ── 1 · El titular ── */}
            <div className="bg-white border border-warm-200 rounded-2xl px-5 py-4 flex flex-col gap-2">
              <p className="text-[20px] sm:text-[23px] font-extrabold text-warm-700 leading-snug">
                Salieron <span className="font-mono text-danger-700">{fmtC(r.total_salio)} {u}</span>,
                {' '}entraron <span className="font-mono text-forest-700">{fmtC(r.entradas)} {u}</span>
                {' '}y quedan <span className="font-mono">{fmtC(r.queda)} {u}</span>
              </p>
              {r.valor_total_salio > 0 && (
                <span className="text-[12.5px] text-warm-500">
                  Eso son <b className="font-mono text-warm-700">{fmt$(r.valor_total_salio)}</b> que salieron del estante
                </span>
              )}
              {r.otras_salidas > 0 && (
                <div className="flex items-center gap-2 bg-danger-50 border border-danger-100 rounded-xl px-3 py-2.5">
                  <AlertTriangle size={16} className="text-danger shrink-0" />
                  <span className="text-[13px] font-bold text-danger-700">
                    Hay <span className="font-mono">{fmtC(r.otras_salidas)} {u}</span> que salieron sin que nadie anotara por qué
                    {r.valor_sin_causa > 0 && <> — <span className="font-mono">{fmt$(r.valor_sin_causa)}</span></>}
                  </span>
                </div>
              )}
            </div>

            {/* ── 2 · Carteles de honestidad ── */}
            {/* El negativo va PRIMERO y en rojo: los otros dos carteles avisan de
                algo que puede estar mal; este es aritmética. Menos que cero no
                existe en una nevera. */}
            {r.en_negativo && (
              <div className="bg-danger-50 border border-danger-200 rounded-2xl px-4 py-3 flex items-start gap-2.5">
                <AlertTriangle size={18} className="text-danger shrink-0 mt-px" />
                <div className="flex flex-col gap-0.5">
                  <span className="text-[13.5px] font-extrabold text-danger-700">
                    El sistema dice que hay menos que cero
                  </span>
                  <span className="text-[12.5px] text-danger-700 leading-relaxed">
                    Eso no puede pasar en el estante, así que el libro está incompleto. Son dos
                    cosas y solo dos: <b>entró mercadería que nadie registró</b>, o <b>una receta
                    está descontando este insumo cuando debería descontar otro</b>. No es que se
                    haya acabado — mirá los movimientos de abajo.
                  </span>
                </div>
              </div>
            )}
            {r.no_se_mide && (
              <div className="bg-gold-50 border border-gold-200 rounded-2xl px-4 py-3 flex items-start gap-2.5">
                <AlertTriangle size={18} className="text-gold-700 shrink-0 mt-px" />
                <div className="flex flex-col gap-0.5">
                  <span className="text-[13.5px] font-extrabold text-gold-700">Este insumo no se descuenta cuando se vende</span>
                  <span className="text-[12.5px] text-gold-700 leading-relaxed">
                    La caja no lo resta. El <b>0</b> de «se vendió» no significa que no se usó — significa que nadie lo está midiendo.
                  </span>
                </div>
              </div>
            )}
            {r.arranque_estimado && (
              <div className="bg-warm-100 border border-warm-200 rounded-2xl px-4 py-2.5 flex items-start gap-2.5">
                <Info size={15} className="text-warm-500 shrink-0 mt-px" />
                <span className="text-[12.5px] text-warm-600">
                  El arranque del período es un cálculo, no un dato: nadie registró cuánto había antes.
                </span>
              </div>
            )}

            {/* Los cuatro bloques de arriba salen de la fila que la tabla ya
                tenía: se dibujan en el mismo instante del clic. Los de acá abajo
                necesitan la respuesta —facturas una por una, pedidos escritos,
                el motor de consumo— y hasta que llega va este hueco, del alto
                aproximado de lo que viene, para que nada salte cuando aparezca. */}
            {!d ? (
              <div className="bg-white border border-warm-200 rounded-2xl px-4 py-10 flex flex-col items-center gap-1.5">
                <span className="text-[13px] text-warm-400 animate-pulse">Buscando el detalle…</span>
                <span className="text-[11.5px] text-warm-400">pedidos, facturas y movimiento por movimiento</span>
              </div>
            ) : (
              <>
              {/* ── 3 · Pedí vs. llegó ── */}
              {/* La pregunta que motivó guardar el pedido: ¿trajeron lo que pedí?
                  Se compara contra lo que entró CON FACTURA y no contra todo lo que
                  entró: la mercadería cargada a mano no respalda un pedido, y
                  contarla haría cuadrar entregas que nadie hizo. */}
              <Bloque titulo="Pedí vs. llegó">
                {!pl ? null : pl.pedi === 0 ? (
                  <span className="text-[12.5px] text-warm-500 leading-relaxed">
                    {Object.keys(pl.en_otra_unidad).length > 0 ? (
                      <>
                        Se pidió <b className="font-mono">
                          {Object.entries(pl.en_otra_unidad).map(([un, c]) => `${fmtC(c)} ${un}`).join(' · ')}
                        </b>, en una unidad distinta a la del insumo ({u}). No se resta contra lo que
                        llegó porque no son la misma cosa, pero se dice para que el cero de arriba no
                        se lea como «no pediste nada».
                      </>
                    ) : (
                      <>No le pediste este insumo a ningún proveedor en este período. Los pedidos
                      quedan escritos desde que se mandan con el botón «Pedir a…» de la pestaña
                      Pedido.</>
                    )}
                  </span>
                ) : (
                  <>
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
                      <div className="bg-warm-50 rounded-xl px-3 py-2.5 flex flex-col gap-0.5">
                        <span className="text-[11.5px] text-warm-500 leading-tight">Pedí</span>
                        <span className="font-mono text-[18px] font-bold text-warm-700">{fmtC(pl.pedi)} {u}</span>
                        <span className="text-[11px] text-warm-400">
                          en {pl.n_pedidos} pedido{pl.n_pedidos !== 1 ? 's' : ''}
                          {pl.proveedores.length > 0 && ` · ${pl.proveedores.join(', ')}`}
                        </span>
                      </div>
                      <div className="bg-forest-50 rounded-xl px-3 py-2.5 flex flex-col gap-0.5">
                        <span className="text-[11.5px] text-forest-700 leading-tight">Llegó con factura</span>
                        <span className="font-mono text-[18px] font-bold text-forest-700">{fmtC(pl.llego_con_factura)} {u}</span>
                      </div>
                      <div className={`rounded-xl px-3 py-2.5 flex flex-col gap-0.5 ${
                        pl.diferencia > 0 ? 'bg-danger-50' : 'bg-warm-50'}`}>
                        <span className={`text-[11.5px] leading-tight ${
                          pl.diferencia > 0 ? 'text-danger-700' : 'text-warm-500'}`}>
                          {pl.diferencia > 0 ? 'Faltó' : pl.diferencia < 0 ? 'Llegó de más' : 'Cuadra'}
                        </span>
                        <span className={`font-mono text-[18px] font-bold ${
                          pl.diferencia > 0 ? 'text-danger-700' : 'text-warm-700'}`}>
                          {pl.diferencia === 0 ? '✓' : `${fmtC(Math.abs(pl.diferencia))} ${u}`}
                        </span>
                      </div>
                    </div>
                    {pl.diferencia > 0 && (
                      <span className="text-[12.5px] text-warm-500 leading-relaxed">
                        Puede ser que no lo trajeron, que llegó después del período, o que entró sin
                        factura — mirá «Llegó», más abajo, antes de reclamarle a nadie.
                      </span>
                    )}
                    {Object.keys(pl.en_otra_unidad).length > 0 && (
                      <span className="text-[11.5px] text-warm-400 leading-relaxed">
                        Aparte, se pidió {Object.entries(pl.en_otra_unidad)
                          .map(([un, c]) => `${fmtC(c)} ${un}`).join(' · ')} — otra unidad, no entra en la resta.
                      </span>
                    )}
                  </>
                )}
              </Bloque>

              {/* ── 4 · Hacía falta ── */}
              {/* Convive con «pedí» y no lo reemplaza: uno es lo que el sistema
                  calcula y el otro lo que el dueño decidió. La diferencia entre
                  los dos es su criterio de compra. */}
              <Bloque titulo="Hacía falta">
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
                  <div className="bg-warm-50 rounded-xl px-3 py-2.5 flex flex-col gap-0.5">
                    <span className="text-[11.5px] text-warm-500 leading-tight">Para reponer lo que salió</span>
                    <span className="font-mono text-[18px] font-bold text-warm-700">{fmtC(r.total_salio)} {u}</span>
                  </div>
                  <div className="bg-gold-50 rounded-xl px-3 py-2.5 flex flex-col gap-0.5">
                    <span className="text-[11.5px] text-gold-700 leading-tight">Hoy hay que pedir</span>
                    <span className="font-mono text-[18px] font-bold text-gold-700">
                      {d.hacia_falta.hoy_hay_que_pedir == null ? '—' : `${fmtC(d.hacia_falta.hoy_hay_que_pedir)} ${u}`}
                    </span>
                    {d.hacia_falta.empaques_sugeridos != null && (
                      <span className="text-[11px] text-gold-600">≈ {fmtC(d.hacia_falta.empaques_sugeridos)} empaques</span>
                    )}
                    {d.hacia_falta.accion === 'preparar' && d.hacia_falta.tandas_sugeridas != null && (
                      <span className="text-[11px] text-gold-600">no se compra: son {d.hacia_falta.tandas_sugeridas} tandas</span>
                    )}
                  </div>
                  <div className="bg-forest-50 rounded-xl px-3 py-2.5 flex flex-col gap-0.5">
                    <span className="text-[11.5px] text-forest-700 leading-tight">Se compró</span>
                    <span className="font-mono text-[18px] font-bold text-forest-700">{fmtC(r.entradas)} {u}</span>
                  </div>
                </div>
                {r.entradas < r.total_salio && (
                  <span className="text-[12.5px] font-semibold text-danger-700">
                    Se compró menos de lo que salió: el estante se está vaciando.
                  </span>
                )}
              </Bloque>

              {/* ── 5 · Lo que se pidió por escrito ── */}
              {/* Bitácora de las dos clases de pedido, cada línea con su origen a
                  la vista. Las del dueño ya están sumadas arriba; las del kiosko
                  no se suman nunca —la barista teclea la unidad libre— y por eso
                  la etiqueta importa: sin ella, dos líneas idénticas en pantalla
                  significarían cosas distintas y nadie podría notarlo. */}
              <Bloque titulo="Lo que se pidió por escrito">
                {d.pedido_escrito.length === 0 ? (
                  <span className="text-[12.5px] text-warm-500 leading-relaxed">
                    Nadie pidió este insumo por escrito en este período: ni vos a un proveedor, ni la
                    barista desde el kiosko.
                  </span>
                ) : (
                  <>
                    <div className="flex flex-col gap-1.5">
                      {d.pedido_escrito.map((p, i) => (
                        <div key={`${p.solicitud_id}-${i}`}
                             className="flex items-center justify-between gap-3 bg-warm-50 rounded-lg px-3 py-2">
                          <span className="text-[13px] text-warm-700">
                            <b className="font-mono">{fmtFecha(p.fecha)}</b> · {fmtC(p.cantidad)} {p.unidad}
                            {p.proveedor && <span className="text-warm-500"> · a {p.proveedor}</span>}
                          </span>
                          {p.origen === 'admin' ? (
                            <span className="text-[10.5px] font-bold px-2 py-0.5 rounded-full uppercase bg-forest-50 text-forest-700 whitespace-nowrap">
                              lo pediste vos
                            </span>
                          ) : (
                            <span className={`text-[10.5px] font-bold px-2 py-0.5 rounded-full uppercase whitespace-nowrap ${
                              p.estado === 'rechazada' ? 'bg-danger-50 text-danger-700'
                              : p.estado === 'aprobada' ? 'bg-warm-100 text-warm-600'
                              : 'bg-gold-50 text-gold-700'}`}>kiosko · {p.estado}</span>
                          )}
                        </div>
                      ))}
                    </div>
                    <span className="text-[11.5px] text-warm-400 leading-relaxed">
                      Lo del <b>kiosko</b> es la barista avisando que falta algo, y se muestra tal cual lo
                      tecleó, sin sumarse: el mismo insumo se pide en unidades distintas según el día.
                      Ahí «aprobada» quiere decir que lo viste, no que se mandó.
                    </span>
                  </>
                )}
              </Bloque>

              {/* ── 6 · Llegó ── */}
              <Bloque titulo="Llegó">
                <div className="flex items-center justify-between gap-3">
                  <span className="text-[13.5px] font-semibold text-warm-700">
                    Con factura
                    {d.llego.facturas.length > 0 && (
                      <span className="font-normal text-warm-500"> · {d.llego.facturas.length} factura{d.llego.facturas.length > 1 ? 's' : ''}</span>
                    )}
                  </span>
                  <span className="font-mono text-[15px] font-bold text-forest-700">{fmtC(d.llego.con_factura)} {u}</span>
                </div>
                {d.llego.facturas.length > 0 && (
                  <div className="flex flex-col gap-1 pl-3 border-l-2 border-warm-100">
                    {d.llego.facturas.map(f => (
                      <div key={f.factura_id} className="flex items-center justify-between gap-3 text-[11.5px] text-warm-500">
                        <span className="truncate">
                          {fmtFecha(f.fecha)} · {f.proveedor}{f.numero_factura ? ` · N° ${f.numero_factura}` : ' · sin N°'}
                        </span>
                        <span className="font-mono shrink-0">
                          {fmtC(f.cantidad)} {u}{f.total != null && ` · ${fmt$(f.total)}`}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
                {Math.abs(d.llego.sin_papel) > 0.01 && (
                  <div className="flex items-center justify-between gap-3 pt-2 border-t border-warm-100">
                    <span className="text-[13px] font-semibold text-gold-700">Cargado a mano, sin papel</span>
                    <span className="font-mono text-[14px] font-bold text-gold-700">{fmtC(d.llego.sin_papel)} {u}</span>
                  </div>
                )}
                {(d.llego.vino_de_la_otra_sede > 0 || d.llego.se_produjo_aca > 0) && (
                  <div className="bg-warm-50 rounded-xl px-3 py-2.5 flex flex-col gap-1">
                    <span className="text-[10px] font-bold uppercase tracking-wider text-warm-400">No se compró</span>
                    {d.llego.vino_de_la_otra_sede > 0 && (
                      <div className="flex justify-between text-[12.5px] text-warm-600">
                        <span>Vino de la otra sede</span><span className="font-mono font-bold">{fmtC(d.llego.vino_de_la_otra_sede)} {u}</span>
                      </div>
                    )}
                    {d.llego.se_produjo_aca > 0 && (
                      <div className="flex justify-between text-[12.5px] text-warm-600">
                        <span>Se produjo acá</span><span className="font-mono font-bold">{fmtC(d.llego.se_produjo_aca)} {u}</span>
                      </div>
                    )}
                  </div>
                )}
              </Bloque>
              </>
            )}

            {/* ── 7 · Salió ── */}
            <Bloque titulo="Salió · por qué">
              <div className="flex flex-col">
                {RENGLONES.filter(x => x.siempre || Number(r[x.k]) !== 0).map(x => {
                  const v = Number(r[x.k] ?? 0)
                  return (
                    <div key={x.k}
                      className={`flex items-center justify-between gap-3 px-3 py-2.5 rounded-xl ${
                        x.alerta ? 'bg-danger-50 border border-danger-100 mb-1.5' : 'border-b border-warm-100'}`}>
                      <span className={`text-[13.5px] font-semibold flex items-center gap-2 ${x.alerta ? 'text-danger-700' : 'text-warm-700'}`}>
                        {x.alerta && <AlertTriangle size={14} className="shrink-0" />}
                        {x.label}
                      </span>
                      <span className="text-right shrink-0">
                        <span className={`font-mono text-[15px] font-bold ${x.alerta ? 'text-danger-700' : 'text-warm-700'}`}>
                          {fmtC(v)} {u}
                        </span>
                        {x.alerta && r.valor_sin_causa > 0 && (
                          <><br /><span className="font-mono text-[11px] text-danger-500">{fmt$(r.valor_sin_causa)}</span></>
                        )}
                      </span>
                    </div>
                  )
                })}
                <div className="flex items-center justify-between gap-3 px-3 pt-3 mt-1 border-t-2 border-warm-200">
                  <span className="text-[14px] font-extrabold text-warm-700">TOTAL QUE SALIÓ</span>
                  <span className="text-right">
                    <span className="font-mono text-[17px] font-extrabold text-warm-700">{fmtC(r.total_salio)} {u}</span>
                    {r.valor_total_salio > 0 && (
                      <><br /><span className="font-mono text-[11.5px] text-warm-500">{fmt$(r.valor_total_salio)}</span></>
                    )}
                  </span>
                </div>
              </div>

              {(r.ajustes_conteo !== 0 || r.ajustes !== 0) && (
                <div className="bg-warm-100 rounded-xl px-3 py-2.5 flex flex-col gap-1">
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-[12.5px] font-bold text-warm-600">APARTE · Ajustes de conteo</span>
                    <span className="font-mono text-[14px] font-bold text-warm-600">{fmtC(r.ajustes_conteo + r.ajustes)} {u}</span>
                  </div>
                  <span className="text-[11.5px] text-warm-500 leading-relaxed">
                    Esto no salió ahora: es faltante viejo que apareció al contar y recién se anotó en el sistema.
                  </span>
                </div>
              )}
            </Bloque>

            {/* ── 8 · Queda ── */}
            <div className="bg-white border border-warm-200 rounded-2xl px-4 py-3.5 flex items-center justify-between gap-4">
              <div className="flex flex-col gap-0.5">
                <span className="text-[10.5px] font-bold uppercase tracking-wider text-warm-500">Queda</span>
                <span className="text-[11.5px] text-warm-500">Lo que dice el sistema, no lo que hay en el estante.</span>
              </div>
              <div className="text-right shrink-0">
                <span className="font-mono text-[24px] font-extrabold text-warm-700">{fmtC(r.queda)} {u}</span>
                {d?.hacia_falta.stock_minimo ? (
                  <><br /><span className="text-[11.5px] text-warm-500">mínimo <b className="font-mono">{fmtC(d.hacia_falta.stock_minimo)}</b></span></>
                ) : null}
              </div>
            </div>

            {d && (
              <>
              {/* ── 9 · Movimientos ── */}
              <Bloque titulo={`Movimiento por movimiento · ${d.movimientos_total}`}>
                {/* Los chips salen de `causas`, que cuenta sobre el rango COMPLETO
                    aunque haya filtro: así el número de cada uno es de verdad. */}
                <div className="flex flex-wrap gap-1.5">
                  <button onClick={() => setCausa(null)}
                    className={`text-[11.5px] font-semibold px-2.5 py-1 rounded-full transition-colors ${
                      causa === null ? 'bg-warm-700 text-white' : 'bg-warm-100 text-warm-600 hover:bg-warm-200'}`}>
                    Todos
                  </button>
                  {Object.entries(d.causas)
                    .sort((a, b) => b[1] - a[1])
                    .map(([k, n]) => (
                      <button key={k} onClick={() => setCausa(k)}
                        className={`text-[11.5px] font-semibold px-2.5 py-1 rounded-full transition-colors ${
                          causa === k
                            ? (k === 'otras_salidas' ? 'bg-danger text-white' : 'bg-warm-700 text-white')
                            : k === 'otras_salidas'
                              ? 'bg-danger-50 text-danger-700 hover:bg-danger-100'
                              : 'bg-warm-100 text-warm-600 hover:bg-warm-200'}`}>
                        {CAUSA_LABEL[k] ?? k} <span className="font-mono opacity-70">{n}</span>
                      </button>
                    ))}
                </div>
                {d.movimientos.length === 0 ? (
                  <span className="text-[12.5px] text-warm-400">
                    {causa ? 'Ningún movimiento de esa causa en el período.' : 'Sin movimientos en el período.'}
                  </span>
                ) : (
                  <>
                    <div className="flex flex-col max-h-[340px] overflow-y-auto">
                      {d.movimientos.map(m => {
                        const entra = m.tipo === 'entrada'
                        const ajuste = m.tipo === 'ajuste'
                        const sinCausa = m.causa === 'otras_salidas'
                        return (
                          <div key={m.id} className="flex items-center gap-2.5 py-2 border-b border-warm-100 last:border-0">
                            {ajuste ? <Clock size={13} className="text-warm-400 shrink-0" />
                              : entra ? <ArrowDown size={13} className="text-forest shrink-0" />
                              : <ArrowUp size={13} className={`shrink-0 ${sinCausa ? 'text-danger' : 'text-warm-400'}`} />}
                            <span className="font-mono text-[11.5px] text-warm-500 shrink-0 w-[52px]">{fmtFecha(m.fecha)}</span>
                            <div className="flex-1 min-w-0">
                              <span className={`text-[12.5px] font-semibold ${sinCausa ? 'text-danger-700' : 'text-warm-700'}`}>
                                {CAUSA_LABEL[m.causa] ?? m.causa}
                              </span>
                              {m.motivo && <span className="text-[11.5px] text-warm-400 truncate"> · {m.motivo}</span>}
                              {m.barista && <span className="text-[11px] text-warm-400"> · {m.barista}</span>}
                            </div>
                            <span className={`font-mono text-[12.5px] font-bold shrink-0 ${
                              ajuste ? 'text-warm-500' : entra ? 'text-forest-700' : sinCausa ? 'text-danger-700' : 'text-warm-700'}`}>
                              {ajuste ? '=' : entra ? '+' : '−'}{fmtC(m.cantidad)}
                            </span>
                          </div>
                        )
                      })}
                    </div>
                    {d.movimientos_truncados && (
                      <span className="text-[11.5px] text-warm-400">
                        Se muestran los {d.movimientos.length} más recientes de {d.movimientos_total}.
                      </span>
                    )}
                    <span className="text-[11.5px] text-warm-400 leading-relaxed flex items-start gap-1.5">
                      <FileText size={12} className="shrink-0 mt-0.5" />
                      Un <b>ajuste</b> no suma ni resta: fija el saldo en lo que se contó.
                    </span>
                  </>
                )}
              </Bloque>
              </>
            )}

          </>
        )}
      </div>
    </div>
  )
}
