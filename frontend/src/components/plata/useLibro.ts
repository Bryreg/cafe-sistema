import { useCallback, useEffect, useMemo, useState } from 'react'
import api from '../../api/client'
import { hoyBogota } from '../../utils/fechaLocal'
import { DiaConSaldo, LibroMes, SerieAnual, detalleDeError } from './banco'

/**
 * El libro del banco: el mes que se está mirando, los doce meses del año y —lo
 * importante— LA FILA DE HOY.
 *
 * ═════════════════════════════════════════════════════════════════════════════
 * POR QUÉ ES UN HOOK Y NO ESTADO DEL BANNER
 * ═════════════════════════════════════════════════════════════════════════════
 * Dos banners distintos leen el mismo libro: «¿cuánta plata hay?» necesita la
 * fila de hoy y el ancla, y «el libro del banco» necesita el mes entero. Si cada
 * uno pidiera lo suyo habría DOS consultas del mismo mes y —peor— dos momentos
 * distintos: guardar un movimiento actualizaría uno y dejaría al otro mostrando
 * el saldo viejo, que es exactamente la clase de bug que este módulo viene
 * arrastrando (dos números para la misma pregunta, con el optimista adelante).
 *
 * ═════════════════════════════════════════════════════════════════════════════
 * LAS DOS REGLAS QUE NO SE PUEDEN TOCAR
 * ═════════════════════════════════════════════════════════════════════════════
 *  1. EL SALDO DE HOY NO DEPENDE DE DÓNDE MIRÓ EL OJO. Cuando el usuario navega
 *     a otro mes, el mes de hoy se pide APARTE. Sin esto, mirar octubre dejaba
 *     la cabecera de la página sin saldo — como si no se supiera cuánta plata
 *     hay, cuando sí se sabe.
 *  2. LA CADENA SE DECIDE POR LA FILA, NO POR EL MES. `cadena_completa` significa
 *     «todos los días del rango tienen saldo» y con el ancla a mitad de mes —el
 *     caso NORMAL— es false aunque el saldo de hoy sea exacto. Decidir con esa
 *     bandera fue el bug que le pedía al dueño cargar el extracto que acababa de
 *     cargar. La unión discriminada de `DiaLibro` hace que el compilador —y no
 *     la disciplina de quien edite después— impida pintar un saldo que el
 *     backend declaró desconocido.
 */
export function useLibro(refreshKey: number) {
  const hoy = hoyBogota()
  const anioDeHoy = Number(hoy.slice(0, 4))
  const mesDeHoy = Number(hoy.slice(5, 7))

  const [anio, setAnio] = useState(anioDeHoy)
  const [mes, setMes] = useState(mesDeHoy)
  const [libro, setLibro] = useState<LibroMes | null>(null)
  const [serie, setSerie] = useState<SerieAnual | null>(null)
  const [libroDeHoy, setLibroDeHoy] = useState<LibroMes | null>(null)
  const [cargando, setCargando] = useState(true)
  const [error, setError] = useState('')
  const [propio, setPropio] = useState(0)
  const recargar = useCallback(() => setPropio(n => n + 1), [])

  const viendoElMesDeHoy = anio === anioDeHoy && mes === mesDeHoy

  useEffect(() => {
    let vivo = true
    setCargando(true); setError('')
    Promise.all([
      api.get<LibroMes>('/banco/libro', { params: { anio, mes } }),
      api.get<SerieAnual>('/banco/serie', { params: { anio } }),
    ])
      .then(([l, s]) => { if (!vivo) return; setLibro(l.data); setSerie(s.data) })
      .catch(e => {
        if (!vivo) return
        setLibro(null); setSerie(null)
        setError(detalleDeError(e, 'No se pudo cargar el libro del banco.'))
      })
      .finally(() => { if (vivo) setCargando(false) })
    return () => { vivo = false }
  }, [anio, mes, propio, refreshKey])

  // El mes de hoy solo se pide aparte cuando NO es el que se está mirando: en el
  // caso normal se lee del mismo libro y no se gasta una segunda consulta.
  useEffect(() => {
    if (viendoElMesDeHoy) { setLibroDeHoy(null); return }
    let vivo = true
    api.get<LibroMes>('/banco/libro', { params: { anio: anioDeHoy, mes: mesDeHoy } })
      .then(r => { if (vivo) setLibroDeHoy(r.data) })
      .catch(() => { if (vivo) setLibroDeHoy(null) })
    return () => { vivo = false }
  }, [viendoElMesDeHoy, anioDeHoy, mesDeHoy, propio, refreshKey])

  const libroConHoy = viendoElMesDeHoy ? libro : libroDeHoy
  /** La fila de hoy SOLO si su cadena existe. En la rama con cadena, `inicial` y
   *  `final` son números y no `number | null`: lo garantiza el tipo. */
  const filaHoy = useMemo<DiaConSaldo | null>(() => {
    const f = libroConHoy?.dias.find(d => d.fecha === hoy)
    return f && f.cadena ? f : null
  }, [libroConHoy, hoy])

  /** El ancla del mes que se mira; si ese mes no cargó, la del mes de hoy. */
  const ancla = libro?.ancla ?? libroConHoy?.ancla ?? null

  const irAlMes = useCallback((delta: number) => {
    const d = new Date(anio, mes - 1 + delta, 1)
    setAnio(d.getFullYear()); setMes(d.getMonth() + 1)
  }, [anio, mes])

  const irAHoy = useCallback(() => { setAnio(anioDeHoy); setMes(mesDeHoy) }, [anioDeHoy, mesDeHoy])

  /** Saltar al mes de una fecha ISO (lo usa guardar: la fecha es editable y
   *  guardar algo de otro mes sin ver ningún cambio se lee como que no guardó). */
  const irALaFechaDe = useCallback((iso: string) => {
    setAnio(Number(iso.slice(0, 4))); setMes(Number(iso.slice(5, 7)))
  }, [])

  return {
    hoy, anio, mes, anioDeHoy, mesDeHoy, viendoElMesDeHoy,
    libro, libroConHoy, serie, filaHoy, ancla, cargando, error,
    setAnio, irAlMes, irAHoy, irALaFechaDe, setMes, recargar,
  }
}
