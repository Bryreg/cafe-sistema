import { Search, Star, X } from 'lucide-react'
import { Badge, SectionLabel } from './ui'

// ─── Tipos ───────────────────────────────────────────────────────────────────

export interface Producto {
  id: number
  nombre: string
  categoria: string
  precio_venta: number
  controla_stock: boolean
  unidad_medida: string
  vendidos_7d: number
}

interface Props {
  productos: Producto[]
  cart: Array<{ producto_id: number; cantidad: number }>
  onAdd: (p: Producto) => void
  search: string
  onSearch: (v: string) => void
  catFiltro: string
  onCatFiltro: (v: string) => void
  soloFavoritos: boolean
  onToggleFavoritos: () => void
  loading: boolean
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

const fmtCO = (v: number) => `$${v.toLocaleString('es-CO')}`

const CAT_LABEL: Record<string, string> = {
  bebida: 'Bebidas',
  pasteleria: 'Pastelería',
  insumo: 'Insumos',
}

// Tono de Badge por categoría (tokens del sistema, sin oklch inline).
const CAT_TONE: Record<string, 'success' | 'gold' | 'clay' | 'warm'> = {
  bebida: 'success',
  pasteleria: 'gold',
  insumo: 'clay',
}

// ─── Componente ──────────────────────────────────────────────────────────────

/**
 * Panel izquierdo del POS: búsqueda, chip de favoritos, filtros de categoría
 * y la grilla de productos. Presentacional — el estado vive en POS.tsx.
 */
export default function ProductGrid({
  productos,
  cart,
  onAdd,
  search,
  onSearch,
  catFiltro,
  onCatFiltro,
  soloFavoritos,
  onToggleFavoritos,
  loading,
}: Props) {
  const categorias = Array.from(new Set(productos.map(p => p.categoria))).sort()
  const hayFavoritos = productos.some(p => p.vendidos_7d > 0)

  const term = search.trim().toLowerCase()
  const filtrados = productos.filter(p => {
    if (catFiltro !== 'todas' && p.categoria !== catFiltro) return false
    if (soloFavoritos && p.vendidos_7d <= 0) return false
    if (term && !p.nombre.toLowerCase().includes(term)) return false
    return true
  })

  const chipBase =
    'px-3 py-1.5 rounded-xl text-xs font-bold border-2 transition-all shrink-0 active:scale-95'
  const chipActive = 'bg-forest border-forest text-white'
  const chipIdle = 'bg-white border-warm-200 text-warm-500 hover:border-warm-300'

  return (
    <div className="flex flex-col gap-3">
      {/* ── Búsqueda ── */}
      <div className="relative">
        <Search
          size={16}
          className="absolute left-3 top-1/2 -translate-y-1/2 text-warm-400 pointer-events-none"
        />
        <input
          type="text"
          value={search}
          onChange={e => onSearch(e.target.value)}
          placeholder="Buscar producto…"
          className="w-full bg-white border border-warm-200 rounded-xl pl-9 pr-9 py-2.5 text-sm text-bark-800 placeholder:text-warm-400 focus:outline-none focus:border-forest focus:ring-2 focus:ring-forest/15 transition-all"
        />
        {search && (
          <button
            onClick={() => onSearch('')}
            aria-label="Limpiar búsqueda"
            className="absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded-lg text-warm-400 hover:text-warm-600 hover:bg-warm-100 transition-colors"
          >
            <X size={15} />
          </button>
        )}
      </div>

      {/* ── Chips: Favoritos + categorías ── */}
      <div className="flex gap-2 overflow-x-auto pb-1 -mx-1 px-1">
        {hayFavoritos && (
          <button
            onClick={onToggleFavoritos}
            className={`${chipBase} flex items-center gap-1 ${
              soloFavoritos ? 'bg-clay border-clay text-white' : chipIdle
            }`}
          >
            <Star size={12} className={soloFavoritos ? 'fill-white' : 'fill-clay-400 text-clay-400'} />
            Favoritos
          </button>
        )}
        <button
          onClick={() => onCatFiltro('todas')}
          className={`${chipBase} ${catFiltro === 'todas' ? chipActive : chipIdle}`}
        >
          Todos
        </button>
        {categorias.map(cat => (
          <button
            key={cat}
            onClick={() => onCatFiltro(cat)}
            className={`${chipBase} ${catFiltro === cat ? chipActive : chipIdle}`}
          >
            {CAT_LABEL[cat] ?? cat}
          </button>
        ))}
      </div>

      {/* ── Grilla ── */}
      {filtrados.length === 0 ? (
        <div className="text-center text-sm text-warm-400 py-12">
          {loading
            ? 'Cargando productos…'
            : term || soloFavoritos || catFiltro !== 'todas'
              ? 'Sin resultados para este filtro'
              : 'No hay productos disponibles'}
        </div>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-2.5">
          {filtrados.map(p => {
            const inCart = cart.find(i => i.producto_id === p.id)
            const esTop = p.vendidos_7d > 0
            return (
              <button
                key={p.id}
                onClick={() => onAdd(p)}
                className={`relative flex flex-col gap-1.5 p-3.5 rounded-2xl border-2 text-left active:scale-95 transition-all ${
                  inCart
                    ? 'border-success-500 bg-success-50'
                    : 'border-warm-200 bg-white hover:border-warm-300'
                }`}
              >
                {inCart && (
                  <span className="absolute top-2 right-2 w-5 h-5 rounded-full bg-success-500 flex items-center justify-center text-[10px] font-bold text-white tabular-nums">
                    {inCart.cantidad}
                  </span>
                )}
                <div className="flex items-center gap-1.5 self-start">
                  <Badge tone={CAT_TONE[p.categoria] ?? 'warm'}>
                    {CAT_LABEL[p.categoria] ?? p.categoria}
                  </Badge>
                  {esTop && (
                    <Star size={12} className="fill-clay-400 text-clay-400 shrink-0" />
                  )}
                </div>
                <p className="text-sm font-bold text-bark-800 leading-tight">{p.nombre}</p>
                <p className="text-base font-bold text-forest tabular-nums">
                  {fmtCO(p.precio_venta)}
                </p>
              </button>
            )
          })}
        </div>
      )}

      {filtrados.length > 0 && (
        <SectionLabel className="text-warm-400">
          {filtrados.length} {filtrados.length === 1 ? 'producto' : 'productos'}
        </SectionLabel>
      )}
    </div>
  )
}
