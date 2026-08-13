/**
 * El orden en que se cuenta: el recorrido físico del local.
 *
 * `orden_conteo` lo siembra el backend desde `app/data/orden_conteo.json` — la
 * lista que dictó el dueño, en tres bloques que son las tres zonas que las
 * baristas caminan al contar. Los órdenes saltan de 1000 en 1000 entre bloques
 * (10, 20, 30… / 1010, 1020… / 2010, 2020…), y ese salto es lo único que hace
 * falta para dibujar el corte entre zonas sin inventar encabezados.
 *
 * Un producto sin posición (`null`) no está en la lista del dueño: se cuenta al
 * final, alfabético. Es a propósito — el cargador solo asigna posición cuando
 * está seguro de qué producto es, y ponerlo en la fila equivocada sería peor
 * que ponerlo al final.
 *
 * Vive acá y no en cada pantalla porque las tres pantallas de conteo (apertura,
 * cierre y fin de mes) tienen que mostrar EL MISMO orden: es el mismo recorrido.
 */

export interface ConOrdenConteo {
  orden_conteo?: number | null
}

const SALTO_BLOQUE = 1000

/** Bloque (zona del local) al que pertenece una posición. Sin posición → el
 *  tramo final, después de todo lo que sí está en la lista. */
export function bloqueDe(orden?: number | null): number {
  return orden === null || orden === undefined ? Infinity : Math.floor(orden / SALTO_BLOQUE)
}

/**
 * Comparador del recorrido: por posición y, a igualdad (o sin posición),
 * alfabético por nombre.
 *
 * OJO con el `??  Infinity`: dos productos sin posición dan `Infinity - Infinity`
 * = NaN, y un comparador que devuelve NaN deja el orden indefinido. Por eso se
 * comparan las posiciones con `!==` antes de restarlas.
 */
export function compararRecorrido<T extends ConOrdenConteo>(
  nombreDe: (x: T) => string,
): (a: T, b: T) => number {
  return (a, b) => {
    const oa = a.orden_conteo ?? Infinity
    const ob = b.orden_conteo ?? Infinity
    if (oa !== ob) return oa - ob
    return (nombreDe(a) || '').localeCompare(nombreDe(b) || '', 'es')
  }
}

/** El mismo orden, ya aplicado. No muta el arreglo original. */
export function ordenarPorRecorrido<T extends ConOrdenConteo>(
  items: readonly T[],
  nombreDe: (x: T) => string,
): T[] {
  return [...items].sort(compararRecorrido(nombreDe))
}

/** ¿Este ítem abre una zona nueva? (para dibujar el corte entre bloques) */
export function abreBloque(actual?: number | null, anterior?: number | null): boolean {
  return bloqueDe(actual) !== bloqueDe(anterior)
}
