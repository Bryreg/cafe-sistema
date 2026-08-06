import { useEffect, useMemo, useState } from 'react'
import { TrendingUp, Activity, Wallet, Database } from 'lucide-react'
import api from '../api/client'
import {
  RentabilidadData, PorProductoData, PulsoData,
  computeOutliers, computeInsumosSinCosto,
} from '../components/rentabilidad/helpers'
import PulsoView from '../components/rentabilidad/PulsoView'
import PnLView from '../components/rentabilidad/PnLView'
import DatosSheet from '../components/rentabilidad/DatosSheet'

// ─── Cockpit de rentabilidad: DOS vistas + sheet Datos ───────────────────────
//   Pulso → ¿cómo vamos?        P&L → ¿dónde está la plata?
// El estado de la tab vive en el hash de la URL (#pulso · #pyl).
//
// Eran cuatro. Se podaron dos porque no se miran un martes:
//   - Jugadas: sugerencias calculadas ENTERAS en el cliente con constantes
//     inventadas ahí (precio objetivo 62%, add-on $2.900, umbral de "caballo").
//     No consultaba ningún endpoint: se leía una vez y no cambiaba. Lo único
//     operativo que tenía —los insumos que se encarecieron— se rescató al Pulso.
//   - Menú: decide carta y precios, o sea trabajo trimestral, no diario. Sigue
//     entera en /carta, junto a Catálogo, que es donde se toma esa decisión.

type Tab = 'pulso' | 'pyl'
const TABS: { id: Tab; label: string; Icon: typeof Activity }[] = [
  { id: 'pulso', label: 'Pulso', Icon: Activity },
  { id: 'pyl', label: 'P&L', Icon: Wallet },
]
const tabFromHash = (): Tab => {
  const h = window.location.hash.replace('#', '')
  return (['pulso', 'pyl'] as Tab[]).includes(h as Tab) ? (h as Tab) : 'pulso'
}

// "Hoy"/inicio de mes según el reloj de Colombia (no el del navegador).
function mesActualBogota(): { desde: string; hasta: string } {
  const s = new Date().toLocaleDateString('en-CA', { timeZone: 'America/Bogota' })
  const [y, m] = s.split('-')
  return { desde: `${y}-${m}-01`, hasta: s }
}

export default function Rentabilidad() {
  const [tab, setTab] = useState<Tab>(tabFromHash)
  const [pulso, setPulso] = useState<PulsoData | null>(null)
  const [prodData, setProdData] = useState<PorProductoData | null>(null)
  const [plMes, setPlMes] = useState<RentabilidadData | null>(null)
  const [datosOpen, setDatosOpen] = useState(false)

  const fetchProductos = () =>
    api.get<PorProductoData>('/rentabilidad/por-producto')
      .then(r => setProdData(r.data)).catch(() => setProdData(null))

  useEffect(() => {
    api.get<PulsoData>('/rentabilidad/pulso').then(r => setPulso(r.data)).catch(() => setPulso(null))
    fetchProductos()
    const { desde, hasta } = mesActualBogota()
    api.get<RentabilidadData>('/rentabilidad/', { params: { desde, hasta } })
      .then(r => setPlMes(r.data)).catch(() => setPlMes(null))
  }, [])

  // Tab ↔ hash de URL (permite deep-links y back del navegador).
  useEffect(() => {
    const onHash = () => setTab(tabFromHash())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])
  const goTab = (t: Tab) => {
    window.location.hash = t
    setTab(t)
    window.scrollTo({ top: 0 })
  }
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
        <TrendingUp size={20} className="text-forest" />
        <h1 className="text-lg font-bold text-warm-700">Rentabilidad</h1>
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
        <div className="grid grid-cols-2 gap-1 bg-warm-100 rounded-xl p-1">
          {TABS.map(({ id, label, Icon }) => (
            <button key={id} onClick={() => goTab(id)}
              className={`flex items-center justify-center gap-1.5 min-h-[42px] rounded-lg text-xs font-bold transition-colors ${
                tab === id ? 'bg-white text-forest shadow-sm' : 'text-warm-500'}`}>
              <Icon size={14} /> {label}
            </button>
          ))}
        </div>
      </div>

      {tab === 'pulso' && (
        <PulsoView pulso={pulso} plMes={plMes} prodData={prodData}
        />
      )}
      {tab === 'pyl' && <PnLView onVerMetodologia={() => setDatosOpen(true)} />}

      <DatosSheet open={datosOpen} prodData={prodData} plMes={plMes}
        onClose={() => setDatosOpen(false)} onRefresh={fetchProductos} />
    </div>
  )
}
