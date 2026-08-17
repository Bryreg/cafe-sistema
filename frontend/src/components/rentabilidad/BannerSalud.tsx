import { useRef, useState } from 'react'
import { Database, Loader2, ScanLine, Trash2 } from 'lucide-react'
import api from '../../api/client'
import { detalleDeError } from '../plata/banco'
import { Banner, ComoSeCalcula, ErrorCampo } from '../plata/campos'
import {
  PorProductoData, RentabilidadData,
  computeInsumosSinCosto, computeOutliers, fmt, fmtTasa,
} from './helpers'

/** Fila de `GET /rentabilidad/aliases`: lo que el sistema aprendió de las facturas. */
interface AliasRow {
  id: number
  alias_original: string
  producto_nombre: string
  origen: string
  veces_visto: number
  actualizado_en: string | null
  barista_nombre: string | null
}

/**
 * ═════════════════════════════════════════════════════════════════════════════
 * ¿LE PUEDO CREER A ESTOS NÚMEROS? — el banner de salud, al pie de Resultado
 * ═════════════════════════════════════════════════════════════════════════════
 * Era una HOJA que se abría desde un badge en el header y desde un «¿cómo se
 * calcula esto?» al pie. Dos puertas a una pantalla flotante para contestar una
 * pregunta que se hace justo mirando el margen. Ahora es el último banner de la
 * página: se llega leyendo, no abriendo.
 *
 * Todo lo que califica al margen vive acá: cuántos productos tienen costo, si el
 * mes tiene arriendo y nómina cargados, qué facturas quedaron sin leer, qué
 * márgenes están fuera de rango y qué insumos no tienen costo.
 *
 * ── LAS DOS DECISIONES QUE SE TOMAN POR MONTO Y NO POR CONTADOR ────────────
 *  · «Faltan costos fijos» se decide por `costos_fijos_devengados <= 0`, NO por
 *    `n_costos_fijos`: una obligación cargada en $0 apagaría el aviso para
 *    siempre si dependiera de contar filas.
 *  · La nota del impoconsumo se muestra solo si de verdad está separando plata
 *    (`impoconsumo > 0`): con la tarifa en 0 la bandera de «sin confirmar» viene
 *    prendida por defecto y el cartel hablaría de una tarifa que no se aplica.
 */
export default function BannerSalud({ prodData, plMes, pendientes, onRefrescarProductos, onIrALaPlata }: {
  prodData: PorProductoData | null
  /** El P&L del MES EN CURSO. No sigue al filtro de período: la cobertura de
   *  costos fijos que califica al semáforo es la del mes, no la del rango. */
  plMes: RentabilidadData | null
  /** El mismo contador que se muestra arriba, calculado una sola vez. */
  /** `null` = no se pudo medir (falta `prodData`). NO es lo mismo que 0: cero
   *  afirma que está todo cubierto, y eso hay que haberlo verificado. */
  pendientes: number | null
  onRefrescarProductos: () => void
  onIrALaPlata: () => void
}) {
  const [leyendo, setLeyendo] = useState(false)
  const [msg, setMsg] = useState('')
  const pararRef = useRef(false)

  const [verAliases, setVerAliases] = useState(false)
  const [aliases, setAliases] = useState<AliasRow[] | null>(null)
  const [aliasMsg, setAliasMsg] = useState('')

  const all = prodData?.productos ?? []
  // Por MONTO, no por presencia del campo: sin un peso de impuesto separado, el
  // precio neto es el de la carta y nombrar la base sería ruido.
  const hayImpoProd = all.some(p => p.impoconsumo_unitario > 0)
  const hayImpoPL = (plMes?.resumen.impoconsumo ?? 0) > 0
  const outliers = computeOutliers(all)
  const insumos = computeInsumosSinCosto(all)
  const completos = all.filter(p => p.costo_completo).length
  const cobertura = all.length ? Math.round((completos / all.length) * 100) : 0
  const facturasSinLeer = prodData?.facturas_pendientes_de_costos ?? 0
  const nFijos = plMes?.resumen.n_costos_fijos ?? 0
  const montoFijos = plMes?.resumen.costos_fijos_devengados ?? 0
  const sinFijos = montoFijos <= 0

  const toggleAliases = async () => {
    const abrir = !verAliases
    setVerAliases(abrir)
    // Carga diferida: la lista de aliases no le interesa a nadie hasta que la piden.
    if (abrir && aliases === null) {
      try {
        const r = await api.get<AliasRow[]>('/rentabilidad/aliases')
        setAliases(r.data); setAliasMsg('')
      } catch (e) {
        setAliasMsg(detalleDeError(e, 'No se pudieron cargar los aliases.'))
      }
    }
  }

  const borrarAlias = async (id: number) => {
    try {
      await api.delete(`/rentabilidad/aliases/${id}`)
      setAliases(a => (a ?? []).filter(x => x.id !== id))
    } catch (e) {
      setAliasMsg(detalleDeError(e, 'No se pudo eliminar el alias.'))
    }
  }

  /** Lee las facturas guardadas de a dos, con corte: sin el botón «Parar» el
   *  dueño queda mirando un spinner sin salida. */
  const leerFacturas = async () => {
    if (!prodData) return
    setLeyendo(true)
    pararRef.current = false
    let quedan = prodData.facturas_pendientes_de_costos
    try {
      while (quedan > 0 && !pararRef.current) {
        setMsg(`Leyendo facturas guardadas… quedan ${quedan}`)
        const r = await api.post('/rentabilidad/backfill-costos?limite=2', null, { timeout: 300000 })
        const d = r.data
        if (d.detenido_por) { setMsg(d.detenido_por); break }
        quedan = d.pendientes
        if (d.procesadas === 0) {
          if (quedan > 0) setMsg(`Quedan ${quedan} que no se pudieron leer solas — completá esos precios a mano en el banner de proveedores.`)
          break
        }
      }
      if (quedan === 0) setMsg('Listo: todas las facturas con foto quedaron leídas.')
    } catch (e) {
      setMsg(detalleDeError(e, 'Error leyendo facturas — intentá más tarde.'))
    } finally {
      setLeyendo(false)
      onRefrescarProductos()
    }
  }

  return (
    <Banner
      id="salud-de-datos"
      titulo="¿Le puedo creer a estos números?"
      /* TRES estados, no dos. «No se pudo medir» no es «está todo bien»: es la
         misma trampa que el ámbar de la proyección («que no haya alarma no
         significa que estés bien»), acá al revés. */
      sub={pendientes === null
        ? 'No se pudo medir: no cargaron los datos de producto'
        : pendientes > 0
          ? `${pendientes} ${pendientes === 1 ? 'cosa' : 'cosas'} por arreglar para que el margen sea real`
          : 'Sin pendientes: el costeo y los costos fijos están cubiertos'}
      accion={
        /* La chapa verde «Datos sanos» es un VEREDICTO y solo se emite con la
           medición en la mano. Sin ella va gris: no sabemos. */
        <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-[11px] font-bold ${
          pendientes === null ? 'bg-warm-100 text-warm-500 border-warm-200'
            : pendientes > 0 ? 'bg-gold-50 text-gold-700 border-gold-200'
              : 'bg-success-50 text-success-600 border-success-200'}`}>
          <Database size={12} /> {pendientes === null ? 'Sin medir'
            : pendientes > 0 ? `${pendientes} pendientes` : 'Datos sanos'}
        </span>
      }
    >
      {/* ── Cobertura de costeo ────────────────────────────────────────────── */}
      <div className="px-4 py-3 border-b border-warm-100">
        <div className="flex items-baseline justify-between gap-2">
          <p className="text-[10px] font-bold uppercase tracking-wide text-warm-500">Cobertura de costeo</p>
          <p className="text-base font-mono font-extrabold tabular-nums text-warm-700">
            {completos}/{all.length}
          </p>
        </div>
        <div className="h-2 rounded-full bg-warm-100 overflow-hidden mt-1.5">
          <div className={`h-full rounded-full ${cobertura >= 90 ? 'bg-success-500' : 'bg-gold-500'}`}
            style={{ width: `${cobertura}%` }} />
        </div>
        <p className="text-[11px] text-warm-500 mt-1">
          {cobertura}% de los productos tienen el costo completo. Un producto sin costo tiene
          margen falso, y ese margen falso está sumado en los números de arriba.
        </p>
      </div>

      {/* ── Costos fijos del mes ───────────────────────────────────────────── */}
      <div className={`px-4 py-3 border-b ${sinFijos ? 'border-gold-200 bg-gold-50' : 'border-warm-100'}`}>
        <div className="flex items-baseline justify-between gap-2">
          <p className="text-[10px] font-bold uppercase tracking-wide text-warm-500">
            Costos fijos del mes en curso
          </p>
          <p className="text-base font-mono font-extrabold tabular-nums text-warm-700">{fmt(montoFijos)}</p>
        </div>
        {sinFijos ? (
          <p className="text-[11px] text-warm-600 mt-1 leading-relaxed">
            No hay arriendo, nómina ni servicios devengados este mes. Mientras falten, el margen
            neto se ve <b>más alto de lo que es</b> y el semáforo no puede decir si el negocio va
            bien.{' '}
            <button onClick={onIrALaPlata} className="font-bold text-gold-700 underline decoration-dotted">
              Cargalos en La plata
            </button>.
          </p>
        ) : (
          <p className="text-[11px] text-warm-500 mt-1">
            {nFijos} {nFijos === 1 ? 'obligación fija devengada' : 'obligaciones fijas devengadas'} —
            el margen neto ya las descuenta.
          </p>
        )}
      </div>

      {/* ── Backfill OCR: la acción que sube la cobertura ──────────────────── */}
      {facturasSinLeer > 0 && (
        <div className="px-4 py-3 border-b border-warm-100 bg-clay-50">
          <p className="text-sm font-bold text-warm-700">{facturasSinLeer} facturas guardadas sin leer</p>
          <p className="text-[11px] text-warm-500 mt-0.5">
            Leerlas completa los costos automáticamente desde las fotos: es lo que arregla el
            margen sin teclear nada.
          </p>
          <div className="flex items-center gap-2 mt-2">
            {leyendo ? (<>
              <span className="flex items-center gap-1.5 text-[11px] font-semibold text-gold-700">
                <Loader2 size={13} className="animate-spin" /> {msg}
              </span>
              <button onClick={() => { pararRef.current = true }}
                className="ml-auto min-h-[40px] px-3 rounded-lg text-[11px] font-bold border border-warm-200 text-warm-500 bg-white">
                Parar
              </button>
            </>) : (
              <button onClick={leerFacturas}
                className="flex items-center gap-1.5 min-h-[44px] px-4 rounded-lg text-xs font-bold text-white bg-clay-500 active:scale-[0.98] transition-transform">
                <ScanLine size={14} /> Leer los costos de {facturasSinLeer} facturas
              </button>
            )}
          </div>
          {!leyendo && msg && <p className="text-[11px] text-warm-500 mt-2">{msg}</p>}
        </div>
      )}

      {/* ── Márgenes sospechosos ───────────────────────────────────────────── */}
      <div className="px-4 py-3 border-b border-warm-100">
        <p className="text-[10px] font-bold uppercase tracking-wide text-warm-500 mb-1">
          Márgenes sospechosos
        </p>
        {outliers.length === 0 ? (
          <p className="text-xs text-success-600 font-semibold">
            Ninguno — todos coherentes con su categoría
          </p>
        ) : outliers.map(o => (
          <div key={o.p.producto_id} className="flex items-center gap-2 py-1.5 border-b border-warm-100 last:border-0">
            <span className="flex-1 min-w-0 text-xs text-warm-700 truncate">{o.p.nombre}</span>
            <span className={`text-[11px] font-mono font-bold tabular-nums ${
              o.alto ? 'text-danger-600' : 'text-gold-700'}`}>{o.p.pct_margen}%</span>
            <span className="text-[10px] text-warm-400 w-24 text-right capitalize truncate">
              {o.p.categoria} ~{o.mean}%
            </span>
          </div>
        ))}
        <p className="text-[11px] text-warm-400 mt-1.5 leading-relaxed">
          {hayImpoProd && <>Los % son margen sobre el precio neto (la carta sin impoconsumo). </>}
          Un margen muy desviado del promedio de su categoría casi siempre es un costo mal cargado
          (así se cazó el helado de las malteadas).
        </p>
      </div>

      {/* ── Insumos sin costear ────────────────────────────────────────────── */}
      <div className="px-4 py-3 border-b border-warm-100">
        <p className="text-[10px] font-bold uppercase tracking-wide text-warm-500 mb-1">
          Insumos sin costear
        </p>
        {insumos.length === 0 ? (
          <p className="text-xs text-success-600 font-semibold">Todo costeado</p>
        ) : (<>
          {insumos.map(i => (
            <div key={i.nombre} className="flex items-center gap-2 py-1.5 border-b border-warm-100 last:border-0">
              <span className="flex-1 min-w-0 text-xs text-warm-700 truncate">{i.nombre}</span>
              <span className="text-[10px] text-warm-400 shrink-0">
                {i.n} {i.n === 1 ? 'producto' : 'productos'}
              </span>
              <span className="text-[11px] font-mono tabular-nums text-gold-700 w-20 text-right shrink-0">
                {fmt(i.venta)}
              </span>
            </div>
          ))}
          <p className="text-[11px] text-warm-400 mt-1.5 leading-relaxed">
            Ordenados por la venta que arrastran: el de arriba es el que más margen está
            ensuciando. El costo se carga desde el catálogo del insumo o leyendo la factura donde
            aparece.
          </p>
        </>)}
      </div>

      {/* ── Lo que el sistema aprendió de las facturas ─────────────────────── */}
      {typeof prodData?.aliases_conocidos === 'number' && (() => {
        const n = aliases !== null ? aliases.length : prodData.aliases_conocidos
        return (
          <div className="px-4 py-3 border-b border-warm-100">
            <p className="text-[11px] text-warm-500 leading-relaxed">
              El sistema conoce <b>{n}</b> {n === 1 ? 'alias' : 'aliases'} de proveedores — aprende
              con cada factura escaneada, corregida o leída. Un alias mal aprendido se refuerza
              solo con cada escaneo, así que se puede borrar.{' '}
              {n > 0 && (
                <button onClick={toggleAliases}
                  className="font-bold text-gold-700 underline decoration-dotted">
                  {verAliases ? 'ocultar' : 'ver y gestionar'}
                </button>
              )}
            </p>
            {verAliases && (
              <div className="mt-2 rounded-lg border border-warm-200 divide-y divide-warm-100 max-h-56 overflow-y-auto">
                {aliases === null ? (
                  <p className="text-[11px] text-warm-400 px-2.5 py-2">Cargando…</p>
                ) : aliases.length === 0 ? (
                  <p className="text-[11px] text-warm-400 px-2.5 py-2">No queda ningún alias.</p>
                ) : aliases.map(a => (
                  <div key={a.id} className="flex items-center gap-2 px-2.5 py-2">
                    <div className="flex-1 min-w-0">
                      <p className="text-[11px] text-warm-700 truncate">
                        <span className="font-mono">{a.alias_original}</span>
                        <span className="text-warm-400"> → </span>
                        <span className="font-semibold">{a.producto_nombre}</span>
                      </p>
                      <p className="text-[10px] text-warm-400">
                        {a.origen} · visto {a.veces_visto} {a.veces_visto === 1 ? 'vez' : 'veces'}
                        {a.barista_nombre ? ` · enseñó ${a.barista_nombre}` : ''}
                        {a.actualizado_en ? ` · ${String(a.actualizado_en).slice(0, 10)}` : ''}
                      </p>
                    </div>
                    <button onClick={() => borrarAlias(a.id)} aria-label={`Eliminar el alias ${a.alias_original}`}
                      className="p-2 rounded-md text-warm-300 hover:text-danger-500 hover:bg-danger-50 shrink-0">
                      <Trash2 size={13} />
                    </button>
                  </div>
                ))}
              </div>
            )}
            {aliasMsg && <div className="mt-1"><ErrorCampo msg={aliasMsg} /></div>}
          </div>
        )
      })()}

      {/* ── Metodología ────────────────────────────────────────────────────── */}
      <ComoSeCalcula>
        {plMes?.nota && <p>{plMes.nota}</p>}
        {prodData?.nota && <p>{prodData.nota}</p>}
        {/* La corrección que cambió TODOS los márgenes del sistema. Va acá porque
            es la respuesta a «¿por qué mi margen bajó?», y se muestra con los
            montos del mes en curso, no como una afirmación general. */}
        {hayImpoPL && plMes && (
          <p>
            El precio de la carta lleva el impoconsumo adentro
            ({fmtTasa(plMes.resumen.tasa_impoconsumo)} sobre la venta neta). De los{' '}
            {fmt(plMes.resumen.ventas)} cobrados este mes, {fmt(plMes.resumen.impoconsumo)} se le
            giran a la DIAN y nunca fueron del negocio: el margen neto y su % se miden contra la
            venta neta ({fmt(plMes.resumen.venta_neta)}) y no contra lo cobrado, y el margen de
            cada producto contra su precio neto. La excepción es el margen sobre lo vendido (COGS
            teórico y fuga de inventario): ese sí se compara contra lo cobrado, así que se ve más
            alto.
            {plMes.resumen.impoconsumo_confirmar_contador
              && ' La tarifa está cargada pero todavía sin confirmar con tu contador.'}
          </p>
        )}
        <p>
          El margen neto ya descuenta los costos fijos que estén cargados (arriendo, nómina,
          servicios, impuestos) — pero solo esos: lo que nadie cargó no se resta, y por eso acá
          arriba se declara la cobertura del mes. El costo de lo vendido (COGS teórico) usa las
          recetas y los costos confirmados, y complementa a «Compras», que va por recepción: un mes
          que stockea fuerte se ve peor de lo que fue.
        </p>
      </ComoSeCalcula>
    </Banner>
  )
}
