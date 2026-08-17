import { useCallback, useEffect, useMemo, useState } from 'react'
import { Landmark, Wallet } from 'lucide-react'
import api from '../api/client'
import {
  RentabilidadData, PorProductoData, PulsoData,
  computeOutliers, computeInsumosSinCosto,
} from '../components/rentabilidad/helpers'
import ResultadoView from '../components/rentabilidad/ResultadoView'
import LaPlataView from '../components/plata/LaPlataView'
import { Agenda, Categoria, Flujo, Tienda } from '../components/plata/tipos'
import { CuentaBanco } from '../components/plata/banco'
import { hoyBogota } from '../utils/fechaLocal'

// ─── Plata: el módulo único de la plata del negocio ──────────────────────────
//
// ═════════════════════════════════════════════════════════════════════════════
// DOS PESTAÑAS, DOS PREGUNTAS
// ═════════════════════════════════════════════════════════════════════════════
//   La plata  → ¿ME ALCANZA?  cuánta hay, qué entró, qué hay que pagar y cuándo
//                             se acaba. Abre en HOY, porque hoy es una fila del
//                             libro.
//   Resultado → ¿GANO?        el margen del mes, en qué se fue lo que no quedó,
//                             qué sede y qué producto dejan plata.
//
// ── POR QUÉ MURIÓ «HOY» ────────────────────────────────────────────────────
// Se verificó leyendo el código: la vista de «Hoy» no traía UN SOLO dato propio.
// Consumía `pulso` (la venta), `plMes` (el margen del mes, que es Resultado),
// `prodData` (los productos, que es Resultado) y la tarjeta de compromisos (el
// punto de quiebre, que es La plata). No era una pregunta: era un resumen de las
// otras dos, y por eso el dueño tenía tres pestañas para dos decisiones.
//
// Cada pieza que vivía ahí se mudó a la pestaña que contesta SU pregunta: la
// venta del día y el punto de quiebre a La plata; el margen con su semáforo, el
// duelo de sedes y los insumos que subieron a Resultado.
//
// ── POR QUÉ MURIERON LOS CAJONES ───────────────────────────────────────────
// Pedido textual del dueño: «no quiero desplegar pestañas para hacer un
// movimiento o agregar una obligación, tampoco quiero que los pagos a
// proveedores queden escondidos». Los cuatro cajones y los ocho modales dejaron
// de existir COMO MECANISMO; su contenido está entero, repartido en banners de
// las dos páginas. La carga de un movimiento y la de una obligación —lo que se
// hace todos los días— quedaron como filas siempre visibles.

type Tab = 'plata' | 'resultado'
const TABS: { id: Tab; label: string; sub: string; Icon: typeof Wallet }[] = [
  { id: 'plata', label: 'La plata', sub: '¿me alcanza?', Icon: Landmark },
  { id: 'resultado', label: 'Resultado', sub: '¿gano?', Icon: Wallet },
]
const IDS = TABS.map(t => t.id)

/**
 * Los links viejos siguen entrando donde corresponde.
 *
 * `hoy` TIENE que estar acá: esa pestaña ya no existe, y el dueño tiene la URL
 * `/plata#hoy` guardada en el navegador de la tablet. Sin el alias caería en el
 * default sin ninguna explicación. `calendario` es el nombre todavía más viejo
 * de «La plata», y /costos y /pagos-proveedores redirigen a `/plata#plata`
 * (App.tsx).
 */
const ALIAS: Record<string, Tab> = { calendario: 'plata', hoy: 'plata' }
const tabFromHash = (): Tab => {
  const h = window.location.hash.replace('#', '')
  if (IDS.includes(h as Tab)) return h as Tab
  // El default es «La plata»: es la pantalla de todos los días.
  return ALIAS[h] ?? 'plata'
}

/** «Hoy» e inicio de mes según el reloj de COLOMBIA, nunca el del navegador. */
function mesActualBogota(): { desde: string; hasta: string } {
  const s = hoyBogota()
  const [y, m] = s.split('-')
  return { desde: `${y}-${m}-01`, hasta: s }
}

export default function Plata() {
  const [tab, setTab] = useState<Tab>(tabFromHash)

  // Datos compartidos por las dos pestañas. Viven acá porque una mutación en un
  // banner cambia lo que muestran otros: pagar una obligación mueve la agenda,
  // el punto de quiebre Y el margen del mes.
  const [pulso, setPulso] = useState<PulsoData | null>(null)
  const [prodData, setProdData] = useState<PorProductoData | null>(null)
  const [plMes, setPlMes] = useState<RentabilidadData | null>(null)
  const [ventasHoy, setVentasHoy] = useState<RentabilidadData | null>(null)
  const [agenda, setAgenda] = useState<Agenda | null>(null)
  const [flujo, setFlujo] = useState<Flujo | null>(null)
  const [categorias, setCategorias] = useState<Categoria[]>([])
  const [tiendas, setTiendas] = useState<Tienda[]>([])
  const [cuentas, setCuentas] = useState<CuentaBanco[]>([])
  const [cargandoPagos, setCargandoPagos] = useState(true)
  const [cargandoVentas, setCargandoVentas] = useState(true)
  /** Sube con cada mutación: es la señal para las vistas con fetch propio. */
  const [refresco, setRefresco] = useState(0)

  const fetchProductos = useCallback(
    () => api.get<PorProductoData>('/rentabilidad/por-producto')
      .then(r => setProdData(r.data)).catch(() => setProdData(null)), [])

  /**
   * LA VENTA DEL DÍA, pedida aparte y con el rango de HOY.
   *
   * No se deriva de `/rentabilidad/pulso`: ese endpoint es del MES a la fecha
   * (get_pulso arranca el día 1), y rotular sus KPIs como «hoy» sería decidir
   * con un dato que está CERCA del correcto — la familia de error que costó
   * nueve rondas. Acá el backend devuelve `ventas` y `n_tickets` del día
   * Colombia, resueltos, y son los que se muestran.
   */
  const fetchVentasHoy = useCallback(() => {
    setCargandoVentas(true)
    const hoy = hoyBogota()
    return api.get<RentabilidadData>('/rentabilidad/', { params: { desde: hoy, hasta: hoy } })
      .then(r => setVentasHoy(r.data)).catch(() => setVentasHoy(null))
      .finally(() => setCargandoVentas(false))
  }, [])

  /**
   * La agenda va SIN rango: «La plata» navega meses hacia adelante y hacia atrás
   * y pedirla por rango obligaría a un fetch por cada flechita. El flujo va con
   * horizonte fijo de 30 días, que es lo único que se muestra de él.
   *
   * Ninguno de los dos lleva `tienda_id`: filtrar el flujo por sede saca el saldo
   * del banco de la cuenta (la cuenta es de la empresa) y deja afuera el arriendo
   * y la nómina, que son corporativos. El resultado sería una proyección que no
   * contesta «¿me alcanza?» sino una versión mutilada de la pregunta.
   */
  const fetchPagos = useCallback(() => {
    setCargandoPagos(true)
    return Promise.all([
      api.get<Agenda>('/costos/agenda').then(r => setAgenda(r.data)).catch(() => setAgenda(null)),
      api.get<Flujo>('/costos/flujo', { params: { dias: 30 } })
        .then(r => setFlujo(r.data)).catch(() => setFlujo(null)),
    ]).finally(() => setCargandoPagos(false))
  }, [])

  const fetchPlMes = useCallback(() => {
    const { desde, hasta } = mesActualBogota()
    return api.get<RentabilidadData>('/rentabilidad/', { params: { desde, hasta } })
      .then(r => setPlMes(r.data)).catch(() => setPlMes(null))
  }, [])

  useEffect(() => {
    api.get<PulsoData>('/rentabilidad/pulso').then(r => setPulso(r.data)).catch(() => setPulso(null))
    api.get<Categoria[]>('/costos/categorias').then(r => setCategorias(r.data)).catch(() => setCategorias([]))
    api.get<Tienda[]>('/auth/tiendas').then(r => setTiendas(r.data)).catch(() => setTiendas([]))
    api.get<CuentaBanco[]>('/banco/cuentas').then(r => setCuentas(r.data)).catch(() => setCuentas([]))
    fetchProductos()
    fetchPlMes()
    fetchVentasHoy()
    fetchPagos()
  }, [fetchPagos, fetchPlMes, fetchProductos, fetchVentasHoy])

  /**
   * Se tocó plata en algún banner. Sin esto quedaban dos números para la misma
   * pregunta: el dueño adoptaba un egreso o pagaba el arriendo y la proyección
   * seguía mostrando el mundo de antes, con el optimista adelante.
   */
  const refrescarTodo = useCallback(() => {
    setRefresco(n => n + 1)
    fetchPagos()
    fetchPlMes()
    fetchProductos()
  }, [fetchPagos, fetchPlMes, fetchProductos])

  // Tab ↔ hash de URL (deep-links y botón atrás del navegador).
  useEffect(() => {
    const onHash = () => setTab(tabFromHash())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])
  const goTab = useCallback((t: Tab) => {
    window.location.hash = t
    setTab(t)
    window.scrollTo({ top: 0 })
  }, [])
  const irALaPlata = useCallback(() => goTab('plata'), [goTab])

  /**
   * Lo que le falta a los datos para que el margen sea real.
   *
   * Se calcula acá una sola vez y baja al banner de salud: sumar outliers,
   * insumos sin costo, facturas sin leer y —por MONTO, no por contador— la falta
   * de costos fijos del mes. Sin el último, «Datos sanos» podía afirmarse con el
   * arriendo entero faltando.
   */
  const pendientesDatos = useMemo(() => {
    // `null`, no 0. Sin `prodData` no se MIDIÓ nada, y devolver cero convertía
    // la ausencia de medición en un veredicto positivo: el banner afirmaba «el
    // costeo y los costos fijos están cubiertos» dos renglones arriba de un
    // «0/0 · 0% de los productos tienen el costo completo».
    if (!prodData) return null
    const faltanFijos = plMes && !plMes.resumen.tiene_costos_fijos ? 1 : 0
    return computeOutliers(prodData.productos).length
      + computeInsumosSinCosto(prodData.productos).length
      + (prodData.facturas_pendientes_de_costos || 0)
      + faltanFijos
  }, [prodData, plMes])

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <Wallet size={20} className="text-forest" />
        <h1 className="text-lg font-bold text-warm-700">Plata</h1>
      </div>

      {/* Dos pestañas, con la pregunta que contesta cada una debajo del nombre:
          es lo que evita tener que abrirlas para acordarse cuál era cuál. */}
      <div className="sticky top-0 z-20 -mx-1 px-1 py-1.5 bg-warm-50/90 backdrop-blur-sm">
        <div className="grid grid-cols-2 gap-1 bg-warm-100 rounded-xl p-1">
          {TABS.map(({ id, label, sub, Icon }) => (
            <button key={id} onClick={() => goTab(id)}
              className={`flex items-center justify-center gap-1.5 min-h-[46px] rounded-lg transition-colors ${
                tab === id ? 'bg-white text-forest shadow-sm' : 'text-warm-500'}`}>
              <Icon size={15} className="shrink-0" />
              <span className="text-left leading-tight">
                <span className="block text-xs font-bold">{label}</span>
                <span className={`block text-[10px] ${tab === id ? 'text-forest/70' : 'text-warm-400'}`}>
                  {sub}
                </span>
              </span>
            </button>
          ))}
        </div>
      </div>

      {tab === 'plata' && (
        <LaPlataView
          agenda={agenda} flujo={flujo} pulso={pulso} ventasHoy={ventasHoy}
          categorias={categorias} tiendas={tiendas} cuentas={cuentas}
          cargandoPagos={cargandoPagos} cargandoVentas={cargandoVentas}
          onCambio={refrescarTodo} />
      )}

      {tab === 'resultado' && (
        <ResultadoView
          pulso={pulso} prodData={prodData} plMes={plMes}
          categorias={categorias} tiendas={tiendas}
          pendientesDatos={pendientesDatos}
          refreshKey={refresco}
          onRefrescarProductos={fetchProductos}
          onIrALaPlata={irALaPlata}
          onCambio={refrescarTodo} />
      )}
    </div>
  )
}
