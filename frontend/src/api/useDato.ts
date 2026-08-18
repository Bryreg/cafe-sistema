import { DependencyList, useCallback, useEffect, useState } from 'react'
import type { AxiosResponse } from 'axios'
import { detalleDeError } from './errores'
import { Dato, datoCargando, datoFalla, datoListo } from './dato'

/**
 * Lo que la página tiene de cada endpoint.
 *
 * Se pasa ENTERO a los hijos —no solo el `dato`— para que cada banner tenga su
 * propio «Reintentar» sin cablear un callback por recurso desde arriba. Que el
 * hijo pueda repedir SU dato es lo que evita que el dueño tenga que recargar la
 * página y perder lo que estaba tecleando.
 */
export interface Fuente<T> {
  dato: Dato<T>
  /** En el idioma del dueño: «la agenda de pagos», no «/costos/agenda». */
  nombre: string
  /** Epoch ms de la última lectura BUENA. `null` = nunca hubo una. */
  leido: number | null
  /** Repide SOLO este recurso. No desmonta a nadie. */
  recargar: () => void
}

/**
 * Un recurso del backend con sus cuatro estados, en vez de un `T | null`.
 *
 * `fallback` es solo para cuando NO hubo respuesta. Si el backend contestó con
 * un `detail`, gana el `detail`: esos mensajes están escritos para el dueño y
 * son la única parte del error que sirve.
 */
export function useDato<T>(
  pedir: () => Promise<AxiosResponse<T>>,
  nombre: string,
  fallback: string,
  deps: DependencyList = [],
): Fuente<T> {
  const [dato, setDato] = useState<Dato<T>>(datoCargando)
  const [leido, setLeido] = useState<number | null>(null)
  const [tick, setTick] = useState(0)
  const recargar = useCallback(() => setTick(n => n + 1), [])

  useEffect(() => {
    // Guard anti-carrera con bandera, que es el patrón que este repo ya usa en
    // ResultadoView. NO AbortController: axios rechaza el abort como un error
    // más, y esa rama pintaría «no se pudo cargar» sobre un fetch que se
    // canceló solo — la misma familia de mentira que vinimos a matar.
    let vigente = true
    setDato(datoCargando)
    pedir()
      .then(r => { if (vigente) { setDato(datoListo(r.data)); setLeido(Date.now()) } })
      .catch(e => { if (vigente) setDato(datoFalla(detalleDeError(e, fallback))) })
    return () => { vigente = false }
    // `pedir` NO va en las deps a propósito: es una arrow nueva en cada render
    // y metería el fetch en un bucle. `deps` tiene que ser de largo constante.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick])

  return { dato, nombre, leido, recargar }
}
