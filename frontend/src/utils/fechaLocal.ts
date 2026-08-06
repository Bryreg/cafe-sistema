// Fechas "de hoy" en hora LOCAL del dispositivo (Colombia), formato YYYY-MM-DD.
//
// NUNCA usar new Date().toISOString().slice(0, 10) para "hoy": toISOString es UTC,
// y despues de las 19:00 de Colombia (UTC-5) devuelve la fecha de MANANA. Todo
// filtro "hoy" que viaje al backend con esa fecha consulta un dia futuro y da cero.
// El backend interpreta fecha_desde/fecha_hasta como dias de Colombia (rango_col_utc).

const pad = (n: number) => String(n).padStart(2, '0')

/** YYYY-MM-DD de un Date usando sus componentes LOCALES (sin pasar por UTC). */
export function isoLocal(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/** Fecha de hoy en hora local del dispositivo. */
export function hoyLocal(): string {
  return isoLocal(new Date())
}

/**
 * "Hoy" segun el reloj de COLOMBIA (el negocio), no el del dispositivo.
 *
 * El modulo Plata lo necesita en varios lugares y cada uno tenia su propia copia:
 * con un admin viajando (o un navegador mal configurado) esas copias se separan y
 * "vencido" empieza a significar cosas distintas en dos tarjetas de la misma
 * pantalla. Igual que en el backend, la fecha del negocio es una sola.
 */
export function hoyBogota(): string {
  return new Date().toLocaleDateString('en-CA', { timeZone: 'America/Bogota' })
}

/** Fecha de hace `n` dias en hora local. */
export function haceDiasLocal(n: number): string {
  const d = new Date()
  d.setDate(d.getDate() - n)
  return isoLocal(d)
}

/** Primer dia del mes actual en hora local. */
export function inicioMesLocal(): string {
  const d = new Date()
  return isoLocal(new Date(d.getFullYear(), d.getMonth(), 1))
}

/** Lunes de la semana actual en hora local. */
export function inicioSemanaLocal(): string {
  const d = new Date()
  const day = d.getDay() || 7 // domingo=0 -> 7
  d.setDate(d.getDate() - (day - 1))
  return isoLocal(d)
}
