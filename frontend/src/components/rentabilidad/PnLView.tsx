import { ReactNode, useEffect, useState } from 'react'
import { Wallet, ShoppingCart, Receipt, TrendingUp, TrendingDown, HelpCircle, ArrowRight, Inbox, Scissors } from 'lucide-react'
import api from '../../api/client'
import { RentabilidadData, fmt } from './helpers'

interface Tienda { id: number; nombre: string }

function isoLocal(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
// "Hoy" según el reloj de COLOMBIA (el negocio), no el del navegador.
function hoyBogota(): Date {
  const s = new Date().toLocaleDateString('en-CA', { timeZone: 'America/Bogota' })
  const [y, m, d] = s.split('-').map(Number)
  return new Date(y, m - 1, d)
}
type Periodo = 'mes' | 'mes_pasado' | '30d' | 'anio'
function rangoPeriodo(p: Periodo): { desde: string; hasta: string } {
  const hoy = hoyBogota()
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

function Kpi({ label, value, sub, Icon, tint }: {
  label: string; value: string; sub?: ReactNode; Icon: typeof Wallet; tint: string
}) {
  return (
    <div className="bg-white rounded-2xl border border-warm-200 p-4">
      <div className="flex items-center gap-2 mb-1.5">
        <Icon size={14} className={tint} />
        <p className="text-[11px] font-bold uppercase tracking-wide text-warm-400">{label}</p>
      </div>
      <p className="text-xl font-bold text-warm-700 font-mono leading-none tabular-nums">{value}</p>
      {sub && <p className="text-xs text-warm-400 mt-1.5">{sub}</p>}
    </div>
  )
}

/**
 * `refreshKey` cierra el loop CTA→acción→resultado del cajón «Egresos sin
 * categorizar». Esta vista tiene su PROPIO `data` (necesita el selector de período
 * y de sede, que el resto de Plata no usa), así que el refresco que hace Plata al
 * cerrar un cajón —`plMes`, agenda y flujo— no la tocaba: el dueño adoptaba un
 * egreso, cerraba, y la fila que acababa de arreglar seguía bajo «Sin categorizar».
 * Un contador que sube al cerrar el cajón es lo que vuelve a pedir estos datos.
 */
export default function PnLView({ onVerMetodologia, onAbrirSinCategorizar, refreshKey = 0 }: {
  onVerMetodologia: () => void
  onAbrirSinCategorizar: () => void
  refreshKey?: number
}) {
  const [periodo, setPeriodo] = useState<Periodo>('mes')
  const [tiendas, setTiendas] = useState<Tienda[]>([])
  const [tiendaId, setTiendaId] = useState<number | null>(null)
  const [data, setData] = useState<RentabilidadData | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    api.get<Tienda[]>('/auth/tiendas').then(r => setTiendas(r.data)).catch(() => {})
  }, [])

  useEffect(() => {
    // Guard anti-carrera: si el filtro cambia antes de la respuesta, se descarta.
    let vigente = true
    const { desde, hasta } = rangoPeriodo(periodo)
    setLoading(true)
    api.get<RentabilidadData>('/rentabilidad/', {
      params: { desde, hasta, ...(tiendaId ? { tienda_id: tiendaId } : {}) },
    })
      .then(r => { if (vigente) setData(r.data) })
      .catch(() => { if (vigente) setData(null) })
      .finally(() => { if (vigente) setLoading(false) })
    return () => { vigente = false }
  }, [periodo, tiendaId, refreshKey])

  const r = data?.resumen
  const margenPositivo = (r?.margen_neto ?? 0) >= 0
  // Los dos ejes de la cobertura de la fuga: MESES y SEDES. Cada uno se declara
  // solo cuando falta algo, y los dos sesgan para el mismo lado (subdeclaran).
  const mesesParcial = (r?.fuga_meses ?? 0) > 0 && (r?.fuga_meses ?? 0) < (r?.fuga_meses_rango ?? 0)
  const sedesParcial = (r?.fuga_sedes ?? 0) > 0 && (r?.fuga_sedes ?? 0) < (r?.fuga_sedes_rango ?? 0)

  return (
    <div className="space-y-3">
      {/* Filtros (viven acá: es la única vista donde aplican) */}
      <div className="sticky top-[52px] z-10 -mx-1 px-1 py-1.5 bg-warm-50/90 backdrop-blur-sm flex items-center gap-1.5 overflow-x-auto">
        {(([['mes', 'Este mes'], ['mes_pasado', 'Mes pasado'], ['30d', '30 días'], ['anio', 'Este año']]) as [Periodo, string][]).map(([p, lbl]) => (
          <button key={p} onClick={() => setPeriodo(p)}
            className={`shrink-0 min-h-[40px] px-3 rounded-full text-xs font-bold border transition-colors ${
              periodo === p ? 'bg-forest text-white border-forest' : 'bg-white text-warm-500 border-warm-200'}`}>
            {lbl}
          </button>
        ))}
        <select value={tiendaId ?? ''} onChange={e => setTiendaId(e.target.value ? Number(e.target.value) : null)}
          className="shrink-0 ml-auto border border-warm-200 rounded-full px-3 min-h-[40px] text-xs font-bold bg-white text-warm-600">
          <option value="">Todas las sedes</option>
          {tiendas.map(t => <option key={t.id} value={t.id}>{t.nombre}</option>)}
        </select>
      </div>

      {loading && (
        <div className="space-y-3" aria-label="Cargando">
          <div className="h-24 rounded-2xl bg-warm-100 animate-pulse" />
          <div className="h-40 rounded-2xl bg-warm-100 animate-pulse" />
        </div>
      )}
      {!loading && !data && <p className="text-sm text-warm-400 px-1">No se pudo cargar la información.</p>}

      {!loading && data && r && (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <Kpi label="Ventas" value={fmt(r.ventas)} Icon={Wallet} tint="text-forest"
              sub={`${r.n_tickets} tickets`} />
            <Kpi label="Compras proveedor" value={fmt(r.compras)} Icon={ShoppingCart} tint="text-gold-600"
              sub={`${r.n_facturas} facturas recibidas`} />
            {/* El valor ya son las DOS mitades: egresos de caja sin adoptar +
                obligaciones devengadas (services/rentabilidad.py). El detalle por
                categoría ahora está ACÁ ABAJO, no en otra pantalla. */}
            <Kpi label="Costos operativos" value={fmt(r.gastos)} Icon={Receipt} tint="text-danger-500"
              sub={`${data.gastos_por_categoria?.length ?? 0} categorías`} />
            <div className={`rounded-2xl border p-4 border-l-[3px] ${margenPositivo ? 'bg-success-50 border-success-200 border-l-success-500' : 'bg-danger-50 border-danger-200 border-l-danger-500'}`}>
              <div className="flex items-center gap-2 mb-1.5">
                {margenPositivo ? <TrendingUp size={14} className="text-success-600" /> : <TrendingDown size={14} className="text-danger-500" />}
                {/* MISMO número que el hero del Pulso (resumen.margen_neto). Se
                    llamaba "Margen operativo" acá y "Margen neto" allá: dos nombres
                    para la misma plata es exactamente la confusión que este módulo
                    vino a sacar. Un número, un nombre. */}
                <p className="text-[11px] font-bold uppercase tracking-wide text-warm-400">Margen neto</p>
              </div>
              <p className={`text-xl font-bold font-mono leading-none tabular-nums ${margenPositivo ? 'text-success-600' : 'text-danger-700'}`}>
                {fmt(r.margen_neto)}
              </p>
              {/* Sin muletilla cuando hay cobertura: el número ya resta arriendo y
                  nómina. Cuando NO la hay, se declara — un margen sin costos fijos
                  leído como si los tuviera es la mentira que esta fase corrige. */}
              <p className="text-xs text-warm-400 mt-1.5">
                {r.pct_margen_neto != null ? `${r.pct_margen_neto}% de la venta` : 'sin ventas'}
                {r.tiene_costos_fijos ? '' : ' · sin costos fijos cargados'}
              </p>
            </div>
          </div>

          {/* ── Fuga de inventario medida por el conteo físico ──────────────── */}
          {/* El conteo mensual medía la merma real y ese número no llegaba nunca
              al estado de resultados. Entra acá, contra el margen bruto REAL:
              `margen_neto` sale de `compras`, que es base de RECEPCIÓN, así que la
              mercadería fugada YA está gastada ahí adentro y restársela otra vez
              descontaría dos veces la misma plata. `margen_bruto_real` es base de
              CONSUMO (ventas − costo de lo vendido) y ahí la fuga todavía no está. */}
          {r.tiene_fuga_medida && r.fuga_inventario != null && (
            <div className="bg-white rounded-2xl border border-warm-200 p-4">
              <p className="text-[11px] font-bold uppercase tracking-wide text-warm-500 mb-2">
                Fuga de inventario — lo que el conteo midió y nada explica
              </p>
              <div className="grid grid-cols-3 gap-2 text-center">
                <div>
                  <p className="text-[10px] uppercase font-bold text-warm-400">Margen sobre lo vendido</p>
                  <p className="text-sm font-mono font-bold text-warm-700 mt-0.5 tabular-nums">{fmt(r.margen_bruto_real ?? 0)}</p>
                </div>
                <div>
                  {/* RESIDUO NETO, no "fuga": los sobrantes de un producto netean
                      contra los faltantes de otro, así que un solo número puede
                      esconder las dos puntas. Neto es lo que la resta de al lado
                      necesita —sumar solo los faltantes descontaría dos veces el
                      producto que apareció de más—, pero el rótulo tiene que decir
                      qué es en vez de dejarlo creer que es todo lo que falta. */}
                  <p className="text-[10px] uppercase font-bold text-warm-400">Residuo neto</p>
                  <p className={`text-sm font-mono font-bold mt-0.5 tabular-nums ${r.fuga_inventario < 0 ? 'text-danger-600' : 'text-warm-700'}`}
                    title="Faltantes MENOS sobrantes: un producto que apareció de más compensa al que faltó. El faltante bruto es mayor que este número.">
                    {fmt(r.fuga_inventario)}
                  </p>
                </div>
                <div>
                  <p className="text-[10px] uppercase font-bold text-warm-400">Queda después del residuo</p>
                  <p className={`text-sm font-mono font-bold mt-0.5 tabular-nums ${(r.margen_bruto_real_con_fuga ?? 0) >= 0 ? 'text-success-600' : 'text-danger-700'}`}>
                    {fmt(r.margen_bruto_real_con_fuga ?? 0)}
                    {r.pct_margen_bruto_real_con_fuga != null && (
                      <span className="text-warm-400 font-normal"> ({r.pct_margen_bruto_real_con_fuga}%)</span>
                    )}
                  </p>
                </div>
              </div>
              {/* LOS DOS TÉRMINOS NO MIDEN EL MISMO TRAMO, Y EL TRAMO TIENE DOS EJES.
                  MESES: el margen es de todo el período; la fuga solo de los meses
                  calendario COMPLETOS ya cerrados. En "Este año" eso puede ser 8
                  meses de margen contra 6 de fuga.
                  SEDES: con "Todas las sedes" el margen suma ventas y COGS de todas
                  las que vendieron, y la fuga solo de las que cerraron un conteo —
                  la sede que nunca cierra desaparecía del término de fuga sin
                  ninguna señal.
                  Los dos sesgos van para el mismo lado, el optimista: subdeclaran la
                  fuga. Se dicen los dos, donde está el KPI. */}
              {(mesesParcial || sedesParcial) && (
                <p className="text-[11px] text-gold-700 bg-gold-50 border border-gold-200 rounded-lg px-2.5 py-1.5 mt-2">
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
              <p className="text-[11px] text-warm-400 mt-2">
                Sale de los cierres de mes que caen completos en este período: lo contado contra lo que
                el libro de movimientos dice que debería haber, descontando entradas, ventas, mermas,
                traslados y ajustes. Es un <b>neto</b>: lo que sobró en un producto compensa lo que
                faltó en otro, así que el faltante bruto es mayor que este número. Se descuenta del
                margen sobre lo VENDIDO y no del margen neto:
                ahí la mercadería ya está gastada entera al recibirla, así que restarla de nuevo sería
                contar la misma plata dos veces.
                {/* PRODUCTO-MES, no productos: la cobertura de cada cierre sumada a
                    lo largo del rango. Con 3 cierres de 97 productos el denominador
                    da 291, y ese local nunca tuvo 291 productos: el ratio es el que
                    vale, y con los cierres al lado se puede dividir de vuelta. */}
                {(r.fuga_cobertura_productos ?? 0) > 0 && (
                  <> Cubre {r.fuga_cobertura_contados} de {r.fuga_cobertura_productos} producto-mes
                    {(r.fuga_cierres ?? 0) > 0 && <> en {r.fuga_cierres} cierre{r.fuga_cierres === 1 ? '' : 's'} de mes</>}.</>
                )}
                {(r.fuga_sin_costo ?? 0) > 0 && (
                  <> {r.fuga_sin_costo} producto{r.fuga_sin_costo === 1 ? '' : 's'} con
                    faltante no tiene costo cargado, así que su fuga no suma acá.</>
                )}
                {(r.fuga_estimados ?? 0) > 0 && (
                  <> {r.fuga_estimados} se valorizó con el precio de VENTA porque no hay costo ni
                    factura: ese pedazo del total está <b>sobrestimado</b>.</>
                )}
              </p>
              {/* ASIMETRÍA DE VALORIZACIÓN DENTRO DE LA MISMA RESTA. El costo de lo
                  vendido no cae al precio de venta (un producto sin costo cargado
                  aporta $0); la fuga sí cae, marcándolo como estimado. O sea que el
                  MISMO producto puede pesar $0 de un lado y 3,3× de costo del otro.
                  No se unifica —hacerlo pondría en $0 la fuga de justo los productos
                  que nadie va a investigar, y cambiaría meses ya cerrados— así que
                  se declara acá, que es donde se hace la resta. */}
              <p className="text-[11px] text-warm-400 mt-1.5">
                Los dos términos <b>no se valorizan con la misma regla</b>: el costo de lo vendido deja
                en $0 lo que no tiene costo cargado (cubre el {r.pct_venta_costeada ?? '—'}% de la venta),
                y la fuga en cambio cae al precio de venta cuando no hay costo. El mismo producto puede
                pesar distinto de cada lado de la resta.
              </p>
            </div>
          )}

          {/* COGS teórico: base de consumo (complementa a compras = base de recepción) */}
          {r.cogs_teorico != null && (
            <div className="bg-white rounded-2xl border border-warm-200 p-4">
              <p className="text-[11px] font-bold uppercase tracking-wide text-warm-500 mb-2">
                Costo de lo VENDIDO (teórico) — sin la distorsión del stockeo
              </p>
              <div className="grid grid-cols-3 gap-2 text-center">
                <div>
                  <p className="text-[10px] uppercase font-bold text-warm-400">Consumo teórico</p>
                  <p className="text-sm font-mono font-bold text-warm-700 mt-0.5 tabular-nums">{fmt(r.cogs_teorico)}</p>
                </div>
                <div>
                  <p className="text-[10px] uppercase font-bold text-warm-400">Margen bruto real</p>
                  <p className="text-sm font-mono font-bold text-success-600 mt-0.5 tabular-nums">
                    {fmt(r.margen_bruto_real ?? 0)}
                    {r.pct_margen_bruto_real != null && <span className="text-warm-400 font-normal"> ({r.pct_margen_bruto_real}%)</span>}
                  </p>
                </div>
                <div>
                  <p className="text-[10px] uppercase font-bold text-warm-400">Compras − consumo</p>
                  <p className={`text-sm font-mono font-bold mt-0.5 tabular-nums ${(r.brecha_compras ?? 0) >= 0 ? 'text-gold-700' : 'text-danger-700'}`}>
                    {fmt(r.brecha_compras ?? 0)}
                  </p>
                </div>
              </div>
              <p className="text-[11px] text-warm-400 mt-2">
                Brecha positiva = stockeaste (compraste más de lo consumido). Cubre el {r.pct_venta_costeada ?? '—'}% de la venta (productos con costo).
              </p>
            </div>
          )}

          {/* Por mes: solo aporta con rango multi-mes */}
          {data.por_mes.length > 1 && (
            <div className="bg-white rounded-2xl border border-warm-200 overflow-hidden">
              <p className="px-4 py-3 text-sm font-bold text-warm-700 border-b border-warm-100">Por mes</p>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-[11px] uppercase tracking-wide text-warm-400 border-b border-warm-100">
                      <th className="text-left px-4 py-2 font-bold">Mes</th>
                      <th className="text-right px-3 py-2 font-bold">Ventas</th>
                      <th className="text-right px-3 py-2 font-bold">Compras</th>
                      <th className="text-right px-3 py-2 font-bold">Gastos</th>
                      <th className="text-right px-4 py-2 font-bold">Margen</th>
                      <th className="text-right px-4 py-2 font-bold">%</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.por_mes.map(m => (
                      <tr key={m.mes} className="border-b border-warm-100 last:border-0">
                        <td className="px-4 py-2.5 font-semibold text-warm-700">{nombreMes(m.mes)}</td>
                        <td className="px-3 py-2.5 text-right font-mono text-warm-700 tabular-nums">{fmt(m.ventas)}</td>
                        <td className="px-3 py-2.5 text-right font-mono text-warm-500 tabular-nums">{fmt(m.compras)}</td>
                        <td className="px-3 py-2.5 text-right font-mono text-warm-500 tabular-nums">{fmt(m.gastos)}</td>
                        <td className={`px-4 py-2.5 text-right font-mono font-bold tabular-nums ${m.margen_neto >= 0 ? 'text-success-600' : 'text-danger-500'}`}>
                          {fmt(m.margen_neto)}
                        </td>
                        <td className="px-4 py-2.5 text-right font-mono text-warm-400 tabular-nums">
                          {m.pct_margen_neto != null ? `${m.pct_margen_neto}%` : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Por sede (detalle completo) */}
          {!tiendaId && data.por_sede.length > 1 && (
            <div className="grid sm:grid-cols-2 gap-3">
              {data.por_sede.map(s => (
                <div key={s.tienda_id ?? 'corporativo'} className="bg-white rounded-2xl border border-warm-200 p-4">
                  <p className="text-sm font-bold text-warm-700 mb-2">{s.tienda}</p>
                  <div className="grid grid-cols-3 gap-2 text-center">
                    <div>
                      <p className="text-[10px] uppercase font-bold text-warm-400">Ventas</p>
                      <p className="text-sm font-mono font-bold text-warm-700 mt-0.5 tabular-nums">{fmt(s.ventas)}</p>
                    </div>
                    <div>
                      <p className="text-[10px] uppercase font-bold text-warm-400">Compras+Gastos</p>
                      <p className="text-sm font-mono font-bold text-warm-500 mt-0.5 tabular-nums">{fmt(s.compras + s.gastos)}</p>
                    </div>
                    <div>
                      <p className="text-[10px] uppercase font-bold text-warm-400">Margen</p>
                      <p className={`text-sm font-mono font-bold mt-0.5 tabular-nums ${s.margen_neto >= 0 ? 'text-success-600' : 'text-danger-500'}`}>
                        {fmt(s.margen_neto)}
                      </p>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* EN QUÉ SE FUE. Antes acá había conceptos de texto libre agrupados por
              string crudo; después, un link a Costos. Las dos versiones eran el
              mismo bug: el backend YA agrupaba este gasto por categoría y el P&L
              tiraba el dato. Ahora se muestra donde se pregunta.
              Σ de las categorías == "Costos operativos": es una partición, no otro
              número (backend: services/rentabilidad.py). */}
          {(data.gastos_por_categoria?.length ?? 0) > 0 && (
            <div className="bg-white rounded-2xl border border-warm-200 overflow-hidden">
              <div className="px-4 py-3 border-b border-warm-100">
                <p className="text-sm font-bold text-warm-700">En qué se fueron los {fmt(r.gastos)}</p>
                <p className="text-[11px] text-warm-500">
                  Nómina, arriendo, servicios: la categoría, no el texto que alguien tecleó en caja
                </p>
              </div>
              {data.gastos_por_categoria!.map(g => {
                const pct = r.gastos > 0 ? (g.total / r.gastos) * 100 : 0
                const suelto = g.clave === 'sin_categorizar'
                return (
                  <div key={g.clave} className="px-4 py-2.5 border-b border-warm-100 last:border-0">
                    <div className="flex items-baseline justify-between gap-2 text-sm">
                      <span className="min-w-0 truncate">
                        <span className={`font-semibold ${suelto ? 'text-gold-700' : 'text-warm-700'}`}>{g.nombre}</span>
                        {g.grupo && (
                          <span className="text-[10px] uppercase font-bold text-warm-400 ml-1.5">{g.grupo}</span>
                        )}
                      </span>
                      <span className="font-mono text-warm-700 tabular-nums shrink-0">
                        {fmt(g.total)} <span className="text-warm-400">({Math.round(pct)}%)</span>
                      </span>
                    </div>
                    <div className="h-1.5 rounded-full bg-warm-100 overflow-hidden mt-1">
                      <div className={`h-full rounded-full ${suelto ? 'bg-gold-400' : 'bg-danger-400'}`}
                        style={{ width: `${Math.max(2, pct)}%` }} />
                    </div>
                  </div>
                )
              })}
              {/* La bolsa sin categorizar es la única fila accionable: adoptarla no
                  mueve un peso del total, mueve la plata de "no sé" a "nómina". */}
              {data.gastos_por_categoria!.some(g => g.clave === 'sin_categorizar') && (
                <button onClick={onAbrirSinCategorizar}
                  className="w-full flex items-center gap-2 px-4 py-2.5 bg-gold-50 border-t border-gold-200 text-left">
                  <Inbox size={15} className="text-gold-700 shrink-0" />
                  <span className="min-w-0 flex-1 text-[11px] text-gold-700 leading-relaxed">
                    <b>Categorizá lo que quedó suelto.</b> El total de costos no cambia — el gasto
                    solo deja de ser un texto libre de caja.
                  </span>
                  <ArrowRight size={14} className="text-gold-700 shrink-0" />
                </button>
              )}
            </div>
          )}

          {/* NÓMINA: de dónde salió el costo laboral de este período.
              El número ya está DENTRO de "Costos operativos" y del margen neto —
              acá no se vuelve a sumar nada. Se muestra porque son DOS fuentes
              posibles y leerlas como una sola escondería cuál se usó: los meses
              calculados salen de las horas marcadas, los manuales de una
              obligación que alguien cargó. Un mes nunca está en las dos. */}
          {((r.nomina_calculada ?? 0) > 0 || (r.nomina_meses_manuales?.length ?? 0) > 0) && (
            <div className="bg-white rounded-2xl border border-warm-200 p-4">
              <p className="text-[11px] font-bold uppercase tracking-wide text-warm-500 mb-2">
                Nómina — de dónde sale este costo
              </p>
              {(r.nomina_calculada ?? 0) > 0 && (
                <p className="text-sm text-warm-700">
                  <span className="font-mono font-bold tabular-nums">{fmt(r.nomina_calculada!)}</span>{' '}
                  calculados con {r.nomina_horas} h marcadas de {r.nomina_personas}{' '}
                  {r.nomina_personas === 1 ? 'persona' : 'personas'} y los recargos de ley
                  {(r.nomina_meses_calculados?.length ?? 0) > 0 &&
                    ` (${r.nomina_meses_calculados!.join(', ')})`}.
                </p>
              )}
              {/* Dos frases distintas para dos situaciones distintas. El mes con
                  nómina a mano descarta su cálculo SIEMPRE —esa es la regla—,
                  pero la plata manual entra en la ventana que contiene su fecha
                  de devengo. Mirando "del 1 a hoy" con la nómina devengada el
                  31, el costo laboral de ese mes no está adentro de ningún lado:
                  decir "se usó la cargada a mano" ahí sería mentir sobre un
                  número que no está en pantalla. */}
              {(r.nomina_meses_manuales?.length ?? 0) > 0 &&
                ((r.nomina_manual_en_ventana ?? 0) > 0 ? (
                  <p className="text-xs text-warm-500 mt-1">
                    {r.nomina_meses_manuales!.join(', ')}:{' '}
                    <span className="font-mono tabular-nums">
                      {fmt(r.nomina_manual_en_ventana!)}
                    </span>{' '}
                    de nómina cargada a mano; el cálculo de esos meses se descartó, para no
                    contar el sueldo dos veces.
                  </p>
                ) : (
                  <p className="text-xs text-gold-700 mt-1">
                    {r.nomina_meses_manuales!.join(', ')}: la nómina de esos meses está
                    cargada a mano con fecha fuera de este período, así que{' '}
                    <b>su costo laboral no está en este margen</b>. Consultá el mes completo
                    para verlo.
                  </p>
                ))}
              {(r.nomina_sin_contrato ?? 0) > 0 && (
                <p className="text-xs text-gold-700 mt-1.5">
                  <b>{r.nomina_sin_contrato}</b>{' '}
                  {r.nomina_sin_contrato === 1 ? 'persona trabajó' : 'personas trabajaron'} sin
                  salario cargado en Contratos: esas horas entran al margen valiendo $0 y el
                  costo real es mayor.
                </p>
              )}
              {(r.nomina_calculada ?? 0) > 0 && (
                <p className="text-[11px] text-warm-400 mt-1.5">
                  Es el tiempo trabajado con sus recargos: no incluye prestaciones, seguridad
                  social ni auxilio de transporte. Es un piso, no la liquidación del contador.
                </p>
              )}
            </div>
          )}

          {/* DESCUENTOS: la plata que se regaló en mostrador. El POS la escribe en
              cada ticket y ningún reporte la sumaba, así que un descuento y una
              venta que no ocurrió se veían igual. NO se resta de nada: `ventas` ya
              viene neto — esto dice cuánto se resignó, no cuánto falta. */}
          {(r.descuentos ?? 0) > 0 && (
            <div className="flex items-center gap-3 bg-white rounded-2xl border border-warm-200 px-4 py-3">
              <Scissors size={16} className="text-gold-600 shrink-0" />
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-bold text-warm-700">
                  Se regalaron {fmt(r.descuentos ?? 0)} en descuentos
                </span>
                <span className="block text-xs text-warm-400">
                  {r.n_tickets_con_descuento ?? 0} tickets
                  {r.pct_descuento != null && ` · ${r.pct_descuento}% de lo que se habría facturado`}
                  {' '}— ya está descontado de las ventas de arriba
                </span>
              </span>
            </div>
          )}

          <button onClick={onVerMetodologia}
            className="flex items-center gap-1.5 text-xs text-warm-500 font-semibold min-h-[44px] px-1">
            <HelpCircle size={13} /> ¿Cómo se calcula esto?
          </button>
        </>
      )}
    </div>
  )
}
