import { useState, useEffect } from 'react'
import api from '../api/client'
import { Coffee, SlidersHorizontal } from 'lucide-react'
import MenuView from '../components/rentabilidad/MenuView'
import SimuladorSheet from '../components/rentabilidad/SimuladorSheet'
import type { PorProductoData, PulsoData } from '../components/rentabilidad/helpers'

/**
 * Carta: qué productos funcionan y a qué precio.
 *
 * Vivía como pestaña de Rentabilidad, pero responde una pregunta de otro ritmo:
 * rentabilidad se mira un martes ("¿cómo vamos?"), la carta se decide por
 * trimestre. Mezclarlas era la mitad de la sensación de "muchas pestañas".
 * Acá queda junto a Catálogo y Combos, que es donde se cambia lo que se vende.
 *
 * La vista es la MISMA (MenuView, sin tocar): solo cambió dónde vive y quién le
 * trae los datos.
 */
export default function Carta() {
  const [prodData, setProdData] = useState<PorProductoData | null>(null)
  const [pulso, setPulso] = useState<PulsoData | null>(null)
  const [cargando, setCargando] = useState(true)
  // El simulador se abria SOLO desde la pestana Jugadas; al podarla quedaba
  // inalcanzable. Su lugar es aca: simular precio y costo ES una decision de
  // carta. Trae su propio selector de producto adentro.
  const [simAbierto, setSimAbierto] = useState(false)
  const primerCandidato = prodData?.productos.find(
    p => p.unidades_30d > 0 && p.costo != null && p.costo > 0 && p.precio_venta > 0)?.producto_id ?? null

  useEffect(() => {
    Promise.all([
      api.get<PorProductoData>('/rentabilidad/por-producto'),
      api.get<PulsoData>('/rentabilidad/pulso').catch(() => null),
    ])
      .then(([p, pu]) => { setProdData(p.data); if (pu) setPulso(pu.data) })
      .catch(() => setProdData(null))
      .finally(() => setCargando(false))
  }, [])

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Coffee size={20} className="text-forest" />
        <h1 className="text-lg font-bold text-gray-800">Carta</h1>
        {primerCandidato != null && (
          <button onClick={() => setSimAbierto(true)}
            className="ml-auto inline-flex items-center gap-1.5 min-h-[40px] px-3 rounded-full border border-warm-200 bg-white text-xs font-bold text-forest">
            <SlidersHorizontal size={13} /> Simular costo
          </button>
        )}
      </div>

      {cargando ? (
        <div className="space-y-3">
          <div className="h-24 rounded-2xl bg-warm-100 animate-pulse" />
          <div className="h-64 rounded-2xl bg-warm-100 animate-pulse" />
        </div>
      ) : (
        <MenuView prodData={prodData} pulso={pulso} />
      )}

      <SimuladorSheet prodData={prodData}
        productoId={simAbierto ? primerCandidato : null}
        onClose={() => setSimAbierto(false)} />
    </div>
  )
}
