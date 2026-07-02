/** Helpers for money text inputs with live es-CO thousand separators.
 *  State keeps a digits-only string; the input displays it with dots. */

/** Strip everything but digits from a money input string. */
export const soloDigitos = (s: string) => s.replace(/\D/g, '')

/** Render a digits-only string with es-CO thousand dots ('' stays ''). */
export const conMiles = (s: string) => (s ? Number(s).toLocaleString('es-CO') : '')
