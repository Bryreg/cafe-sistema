// Avatar de barista: color estable por hash del nombre (→ hue) + 2 iniciales.
// Compartido entre el cockpit admin (/cumplimiento) y el hub de la barista (/limpieza)
// para que "quién" se vea idéntico en las dos pantallas.

export const hueDe = (s: string) => {
  let h = 0
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 360
  return h
}
export const inicialesDe = (n: string) => {
  const p = n.trim().split(/\s+/)
  return (((p[0]?.[0] ?? '') + (p[1]?.[0] ?? '')).toUpperCase()) || '—'
}

export function BaristaAvatar({ nombre, size = 22 }: { nombre: string; size?: number }) {
  const h = hueDe(nombre)
  return (
    <span title={nombre} style={{
      width: size, height: size, borderRadius: 999, flexShrink: 0,
      background: `oklch(90% 0.05 ${h})`, color: `oklch(40% 0.13 ${h})`,
      display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
      fontSize: Math.round(size * 0.42), fontWeight: 800, letterSpacing: '-0.03em',
      border: `1px solid oklch(80% 0.06 ${h})`,
    }}>{inicialesDe(nombre)}</span>
  )
}
