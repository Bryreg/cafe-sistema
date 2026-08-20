import { useEffect, useState } from 'react'
import api from '../../api/client'
import { Dato, datoCargando, datoFalla, datoListo } from '../../api/dato'
import { SegunDato, NoSeSabe } from '../ui'
import { detalleDeError, plata } from '../plata/banco'
import type { NominaConsolidada } from './tipos'

// ─── La nómina, abierta ──────────────────────────────────────────────────────
//
// ═════════════════════════════════════════════════════════════════════════════
// POR QUÉ ESTO SE PIDE RECIÉN CUANDO SE ABRE
// ═════════════════════════════════════════════════════════════════════════════
// `/horarios/nomina-consolidada` liquida a cada persona una por una: arma el
// universo, resuelve el IBC, los aportes y las prestaciones de cada barista. Es
// la lectura más cara de la página y contesta una pregunta que el dueño se hace
// una vez al mes, no todas las mañanas.
//
// La regla del pedido es explícita: lo de todos los días tiene que costar cero.
// Así que este fetch no sale con la página — sale la primera vez que alguien
// abre el desplegable, y de ahí en más queda.
//
// ── EL TOTAL SE SUMA, NUNCA SE RECALCULA ────────────────────────────────────
// Los cuatro renglones vienen del backend ya sumados persona por persona. El
// auxilio, el piso del IBC, los aportes y las prestaciones son mensuales POR
// TRABAJADOR: dos baristas de medio tiempo cotizan sobre dos mínimos enteros, no
// sobre uno. Sumar los devengados y liquidar eso una vez se comería la mitad de
// los aportes. Por eso acá no hay una sola multiplicación.

/** Pide la nómina UNA vez, la primera vez que `activo` se pone en true. */
function useNomina(activo: boolean, anio: number, mes: number): {
  dato: Dato<NominaConsolidada>; recargar: () => void
} {
  const [dato, setDato] = useState<Dato<NominaConsolidada>>(datoCargando)
  const [tick, setTick] = useState(0)
  const [pedido, setPedido] = useState(false)

  useEffect(() => { if (activo) setPedido(true) }, [activo])

  useEffect(() => {
    if (!pedido) return
    let vivo = true
    setDato(datoCargando)
    // Guard anti-carrera con bandera, el patrón que este repo ya usa: NO
    // AbortController, porque axios rechaza el abort como un error más y esa
    // rama pintaría «no se pudo cargar» sobre un fetch que se canceló solo.
    api.get<NominaConsolidada>('/horarios/nomina-consolidada', { params: { anio, mes } })
      .then(r => { if (vivo) setDato(datoListo(r.data)) })
      .catch(e => {
        if (vivo) setDato(datoFalla(detalleDeError(e, 'No se pudo leer la nómina.')))
      })
    return () => { vivo = false }
  }, [pedido, anio, mes, tick])

  return { dato, recargar: () => setTick(n => n + 1) }
}

const Renglon = ({ label, valor, fuerte = false }: {
  label: string; valor: string; fuerte?: boolean
}) => (
  <div className={`flex items-baseline justify-between gap-2 ${
    fuerte ? 'border-t border-warm-200 pt-1.5 mt-1.5' : ''}`}>
    <p className={`text-xs ${fuerte ? 'font-bold text-warm-700' : 'text-warm-500'}`}>{label}</p>
    <p className={`font-mono tabular-nums shrink-0 ${
      fuerte ? 'text-sm font-bold text-warm-700' : 'text-xs text-warm-600'}`}>{valor}</p>
  </div>
)

export default function LaNominaAbierta({ anio, mes, id }: {
  anio: number; mes: number; id?: string
}) {
  const [abierto, setAbierto] = useState(false)
  const { dato, recargar } = useNomina(abierto, anio, mes)

  return (
    <details id={id} className="border-t border-warm-100 group"
      onToggle={e => setAbierto(e.currentTarget.open)}>
      <summary className="cursor-pointer select-none list-none px-4 py-2.5 text-[11px] font-bold
                          text-warm-500 hover:bg-warm-50 min-h-[44px] flex items-center">
        <span className="group-open:hidden">▸ </span>
        <span className="hidden group-open:inline">▾ </span>
        La nómina, abierta
      </summary>

      <div className="px-4 pb-3">
        <SegunDato
          dato={dato}
          cargando={<p className="text-sm text-warm-400 py-3">Liquidando persona por persona…</p>}
          falla={m => (
            <NoSeSabe bloque onReintentar={recargar}
              mensaje={`${m} — no se sabe cómo se reparte el costo de tener al equipo. El total `
                + 'de arriba sale de otra lectura y no depende de esta.'} />
          )}
          listo={n => {
            const t = n.totales
            // Prestaciones = costo − devengado − auxilio − aportes. NO se
            // recalcula: se despeja de los números que el backend ya sumó, para
            // que los cuatro renglones cierren EXACTO contra el total. Sumar
            // provisiones por separado daría un centavo de diferencia y un
            // desglose que no cierra con su propio total no se puede defender.
            const aportesYPrestaciones = t.total_costo_empleador - t.total_devengado - t.total_auxilio
            return (<>
              <div className="space-y-1">
                <Renglon label="Sueldos (lo devengado)" valor={plata(t.total_devengado)} />
                <Renglon label="Auxilio de transporte" valor={plata(t.total_auxilio)} />
                <Renglon label="Aportes y prestaciones (salud, pensión, ARL, caja, prima, cesantías, vacaciones)"
                  valor={plata(aportesYPrestaciones)} />
                <Renglon fuerte
                  label={`Costo real de tener ${n.personas.length} `
                    + `${n.personas.length === 1 ? 'persona' : 'personas'}`}
                  valor={plata(t.total_costo_empleador)} />
              </div>

              <p className="text-[11px] text-warm-500 leading-relaxed mt-2">
                Es un <b>estimado del sistema, no la liquidación del contador</b>: no tiene
                retención en la fuente, ni embargos, ni libranzas, ni el redondeo de PILA.
              </p>

              {t.sin_sueldo > 0 && (
                <p className="text-[11px] text-gold-700 leading-relaxed mt-1">
                  Ojo: {t.sin_sueldo} {t.sin_sueldo === 1 ? 'persona' : 'personas'} sin sueldo
                  cargado. {t.sin_sueldo === 1 ? 'Entra' : 'Entran'} al equipo pero no al costo,
                  así que este total está <b>por debajo</b> del real.
                </p>
              )}

              {n.advertencias.map(a => (
                <p key={a} className="text-[11px] text-warm-400 leading-relaxed mt-1">{a}</p>
              ))}

              <details className="mt-2 group/p">
                <summary className="cursor-pointer select-none list-none text-[11px] font-bold
                                    text-forest min-h-[44px] flex items-center">
                  <span className="group-open/p:hidden">▸ </span>
                  <span className="hidden group-open/p:inline">▾ </span>
                  ver persona por persona
                </summary>
                <div className="mt-1 space-y-0.5">
                  {n.personas.map(p => (
                    <div key={p.usuario_id} className="flex items-baseline justify-between gap-2 text-[11px]">
                      <span className="text-warm-500 truncate">
                        {p.nombre}
                        {!p.tiene_sueldo && <span className="text-gold-700"> · sin sueldo cargado</span>}
                      </span>
                      <span className="font-mono tabular-nums text-warm-600 shrink-0">
                        {plata(p.liquidacion.costo_empleador)}
                      </span>
                    </div>
                  ))}
                </div>
              </details>
            </>)
          }} />
      </div>
    </details>
  )
}
