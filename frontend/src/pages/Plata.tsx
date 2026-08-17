import { useCallback, useEffect, useMemo, useState } from 'react'
import { Activity, Database, Landmark, Wallet } from 'lucide-react'
import api from '../api/client'
import {
  RentabilidadData, PorProductoData, PulsoData,
  computeOutliers, computeInsumosSinCosto,
} from '../components/rentabilidad/helpers'
import PulsoView from '../components/rentabilidad/PulsoView'
import PnLView from '../components/rentabilidad/PnLView'
import DatosSheet from '../components/rentabilidad/DatosSheet'
import LibroView from '../components/plata/LibroView'
import CompromisosCard from '../components/plata/CompromisosCard'
import Drawer from '../components/plata/Drawer'
import Costos, { Agenda, Flujo } from './Costos'
import { hoyBogota } from '../utils/fechaLocal'

// ─── Plata: el módulo único de la plata del negocio ──────────────────────────
//
// Fusiona /rentabilidad y /costos, que nunca fueron dos temas. El backend ya
// estaba fusionado —services/rentabilidad.py importa CostoCategoria y suma las
// obligaciones devengadas: el "costo operativo" del P&L ES el módulo de Costos
// leído por otra puerta—, así que la separación vivía sólo en la UI. De ahí
// salían las dos quejas del dueño, que son la misma vista de dos lados:
// «rentabilidad es pobre» (el P&L calculaba el corte por categoría y lo tiraba)
// y «no veo nómina ni arriendo» (Costos tenía las categorías y no el resultado).
//
// Tres pantallas, tres preguntas:
//   Hoy       → ¿cómo vamos este mes y qué se me viene encima?
//   La plata  → ¿cuánta hay, qué se movió, qué hay que pagar y con qué quedo?
//   Resultado → ¿cuánto quedó de verdad y en qué se fue lo que no quedó?
//
// «La plata» reemplazó a «Calendario». No fue un cambio de nombre: la grilla de
// mes y el detalle del flujo eran la misma vista dibujada dos veces y ninguna
// estaba completa (una tenía el detalle del vencimiento y el botón de pagar pero
// no el saldo ni las entradas; la otra tenía el saldo y las entradas pero su
// lista de días no tenía ni conceptos ni acciones). Ahora hay UNA sola vista, con
// el libro del banco de eje — plata real, conciliable contra el extracto — y la
// agenda de vencimientos fusionada adentro del día que le toca a cada uno.
//
// Lo que NO es una de esas tres preguntas (Obligaciones, Pagos a proveedores, el
// detalle del flujo, los egresos sin categorizar) sigue existiendo entero, pero
// como CAJÓN: son herramientas de mantenimiento, no pantallas para mirar un
// martes. Volver a subirlas a pestañas es exactamente lo que hacía que el dueño
// no encontrara nada.

type Tab = 'hoy' | 'plata' | 'resultado'
const TABS: { id: Tab; label: string; Icon: typeof Activity }[] = [
  { id: 'hoy', label: 'Hoy', Icon: Activity },
  { id: 'plata', label: 'La plata', Icon: Landmark },
  { id: 'resultado', label: 'Resultado', Icon: Wallet },
]
const IDS = TABS.map(t => t.id)
// Los links viejos (`/plata#calendario`) siguen entrando donde corresponde: el
// dueño tiene esa URL en el navegador de la tablet y romperla lo dejaría en «Hoy»
// sin explicación.
const ALIAS: Record<string, Tab> = { calendario: 'plata' }
const tabFromHash = (): Tab => {
  const h = window.location.hash.replace('#', '')
  if (IDS.includes(h as Tab)) return h as Tab
  return ALIAS[h] ?? 'hoy'
}

// "Hoy"/inicio de mes según el reloj de Colombia (no el del navegador).
function mesActualBogota(): { desde: string; hasta: string } {
  const s = hoyBogota()
  const [y, m] = s.split('-')
  return { desde: `${y}-${m}-01`, hasta: s }
}

// Qué cajón está abierto. 'flujo' es el detalle de la proyección (incluye el
// editor del saldo del banco, que es un dato que sólo el dueño puede dar).
type Cajon = null | 'obligaciones' | 'proveedores' | 'flujo' | 'sinCategorizar'
const CAJONES: Record<Exclude<Cajon, null>, { titulo: string; subtitulo: string }> = {
  obligaciones: {
    titulo: 'Obligaciones',
    subtitulo: 'Cargar, repetir y anular los costos fijos que después caen en el día que les toca',
  },
  proveedores: {
    titulo: 'Pagos a proveedores',
    subtitulo: 'El pago de una factura se registra acá: es lo que mueve su saldo',
  },
  flujo: {
    titulo: 'Flujo proyectado',
    subtitulo: 'La ESTIMACIÓN de las próximas semanas: la venta esperada y el día en que te quedarías sin plata. Lo que ya se movió está en «La plata»',
  },
  sinCategorizar: {
    titulo: 'Egresos sin categorizar',
    subtitulo: 'Adoptarlos no cambia el total de costos: mueve la plata de «texto libre» a una categoría',
  },
}

export default function Plata() {
  const [tab, setTab] = useState<Tab>(tabFromHash)
  const [pulso, setPulso] = useState<PulsoData | null>(null)
  const [prodData, setProdData] = useState<PorProductoData | null>(null)
  const [plMes, setPlMes] = useState<RentabilidadData | null>(null)
  const [agenda, setAgenda] = useState<Agenda | null>(null)
  const [flujo, setFlujo] = useState<Flujo | null>(null)
  const [cargandoPagos, setCargandoPagos] = useState(true)
  const [datosOpen, setDatosOpen] = useState(false)
  const [cajon, setCajon] = useState<Cajon>(null)
  // Sube cada vez que se cierra un cajón. Es la señal para las vistas que traen su
  // propio fetch (hoy, PnLView) de que el mundo cambió abajo.
  const [refresco, setRefresco] = useState(0)

  const fetchProductos = () =>
    api.get<PorProductoData>('/rentabilidad/por-producto')
      .then(r => setProdData(r.data)).catch(() => setProdData(null))

  // Agenda SIN rango: «La plata» navega meses hacia adelante y hacia atrás, y
  // pedirla por rango obligaría a un fetch por cada flechita.
  //
  // El flujo se pide con horizonte fijo de 30 días porque es lo único que se
  // muestra de él acá: «lo que se viene» en 7 y 30 días y el punto de quiebre, los
  // dos en la pestaña Hoy. Antes ese mismo `dias: 30` alimentaba también el saldo
  // que se pintaba sobre el calendario, que navegaba doce meses: pasado el día 30
  // la celda mostraba el vencimiento y dejaba de mostrar saldo sin decir por qué.
  // Ese overlay ya no existe — el saldo de «La plata» sale del libro del banco,
  // que no tiene horizonte porque no proyecta nada.
  const fetchPagos = useCallback(() => {
    setCargandoPagos(true)
    return Promise.all([
      api.get<Agenda>('/costos/agenda').then(r => setAgenda(r.data)).catch(() => setAgenda(null)),
      api.get<Flujo>('/costos/flujo', { params: { dias: 30 } })
        .then(r => setFlujo(r.data)).catch(() => setFlujo(null)),
    ]).finally(() => setCargandoPagos(false))
  }, [])

  useEffect(() => {
    api.get<PulsoData>('/rentabilidad/pulso').then(r => setPulso(r.data)).catch(() => setPulso(null))
    fetchProductos()
    const { desde, hasta } = mesActualBogota()
    api.get<RentabilidadData>('/rentabilidad/', { params: { desde, hasta } })
      .then(r => setPlMes(r.data)).catch(() => setPlMes(null))
    fetchPagos()
  }, [fetchPagos])

  // Tab ↔ hash de URL (permite deep-links y back del navegador).
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

  // Los cajones mutan datos (crear obligación, pagar, adoptar un egreso) con su
  // propio estado interno. Al cerrarlos se repide lo de Plata: si no, la agenda
  // seguiría mostrando el mundo de antes de haber cargado el arriendo.
  //
  // `refresco` es la otra mitad: Resultado (PnLView) no lee de estos estados sino
  // del suyo, y sin avisarle el dueño adoptaba un egreso desde el cajón y volvía a
  // ver la misma fila «Sin categorizar» que acababa de arreglar.
  const cerrarCajon = useCallback(() => {
    setCajon(null)
    setRefresco(n => n + 1)
    fetchPagos()
    const { desde, hasta } = mesActualBogota()
    api.get<RentabilidadData>('/rentabilidad/', { params: { desde, hasta } })
      .then(r => setPlMes(r.data)).catch(() => {})
  }, [fetchPagos])

  const pendientesDatos = useMemo(() => {
    if (!prodData) return 0
    // Sin costos fijos devengados en el mes, el margen neto está inflado: es un
    // pendiente de datos igual de real que un insumo sin costear, y esconderlo
    // dejaría el badge en "Datos sanos" con el arriendo entero faltando.
    const faltanFijos = plMes && !plMes.resumen.tiene_costos_fijos ? 1 : 0
    return computeOutliers(prodData.productos).length
      + computeInsumosSinCosto(prodData.productos).length
      + (prodData.facturas_pendientes_de_costos || 0)
      + faltanFijos
  }, [prodData, plMes])

  return (
    <div className="space-y-3">
      {/* Header + badge de salud de datos */}
      <div className="flex items-center gap-2">
        <Wallet size={20} className="text-forest" />
        <h1 className="text-lg font-bold text-warm-700">Plata</h1>
        <button onClick={() => setDatosOpen(true)}
          className={`ml-auto inline-flex items-center gap-1.5 min-h-[40px] px-3 rounded-full border text-xs font-bold transition-colors ${
            pendientesDatos > 0
              ? 'bg-gold-50 text-gold-700 border-gold-200'
              : 'bg-success-50 text-success-600 border-success-200'}`}>
          <Database size={13} />
          {pendientesDatos > 0 ? `Datos: ${pendientesDatos} pendientes` : 'Datos sanos'}
        </button>
      </div>

      {/* Tabs sticky */}
      <div className="sticky top-0 z-20 -mx-1 px-1 py-1.5 bg-warm-50/90 backdrop-blur-sm">
        <div className="grid grid-cols-3 gap-1 bg-warm-100 rounded-xl p-1">
          {TABS.map(({ id, label, Icon }) => (
            <button key={id} onClick={() => goTab(id)}
              className={`flex items-center justify-center gap-1.5 min-h-[42px] rounded-lg text-xs font-bold transition-colors ${
                tab === id ? 'bg-white text-forest shadow-sm' : 'text-warm-500'}`}>
              <Icon size={14} /> {label}
            </button>
          ))}
        </div>
      </div>

      {tab === 'hoy' && (
        <PulsoView pulso={pulso} plMes={plMes} prodData={prodData}
          onIrALaPlata={irALaPlata}
          slotCompromisos={
            <CompromisosCard agenda={agenda} flujo={flujo} onVerLaPlata={irALaPlata} />
          }
        />
      )}

      {tab === 'plata' && (
        <LibroView
          agenda={agenda} cargandoAgenda={cargandoPagos} onRefrescar={fetchPagos}
          refreshKey={refresco}
          onAbrirObligaciones={() => setCajon('obligaciones')}
          onAbrirProveedores={() => setCajon('proveedores')}
          onAbrirFlujo={() => setCajon('flujo')}
        />
      )}

      {tab === 'resultado' && (
        <PnLView onVerMetodologia={() => setDatosOpen(true)}
          onAbrirSinCategorizar={() => setCajon('sinCategorizar')}
          refreshKey={refresco} />
      )}

      <DatosSheet open={datosOpen} prodData={prodData} plMes={plMes}
        onClose={() => setDatosOpen(false)} onRefresh={fetchProductos}
        onIrALaPlata={irALaPlata} />

      {/* Los cajones: las herramientas de Costos, enteras y sin reescribir. */}
      <Drawer open={cajon !== null} onClose={cerrarCajon}
        titulo={cajon ? CAJONES[cajon].titulo : ''}
        subtitulo={cajon ? CAJONES[cajon].subtitulo : undefined}>
        {/* `key` fuerza un montaje limpio por cajón: sin esto, abrir Obligaciones
            después de Proveedores reusaría el estado (filtros, modales) del anterior. */}
        {cajon && <Costos key={cajon} vistas={[cajon]} embebido />}
      </Drawer>
    </div>
  )
}
