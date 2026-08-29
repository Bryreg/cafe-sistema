import { useEffect, useState } from 'react'
import api from '../../api/client'
import { diaCol, instanteCol, fechaHoraCol } from '../../utils/fechaLocal'
import { AlertTriangle, Info, X, FileText, ArrowDown, ArrowUp, Clock } from 'lucide-react'
import BarraInsumo, { EjeTiempo, marcasTiempo } from './BarraInsumo'

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
  /** Lo que había cuando arrancó el período. Sin este número la resta de la fila
   *  no da, y el que la mira concluye que el sistema está mal. */
  arranco: number
  entradas: number; traslados_recibidos: number; preparaciones_producidas: number
  reversas: number; unificaciones: number
  /** Todo lo que mueve el saldo y NO está en el arco que la pantalla cuenta:
   *  lo recibido de la otra sede, lo producido acá, anulaciones, unificaciones y
   *  ajustes. Con signo, en un solo número; el desglose vive en esta ficha. */
  otros: number
  /** La identidad comprobada en el backend con estos mismos números. */
  cuadra: boolean
  ventas: number; mermas: number; traslados: number; preparaciones: number
  reversas_salida: number; otras_salidas: number; total_salio: number
  ajustes_conteo: number; ajustes: number; queda: number
  valor_unitario: number; valor_origen: string | null
  valor_sin_causa: number; valor_total_salio: number
  arranque_estimado: boolean; no_se_mide: boolean
  /** El stock quedó por debajo de cero. No es «se acabó»: es imposible, y por
   *  eso es una certeza y no una sospecha — falta registrar algo. */
  en_negativo: boolean
  /** El cliente lo pide o no lo pide —azúcar en tubos, Splenda, el mezclador—.
   *  Va pegado a `no_se_mide`: ese dice que el libro no lo ve, y este dice si
   *  eso es un agujero de configuración o simplemente cómo es el insumo. */
  consumo_opcional: boolean
  /** Sólo cuando se pide `con_curva`: CUÁNDO pasó lo que los totales resumen. */
  curva?: Curva
}

/** Un punto de la curva. `t` son segundos desde el arranque del rango (no una
 *  fecha: son 5 bytes contra 26, y esto viaja para ~120 insumos a una tablet).
 *  `c` es cuánto movió ese escalón — en una salida raleada, cuánto salió DESDE
 *  el punto anterior, que es lo que el globo tiene que decir. */
export interface PuntoCurva {
  t: number; v: number
  k: 'inicio' | 'entrada' | 'salida' | 'ajuste' | 'fin'
  c?: number; causa?: string
  /** Cuántos movimientos junta este escalón cuando la curva se raleó. Sin
   *  esto, un escalón de 340 gr se presenta como una venta única de 340. */
  n?: number
  /** El saldo salió de suponer que el producto arrancó en cero antes del ajuste
   *  más viejo. Es un supuesto y se dibuja como tal. */
  est?: boolean
}

/** Un conteo físico: lo ÚNICO que no sale del libro. `sistema` es lo que el
 *  sistema creía en ese instante y `real` lo que alguien vio en el estante; la
 *  distancia entre los dos es la fuga. `registros` > 1 es la apertura que copió
 *  el cierre de la noche anterior. */
export interface ConteoCurva {
  conteo_id: number; t: number; tipos: string[]; registros: number
  sistema: number; real: number; dif: number; curva: number
  es_atajo: boolean; aplicado: boolean
}

/** Lo que de verdad salió del estante, medido entre dos conteos y sin pasar por
 *  el libro: contado antes + lo que entró en medio − contado después. Para un
 *  insumo opcional es el ÚNICO número que existe, porque la caja nunca lo
 *  descuenta. `null` con menos de dos conteos: sin un antes y un después no hay
 *  tramo que medir, y un 0 diría que no se gastó nada. */
export interface ConsumoMedido {
  usado: number; por_dia: number | null; dias: number; tramos: number
}

export interface Curva {
  puntos: PuntoCurva[]; puntos_total: number
  conteos: ConteoCurva[]; n_movs: number
  consumo_medido: ConsumoMedido | null
  ancla: 'libro' | 'estimado'
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
  curva: Curva | null
  /** Arranque del rango en UTC y con su marca de zona. Los `t` de la curva
   *  son segundos desde acá; sin esto la regla de fechas tendría que suponer
   *  el huso, que es como se corrieron cinco horas todas las horas. */
  desde_utc: string
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
/** Cortar el ISO a secas mostraba el día UTC: un movimiento de las 8 de la
 *  noche en Colombia ya es del día siguiente en UTC, así que todo el cierre del
 *  turno se fechaba un día tarde. */
const fmtFecha = (s: string | null) => diaCol(s)

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


/** La hora de un punto de la curva. Los `t` son segundos desde el arranque del
 *  rango: sin el ancla con zona, sumarlos a un `new Date` del ISO pelado corre
 *  todo cinco horas en la tablet. */
const horaFicha = (desdeUtc: string | undefined, t: number) =>
  !desdeUtc ? '' : fechaHoraCol(new Date(instanteCol(desdeUtc).getTime() + t * 1000)) + ' · '

/** Una sección de la hoja. NO es una tarjeta: la ficha entera es UN papel y las
 *  secciones se separan con una línea, no con un hueco.
 *
 *  Antes era un `Bloque` con borde, esquinas redondeadas y fondo blanco, y la
 *  ficha era una pila de once tarjetas flotando sobre el velo oscuro. Cada
 *  hueco entre dos tarjetas leía como «acá se terminó una cosa y empieza otra»,
 *  once veces, para lo que en realidad es una sola respuesta —qué pasó con este
 *  insumo— contada por partes. */
function Seccion({ titulo, extra, children }: {
  titulo?: string; extra?: React.ReactNode; children: React.ReactNode
}) {
  return (
    <section className="px-4 sm:px-5 py-4 flex flex-col gap-3">
      {titulo && (
        <div className="flex items-baseline justify-between gap-3">
          <h3 className="text-[10.5px] font-bold uppercase tracking-[0.09em] text-warm-400">{titulo}</h3>
          {extra}
        </div>
      )}
      {children}
    </section>
  )
}

/** Un dato suelto: el rótulo chico arriba y el número abajo. Sin caja: el fondo
 *  de color en cada dato convertía cada sección en otra grilla de tarjetitas. */
function Dato({ label, valor, nota, tono = 'normal' }: {
  label: string; valor: React.ReactNode; nota?: React.ReactNode
  tono?: 'normal' | 'bueno' | 'malo' | 'aviso'
}) {
  const color = tono === 'bueno' ? 'text-forest-700' : tono === 'malo' ? 'text-danger-700'
    : tono === 'aviso' ? 'text-gold-700' : 'text-warm-700'
  return (
    <div className="flex flex-col gap-0.5 min-w-0">
      <span className="text-[11px] text-warm-500 leading-tight">{label}</span>
      <span className={`font-mono text-[17px] font-bold leading-none ${color}`}>{valor}</span>
      {nota && <span className="text-[11px] text-warm-400 leading-tight">{nota}</span>}
    </div>
  )
}

/** Un aviso en línea. Va dentro de la sección que lo necesita y no como una
 *  tarjeta propia: «el arranque es un cálculo» ocupaba un módulo entero del
 *  ancho de la pantalla para decir una frase. */
function Aviso({ tono, children }: { tono: 'rojo' | 'ambar' | 'gris'; children: React.ReactNode }) {
  const cls = tono === 'rojo' ? 'bg-danger-50 text-danger-700 border-danger-100'
    : tono === 'ambar' ? 'bg-gold-50 text-gold-700 border-gold-200'
    : 'bg-warm-50 text-warm-600 border-warm-200'
  const Icono = tono === 'gris' ? Info : AlertTriangle
  return (
    <div className={`flex items-start gap-2 rounded-xl border px-3 py-2 ${cls}`}>
      <Icono size={14} className="shrink-0 mt-[2px]" />
      <div className="text-[12.5px] leading-relaxed min-w-0">{children}</div>
    </div>
  )
}

// ─── Componente ───────────────────────────────────────────────────────────────

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
  // Marcar el insumo como opcional se hace ACÁ, que es donde el dueño está
  // mirando cuando se da cuenta: el aviso dice «nadie lo está midiendo» y él
  // sabe que no hay nada que medir porque depende de si el cliente lo pide.
  // Mandarlo al catálogo a buscar el producto sería perder el momento.
  const [opcional, setOpcional] = useState<boolean | null>(null)
  const [guardando, setGuardando] = useState(false)
  // Qué está señalando el dedo sobre la barra. Va a un renglón fijo debajo
  // del gráfico y no a un globo flotante: en una tablet el globo tapa
  // justamente el escalón que se está tocando.
  const [detalle, setDetalle] = useState<string | null>(null)

  useEffect(() => {
    let cancel = false
    setCargando(true); setError('')
    api.get<Ficha>(`/inventario/insumo/${productoId}/ficha`, {
      params: { tienda_id: tiendaId, desde, hasta, ...(causa ? { causa } : {}) },
    })
      .then(r => { if (!cancel) { setD(r.data); setOpcional(r.data.resumen.consumo_opcional) } })
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
  // Lo que el usuario acaba de marcar manda sobre lo que trajo la respuesta:
  // el interruptor tiene que responder al toque, no al viaje de vuelta.
  const esOpcional = opcional ?? r?.consumo_opcional ?? false
  const medido = d?.curva?.consumo_medido ?? null

  const marcarOpcional = async () => {
    if (guardando) return
    setGuardando(true)
    const nuevo = !esOpcional
    try {
      await api.patch(`/inventario/productos/${productoId}`, { consumo_opcional: nuevo })
      setOpcional(nuevo)
    } catch {
      setError('No se pudo guardar. Probá de nuevo.')
    } finally {
      setGuardando(false)
    }
  }
  const pl = d?.pedi_llego
  const u = r?.unidad ?? ''
  const nombre = d?.producto.nombre ?? filaPrevia?.producto
  // Nunca hubo nada que mostrar: se abrió sin fila previa y todavía no llegó.
  const enBlanco = !r

  // La curva de ESTE insumo, a lo ancho de la ficha. En la lista mide 52 px de
  // alto porque hay 110; acá hay una sola y la pantalla entera.
  const curva = d?.curva ?? null
  const spanFicha = curva?.puntos.length ? curva.puntos[curva.puntos.length - 1].t : 0
  const guias = marcasTiempo(d?.desde_utc, spanFicha).map(m => m.u)
  const salidaPorCausa = RENGLONES
    .map(x => ({ ...x, v: Number(r?.[x.k] ?? 0) }))
    .filter(x => x.siempre || x.v !== 0)
  const mayorSalida = Math.max(...salidaPorCausa.map(x => Math.abs(x.v)), 0.0001)
  // El ritmo con el que se decide cuánto pedir. Primero el medido contra los
  // conteos —mide el estante, no el libro—; si no hay dos conteos, lo que la
  // caja descontó, que es lo único que queda.
  const porDia = medido?.por_dia ?? d?.hacia_falta.consumo_diario ?? null
  const porDiaMedido = medido?.por_dia != null

  // El aire de arriba y abajo va en el PAPEL y no en el velo: con relleno en el
  // velo, la cabecera pegada se detiene 32 px más abajo del borde de la pantalla
  // y por esa franja se ve pasar el contenido que va subiendo.
  return (
    <div className="fixed inset-0 z-50 overflow-y-auto bg-warm-700/35 px-2 sm:px-4"
         onClick={onClose}>
      {/* UN SOLO PAPEL. Antes eran once tarjetas con borde y esquinas
          redondeadas separadas por huecos, y cada hueco decía «acá se terminó
          una cosa» — once veces, para una sola respuesta contada por partes.
          Ahora las secciones se separan con una línea. */}
      {/* SIN `overflow-hidden`. Medido: recortar el papel lo convierte en el
          contenedor de scroll de sus hijos, y ahí la cabecera pegada deja de
          pegarse —bajando 900 px se iba a −867, o sea se fue con el resto y el
          botón de cerrar quedó fuera de la pantalla—. Las esquinas se redondean
          en la cabecera y en el papel, que es lo único que tiene fondo. */}
      <div className="w-full max-w-[880px] mx-auto my-4 sm:my-8 bg-white border border-warm-200
                      rounded-2xl shadow-xl"
           onClick={e => e.stopPropagation()}>

        {/* ── Cabecera ── */}
        <div className="sticky top-0 z-10 bg-white border-b border-warm-200 rounded-t-2xl
                        px-4 sm:px-5 py-3 flex items-start justify-between gap-3">
          <div className="flex flex-col gap-1 min-w-0">
            <span className="text-[17px] font-bold text-warm-700 leading-tight truncate">
              {nombre ?? 'Cargando…'}
            </span>
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
              {d && (
                <span className="text-[11.5px] text-warm-400">
                  · {fmtFecha(d.periodo.desde)} a {fmtFecha(d.periodo.hasta)}
                </span>
              )}
            </div>
          </div>
          <button onClick={onClose} aria-label="Cerrar"
            className="shrink-0 w-9 h-9 rounded-full bg-warm-50 border border-warm-200 flex items-center
                       justify-center text-warm-500 hover:bg-warm-100 transition-colors">
            <X size={16} />
          </button>
        </div>

        {/* El cartel de carga queda SOLO para la ficha abierta sin venir de la
            tabla. Con la fila previa los números ya están acá, y taparlos con
            «Cargando…» sería esconder lo que el dueño vino a ver. */}
        {cargando && enBlanco && (
          <p className="py-16 text-center text-sm text-warm-400">Cargando…</p>
        )}
        {!cargando && error && (
          <p className="py-16 text-center text-sm text-danger-700">{error}</p>
        )}

        {r && !error && (
          <div className="divide-y divide-warm-100">

            {/* ── 1 · Cuánto queda, y la cuenta que lleva hasta ahí ──
                Antes esto eran TRES módulos: el titular en prosa arriba, la
                resta en una franja de color en el medio, y «Queda» otra vez en
                una tarjeta propia al final. Es un solo dato con su derivación. */}
            <Seccion>
              <div className="flex flex-wrap items-end justify-between gap-x-8 gap-y-4">
                <div className="flex flex-col gap-1">
                  <span className="text-[11px] text-warm-500 leading-none">
                    Queda ahora <span className="text-warm-400">· lo que dice el sistema</span>
                  </span>
                  <span className={`font-mono text-[34px] font-extrabold leading-none ${
                    r.en_negativo ? 'text-danger-700' : 'text-warm-700'}`}>
                    {fmtC(r.queda)} <span className="text-[15px] font-bold text-warm-400">{u}</span>
                  </span>
                  {d?.hacia_falta.stock_minimo ? (
                    <span className="text-[11px] text-warm-400">
                      mínimo <b className="font-mono">{fmtC(d.hacia_falta.stock_minimo)} {u}</b>
                    </span>
                  ) : null}
                </div>

                <div className="flex flex-col items-start sm:items-end gap-1 min-w-0">
                  <span className="font-mono text-[12.5px] text-warm-500 leading-relaxed">
                    {fmtC(r.arranco)}<span className="text-warm-400"> arrancó</span>
                    {' + '}{fmtC(r.entradas)}<span className="text-warm-400"> entró</span>
                    {Math.abs(r.otros) > 0.001 && (
                      <>{r.otros >= 0 ? ' + ' : ' − '}{fmtC(Math.abs(r.otros))}
                        <span className="text-warm-400"> otros</span></>
                    )}
                    {' − '}{fmtC(r.total_salio)}<span className="text-warm-400"> salió</span>
                    {' = '}<b className="text-warm-700">{fmtC(r.queda)}</b>
                  </span>
                  <span className={`text-[11px] font-bold ${
                    r.cuadra ? 'text-forest-700' : 'text-danger-700'}`}>
                    {r.cuadra ? 'la cuenta cierra' : 'la cuenta NO cierra'}
                  </span>
                  {r.valor_total_salio > 0 && (
                    <span className="text-[11.5px] text-warm-500">
                      costó <b className="font-mono text-warm-700">{fmt$(r.valor_total_salio)}</b> lo que salió
                    </span>
                  )}
                </div>
              </div>

              {r.arranque_estimado && (
                <span className="text-[11.5px] text-warm-400 leading-relaxed">
                  El <b>arranque</b> es un cálculo, no un dato: nadie registró cuánto había antes.
                </span>
              )}

              {r.en_negativo && (
                <Aviso tono="rojo">
                  <b>El sistema dice que hay menos que cero.</b> Eso no puede pasar en el estante, así
                  que el libro está incompleto. Son dos cosas y sólo dos: entró mercadería que nadie
                  registró, o una receta está descontando este insumo cuando debería descontar otro.
                  No es que se haya acabado — mirá los movimientos de abajo.
                </Aviso>
              )}
              {r.otras_salidas > 0 && (
                <Aviso tono="rojo">
                  Hay <b className="font-mono">{fmtC(r.otras_salidas)} {u}</b> que salieron sin que nadie
                  anotara por qué{r.valor_sin_causa > 0 && <> — <b className="font-mono">{fmt$(r.valor_sin_causa)}</b></>}.
                </Aviso>
              )}
            </Seccion>

            {/* ── 2 · Cómo se movió, día por día ──
                La curva estaba viajando en la respuesta y no se dibujaba en
                ningún lado: la ficha pedía `con_curva` y sólo usaba el consumo
                medido. Acá hay una sola barra y la pantalla entera, así que va
                alta y con la regla de fechas encima. */}
            {curva && curva.puntos.length > 1 && (
              <Seccion titulo="Cómo se movió">
                <EjeTiempo desdeUtc={d?.desde_utc} span={spanFicha} />
                <BarraInsumo curva={curva} span={spanFicha} guias={guias} alto={130}
                  onPunto={p => setDetalle(
                    p.k === 'inicio' ? `Al arrancar el período quedaban ${fmtC(p.v)} ${u}`
                    : p.k === 'fin' ? `Al cerrar quedaban ${fmtC(p.v)} ${u}`
                    : p.k === 'entrada' ? `${horaFicha(d?.desde_utc, p.t)}llegaron ${fmtC(p.c ?? 0)} ${u} — quedan ${fmtC(p.v)}`
                    : p.k === 'ajuste' ? `${horaFicha(d?.desde_utc, p.t)}se aplicó un conteo: el saldo quedó en ${fmtC(p.v)} ${u}`
                    : `${horaFicha(d?.desde_utc, p.t)}salieron ${fmtC(p.c ?? 0)} ${u}`
                      + `${p.n != null ? ` en ${p.n} movimientos` : ''}`
                      + `${p.causa ? ` · ${CAUSA_LABEL[p.causa] ?? p.causa}` : ''} — quedan ${fmtC(p.v)}`)}
                  onConteo={c => setDetalle(
                    `${horaFicha(d?.desde_utc, c.t)}conteo de ${c.tipos[0]}: el sistema decía `
                    + `${fmtC(c.sistema)} y contaron ${fmtC(c.real)} ${u}`
                    + `${Math.abs(c.dif) <= 0.001 ? ' — coincidió exacto'
                       : c.dif > 0 ? ` — sobran ${fmtC(c.dif)}` : ` — faltan ${fmtC(-c.dif)}`}`)} />
                {/* La línea de detalle ocupa el lugar de la leyenda mientras se
                    recorre la barra: en una tablet un globo flotante tapa
                    justamente lo que el dedo está señalando. */}
                <div className="min-h-[32px] flex items-center rounded-xl bg-warm-50 px-3 py-2">
                  <span className="text-[12px] text-warm-600 leading-snug">
                    {detalle ?? (
                      <span className="text-warm-400">
                        La línea verde es lo que había; la sombra gris, el hueco contra su punto más
                        lleno. El palito naranja es mercadería que llegó y el punto negro, un conteo.
                        Tocá la barra para ver qué pasó en cada momento.
                      </span>
                    )}
                  </span>
                </div>
              </Seccion>
            )}

            {/* ── 3 · Cuando la caja no lo descuenta ──
                Cambia cómo se lee TODO lo de abajo, así que va antes que los
                números de pedido y no perdido al final. */}
            {(r.no_se_mide || esOpcional) && (
              <Seccion titulo={esOpcional ? 'Este insumo se mide contando' : 'Este insumo no se está midiendo'}>
                <span className="text-[12.5px] text-warm-600 leading-relaxed">
                  {esOpcional ? (
                    <>Se gasta según lo pida el cliente —el azúcar en tubos, el mezclador— o según se
                    opere el local —el limpiapisos, la bolsa de basura—, no según lo que se vendió.
                    Ninguna receta puede predecirlo, así que la caja nunca lo descuenta y el
                    <b> conteo deja de ser un control para ser la medición</b>.</>
                  ) : (
                    <>La caja no lo resta cuando se vende. El <b>0</b> de «se vendió» no significa que no
                    se usó: significa que nadie lo está midiendo. Puede ser que le falte la receta… o
                    que sea de los que ninguna receta puede predecir, porque se gastan según lo pida
                    el cliente o según se opere el local.</>
                  )}
                </span>
                {esOpcional && medido && (
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-3">
                    <Dato label="Se usó, medido entre conteos" tono="malo"
                      valor={<>{fmtC(medido.usado)} {u}</>}
                      nota={`${medido.tramos + 1} conteos en ${fmtC(medido.dias)} días`} />
                    {medido.por_dia != null && (
                      <Dato label="Se van por día" valor={<>{fmtC(medido.por_dia)} {u}</>}
                        nota={<>unos {fmtC(medido.por_dia * 7)} {u} por semana</>} />
                    )}
                    <Dato label="Entró en el período" tono="bueno" valor={<>{fmtC(r.entradas)} {u}</>} />
                  </div>
                )}
                {esOpcional && !medido && (
                  <Aviso tono="gris">
                    Hacen falta <b>dos conteos</b> en el período para medir cuánto se usó: con una sola
                    mirada no hay un antes y un después que restar.
                  </Aviso>
                )}
                <button
                  onClick={marcarOpcional} disabled={guardando}
                  className={`self-start text-[12px] font-bold px-3 py-1.5 rounded-xl border transition-colors ${
                    esOpcional
                      ? 'bg-white border-warm-200 text-warm-600 hover:text-warm-700'
                      : 'bg-white border-gold-200 text-gold-700 hover:bg-gold-50'} disabled:opacity-50`}>
                  {guardando ? 'Guardando…'
                    : esOpcional ? 'No, sí debería descontarse por receta'
                    : 'No sale de una receta: medirlo por venta es imposible'}
                </button>
              </Seccion>
            )}

            {/* ── 4 · ¿Hay que pedir? ──
                Antes eran DOS secciones —«pedí vs. llegó» y «hacía falta»— con
                seis recuadros de colores entre las dos, y una de ellas se
                dibujaba entera para decir «no pediste nada». Es una sola
                pregunta: la decisión arriba y la evidencia al lado. */}
            <Seccion titulo="¿Hay que pedir?">
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-x-4 gap-y-4">
                <Dato label="Hoy hay que pedir" tono="aviso"
                  valor={d?.hacia_falta.hoy_hay_que_pedir == null
                    ? '—' : <>{fmtC(d.hacia_falta.hoy_hay_que_pedir)} {u}</>}
                  nota={d?.hacia_falta.empaques_sugeridos != null
                    ? <>≈ {fmtC(d.hacia_falta.empaques_sugeridos)} empaques</>
                    : d?.hacia_falta.accion === 'preparar' && d.hacia_falta.tandas_sugeridas != null
                      ? <>no se compra: son {d.hacia_falta.tandas_sugeridas} tandas</> : undefined} />
                <Dato label="Se van por día"
                  valor={porDia == null ? '—' : <>{fmtC(porDia)} {u}</>}
                  nota={porDia == null ? 'hacen falta dos conteos'
                    : porDiaMedido ? 'medido contra los conteos' : 'según lo que descontó la caja'} />
                <Dato label="Pedí por escrito"
                  valor={<>{fmtC(pl?.pedi ?? r.pedi)} {u}</>}
                  nota={pl && pl.n_pedidos > 0
                    ? `en ${pl.n_pedidos} pedido${pl.n_pedidos !== 1 ? 's' : ''}${
                        pl.proveedores.length ? ` · ${pl.proveedores.join(', ')}` : ''}`
                    : 'a ningún proveedor'} />
                <Dato label="Llegó con factura" tono="bueno"
                  valor={<>{fmtC(pl?.llego_con_factura ?? r.entradas)} {u}</>}
                  nota={pl && pl.pedi > 0
                    ? (pl.diferencia > 0 ? <span className="text-danger-700">faltó {fmtC(pl.diferencia)} {u}</span>
                      : pl.diferencia < 0 ? <>llegó {fmtC(-pl.diferencia)} de más</>
                      : <span className="text-forest-700">cuadra con lo pedido</span>)
                    : undefined} />
              </div>

              {r.entradas < r.total_salio && !esOpcional && (
                <span className="text-[12.5px] font-semibold text-danger-700">
                  Se compró menos de lo que salió: el estante se está vaciando.
                </span>
              )}
              {pl && pl.pedi > 0 && pl.diferencia > 0 && (
                <span className="text-[12px] text-warm-500 leading-relaxed">
                  Puede ser que no lo trajeron, que llegó después del período, o que entró sin
                  factura — mirá «Llegó», más abajo, antes de reclamarle a nadie.
                </span>
              )}
              {pl && Object.keys(pl.en_otra_unidad).length > 0 && (
                <span className="text-[12px] text-warm-500 leading-relaxed">
                  Aparte se pidió <b className="font-mono">{Object.entries(pl.en_otra_unidad)
                    .map(([un, c]) => `${fmtC(c)} ${un}`).join(' · ')}</b>, en otra unidad: no entra en la
                  resta porque no son la misma cosa, pero se dice para que el cero no se lea como
                  «no pediste nada».
                </span>
              )}
              {esOpcional && (
                <span className="text-[12px] text-warm-500 leading-relaxed">
                  <b>«Hoy hay que pedir» sale de lo que la caja descontó, que en este insumo es cero.</b>
                  {medido?.por_dia != null
                    ? <> Para pedir andá por el consumo medido: {fmtC(medido.por_dia)} {u} por día,
                        o sea unos {fmtC(medido.por_dia * 7)} {u} por semana.</>
                    : <> Con dos conteos en el período se puede medir el consumo real y usarlo para pedir.</>}
                </span>
              )}
            </Seccion>

            {/* ── 5 · Por dónde se fue ──
                Con una barra por renglón: en una lista de números sueltos hay
                que leer los seis y compararlos de cabeza para ver quién manda. */}
            <Seccion titulo="Por dónde se fue"
              extra={<span className="font-mono text-[13px] font-bold text-warm-700">
                {fmtC(r.total_salio)} {u}
                {r.valor_total_salio > 0 && <span className="font-normal text-warm-400"> · {fmt$(r.valor_total_salio)}</span>}
              </span>}>
              <div className="flex flex-col gap-2.5">
                {salidaPorCausa.map(x => (
                  <div key={x.k} className="flex flex-col gap-1">
                    <div className="flex items-baseline justify-between gap-3">
                      <span className={`text-[13px] font-semibold flex items-center gap-1.5 ${
                        x.alerta && x.v > 0 ? 'text-danger-700' : 'text-warm-700'}`}>
                        {x.alerta && x.v > 0 && <AlertTriangle size={13} className="shrink-0" />}
                        {x.label}
                      </span>
                      <span className="shrink-0 text-right">
                        <span className={`font-mono text-[13.5px] font-bold ${
                          x.alerta && x.v > 0 ? 'text-danger-700' : 'text-warm-700'}`}>
                          {fmtC(x.v)} {u}
                        </span>
                        {x.alerta && r.valor_sin_causa > 0 && (
                          <span className="font-mono text-[11px] text-danger-500"> · {fmt$(r.valor_sin_causa)}</span>
                        )}
                      </span>
                    </div>
                    <div className="h-[5px] rounded-full bg-warm-100 overflow-hidden">
                      <div className={`h-full rounded-full ${x.alerta && x.v > 0 ? 'bg-danger-400' : 'bg-warm-400'}`}
                        style={{ width: `${Math.max(0, Math.min(100, (Math.abs(x.v) / mayorSalida) * 100))}%` }} />
                    </div>
                  </div>
                ))}
              </div>
              {(r.ajustes_conteo !== 0 || r.ajustes !== 0) && (
                <Aviso tono="gris">
                  <b>Aparte · ajustes de conteo: <span className="font-mono">{fmtC(r.ajustes_conteo + r.ajustes)} {u}</span>.</b>{' '}
                  Esto no salió ahora: es faltante viejo que apareció al contar y recién se anotó.
                </Aviso>
              )}
            </Seccion>

            {/* ── 6 · Lo que llegó ── */}
            {d && (
              <Seccion titulo="Lo que llegó"
                extra={<span className="font-mono text-[13px] font-bold text-forest-700">
                  {fmtC(d.llego.con_factura)} {u}
                  <span className="font-normal text-warm-400"> · con factura</span>
                </span>}>
                {d.llego.facturas.length === 0 ? (
                  <span className="text-[12.5px] text-warm-400">No entró nada con factura en el período.</span>
                ) : (
                  <div className="flex flex-col">
                    {d.llego.facturas.map(f => (
                      <div key={f.factura_id}
                        className="flex items-center justify-between gap-3 py-1.5 border-b border-warm-100 last:border-0">
                        <span className="text-[12px] text-warm-600 truncate">
                          <b className="font-mono text-warm-700">{fmtFecha(f.fecha)}</b> · {f.proveedor}
                          {f.numero_factura ? ` · N° ${f.numero_factura}` : ' · sin N°'}
                        </span>
                        <span className="font-mono text-[12px] text-warm-700 shrink-0">
                          {fmtC(f.cantidad)} {u}
                          {f.total != null && <span className="text-warm-400"> · {fmt$(f.total)}</span>}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
                {(Math.abs(d.llego.sin_papel) > 0.01 || d.llego.vino_de_la_otra_sede > 0 || d.llego.se_produjo_aca > 0) && (
                  <div className="flex flex-col gap-1 pt-1">
                    {Math.abs(d.llego.sin_papel) > 0.01 && (
                      <div className="flex justify-between gap-3 text-[12.5px]">
                        <span className="font-semibold text-gold-700">Cargado a mano, sin papel</span>
                        <span className="font-mono font-bold text-gold-700">{fmtC(d.llego.sin_papel)} {u}</span>
                      </div>
                    )}
                    {d.llego.vino_de_la_otra_sede > 0 && (
                      <div className="flex justify-between gap-3 text-[12.5px] text-warm-600">
                        <span>Vino de la otra sede</span>
                        <span className="font-mono font-bold">{fmtC(d.llego.vino_de_la_otra_sede)} {u}</span>
                      </div>
                    )}
                    {d.llego.se_produjo_aca > 0 && (
                      <div className="flex justify-between gap-3 text-[12.5px] text-warm-600">
                        <span>Se produjo acá</span>
                        <span className="font-mono font-bold">{fmtC(d.llego.se_produjo_aca)} {u}</span>
                      </div>
                    )}
                  </div>
                )}
              </Seccion>
            )}

            {/* ── 7 · Los pedidos escritos ──
                Sólo si los hay: la sección que se dibujaba entera para decir
                «nadie pidió nada» es un módulo gastado en un hueco. Cuando no
                hay, «Pedí por escrito 0 · a ningún proveedor» ya lo dijo. */}
            {d && d.pedido_escrito.length > 0 && (
              <Seccion titulo="Lo que se pidió por escrito">
                <div className="flex flex-col">
                  {d.pedido_escrito.map((p, i) => (
                    <div key={`${p.solicitud_id}-${i}`}
                      className="flex items-center justify-between gap-3 py-1.5 border-b border-warm-100 last:border-0">
                      <span className="text-[12.5px] text-warm-700">
                        <b className="font-mono">{fmtFecha(p.fecha)}</b> · {fmtC(p.cantidad)} {p.unidad}
                        {p.proveedor && <span className="text-warm-500"> · a {p.proveedor}</span>}
                      </span>
                      {p.origen === 'admin' ? (
                        <span className="text-[10px] font-bold px-2 py-0.5 rounded-full uppercase bg-forest-50 text-forest-700 whitespace-nowrap">
                          lo pediste vos
                        </span>
                      ) : (
                        <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full uppercase whitespace-nowrap ${
                          p.estado === 'rechazada' ? 'bg-danger-50 text-danger-700'
                          : p.estado === 'aprobada' ? 'bg-warm-100 text-warm-600'
                          : 'bg-gold-50 text-gold-700'}`}>kiosko · {p.estado}</span>
                      )}
                    </div>
                  ))}
                </div>
                <span className="text-[11.5px] text-warm-400 leading-relaxed">
                  Lo del <b>kiosko</b> es la barista avisando que falta algo, y va tal cual lo tecleó, sin
                  sumarse: el mismo insumo se pide en unidades distintas según el día. Ahí «aprobada»
                  quiere decir que lo viste, no que se mandó.
                </span>
              </Seccion>
            )}

            {/* ── 8 · Movimiento por movimiento ── */}
            {!d ? (
              <Seccion>
                <div className="py-8 flex flex-col items-center gap-1.5">
                  <span className="text-[13px] text-warm-400 animate-pulse">Buscando el detalle…</span>
                  <span className="text-[11.5px] text-warm-400">pedidos, facturas y movimiento por movimiento</span>
                </div>
              </Seccion>
            ) : (
              <Seccion titulo="Movimiento por movimiento"
                extra={<span className="font-mono text-[12px] text-warm-400">{d.movimientos_total}</span>}>
                {/* Los chips salen de `causas`, que cuenta sobre el rango COMPLETO
                    aunque haya filtro: así el número de cada uno es de verdad. */}
                <div className="flex flex-wrap gap-1.5">
                  <button onClick={() => setCausa(null)}
                    className={`text-[11.5px] font-semibold px-2.5 py-1 rounded-full transition-colors ${
                      causa === null ? 'bg-warm-700 text-white' : 'bg-warm-100 text-warm-600 hover:bg-warm-200'}`}>
                    Todos
                  </button>
                  {Object.entries(d.causas).sort((a, b) => b[1] - a[1]).map(([k, n]) => (
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
              </Seccion>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
