import { useEffect, useRef, useState } from 'react'
import { useFiltro } from '../contexts/FiltroContext'

const CATEGORIAS = ['bebida', 'pasteleria', 'insumo']

export default function FilterBar() {
  const { filtro, setFiltro } = useFiltro()
  const [searchInput, setSearchInput] = useState(filtro.productoSearch ?? '')
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Sync searchInput when filtro.productoSearch is cleared externally
  useEffect(() => {
    if (filtro.productoSearch === null) {
      setSearchInput('')
    }
  }, [filtro.productoSearch])

  const handleSearchChange = (value: string) => {
    setSearchInput(value)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      setFiltro(prev => ({ ...prev, productoSearch: value || null }))
    }, 300)
  }

  const clearOptional = () => {
    setSearchInput('')
    if (debounceRef.current) clearTimeout(debounceRef.current)
    setFiltro(prev => ({
      ...prev,
      categoria: null,
      turnoId: null,
      productoSearch: null,
      conDescuento: null,
    }))
  }

  const activeChips: { label: string; onRemove: () => void }[] = []

  if (filtro.categoria !== null) {
    activeChips.push({
      label: `Categoría: ${filtro.categoria}`,
      onRemove: () => setFiltro(prev => ({ ...prev, categoria: null })),
    })
  }
  if (filtro.turnoId !== null) {
    activeChips.push({
      label: `Turno: #${filtro.turnoId}`,
      onRemove: () => setFiltro(prev => ({ ...prev, turnoId: null })),
    })
  }
  if (filtro.productoSearch !== null) {
    activeChips.push({
      label: `Producto: ${filtro.productoSearch}`,
      onRemove: () => {
        setSearchInput('')
        setFiltro(prev => ({ ...prev, productoSearch: null }))
      },
    })
  }
  if (filtro.conDescuento !== null) {
    activeChips.push({
      label: 'Con descuento',
      onRemove: () => setFiltro(prev => ({ ...prev, conDescuento: null })),
    })
  }

  return (
    <div className="bg-white border border-gray-200 rounded-xl px-4 py-3 space-y-3">
      <div className="flex gap-2 flex-wrap items-end">
        <div>
          <label className="text-xs text-gray-500 block mb-1">Desde</label>
          <input
            type="date"
            value={filtro.desde}
            onChange={e => setFiltro(prev => ({ ...prev, desde: e.target.value }))}
            className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400"
          />
        </div>
        <div>
          <label className="text-xs text-gray-500 block mb-1">Hasta</label>
          <input
            type="date"
            value={filtro.hasta}
            onChange={e => setFiltro(prev => ({ ...prev, hasta: e.target.value }))}
            className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400"
          />
        </div>

        <div>
          <label className="text-xs text-gray-500 block mb-1">Categoría</label>
          <select
            value={filtro.categoria ?? ''}
            onChange={e => setFiltro(prev => ({ ...prev, categoria: e.target.value || null }))}
            className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400"
          >
            <option value="">Todas</option>
            {CATEGORIAS.map(c => (
              <option key={c} value={c}>{c.charAt(0).toUpperCase() + c.slice(1)}</option>
            ))}
          </select>
        </div>

        <div>
          <label className="text-xs text-gray-500 block mb-1">Turno #</label>
          <input
            type="number"
            placeholder="Turno #"
            value={filtro.turnoId ?? ''}
            onChange={e => setFiltro(prev => ({ ...prev, turnoId: e.target.value ? Number(e.target.value) : null }))}
            className="border border-gray-200 rounded-lg px-3 py-2 text-sm w-24 focus:outline-none focus:ring-2 focus:ring-amber-400"
          />
        </div>

        <div>
          <label className="text-xs text-gray-500 block mb-1">Producto</label>
          <input
            type="text"
            placeholder="Buscar producto..."
            value={searchInput}
            onChange={e => handleSearchChange(e.target.value)}
            className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400"
          />
        </div>

        <div className="flex items-end gap-2">
          <label className="flex items-center gap-1.5 text-sm text-gray-600 cursor-pointer pb-2">
            <input
              type="checkbox"
              checked={filtro.conDescuento === true}
              onChange={e => setFiltro(prev => ({ ...prev, conDescuento: e.target.checked ? true : null }))}
              className="rounded"
            />
            Con descuento
          </label>
        </div>

        {activeChips.length > 0 && (
          <button
            onClick={clearOptional}
            className="text-xs text-gray-500 border border-gray-200 rounded-lg px-3 py-2 hover:border-gray-400 hover:text-gray-700 transition-colors"
          >
            Limpiar filtros
          </button>
        )}
      </div>

      {activeChips.length > 0 && (
        <div className="flex gap-1.5 flex-wrap">
          {activeChips.map((chip, i) => (
            <span
              key={i}
              className="flex items-center gap-1 px-2 py-1 rounded-full text-xs font-semibold bg-amber-50 text-amber-800 border border-amber-200"
            >
              {chip.label}
              <button
                onClick={chip.onRemove}
                className="hover:text-amber-900 font-bold ml-0.5"
                aria-label="Quitar filtro"
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
