// Tema DÍA del kiosko (modo claro).
//
// Nota: el export sigue llamándose `dark` por compatibilidad con los imports
// existentes en las pantallas operativas (GestionTurno, Cierre, Entrega,
// ContadorEfectivo, ConteoInventario, FilaDenom, OperativeBanner). Los VALORES
// son de modo día: superficies claras, texto oscuro y acentos saturados que
// resaltan sobre fondo claro. Renombrar el token es deuda aparte.
//
// Reglas de contraste (día):
//  - Acentos (amber/green/danger): oscuros y saturados → legibles sobre claro.
//  - *Dim: versión suave del acento (bordes, subtexto).
//  - *Tint: fondo de acento muy claro (badges, paneles destacados).
export const dark = {
  bg:         'oklch(98% 0.006 75)',    // fondo de pantalla (igual al body)
  surface:    'oklch(99.5% 0.003 75)',  // tarjetas / superficies
  surfaceAlt: 'oklch(96.5% 0.008 75)',  // cabeceras de sección / filas alternas
  border:     'oklch(90% 0.012 75)',    // bordes suaves
  ink:        'oklch(25% 0.01 60)',     // texto principal (oscuro)
  inkMuted:   'oklch(45% 0.012 60)',    // texto secundario
  inkSubtle:  'oklch(62% 0.012 60)',    // texto terciario / placeholders
  amber:      'oklch(56% 0.14 65)',     // acento ámbar (texto/icono)
  amberDim:   'oklch(72% 0.11 68)',     // ámbar suave (bordes/subtexto)
  green:      'oklch(50% 0.13 155)',    // acento verde
  greenDim:   'oklch(68% 0.12 155)',    // verde suave
  danger:     'oklch(54% 0.18 25)',     // acento rojo
  dangerDim:  'oklch(70% 0.15 25)',     // rojo suave
  // Fondos de acento (tints claros) para badges y paneles destacados
  greenTint:  'oklch(94% 0.04 155)',
  amberTint:  'oklch(95% 0.045 70)',
  dangerTint: 'oklch(95% 0.04 25)',
}
