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

  const [error, setError] = useState<string | null>(null)
  const [lento, setLento] = useState(false)

  useEffect(() => {
    let vivo = true
    setCargando(true)
    setError(null)
    setLento(false)
    // A los 4s sin respuesta ya no es la red: es el backend despertando.
    const avisoLento = setTimeout(() => { if (vivo) setLento(true) }, 4000)
    // El pulso es opcional (solo alimenta "top movers"): si falla, la carta se ve
    // igual. Los productos NO: sin ellos no hay nada que mostrar, y el fallo tiene
    // que DECIRSE — quedarse en el esqueleto para siempre no le dice nada a nadie.
    Promise.all([
      api.get<PorProductoData>('/rentabilidad/por-producto'),
      api.get<PulsoData>('/rentabilidad/pulso').catch(() => null),
    ])
      .then(([p, pu]) => {
        if (!vivo) return
        setProdData(p.data)
        if (pu) setPulso(pu.data)
      })
      .catch((e) => {
        if (!vivo) return
        setProdData(null)
        setError(e?.response?.data?.detail || e?.message || 'No se pudieron cargar los productos')
      })
      .finally(() => { if (vivo) setCargando(false) })
    return () => { vivo = false; clearTimeout(avisoLento) }
  }, [])

  const sinProductos = !cargando && !error && (prodData?.productos?.length ?? 0) === 0

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
          {/* El backend duerme (Render free): el primer pedido del día puede tardar
              casi un minuto en despertarlo. Sin avisar, el esqueleto se lee como
              "la pantalla está rota" — que es exactamente lo que pasó la primera
              vez que se abrió esta página. */}
          {lento && (
            <p className="text-xs text-warm-500 px-1">
              El servidor estaba dormido y está despertando. Puede tardar hasta un minuto la primera vez del día.
            </p>
          )}
          <div className="h-24 rounded-2xl bg-warm-100 animate-pulse" />
          <div className="h-64 rounded-2xl bg-warm-100 animate-pulse" />
        </div>
      ) : error ? (
        <div className="bg-white border border-danger-200 rounded-2xl px-4 py-6 text-center">
          <p className="text-sm font-bold text-danger-700">No se pudo cargar la carta</p>
          <p className="text-xs text-warm-500 mt-1">{error}</p>
          <button onClick={() => window.location.reload()}
            className="mt-3 inline-flex min-h-[40px] items-center px-4 rounded-full border border-warm-200 bg-white text-xs font-bold text-forest">
            Reintentar
          </button>
        </div>
      ) : sinProductos ? (
        <div className="bg-white border border-warm-200 rounded-2xl px-4 py-8 text-center">
          <p className="text-sm font-bold text-warm-700">Todavía no hay productos para analizar</p>
          <p className="text-xs text-warm-500 mt-1">
            La carta compara precio contra costo: necesita productos con precio de venta y
            con costo (receta o compra). Cargalos en Catálogo.
          </p>
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
