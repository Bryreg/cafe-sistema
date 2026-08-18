import { ReactElement, useEffect, useState } from 'react'
import { CloudOff, RefreshCw, WifiOff } from 'lucide-react'
import type { Fuente } from '../../api/useDato'

// ─── «¿Le puedo creer a esta pantalla?» ──────────────────────────────────────
//
// Una página con nueve fetches puede tener ocho buenos y uno roto, y el dueño no
// tiene forma de saber cuál. Arreglar cada banner por separado hace que ninguno
// mienta, pero deja la pregunta que él realmente se hace —¿confío en lo que veo
// para decidir?— repartida en nueve respuestas que hay que ir a buscar.
//
// Esta franja la contesta en un renglón, arriba de todo, y solo aparece cuando
// hay algo roto: en el día normal no ocupa un píxel.

export interface FranjaDeConfianzaProps {
  /** Todas las fuentes de la página. La franja se fija sola cuáles fallaron. */
  fuentes: Fuente<unknown>[]
}

export default function FranjaDeConfianza({ fuentes }: FranjaDeConfianzaProps): ReactElement | null {
  const [reintentando, setReintentando] = useState(false)

  // Solo `falla`. `cargando` no es un problema —es el estado normal del primer
  // segundo— y `sinBase` no lo emite la red: lo emiten las derivaciones de
  // dominio, y cada banner explica el suyo mejor de lo que puede una franja.
  const rotas = fuentes.filter(f => f.dato.estado === 'falla')
  const pidiendo = fuentes.some(f => f.dato.estado === 'cargando')

  // El spinner se apaga cuando NO QUEDA NADA PIDIENDO, no a los N milisegundos.
  // La primera versión usaba un `setTimeout` de 1200ms, que además de inventar
  // un número disparaba sobre un componente ya desmontado: esta franja se va
  // sola en cuanto todo se recupera, que es justo el caso del reintento exitoso.
  useEffect(() => {
    if (reintentando && !pidiendo) setReintentando(false)
  }, [reintentando, pidiendo])

  // La franja se queda mientras hay algo roto, y también mientras se está
  // reintentando: si desapareciera al primer `cargando`, el dueño tocaría el
  // botón y la barra se le evaporaría en la mano sin decirle si funcionó.
  if (rotas.length === 0 && !reintentando) return null

  const sinRed = typeof navigator !== 'undefined' && navigator.onLine === false
  const Icono = sinRed ? WifiOff : CloudOff

  const reintentar = () => {
    setReintentando(true)
    rotas.forEach(f => f.recargar())
  }

  return (
    <div className="flex items-start gap-2 rounded-2xl border border-gold-200 bg-gold-50 px-3 py-2.5">
      <Icono size={16} className="shrink-0 mt-0.5 text-gold-700" />
      <div className="flex-1 min-w-0">
        {/* Mientras se reintenta, las rotas están en `cargando` y esta lista
            queda vacía: imprimir «Faltan 0 de 9» sería exactamente la cifra sin
            sentido que este refactor vino a matar. */}
        {rotas.length === 0 ? (
          <p className="text-xs font-bold text-gold-700 leading-snug">
            Volviendo a pedir lo que no había cargado…
          </p>
        ) : (<>
          <p className="text-xs font-bold text-gold-700 leading-snug">
            {sinRed
              ? 'La tablet está sin internet.'
              : `Faltan ${rotas.length} de ${fuentes.length} datos de esta página.`}
            {' '}Lo que ves abajo está incompleto.
          </p>
          <p className="text-[11px] text-gold-700/80 leading-snug mt-0.5">
            No cargó: {rotas.map(f => f.nombre).join(' · ')}
          </p>
        </>)}
      </div>
      <button onClick={reintentar} disabled={reintentando}
        className="shrink-0 flex items-center gap-1 min-h-[46px] px-2.5 rounded-xl
                   text-[11px] font-bold text-gold-700 hover:bg-gold-100 disabled:opacity-50">
        <RefreshCw size={13} className={reintentando ? 'animate-spin' : ''} />
        {reintentando ? 'Reintentando…' : 'Reintentar'}
      </button>
    </div>
  )
}
