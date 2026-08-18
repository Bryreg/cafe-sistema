import { ReactNode, useCallback, useMemo, useState } from 'react'
import {
  Building2, HelpCircle, Info, Receipt, Scissors, ShoppingCart,
  TrendingDown, TrendingUp, Wallet, X,
} from 'lucide-react'
import api from '../../api/client'
import type { Dato } from '../../api/dato'
import { type Fuente, useDato } from '../../api/useDato'
import { NoSeSabe, SegunDato } from '../ui'
import { Banner, ComoSeCalcula } from '../plata/campos'
import { DashboardFacturas, Categoria, Tienda } from '../plata/tipos'
import { PorProductoData, PulsoData, RentabilidadData, fmt, fmtTasa, pctDelta } from './helpers'
import BannerEgresos from './BannerEgresos'
import BannerProductos from './BannerProductos'
import BannerSalud from './BannerSalud'

// El aviso de que el margen neto CAMBIÓ DE VALOR se muestra una sola vez por
// navegador: el dueño ya conoce el número viejo y verlo bajar sin explicación se
// lee como un error del sistema, no como una mejora de la medición.
const CLAVE_AVISO_FIJOS = 'rentabilidad.aviso_margen_con_fijos.v1'

function isoLocal(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
/** «Hoy» según el reloj de COLOMBIA (el negocio), no el del navegador. */
function hoyBogotaDate(): Date {
  const s = new Date().toLocaleDateString('en-CA', { timeZone: 'America/Bogota' })
  const [y, m, d] = s.split('-').map(Number)
  return new Date(y, m - 1, d)
}
type Periodo = 'mes' | 'mes_pasado' | '30d' | 'anio'
function rangoPeriodo(p: Periodo): { desde: string; hasta: string } {
  const hoy = hoyBogotaDate()
  if (p === 'mes') return { desde: isoLocal(new Date(hoy.getFullYear(), hoy.getMonth(), 1)), hasta: isoLocal(hoy) }
  if (p === 'mes_pasado') {
    return {
      desde: isoLocal(new Date(hoy.getFullYear(), hoy.getMonth() - 1, 1)),
      hasta: isoLocal(new Date(hoy.getFullYear(), hoy.getMonth(), 0)),
    }
  }
  if (p === '30d') {
    const d = new Date(hoy); d.setDate(d.getDate() - 29)
    return { desde: isoLocal(d), hasta: isoLocal(hoy) }
  }
  return { desde: isoLocal(new Date(hoy.getFullYear(), 0, 1)), hasta: isoLocal(hoy) }
}

const MESES_CORTOS = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']
const nombreMes = (ym: string) => {
  const [a, m] = ym.split('-')
  return `${MESES_CORTOS[Number(m) - 1]} ${a}`
}

/**
 * Un campo OPCIONAL del backend puesto en pantalla.
 *
 * `undefined` acá no es cero: es «este backend no calcula ese número». Pasarlo
 * por `fmt(x ?? 0)` imprimía un `$0` que el dueño lee como «se midió y dio
 * cero» — la misma familia de mentira que el `?? 0` sobre un dato que no volvió,
 * un nivel más abajo. Sin el campo se dibuja la raya.
 */
const plataOpcional = (v: number | null | undefined) => (v == null ? '—' : fmt(v))
/** El color también es una afirmación: sin número, ni verde ni rojo. */
const tonoSigno = (v: number | null | undefined) =>
  v == null ? 'text-warm-400' : v >= 0 ? 'text-success-600' : 'text-danger-700'

function Kpi({ label, value, sub, Icon, tint }: {
  label: string; value: string; sub?: ReactNode; Icon: typeof Wallet; tint: string
}) {
  return (
    <div className="px-4 py-3">
      <div className="flex items-center gap-1.5 mb-1">
        <Icon size={13} className={tint} />
        <p className="text-[10px] font-bold uppercase tracking-wide text-warm-500">{label}</p>
      </div>
      <p className="text-lg font-bold font-mono tabular-nums text-warm-700 leading-none">{value}</p>
      {sub && <p className="text-[11px] text-warm-400 mt-1 leading-snug">{sub}</p>}
    </div>
  )
}

/**
 * Un renglón de la escalera «De lo cobrado al margen».
 *
 * `signo` es el operador que se aplica sobre el renglón de ARRIBA, y por eso
 * vive en una columna propia: los montos van siempre en positivo. El operador a
 * la izquierda es lo que hace que la resta se lea como resta.
 */
function Fila({ signo, label, hint, valor, tono = 'neutro', fuerte = false }: {
  signo?: '−' | '='
  label: string
  hint?: ReactNode
  valor: number
  tono?: 'neutro' | 'gold' | 'success' | 'danger'
  fuerte?: boolean
}) {
  const color = tono === 'gold' ? 'text-gold-700'
    : tono === 'success' ? 'text-success-600'
    : tono === 'danger' ? 'text-danger-700'
    : 'text-warm-700'
  return (
    <div className={`flex items-baseline gap-2 px-4 py-2.5 ${fuerte ? 'bg-warm-50' : ''}`}>
      <span className="w-3 shrink-0 font-mono text-sm text-warm-400" aria-hidden="true">{signo ?? ''}</span>
      <span className="min-w-0 flex-1">
        <span className={`block text-sm text-warm-700 ${fuerte ? 'font-bold' : 'font-semibold'}`}>{label}</span>
        {hint && <span className="block text-[11px] text-warm-400 leading-snug">{hint}</span>}
      </span>
      <span className={`shrink-0 font-mono tabular-nums ${fuerte ? 'text-base font-extrabold' : 'text-sm font-bold'} ${color}`}>
        {fmt(valor)}
      </span>
    </div>
  )
}

function Delta({ v }: { v: number | null }) {
  if (v == null) return null
  const up = v >= 0
  return (
    <span className={`inline-flex items-center gap-0.5 text-[11px] font-bold ${
      up ? 'text-success-600' : 'text-danger-600'}`}>
      {up ? <TrendingUp size={11} /> : <TrendingDown size={11} />}{up ? '+' : ''}{v}%
    </span>
  )
}

/**
 * ═════════════════════════════════════════════════════════════════════════════
 * «RESULTADO» — ¿GANO?
 * ═════════════════════════════════════════════════════════════════════════════
 * Una página de banners que baja del veredicto al detalle:
 *
 *   1. Margen neto ......... el número y su semáforo
 *   2. De lo cobrado al margen  la resta completa, con el impuesto en el medio
 *   3. Fuga / COGS ......... lo que se va sin que nadie lo explique
 *   4. Por mes y por sede .. quién gana y quién no
 *   5. En qué se fue ....... los costos por categoría, con los sueltos adentro
 *   6. Compras ............. el desglose que «Compras proveedor» nunca tuvo
 *   7. Nómina y descuentos . de dónde sale el costo laboral, cuánto se regaló
 *   8. Los productos ....... los que más y los que menos dejan
 *   9. Salud de datos ...... ¿le puedo creer a todo esto?
 *
 * ── EL HERO Y EL SEMÁFORO SE FUSIONARON ────────────────────────────────────
 * «Hoy» tenía el hero del margen con su semáforo y Resultado tenía el KPI del
 * margen sin veredicto: eran `resumen.margen_neto` dibujado dos veces. Queda uno
 * solo, el que ahora sí emite veredicto.
 *
 * ── LOS UMBRALES ESTÁN RECALIBRADOS ────────────────────────────────────────
 * 15% / 5% miden un margen que YA resta costos fijos. Los viejos (65/50) medían
 * uno que no los restaba: aplicados al margen real marcarían «Alerta» a un
 * negocio sano. Y sin costos fijos cargados NO se emite veredicto, que es lo
 * único honesto: el número todavía no mira lo que dice mirar.
 *
 * ── TODO LO QUE SE DIBUJA ACÁ SALE DE UN `Dato`, NUNCA DE UN `T | null` ────
 * Los dos fetches propios de esta vista (el P&L del período y el desglose de
 * compras) eran el mismo molde `.catch(() => setX(null))` que la página ya mató:
 * el de compras se llevaba puesto, en silencio, el banner «A quién le compro» y
 * el renglón «le pagó X de Y a proveedores» de cada sede. Un banner que
 * desaparece no dice «no pude leer»: dice «no hay nada».
 */
export default function ResultadoView({
  pulso, prodData, plMes, categorias, tiendas, pendientesDatos,
  refreshKey, onRefrescarProductos, onIrALaPlata, onCambio,
}: {
  /** Solo para el delta mes contra mes: sus ventanas son fijas. */
  pulso: Fuente<PulsoData>
  prodData: Fuente<PorProductoData>
  /** El P&L del MES EN CURSO, que es lo que califica al semáforo de salud. */
  plMes: Fuente<RentabilidadData>
  categorias: Fuente<Categoria[]>
  tiendas: Fuente<Tienda[]>
  /** Lo que le falta a los datos para que el margen sea real. `Dato`, no número:
   *  «no se pudo medir» y «no falta nada» son veredictos opuestos. Ver BannerSalud. */
  pendientesDatos: Dato<number>
  refreshKey: number
  onRefrescarProductos: () => void
  onIrALaPlata: () => void
  onCambio: () => void
}) {
  const [periodo, setPeriodo] = useState<Periodo>('mes')
  const [tiendaId, setTiendaId] = useState<number | null>(null)

  const { desde, hasta } = useMemo(() => rangoPeriodo(periodo), [periodo])
  const params = useMemo(
    () => ({ desde, hasta, ...(tiendaId ? { tienda_id: tiendaId } : {}) }),
    [desde, hasta, tiendaId])

  /**
   * LOS DOS FETCHES PROPIOS DE ESTA VISTA.
   *
   * Siguen el filtro de arriba (por eso no viven en la página), pero ya no son
   * `useState<T | null>` con un `.catch(() => setX(null))`: cada uno es una
   * `Fuente` con sus cuatro estados y su propio «Reintentar», igual que los
   * nueve de `Plata.tsx`. Las deps son de largo constante, que es lo que
   * `useDato` necesita; `refreshKey` sube con cada mutación de plata.
   */
  const pl = useDato<RentabilidadData>(
    () => api.get('/rentabilidad/', { params }), 'el resultado del período',
    'No se pudo leer el resultado del período.', [desde, hasta, tiendaId, refreshKey])

  // El desglose de «Compras proveedor», con el MISMO rango: sin esto el KPI es
  // un número que no se puede abrir, mientras los costos operativos sí tienen su
  // partición por categoría.
  const compras = useDato<DashboardFacturas>(
    () => api.get('/facturas/dashboard', { params }), 'las compras a proveedores',
    'No se pudieron leer las compras a proveedores.', [desde, hasta, tiendaId, refreshKey])
  const comprasListo = compras.dato.estado === 'listo' ? compras.dato.valor : null

  // El aviso solo tiene sentido cuando el número YA cambió de valor (o sea,
  // cuando de verdad hay costos fijos restándose).
  const [avisoVisto, setAvisoVisto] = useState(
    () => localStorage.getItem(CLAVE_AVISO_FIJOS) === '1')
  const ocultarAviso = useCallback(() => {
    localStorage.setItem(CLAVE_AVISO_FIJOS, '1')
    setAvisoVisto(true)
  }, [])

  // ── LOS DELTAS MES CONTRA MES ────────────────────────────────────────────
  // El delta SOLO con «Este mes» seleccionado y sin filtro de sede: `pulso`
  // compara el mes en curso contra el mismo tramo del mes pasado con ventanas
  // FIJAS, así que sobre un rango anual o una sede afirmaría una comparación que
  // no es la del filtro.
  //
  // Y SOLO con el pulso EN LA MANO. El viejo `pulso?.mes_actual` trataba un
  // pulso caído igual que un período no comparable: la línea desaparecía sin
  // decir nada, y el dueño leía «no hay nada que comparar» donde la verdad era
  // «no se pudo preguntar».
  const dPulso = pulso.dato
  const mide = periodo === 'mes' && tiendaId == null
  const par = mide && dPulso.estado === 'listo'
    ? { act: dPulso.valor.mes_actual, ant: dPulso.valor.mes_anterior }
    : null
  const dVentas = par ? pctDelta(par.act.ventas, par.ant.ventas) : null
  // Los otros dos del pulso. Venían del módulo viejo y se habían perdido en la
  // mudanza: los KPI se rehicieron como números del DÍA (que es lo correcto en
  // La plata), pero la COMPARACIÓN mes contra mes es de desempeño y vive acá.
  const dTickets = par ? pctDelta(par.act.tickets, par.ant.tickets) : null
  // `ticket_promedio` viene en null cuando no hubo ventas en la ventana: sin
  // promedio no hay comparación posible, y forzarlo a 0 inventaría una caída
  // del 100% en un mes que simplemente no arrancó.
  const dTicketProm = par && par.act.ticket_promedio != null && par.ant.ticket_promedio != null
    ? pctDelta(par.act.ticket_promedio, par.ant.ticket_promedio) : null

  const estadoUi = {
    bien: { label: 'Sano', cls: 'bg-success-50 text-success-600 border-success-200' },
    ojo: { label: 'Ojo', cls: 'bg-gold-50 text-gold-700 border-gold-200' },
    alerta: { label: 'Alerta', cls: 'bg-danger-50 text-danger-700 border-danger-200' },
    sinFijos: { label: 'Sin costos fijos', cls: 'bg-warm-100 text-warm-600 border-warm-200' },
  } as const

  /**
   * El cuerpo del período, con el P&L YA RESUELTO en la mano.
   *
   * Todo lo que hay adentro se deriva de `data`, así que acá abajo no queda un
   * solo `?? 0` sobre un dato que pudo no volver: si `data` no está, esta
   * función no corre y en su lugar se dibuja el hueco honesto.
   */
  const bloquePeriodo = (data: RentabilidadData) => {
    const r = data.resumen
    const margenPositivo = r.margen_neto >= 0
    const pct = r.pct_margen_neto

    // Gate por MONTO: sin impuesto separado, venta_neta == ventas y repetir el
    // número sería ruido (y contra un backend viejo, `undefined > 0` es false y
    // esta vista queda exactamente como estaba).
    const hayImpo = r.impoconsumo > 0
    const basePct = hayImpo ? 'de la venta neta' : 'de la venta'
    // El margen neto YA resta las obligaciones devengadas — pero solo las que
    // alguien cargó. Sin una sola obligación fija en el período, cualquier
    // veredicto sobre este número es aire: por eso hay un TERCER estado. El
    // `?? false` de un backend que no manda el campo cae del lado de NO emitir
    // veredicto, que es el único lado seguro.
    const tieneFijos = r.tiene_costos_fijos ?? false
    const estado = !tieneFijos ? 'sinFijos'
      : pct == null ? null
      : pct >= 15 ? 'bien' : pct >= 5 ? 'ojo' : 'alerta'

    // `gastos_por_categoria` ausente ≠ cero categorías: es un backend que no
    // manda la partición. «0 categorías» al pie de los costos operativos se lee
    // como «no hay en qué abrirlos», y sí los hay.
    const cats = data.gastos_por_categoria
    const nCats = cats
      ? `${cats.length} ${cats.length === 1 ? 'categoría' : 'categorías'}`
      : 'sin desglose por categoría'

    // Pesos ENTEROS, y los dos renglones nuevos se DERIVAN de los otros cuatro:
    // `venta_neta` sale de una división por (1 + tasa) y arrastra centavos
    // arbitrarios. Los números que tienen GEMELO en otra pantalla se muestran tal
    // cual los manda el backend; el centavo lo absorben Impoconsumo y Venta neta,
    // que no se cruzan con nada más.
    const eVentas = Math.round(r.ventas)
    const eCompras = Math.round(r.compras)
    const eGastos = Math.round(r.gastos)
    const eMargen = Math.round(r.margen_neto)
    const eNeta = eMargen + eCompras + eGastos
    const eImpo = eVentas - eNeta

    const hayImpoMes = data.por_mes.some(m => m.impoconsumo > 0)
    // Los dos ejes de la cobertura de la fuga: MESES y SEDES. Cada uno se declara
    // solo cuando falta algo, y los dos sesgan para el mismo lado (subdeclaran).
    const mesesParcial = (r.fuga_meses ?? 0) > 0 && (r.fuga_meses ?? 0) < (r.fuga_meses_rango ?? 0)
    const sedesParcial = (r.fuga_sedes ?? 0) > 0 && (r.fuga_sedes ?? 0) < (r.fuga_sedes_rango ?? 0)

    // El duelo compara SEDES entre sí: la fila «Corporativo» (tienda_id null,
    // arriendo y nómina sin sede) no compite con nadie y falsearía la barra con
    // ventas en 0. Se conserva aparte, porque su costo es real.
    const sedes = data.por_sede.filter(s => s.tienda_id !== null)
    const corporativo = data.por_sede.find(s => s.tienda_id === null) ?? null
    const maxSedeVenta = Math.max(1, ...sedes.map(s => s.ventas))

    return (<>
      {/* Por qué el número no es el que el dueño recordaba. Se muestra una vez. */}
      {tieneFijos && !avisoVisto && (
        <div className="flex items-start gap-2 rounded-2xl border border-gold-200 bg-gold-50 px-4 py-3">
          <Info size={16} className="text-gold-700 mt-0.5 shrink-0" />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-bold text-gold-700">El margen neto cambió de valor</p>
            <p className="text-[11px] text-gold-700/90 mt-0.5 leading-relaxed">
              Ahora descuenta los costos fijos del período ({plataOpcional(r.costos_fijos_devengados)} en
              arriendo, nómina y servicios). Antes no los restaba, así que se veía más alto de lo
              que era. El negocio no cambió: cambió lo que el número mira.
            </p>
          </div>
          <button onClick={ocultarAviso} aria-label="Entendido, no mostrar más"
            className="shrink-0 p-2 -mr-1 -mt-1 rounded-lg text-gold-700 hover:bg-gold-100">
            <X size={15} />
          </button>
        </div>
      )}

      {/* ── 1 · EL MARGEN, con su veredicto ─────────────────────────────── */}
      <section className={`rounded-2xl border shadow-sm p-5 ${
        margenPositivo ? 'bg-white border-warm-200' : 'bg-danger-50 border-danger-200'}`}>
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <p className="text-[11px] font-bold uppercase tracking-wide text-warm-500">
              Margen neto · {periodo === 'mes' ? 'mes en curso'
                : periodo === 'mes_pasado' ? 'mes pasado'
                : periodo === '30d' ? 'últimos 30 días' : 'este año'}
            </p>
            <p className={`text-[32px] leading-tight font-extrabold font-mono tabular-nums ${
              margenPositivo ? 'text-warm-700' : 'text-danger-700'}`}>
              {fmt(r.margen_neto)}
            </p>
            {/* La leyenda NOMBRA la base y la MUESTRA: un % contra una base
                invisible no se puede verificar, y el dueño terminaba
                dividiéndolo contra las ventas de al lado, que no da. */}
            <p className="text-xs text-warm-500 mt-0.5">
              {tieneFijos ? (pct != null
                ? (hayImpo ? `${pct}% de la venta neta (${fmt(r.venta_neta)})` : `${pct}% de la venta`)
                : 'Sin ventas en el período') : (tiendaId != null ? (
                  /* CON SEDE FILTRADA NO ES «FALTAN»: el backend excluye a
                     propósito las obligaciones corporativas, y el arriendo y
                     la nómina viven ahí. Invitar a cargarlos desde acá manda
                     a duplicar el arriendo. Se dice lo que el backend hace.  */
                  <>Esta sede no tiene costos fijos propios: el arriendo y la
                    nómina son corporativos y no entran en la vista por sede.</>
                ) : (<>
                  Faltan los costos fijos del período —{' '}
                  <button onClick={onIrALaPlata}
                    className="font-bold text-forest underline decoration-dotted">
                    cargalos en La plata
                  </button>
                </>))}
            </p>
            {dVentas != null && (
              <p className="text-xs text-warm-500 mt-1">
                Ventas <Delta v={dVentas} /> vs el mismo tramo del mes pasado
              </p>
            )}
            {/* Los tres juntos contestan POR QUÉ se movió la venta: si cayó
                con el ticket firme, entró menos gente; si cayó el ticket con
                los tickets firmes, la gente está gastando menos. Son dos
                problemas distintos con soluciones distintas. */}
            {(dTickets != null || dTicketProm != null) && (
              <p className="text-xs text-warm-500 mt-0.5">
                {dTickets != null && <>Tickets <Delta v={dTickets} /></>}
                {dTickets != null && dTicketProm != null && ' · '}
                {dTicketProm != null && <>Ticket promedio <Delta v={dTicketProm} /></>}
              </p>
            )}
            {/* El período SÍ es comparable pero el pulso no volvió: sin esto la
                comparación se evaporaba y el hueco se leía como «no hay nada
                que comparar». El mes pasado existe; lo que falta es el dato. */}
            {mide && (
              <SegunDato dato={dPulso}
                cargando={<p className="text-xs text-warm-400 mt-1">Comparando con el mes pasado…</p>}
                falla={m => (
                  <div className="mt-1.5">
                    <NoSeSabe mensaje={`${m} Falta la comparación contra el mes pasado.`}
                      onReintentar={pulso.recargar} />
                  </div>
                )}
                listo={() => null} />
            )}
          </div>
          {/* El semáforo es un VEREDICTO, no una puerta: la única puerta a
              cargar los costos fijos es el link de la leyenda de acá al lado.
              Antes eran dos botones al mismo lugar en la misma tarjeta, y dos
              puertas idénticas hacen dudar de si llevan a lo mismo. */}
          {estado && (
            <span className={`shrink-0 px-2.5 py-1 rounded-full border text-xs font-bold ${estadoUi[estado].cls}`}>
              {estadoUi[estado].label}
            </span>
          )}
        </div>
      </section>

      {/* Los cuatro números sueltos que el dueño resta de cabeza. */}
      <section className="rounded-2xl border border-warm-200 bg-white grid grid-cols-2 sm:grid-cols-4 divide-x divide-y sm:divide-y-0 divide-warm-100 overflow-hidden">
        <Kpi label="Ventas" value={fmt(r.ventas)} Icon={Wallet} tint="text-forest"
          sub={hayImpo ? `${r.n_tickets} tickets · lo cobrado, impoconsumo adentro`
                       : `${r.n_tickets} tickets`} />
        <Kpi label="Compras proveedor" value={fmt(r.compras)} Icon={ShoppingCart} tint="text-gold-600"
          sub={`${r.n_facturas} facturas recibidas`} />
        <Kpi label="Costos operativos" value={fmt(r.gastos)} Icon={Receipt} tint="text-danger-500"
          sub={nCats} />
        <Kpi label="Margen neto" value={fmt(r.margen_neto)}
          Icon={margenPositivo ? TrendingUp : TrendingDown}
          tint={margenPositivo ? 'text-success-600' : 'text-danger-500'}
          sub={<>{pct != null ? `${pct}% ${basePct}` : 'sin ventas'}
            {tieneFijos ? '' : ' · sin costos fijos cargados'}</>} />
      </section>

      {/* ── 2 · LA RESTA COMPLETA ───────────────────────────────────────── */}
      <Banner titulo="De lo cobrado al margen"
        sub={hayImpo
          ? 'El precio de la carta lleva el impoconsumo adentro: esa parte se le gira a la DIAN, nunca fue del negocio.'
          : 'La resta completa, renglón por renglón.'}>
        <div className="divide-y divide-warm-100">
          <Fila label="Ventas" valor={eVentas}
            hint={hayImpo ? `${r.n_tickets} tickets · lo que cobraste` : `${r.n_tickets} tickets`} />
          {hayImpo && (<>
            <Fila signo="−" label="Impoconsumo" valor={eImpo} tono="gold"
              hint={`${fmtTasa(r.tasa_impoconsumo)} sobre la venta neta, incluido en el precio de la carta`} />
            {/* OJO con el copy: la venta neta es la base del margen neto y de su
                %, NO de todos los % de la pantalla — el margen bruto real y la
                fuga se miden contra lo cobrado (y lo dicen en su tarjeta). */}
            <Fila signo="=" label="Venta neta" valor={eNeta} fuerte
              hint="la plata que sí es del negocio — la base del margen neto y de su %" />
          </>)}
          <Fila signo="−" label="Compras proveedor" valor={eCompras}
            hint={`${r.n_facturas} facturas recibidas en el período`} />
          <Fila signo="−" label="Costos operativos" valor={eGastos}
            hint={cats ? `${nCats} — el detalle está más abajo` : nCats} />
          <Fila signo="=" label="Margen neto" valor={eMargen} fuerte
            tono={margenPositivo ? 'success' : 'danger'}
            hint={pct != null
              ? `${pct}% ${basePct}${tieneFijos ? '' : ' · sin costos fijos cargados'}`
              : 'sin ventas en el período'} />
        </div>
        {/* La tarifa sin confirmar se avisa SOLO cuando de verdad está
            separando plata: con impoconsumo en 0 la bandera viene prendida por
            defecto y el cartel hablaría de una tarifa que no se aplica. */}
        {hayImpo && r.impoconsumo_confirmar_contador && (
          <p className="text-[11px] text-clay-600 bg-clay-50 border-t border-clay-200 px-4 py-2">
            La tarifa del impoconsumo (<b className="font-mono">{fmtTasa(r.tasa_impoconsumo)}</b>) está
            cargada pero <b>todavía sin confirmar con tu contador</b>. Si la que te aplica es otra,
            se mueven la venta neta, el margen neto y su %.
          </p>
        )}
        {/* LAS TRES CONDICIONES SON NECESARIAS Y NINGUNA ES DECORATIVA:
            · `typeof` — «el backend mandó cero» y «el backend no mandó el
              campo» son cosas distintas; con un backend viejo esto se calla.
            · `!hayImpo` — el estado del que habla la frase.
            · `r.ventas > 0` — SIN VENTAS el impoconsumo da 0 aunque la tarifa
              esté vigente. Sin este guard, un mes sin ventas afirmaría que el
              precio no lleva el impuesto adentro: una conclusión sacada de un
              cero que solo significa «no se vendió». */}
        {typeof r.impoconsumo === 'number' && !hayImpo && r.ventas > 0 && (
          <p className="text-[11px] text-gold-700 bg-gold-50 border-t border-gold-200 px-4 py-2">
            Este período <b>no descuenta impoconsumo</b>: el margen neto y su % se miden sobre
            todo lo cobrado.{' '}
            {r.tasa_impoconsumo > 0
              ? `La tarifa cargada es ${fmtTasa(r.tasa_impoconsumo)}, pero el parámetro dice que el precio de la carta no la lleva adentro.`
              : 'No hay ninguna tarifa cargada.'}
            {r.impoconsumo_confirmar_contador && ' El parámetro está sin confirmar con tu contador.'}
          </p>
        )}
      </Banner>

      {/* ── 3 · FUGA DE INVENTARIO ──────────────────────────────────────────
          Va contra el margen bruto REAL: `margen_neto` sale de `compras`, que
          es base de RECEPCIÓN, así que la mercadería fugada YA está gastada ahí
          adentro y restarla otra vez descontaría dos veces la misma plata. */}
      {r.tiene_fuga_medida && r.fuga_inventario != null && (
        <Banner titulo="Fuga de inventario — lo que el conteo midió y nada explica"
          sub={hayImpo
            ? '«Margen sobre lo vendido» y «Queda después del residuo» salen de lo cobrado, no de la venta neta'
            : undefined}>
          <div className="grid grid-cols-3 gap-2 text-center px-4 py-3">
            <div>
              <p className="text-[10px] uppercase font-bold text-warm-500">Margen sobre lo vendido</p>
              <p className="text-sm font-mono font-bold tabular-nums text-warm-700 mt-0.5">
                {plataOpcional(r.margen_bruto_real)}
              </p>
            </div>
            <div>
              {/* RESIDUO NETO, no «fuga»: los sobrantes de un producto netean
                  contra los faltantes de otro. Neto es lo que la resta de al
                  lado necesita, pero el rótulo tiene que decir qué es. */}
              <p className="text-[10px] uppercase font-bold text-warm-500">Residuo neto</p>
              <p className={`text-sm font-mono font-bold tabular-nums mt-0.5 ${
                r.fuga_inventario < 0 ? 'text-danger-600' : 'text-warm-700'}`}
                title="Faltantes MENOS sobrantes: un producto que apareció de más compensa al que faltó. El faltante bruto es mayor que este número.">
                {fmt(r.fuga_inventario)}
              </p>
            </div>
            <div>
              <p className="text-[10px] uppercase font-bold text-warm-500">Queda después del residuo</p>
              <p className={`text-sm font-mono font-bold tabular-nums mt-0.5 ${
                tonoSigno(r.margen_bruto_real_con_fuga)}`}>
                {plataOpcional(r.margen_bruto_real_con_fuga)}
                {r.pct_margen_bruto_real_con_fuga != null && (
                  <span className="text-warm-400 font-normal"> ({r.pct_margen_bruto_real_con_fuga}%)</span>
                )}
              </p>
            </div>
          </div>
          {/* LOS DOS TÉRMINOS NO MIDEN EL MISMO TRAMO, Y EL TRAMO TIENE DOS
              EJES (meses y sedes). Los dos sesgos van para el lado optimista:
              subdeclaran la fuga. Se dicen los dos, donde está el KPI. */}
          {(mesesParcial || sedesParcial) && (
            <p className="text-[11px] text-gold-700 bg-gold-50 border-y border-gold-200 px-4 py-2 leading-relaxed">
              <b>Los dos números no cubren el mismo tramo.</b>
              {mesesParcial && (
                <> El margen es de todo el período ({r.fuga_meses_rango} meses); la fuga sale solo
                  de {r.fuga_meses} mes{r.fuga_meses === 1 ? '' : 'es'} ya
                  cerrado{r.fuga_meses === 1 ? '' : 's'} y completo{r.fuga_meses === 1 ? '' : 's'} adentro
                  del rango.</>
              )}
              {sedesParcial && (
                <> El margen suma las {r.fuga_sedes_rango} sedes que vendieron; la fuga sale solo
                  de {r.fuga_sedes} que cerró{r.fuga_sedes === 1 ? '' : 'aron'} el conteo. Lo que se
                  fuga en {(r.fuga_sedes_rango ?? 0) - (r.fuga_sedes ?? 0) === 1 ? 'la sede' : 'las sedes'} que
                  no cuenta{(r.fuga_sedes_rango ?? 0) - (r.fuga_sedes ?? 0) === 1 ? '' : 'n'} no aparece acá,
                  pero su venta sí está arriba.</>
              )}
              {' '}Lo que no se cerró todavía no midió nada, así
              que <b>la fuga real del período es mayor</b> que la de acá.
            </p>
          )}
          <ComoSeCalcula titulo="¿De dónde sale este número y por qué no se resta del margen neto?">
            <p>
              Sale de los cierres de mes que caen completos en este período: lo contado contra lo
              que el libro de movimientos dice que debería haber, descontando entradas, ventas,
              mermas, traslados y ajustes. Es un <b>neto</b>: lo que sobró en un producto compensa
              lo que faltó en otro, así que el faltante bruto es mayor.
              {(r.fuga_cobertura_productos ?? 0) > 0 && (
                <> Cubre {r.fuga_cobertura_contados} de {r.fuga_cobertura_productos} producto-mes
                  {(r.fuga_cierres ?? 0) > 0 && <> en {r.fuga_cierres} cierre{r.fuga_cierres === 1 ? '' : 's'} de mes</>}.</>
              )}
              {(r.fuga_sin_costo ?? 0) > 0 && (
                <> {r.fuga_sin_costo} producto{r.fuga_sin_costo === 1 ? '' : 's'} con faltante no
                  tiene costo cargado, así que su fuga no suma acá.</>
              )}
              {(r.fuga_estimados ?? 0) > 0 && (
                <> {r.fuga_estimados} se valorizó con el precio de VENTA porque no hay costo ni
                  factura: ese pedazo del total está <b>sobrestimado</b>.</>
              )}
            </p>
            <p>
              Se descuenta del margen sobre lo VENDIDO y no del margen neto: ahí la mercadería ya
              está gastada entera al recibirla, así que restarla de nuevo sería contar la misma
              plata dos veces.
            </p>
            {/* ASIMETRÍA DE VALORIZACIÓN DENTRO DE LA MISMA RESTA: el costo de
                lo vendido deja en $0 lo que no tiene costo; la fuga en cambio
                cae al precio de venta. No se unifica —hacerlo pondría en $0 la
                fuga de justo los productos que nadie va a investigar— así que
                se declara donde se hace la resta. */}
            <p>
              Los dos términos <b>no se valorizan con la misma regla</b>: el costo de lo vendido
              deja en $0 lo que no tiene costo cargado (cubre el {r.pct_venta_costeada ?? '—'}% de
              la venta), y la fuga en cambio cae al precio de venta cuando no hay costo. El mismo
              producto puede pesar distinto de cada lado de la resta.
            </p>
          </ComoSeCalcula>
        </Banner>
      )}

      {/* COGS teórico: base de consumo (complementa a compras = recepción). */}
      {r.cogs_teorico != null && (
        <Banner titulo="Costo de lo VENDIDO (teórico) — sin la distorsión del stockeo"
          sub={`Cubre el ${r.pct_venta_costeada ?? '—'}% de la venta (los productos con costo cargado)`}>
          <div className="grid grid-cols-3 gap-2 text-center px-4 py-3">
            <div>
              <p className="text-[10px] uppercase font-bold text-warm-500">Consumo teórico</p>
              <p className="text-sm font-mono font-bold tabular-nums text-warm-700 mt-0.5">{fmt(r.cogs_teorico)}</p>
            </div>
            <div>
              <p className="text-[10px] uppercase font-bold text-warm-500">Margen bruto real</p>
              <p className={`text-sm font-mono font-bold tabular-nums mt-0.5 ${
                r.margen_bruto_real == null ? 'text-warm-400' : 'text-success-600'}`}>
                {plataOpcional(r.margen_bruto_real)}
                {r.pct_margen_bruto_real != null && (
                  <span className="text-warm-400 font-normal"> ({r.pct_margen_bruto_real}%)</span>
                )}
              </p>
            </div>
            <div>
              <p className="text-[10px] uppercase font-bold text-warm-500">Compras − consumo</p>
              <p className={`text-sm font-mono font-bold tabular-nums mt-0.5 ${
                r.brecha_compras == null ? 'text-warm-400'
                  : r.brecha_compras >= 0 ? 'text-gold-700' : 'text-danger-700'}`}>
                {plataOpcional(r.brecha_compras)}
              </p>
            </div>
          </div>
          <p className="px-4 pb-3 text-[11px] text-warm-500 leading-relaxed">
            Brecha positiva = stockeaste (compraste más de lo que consumiste).
            {/* LA BASE DE ESTA TARJETA NO ES LA DE ARRIBA: el backend calcula
                `margen_bruto_real` como ventas − cogs y su % sobre `ventas`, o
                sea sobre lo COBRADO. Son dos números que el dueño va a comparar
                sí o sí, así que la diferencia se dice acá. */}
            {hayImpo && (
              <> Este margen y su % se miden sobre <b>lo cobrado</b> ({fmt(r.ventas)}), no sobre la
                venta neta: todavía tienen el impoconsumo adentro, así que se ven más altos que el
                margen neto de arriba.</>
            )}
          </p>
        </Banner>
      )}

      {/* ── 4 · POR MES ─────────────────────────────────────────────────── */}
      {data.por_mes.length > 1 && (
        <Banner titulo="Mes a mes" sub="¿Voy mejorando?">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-[10px] uppercase tracking-wide text-warm-500 border-b border-warm-100">
                  <th className="text-left px-4 py-2 font-bold">Mes</th>
                  <th className="text-right px-3 py-2 font-bold">{hayImpoMes ? 'Ventas (cobrado)' : 'Ventas'}</th>
                  <th className="text-right px-3 py-2 font-bold">Compras</th>
                  <th className="text-right px-3 py-2 font-bold">Gastos</th>
                  <th className="text-right px-4 py-2 font-bold">Margen</th>
                  <th className="text-right px-4 py-2 font-bold">{hayImpoMes ? '% s/neta' : '%'}</th>
                </tr>
              </thead>
              <tbody>
                {data.por_mes.map(m => (
                  <tr key={m.mes} className="border-b border-warm-100 last:border-0">
                    <td className="px-4 py-2.5 font-semibold text-warm-700">{nombreMes(m.mes)}</td>
                    {/* Gate POR FILA y por monto: cada mes se cierra con la
                        tarifa que regía ESE mes, así que un mes sin impuesto
                        conviviendo con otros que sí lo tienen es un estado
                        posible y no puede mostrar un «neta» que repite el de
                        al lado. */}
                    <td className="px-3 py-2.5 text-right font-mono tabular-nums text-warm-700">
                      {fmt(m.ventas)}
                      {m.impoconsumo > 0 && (
                        <span className="block text-[10px] text-warm-400">neta {fmt(m.venta_neta)}</span>
                      )}
                    </td>
                    <td className="px-3 py-2.5 text-right font-mono tabular-nums text-warm-500">{fmt(m.compras)}</td>
                    <td className="px-3 py-2.5 text-right font-mono tabular-nums text-warm-500">{fmt(m.gastos)}</td>
                    <td className={`px-4 py-2.5 text-right font-mono font-bold tabular-nums ${
                      m.margen_neto >= 0 ? 'text-success-600' : 'text-danger-600'}`}>
                      {fmt(m.margen_neto)}
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono tabular-nums text-warm-400">
                      {m.pct_margen_neto != null ? `${m.pct_margen_neto}%` : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {hayImpoMes && (
            <p className="px-4 py-2 text-[11px] text-warm-500 border-t border-warm-100 leading-relaxed">
              «Ventas» es lo cobrado; «neta» le saca el impoconsumo. El margen y el % de cada mes
              salen de la venta neta de ESE mes, calculada con la tarifa que regía entonces.
            </p>
          )}
        </Banner>
      )}

      {/* ── 5 · LAS SEDES, EN UN SOLO DIBUJO ────────────────────────────────
          «Hoy» tenía un duelo de barras y Resultado unas tarjetas: dos dibujos
          de `por_sede`, y eso es lo que hace dudar de cuál manda. Queda uno,
          con la barra (que deja comparar de un golpe) y el detalle completo.

          El título CUENTA las sedes que vinieron, no dice «las dos»: el día que
          se abra una tercera, la frase seguiría afirmando un número que ya no
          es. Misma disciplina que el resto del módulo. */}
      {!tiendaId && sedes.length > 1 && (
        <Banner titulo={`Las ${sedes.length} sedes`}
          sub="Cuál gana y cuál no, en el período que estás mirando">
          <div className="px-4 py-3 space-y-3">
            {sedes.map(s => {
              // Sin el desglose de compras NO se dibuja el renglón: `?? []`
              // sobre un fetch caído dejaba a cada sede sin su «le pagó X de
              // Y», y la falta se leía como «no le debe nada a nadie». Lo que
              // no volvió se dice una sola vez, al pie del banner.
              const prov = comprasListo?.por_sede.find(x => x.tienda === s.tienda)
              return (
                <div key={s.tienda_id}>
                  <div className="flex items-baseline justify-between gap-2 text-sm">
                    <span className="font-semibold text-warm-700 truncate">{s.tienda}</span>
                    <span className="font-mono tabular-nums text-warm-600 shrink-0">
                      {fmt(s.ventas)} ·{' '}
                      <span className={s.margen_neto >= 0 ? 'text-success-600 font-bold' : 'text-danger-600 font-bold'}>
                        {fmt(s.margen_neto)}
                      </span>
                      {s.pct_margen_neto != null && <span className="text-warm-400"> ({s.pct_margen_neto}%)</span>}
                    </span>
                  </div>
                  <div className="h-2 rounded-full bg-warm-100 overflow-hidden mt-1">
                    <div className="h-full rounded-full bg-forest-400"
                      style={{ width: `${Math.max(4, (s.ventas / maxSedeVenta) * 100)}%` }} />
                  </div>
                  <p className="text-[11px] text-warm-500 mt-1">
                    {s.impoconsumo > 0 && <>Venta neta {fmt(s.venta_neta)} · </>}
                    Compras + costos {fmt(s.compras + s.gastos)}
                    {prov && <> · le pagó {fmt(prov.pagado)} de {fmt(prov.facturado)} a proveedores</>}
                  </p>
                </div>
              )
            })}
          </div>
          {/* El renglón de proveedores que falta en CADA sede, dicho una vez. */}
          <SegunDato dato={compras.dato}
            cargando={null}
            falla={m => (
              <div className="px-4 pb-3">
                <NoSeSabe mensaje={`${m} Por eso a cada sede le falta el renglón de lo que le pagó a proveedores.`}
                  onReintentar={compras.recargar} />
              </div>
            )}
            listo={() => null} />
          {/* Las dos cifras de cada sede NO salen de la misma base: la barra y
              el primer número son lo COBRADO, y el margen con su % salen de la
              venta neta de esa sede. Se dice acá porque es la única forma de
              que el dueño no intente dividir un número por el otro. */}
          {sedes.some(s => s.impoconsumo > 0) && (
            <p className="px-4 pb-2 text-[11px] text-warm-400 leading-relaxed">
              El primer número (y la barra) es lo cobrado; el margen y su % salen de la venta neta,
              sin el impoconsumo.
            </p>
          )}
          {/* Corporativo NO compite en la barra: no vende nada y la falsearía
              con ventas en 0. Pero su costo es real y tiene que verse. */}
          {corporativo && (corporativo.gastos > 0 || corporativo.compras > 0) && (
            <p className="px-4 py-2 text-[11px] text-warm-500 border-t border-warm-100 flex items-start gap-1.5">
              <Building2 size={12} className="mt-0.5 shrink-0" />
              <span>
                Además hay <b className="font-mono tabular-nums">{fmt(corporativo.compras + corporativo.gastos)}</b>{' '}
                de costos <b>corporativos</b> (arriendo, nómina y servicios que no pertenecen a
                ninguna sede). No entran en las barras porque no venden, pero sí están restados en
                el margen de arriba.
              </span>
            </p>
          )}
        </Banner>
      )}

      {/* ── 6 · EN QUÉ SE FUERON LOS COSTOS OPERATIVOS ──────────────────────
          Σ de las categorías == «Costos operativos»: es una PARTICIÓN, no otro
          número (backend: services/rentabilidad.py). */}
      {cats && cats.length > 0 && (
        <Banner titulo={`En qué se fueron los ${fmt(r.gastos)}`}
          sub="Nómina, arriendo, servicios: la categoría, no el texto que alguien tecleó en caja">
          {cats.map(g => {
            const pctCat = r.gastos > 0 ? (g.total / r.gastos) * 100 : 0
            const suelto = g.clave === 'sin_categorizar'
            return (
              <div key={g.clave} className="px-4 py-2 border-b border-warm-100 last:border-0">
                <div className="flex items-baseline justify-between gap-2 text-sm">
                  <span className="min-w-0 truncate">
                    <span className={`font-semibold ${suelto ? 'text-gold-700' : 'text-warm-700'}`}>{g.nombre}</span>
                    {g.grupo && (
                      <span className="text-[10px] uppercase font-bold text-warm-400 ml-1.5">{g.grupo}</span>
                    )}
                  </span>
                  <span className="font-mono tabular-nums text-warm-700 shrink-0">
                    {fmt(g.total)} <span className="text-warm-400">({Math.round(pctCat)}%)</span>
                  </span>
                </div>
                <div className="h-1.5 rounded-full bg-warm-100 overflow-hidden mt-1">
                  <div className={`h-full rounded-full ${suelto ? 'bg-gold-400' : 'bg-danger-400'}`}
                    style={{ width: `${Math.max(2, pctCat)}%` }} />
                </div>
              </div>
            )
          })}
          {/* La bolsa sin categorizar es la única fila ACCIONABLE, y su
              herramienta cuelga de ella en vez de vivir en un cajón. */}
          {cats.some(g => g.clave === 'sin_categorizar') && (
            <BannerEgresos categorias={categorias} desde={desde} hasta={hasta}
              tiendaId={tiendaId} onCambio={onCambio} />
          )}
        </Banner>
      )}

      {/* ── 7 · A QUIÉN LE COMPRO ──────────────────────────────────────────
          El desglose que «Compras proveedor» nunca tuvo: los costos operativos
          sí tenían su partición por categoría y las compras eran un número
          cerrado. Mismo rango que el resto de la pestaña.

          El banner ENTERO se evaporaba con el fetch caído, y un banner que no
          está dice «no le compraste a nadie». Ahora el hueco ocupa su lugar. */}
      <SegunDato dato={compras.dato}
        cargando={<div className="h-28 rounded-2xl bg-warm-100 animate-pulse" />}
        falla={m => (
          <Banner titulo="A quién le compro"
            sub="Las facturas recibidas en el período, por proveedor">
            <div className="p-3">
              <NoSeSabe bloque mensaje={m} onReintentar={compras.recargar} />
            </div>
          </Banner>
        )}
        listo={c => {
          // Acá el vacío SÍ está medido: el backend contestó y no hubo ninguna
          // factura en el rango. Nada que mostrar y nada que afirmar.
          if (c.por_proveedor.length === 0) return null
          const maxProv = Math.max(1, ...c.por_proveedor.map(p => p.facturado))
          return (
            <Banner titulo="A quién le compro"
              sub={<>Las {c.totales.n_facturas} facturas recibidas en el período, por proveedor</>}>
              <div className="px-4 py-3 space-y-2">
                {c.por_proveedor.slice(0, 8).map(p => (
                  <div key={p.proveedor}>
                    <div className="flex items-baseline justify-between gap-2 text-xs mb-0.5">
                      <span className="font-semibold text-warm-700 truncate">{p.proveedor}</span>
                      <span className="font-mono tabular-nums text-warm-600 shrink-0">
                        {fmt(p.facturado)}
                        {p.pendiente > 0 && (
                          <span className="text-danger-700"> · debés {fmt(p.pendiente)}</span>
                        )}
                      </span>
                    </div>
                    <div className="h-2 rounded-full bg-warm-100 overflow-hidden flex">
                      <div className="h-full bg-success-500" style={{ width: `${(p.pagado / maxProv) * 100}%` }}
                        title={`Pagado ${fmt(p.pagado)}`} />
                      <div className="h-full bg-danger-400" style={{ width: `${(p.pendiente / maxProv) * 100}%` }}
                        title={`Pendiente ${fmt(p.pendiente)}`} />
                    </div>
                  </div>
                ))}
              </div>
              <p className="px-4 pb-3 text-[11px] text-warm-500 leading-relaxed">
                La barra verde es lo que ya le pagaste y la roja lo que le debés, medidas contra el
                proveedor al que más le compraste. Cuenta por el día en que <b>entró la mercadería</b>,
                no por el día en que se paga: por eso es la misma base que «Compras proveedor» de
                arriba. Las facturas una por una, con su vencimiento, están en <b>La plata</b>.
              </p>
            </Banner>
          )
        }} />

      {/* ── 8 · NÓMINA ──────────────────────────────────────────────────────
          El número ya está DENTRO de «Costos operativos» y del margen: acá no
          se vuelve a sumar nada. Se muestra porque son DOS fuentes posibles y
          leerlas como una sola escondería cuál se usó. */}
      {((r.nomina_calculada ?? 0) > 0 || (r.nomina_meses_manuales?.length ?? 0) > 0) && (
        <Banner titulo="Nómina — de dónde sale este costo"
          sub="Ya está adentro de «Costos operativos»: acá no se suma otra vez">
          <div className="px-4 py-3 space-y-1.5">
            {(r.nomina_calculada ?? 0) > 0 && (
              <p className="text-sm text-warm-700">
                <span className="font-mono font-bold tabular-nums">{plataOpcional(r.nomina_calculada)}</span>{' '}
                calculados con {r.nomina_horas} h marcadas de {r.nomina_personas}{' '}
                {r.nomina_personas === 1 ? 'persona' : 'personas'} y los recargos de ley
                {(r.nomina_meses_calculados?.length ?? 0) > 0 && ` (${r.nomina_meses_calculados!.join(', ')})`}.
              </p>
            )}
            {/* La separación se hace MES POR MES. El mes con nómina a mano
                descarta su cálculo SIEMPRE, pero la plata manual entra en la
                ventana que contiene su devengo: mirando «del 1 a hoy» con la
                nómina devengada el 31, ese costo laboral no está en ningún
                lado. Con un rango de varios meses los dos casos CONVIVEN, y
                decidir por el total dejaría que un mes cubierto tape al que
                quedó sin nada. */}
            {(() => {
              const meses = r.nomina_meses_manuales ?? []
              if (!meses.length) return null
              const porMes = r.nomina_manual_por_mes ?? {}
              const adentro = meses.filter(m => (porMes[m] ?? 0) > 0)
              const afuera = meses.filter(m => !((porMes[m] ?? 0) > 0))
              const plataManual = adentro.reduce((a, m) => a + (porMes[m] ?? 0), 0)
              return (<>
                {adentro.length > 0 && (
                  <p className="text-xs text-warm-500">
                    {adentro.join(', ')}:{' '}
                    <span className="font-mono tabular-nums">{fmt(plataManual)}</span> de nómina
                    cargada a mano; el cálculo de esos meses se descartó, para no contar el sueldo
                    dos veces.
                  </p>
                )}
                {afuera.length > 0 && (
                  <p className="text-xs text-gold-700">
                    {afuera.join(', ')}: la nómina de{' '}
                    {afuera.length === 1 ? 'ese mes está cargada' : 'esos meses está cargada'} a mano
                    con fecha fuera de este período, así que <b>su costo laboral no está en este
                    margen</b>. Consultá {afuera.length === 1 ? 'ese mes completo' : 'esos meses completos'} para verlo.
                  </p>
                )}
              </>)
            })()}
            {(r.nomina_sin_contrato ?? 0) > 0 && (
              <p className="text-xs text-gold-700">
                <b>{r.nomina_sin_contrato}</b>{' '}
                {r.nomina_sin_contrato === 1 ? 'persona trabajó' : 'personas trabajaron'} sin salario
                cargado en Contratos: esas horas entran al margen valiendo $0 y el costo real es mayor.
              </p>
            )}
            {(r.nomina_calculada ?? 0) > 0 && (
              <p className="text-[11px] text-warm-400 leading-relaxed">
                Es el tiempo trabajado con sus recargos: no incluye prestaciones, seguridad social
                ni auxilio de transporte. Es un piso, no la liquidación del contador.
              </p>
            )}
          </div>
        </Banner>
      )}

      {/* DESCUENTOS: `ventas` ya viene neto — esto dice cuánto se resignó, no
          cuánto falta. Sin el número, un descuento y una venta que no ocurrió
          se ven igual. */}
      {(r.descuentos ?? 0) > 0 && (
        <div className="flex items-center gap-3 bg-white rounded-2xl border border-warm-200 px-4 py-3">
          <Scissors size={16} className="text-gold-600 shrink-0" />
          <span className="min-w-0 flex-1">
            <span className="block text-sm font-bold text-warm-700">
              Se regalaron {plataOpcional(r.descuentos)} en descuentos
            </span>
            <span className="block text-[11px] text-warm-500">
              {/* Con plata regalada, «0 tickets» es imposible: ese cero solo
                  puede venir de un backend que no manda el contador. */}
              {r.n_tickets_con_descuento != null ? `${r.n_tickets_con_descuento} tickets` : 'tickets sin contar'}
              {r.pct_descuento != null && ` · ${r.pct_descuento}% de lo que se habría facturado`}
              {' '}— ya está descontado de las ventas de arriba, no se resta de nuevo
            </span>
          </span>
        </div>
      )}
    </>)
  }

  return (
    <div className="space-y-3">
      {/* Filtros: gobiernan TODOS los banners de esta pestaña. */}
      <div className="sticky top-[52px] z-10 -mx-1 px-1 py-1.5 bg-warm-50/90 backdrop-blur-sm flex items-center gap-1.5 overflow-x-auto">
        {(([['mes', 'Este mes'], ['mes_pasado', 'Mes pasado'], ['30d', '30 días'], ['anio', 'Este año']]) as [Periodo, string][]).map(([p, lbl]) => (
          <button key={p} onClick={() => setPeriodo(p)}
            className={`shrink-0 min-h-[40px] px-3 rounded-full text-xs font-bold border transition-colors ${
              periodo === p ? 'bg-forest text-white border-forest' : 'bg-white text-warm-500 border-warm-200'}`}>
            {lbl}
          </button>
        ))}
        {/* El selector NO se esconde cuando el catálogo de sedes no vuelve: es
            un control, y esconderlo le rompe el filtro al dueño. Queda montado
            con «Todas las sedes» —que es la verdad: no se está filtrando— y el
            renglón de abajo dice por qué no hay ninguna otra opción. */}
        <select value={tiendaId ?? ''} aria-label="Sede"
          onChange={e => setTiendaId(e.target.value ? Number(e.target.value) : null)}
          className="shrink-0 ml-auto border border-warm-200 rounded-full px-3 min-h-[40px] text-xs font-bold bg-white text-warm-600">
          <option value="">Todas las sedes</option>
          {tiendas.dato.estado === 'listo'
            && tiendas.dato.valor.map(t => <option key={t.id} value={t.id}>{t.nombre}</option>)}
        </select>
      </div>

      <SegunDato dato={tiendas.dato}
        cargando={null}
        falla={m => (
          <NoSeSabe mensaje={`${m} El filtro de arriba solo puede quedarse en «Todas las sedes».`}
            onReintentar={tiendas.recargar} />
        )}
        listo={() => null} />

      {/* El P&L del período: el cuerpo entero de la pestaña cuelga de él.
          `cargando` es un esqueleto mudo —no un error— y la falla ocupa el
          mismo lugar que ocuparía el resultado, con su «Reintentar». */}
      <SegunDato dato={pl.dato}
        cargando={
          <div className="space-y-3" aria-label="Cargando">
            <div className="h-24 rounded-2xl bg-warm-100 animate-pulse" />
            <div className="h-40 rounded-2xl bg-warm-100 animate-pulse" />
          </div>
        }
        falla={m => <NoSeSabe bloque mensaje={m} onReintentar={pl.recargar} />}
        listo={bloquePeriodo} />

      {/* ── 9 y 10, FUERA DEL CONDICIONAL DEL P&L ─────────────────────────────
          Estos dos NO dependen del fetch del período: `prodData` y `plMes` los
          trae la página aparte y siguen en memoria aunque `/rentabilidad/` falle
          para el rango elegido. Adentro del bloque, un P&L caído se llevaba
          puesta la única puerta al OCR y a los aliases — que es justamente la
          acción que ARREGLA el margen. Cada uno dibuja sus cuatro estados. */}
      <BannerProductos prodData={prodData} />
      <BannerSalud prodData={prodData} plMes={plMes} pendientes={pendientesDatos}
        onRefrescarProductos={onRefrescarProductos} onIrALaPlata={onIrALaPlata} />

      <p className="flex items-center gap-1.5 px-1 text-[11px] text-warm-400">
        <HelpCircle size={12} /> Cada banner tiene su «¿cómo se calcula?» adentro.
      </p>
    </div>
  )
}
