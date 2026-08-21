import { useEffect, useState } from 'react'
import { ArrowDownRight, ArrowUpRight } from 'lucide-react'
import api from '../../api/client'
import { Dato, datoCargando, datoFalla, datoListo } from '../../api/dato'
import { SegunDato, NoSeSabe } from '../ui'
import { MESES_CORTOS, detalleDeError, plata } from './banco'

/**
 * «LO QUE VIENE» — el cierre estimado de los próximos meses.
 *
 * Sale de `/banco/proyeccion`, que aprende del ritmo del libro (la mediana del
 * neto de los meses completos). Es una GUÍA para prepararse, no una promesa, y
 * la pantalla lo dice sin adornos.
 *
 * `base` en null (con su `motivo`) NO es una falla: es el backend diciendo que
 * todavía no hay con qué estimar sin inventar (falta historial o el saldo del
 * extracto). Se dibuja como un aviso calmo, nunca como números en cero — que es
 * exactamente la clase de mentira que este sistema persigue.
 */
interface MesProyectado { anio: number; mes: number; cierre_estimado: number }
interface Proyeccion {
  base: { saldo_hoy: number; neto_normal: number; meses_de_historial: number } | null
  meses: MesProyectado[]
  motivo: string | null
}

export default function LoQueViene({ refreshKey }: { refreshKey: number }) {
  const [dato, setDato] = useState<Dato<Proyeccion>>(datoCargando)
  const [tick, setTick] = useState(0)

  useEffect(() => {
    let vivo = true
    setDato(datoCargando)
    api.get<Proyeccion>('/banco/proyeccion', { params: { meses: 3 } })
      .then(r => { if (vivo) setDato(datoListo(r.data)) })
      .catch(e => {
        if (vivo) setDato(datoFalla(detalleDeError(e, 'No se pudo leer la proyección.')))
      })
    return () => { vivo = false }
  }, [refreshKey, tick])

  return (
    <section className="rounded-2xl border border-warm-200 bg-white overflow-hidden">
      <div className="flex items-baseline justify-between gap-2 px-4 py-3 border-b border-warm-100">
        <h2 className="text-sm font-bold text-warm-700">Lo que viene</h2>
        <span className="text-[12px] text-warm-500">los próximos meses · estimado</span>
      </div>

      <div className="p-4">
        <SegunDato
          dato={dato}
          cargando={<p className="text-sm text-warm-400 animate-pulse">Estimando…</p>}
          falla={m => (
            <NoSeSabe onReintentar={() => setTick(t => t + 1)}
              mensaje={`${m} — no se sabe cómo vienen los próximos meses.`} />
          )}
          listo={p => p.base === null ? (
            <p className="text-[13px] text-warm-500 leading-relaxed">
              {p.motivo || 'Todavía no hay con qué estimar los próximos meses.'}
            </p>
          ) : (<>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
              {p.meses.map((m, i) => {
                const previo = i === 0 ? p.base!.saldo_hoy : p.meses[i - 1].cierre_estimado
                const sube = m.cierre_estimado >= previo
                const rojo = m.cierre_estimado < 0
                return (
                  <div key={`${m.anio}-${m.mes}`}
                    className="flex items-center justify-between gap-2 rounded-xl bg-warm-50 px-4 py-3">
                    <div className="flex flex-col">
                      <span className="text-[11px] font-bold uppercase tracking-wide text-warm-500">
                        {MESES_CORTOS[m.mes - 1]} {m.anio !== p.meses[0].anio ? m.anio : ''}
                      </span>
                      <span className={`font-mono tabular-nums text-base font-bold ${
                        rojo ? 'text-danger-700' : 'text-success-700'}`}>
                        ~ {plata(m.cierre_estimado)}
                      </span>
                    </div>
                    {sube
                      ? <ArrowUpRight size={18} className="text-success-600 shrink-0" />
                      : <ArrowDownRight size={18} className="text-danger-500 shrink-0" />}
                  </div>
                )
              })}
            </div>
            <p className="mt-3 text-[12px] text-warm-500 leading-relaxed">
              Sale del ritmo de los últimos <b>{p.base.meses_de_historial}</b> meses del libro (la
              mediana del neto, para que un mes raro no la tuerza). Es una guía para prepararte,
              no una promesa.
            </p>
          </>)}
        />
      </div>
    </section>
  )
}
