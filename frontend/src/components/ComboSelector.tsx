import { useEffect, useState } from 'react'
import { Check, Lock, ShoppingBag } from 'lucide-react'
import { Badge, SectionLabel } from './ui'

// ─── Tipos ───────────────────────────────────────────────────────────────────

// Shape que devuelve GET /pos/combos (ComboOut del backend).
export interface ComboOpcionProductoPos {
  producto_id: number
  nombre: string
  cantidad: number
}

export interface ComboOpcionPos {
  id: number
  nombre: string
  orden: number
  productos: ComboOpcionProductoPos[]
}

export interface ComboGrupoPos {
  id: number
  nombre: string
  orden: number
  opciones: ComboOpcionPos[]
}

export interface ComboPos {
  id: number
  nombre: string
  precio_venta: number
  orden: number
  grupos: ComboGrupoPos[]
}

/** Selección resuelta (una opción por grupo) — viaja al carrito y al checkout. */
export interface ComboSeleccion {
  grupo_id: number
  opcion_id: number
  nombre_grupo: string
  nombre_opcion: string
}

interface Props {
  combo: ComboPos
  onAgregar: (combo: ComboPos, selecciones: ComboSeleccion[]) => void
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

const fmtCO = (v: number) => `$${v.toLocaleString('es-CO')}`

/** Preselección inicial: los grupos de UNA sola opción son fijos. */
function seleccionInicial(combo: ComboPos): Record<number, number> {
  const sel: Record<number, number> = {}
  combo.grupos.forEach(g => {
    if (g.opciones.length === 1) sel[g.id] = g.opciones[0].id
  })
  return sel
}

// ─── Componente ──────────────────────────────────────────────────────────────

/**
 * Selector de combo del POS: una opción por grupo (radio-style), grupos de
 * opción única fijos/preseleccionados, precio fijo visible y botón de agregar
 * deshabilitado hasta completar todas las elecciones. Presentacional — el
 * carrito vive en POS.tsx.
 */
export default function ComboSelector({ combo, onAgregar }: Props) {
  const [sel, setSel] = useState<Record<number, number>>(() => seleccionInicial(combo))

  // Al cambiar de pestaña de combo, resetear a la preselección de ese combo.
  useEffect(() => {
    setSel(seleccionInicial(combo))
  }, [combo.id]) // eslint-disable-line react-hooks/exhaustive-deps

  const completo = combo.grupos.every(g => sel[g.id] != null)

  const agregar = () => {
    if (!completo) return
    const selecciones: ComboSeleccion[] = combo.grupos.map(g => {
      const opcion = g.opciones.find(o => o.id === sel[g.id])!
      return {
        grupo_id: g.id,
        opcion_id: opcion.id,
        nombre_grupo: g.nombre,
        nombre_opcion: opcion.nombre,
      }
    })
    onAgregar(combo, selecciones)
  }

  return (
    <div className="bg-white rounded-2xl border-2 border-warm-200 p-4 flex flex-col gap-4">
      {/* ── Encabezado: nombre + precio fijo ── */}
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-base font-bold text-bark-800">{combo.nombre}</p>
          <p className="text-xs text-warm-400 mt-0.5">Precio fijo del combo</p>
        </div>
        <span className="text-2xl font-bold text-forest tabular-nums shrink-0">
          {fmtCO(combo.precio_venta)}
        </span>
      </div>

      {/* ── Grupos ── */}
      {combo.grupos.map(grupo => {
        const fijo = grupo.opciones.length === 1
        return (
          <div key={grupo.id} className="flex flex-col gap-2">
            <div className="flex items-center gap-2">
              <SectionLabel className="text-warm-500">{grupo.nombre}</SectionLabel>
              {fijo ? (
                <Badge tone="warm">
                  <span className="flex items-center gap-1">
                    <Lock size={10} /> Incluido
                  </span>
                </Badge>
              ) : (
                <span className="text-[11px] text-warm-400">Elegí 1</span>
              )}
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {grupo.opciones.map(opcion => {
                const activa = sel[grupo.id] === opcion.id
                const detalle = opcion.productos
                  .map(p => (p.cantidad > 1 ? `${p.nombre} ×${p.cantidad}` : p.nombre))
                  .join(' + ')
                return (
                  <button
                    key={opcion.id}
                    type="button"
                    disabled={fijo}
                    onClick={() => setSel(prev => ({ ...prev, [grupo.id]: opcion.id }))}
                    className={`relative flex items-start gap-2.5 p-3 rounded-2xl border-2 text-left transition-all ${
                      activa
                        ? 'border-success-500 bg-success-50'
                        : 'border-warm-200 bg-white hover:border-warm-300'
                    } ${fijo ? 'cursor-default' : 'active:scale-[0.98]'}`}
                  >
                    {/* Radio visual */}
                    <span
                      className={`mt-0.5 w-4 h-4 shrink-0 rounded-full border-2 flex items-center justify-center ${
                        activa ? 'border-success-500 bg-success-500' : 'border-warm-300 bg-white'
                      }`}
                    >
                      {activa && <Check size={10} className="text-white" strokeWidth={3.5} />}
                    </span>
                    <span className="min-w-0">
                      <span className="block text-sm font-bold text-bark-800 leading-tight">
                        {opcion.nombre}
                      </span>
                      {detalle !== opcion.nombre && (
                        <span className="block text-[11px] text-warm-400 mt-0.5">{detalle}</span>
                      )}
                    </span>
                  </button>
                )
              })}
            </div>
          </div>
        )
      })}

      {/* ── Agregar a la cuenta ── */}
      <button
        type="button"
        onClick={agregar}
        disabled={!completo}
        className={[
          'w-full font-bold py-3.5 rounded-2xl text-sm flex items-center justify-center gap-2 transition-all active:scale-[0.98]',
          'disabled:opacity-40 disabled:cursor-not-allowed',
          completo ? 'bg-clay hover:bg-clay-600 text-white shadow-lg shadow-clay/20' : 'bg-warm-100 text-warm-400',
        ].join(' ')}
      >
        <ShoppingBag size={16} />
        {completo
          ? `Agregar a la cuenta — ${fmtCO(combo.precio_venta)}`
          : 'Elegí una opción de cada grupo'}
      </button>
    </div>
  )
}
