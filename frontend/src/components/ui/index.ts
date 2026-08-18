// Sistema de diseño — barrel de componentes base.
// Importá desde aquí: import { Card, StatTile, Sheet } from '@/components/ui'

export { default as Card } from './Card'
export type { CardProps } from './Card'

export { default as StatTile } from './StatTile'
export type { StatTileProps, StatTint } from './StatTile'

export { default as SectionLabel } from './SectionLabel'
export type { SectionLabelProps } from './SectionLabel'

export { default as Pill } from './Pill'
export type { PillProps, Tone } from './Pill'

export { default as Badge } from './Badge'
export type { BadgeProps } from './Badge'

export { default as MoneyInput } from './MoneyInput'

export { default as Stepper } from './Stepper'
export type { StepperProps } from './Stepper'

export { default as Sheet } from './Sheet'
export type { SheetProps } from './Sheet'

export { default as Toast } from './Toast'
export type { ToastProps, ToastTone } from './Toast'

// Carga · vacío · error: la convención de la casa. Ver README.
export { SegunDato, NoSeSabe } from './SegunDato'
export type { SegunDatoProps, NoSeSabeProps } from './SegunDato'

export { default as FranjaDeConfianza } from './FranjaDeConfianza'
export type { FranjaDeConfianzaProps } from './FranjaDeConfianza'
