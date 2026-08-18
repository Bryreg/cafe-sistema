import { useCallback, useEffect, useState } from 'react'
import api from '../../api/client'
import { hoyBogota } from '../../utils/fechaLocal'
import { Dato, datoCargando, datoFalla, datoListo } from '../../api/dato'
import { DiaConSaldo, LibroMes, SerieAnual, detalleDeError } from './banco'

/**
 * El libro del banco: el mes que se está mirando, los doce meses del año y —lo
 * importante— EL MES DE HOY.
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
 * LAS TRES REGLAS QUE NO SE PUEDEN TOCAR
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
 *  3. «NO VOLVIÓ» NO ES «NO HAY». El molde viejo era
 *     `.catch(() => setLibroDeHoy(null))`, y con ese null la cabecera decía
 *     «Falta el saldo del extracto para saberlo» sobre un mes que quizás tenía
 *     el ancla cargada: la pantalla mandaba a cargar de nuevo un dato que ya
 *     estaba. Ahora cada recurso es un `Dato<T>` y la rama de falla se dibuja
 *     como falla (ver `src/api/dato.ts`).
 */

/**
 * La fila de un día SOLO si su cadena existe.
 *
 * Vive acá —y no repetida en cada banner— porque es la única puerta a los
 * saldos: en la rama con cadena `inicial` y `final` son números y no
 * `number | null`, y eso lo garantiza el tipo. Devolver `null` acá NO es
 * ausencia de dato: es el backend diciendo que ese día es anterior al ancla y
 * su saldo no se conoce. Por eso se llama desde adentro de la rama `listo`.
 */
export function filaConSaldoDe(libro: LibroMes, iso: string): DiaConSaldo | null {
  const f = libro.dias.find(d => d.fecha === iso)
  return f && f.cadena ? f : null
}

export function useLibro(refreshKey: number) {
  const hoy = hoyBogota()
  const anioDeHoy = Number(hoy.slice(0, 4))
  const mesDeHoy = Number(hoy.slice(5, 7))

  const [anio, setAnio] = useState(anioDeHoy)
  const [mes, setMes] = useState(mesDeHoy)
  const [libro, setLibro] = useState<Dato<LibroMes>>(datoCargando)
  const [serie, setSerie] = useState<Dato<SerieAnual>>(datoCargando)
  const [libroDeHoy, setLibroDeHoy] = useState<Dato<LibroMes>>(datoCargando)
  const [propio, setPropio] = useState(0)
  const recargar = useCallback(() => setPropio(n => n + 1), [])

  const viendoElMesDeHoy = anio === anioDeHoy && mes === mesDeHoy

  useEffect(() => {
    let vivo = true
    setLibro(datoCargando); setSerie(datoCargando)
    Promise.all([
      api.get<LibroMes>('/banco/libro', { params: { anio, mes } }),
      api.get<SerieAnual>('/banco/serie', { params: { anio } }),
    ])
      .then(([l, s]) => { if (!vivo) return; setLibro(datoListo(l.data)); setSerie(datoListo(s.data)) })
      .catch(e => {
        if (!vivo) return
        // Los dos van en el MISMO `Promise.all`, así que cuando uno se cae no se
        // sabe cuál fue: los dos quedan en falla con el mismo mensaje. Marcar
        // solo uno sería afirmar sobre el otro sin haberlo leído.
        const m = detalleDeError(e, 'No se pudo leer el libro del banco.')
        setLibro(datoFalla(m)); setSerie(datoFalla(m))
      })
    return () => { vivo = false }
  }, [anio, mes, propio, refreshKey])

  // El mes de hoy solo se pide aparte cuando NO es el que se está mirando: en el
  // caso normal se lee del mismo libro y no se gasta una segunda consulta.
  useEffect(() => {
    if (viendoElMesDeHoy) { setLibroDeHoy(datoCargando); return }
    let vivo = true
    setLibroDeHoy(datoCargando)
    api.get<LibroMes>('/banco/libro', { params: { anio: anioDeHoy, mes: mesDeHoy } })
      .then(r => { if (vivo) setLibroDeHoy(datoListo(r.data)) })
      .catch(e => {
        if (vivo) setLibroDeHoy(datoFalla(
          detalleDeError(e, 'No se pudo leer el libro del mes de hoy.')))
      })
    return () => { vivo = false }
  }, [viendoElMesDeHoy, anioDeHoy, mesDeHoy, propio, refreshKey])

  /** El libro del mes de HOY, venga del mes que se mira o del pedido aparte. */
  const libroConHoy = viendoElMesDeHoy ? libro : libroDeHoy

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
    libro, libroConHoy, serie,
    setAnio, irAlMes, irAHoy, irALaFechaDe, setMes, recargar,
  }
}
