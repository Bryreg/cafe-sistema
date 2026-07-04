// Expression evaluator for count inputs: sums and subtractions only.
// "2500+1000-200" or "+2500+1000" -> 3300. No eval(): digits, + - and decimals.

/** Keep only characters valid in a sum/subtraction expression. */
export function limpiarExpresion(s: string): string {
  return s.replace(/,/g, '.').replace(/[^0-9+\-.\s]/g, '')
}

/** Evaluate "+2500+1000-200" -> 3300. Returns null if not parseable. */
export function evaluarExpresion(s: string): number | null {
  const limpio = limpiarExpresion(s).replace(/\s+/g, '')
  if (!limpio) return null
  // Tokens: signed numbers. Reject dangling operators ("2500+").
  if (!/^[+-]?\d+(\.\d+)?([+-]\d+(\.\d+)?)*$/.test(limpio)) return null
  const tokens = limpio.match(/[+-]?\d+(\.\d+)?/g)
  if (!tokens) return null
  const total = tokens.reduce((acc, t) => acc + Number(t), 0)
  return Number.isFinite(total) ? Math.round(total * 100) / 100 : null
}

/** True if the text contains an operator (i.e., it's an expression, not a plain number). */
export function esExpresion(s: string): boolean {
  return /\d[\s]*[+-]/.test(s) || /^[+-]/.test(s.trim())
}
