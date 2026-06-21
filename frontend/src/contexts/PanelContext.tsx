import { createContext, useContext } from 'react'

/**
 * Signals whether a screen is rendered INSIDE the POS side-panel (embedded)
 * versus as a standalone route. Embedded screens must:
 *  - not paint their own min-h-screen / sticky header (the panel host frames them)
 *  - not cap width with max-w-lg (they fill the panel column)
 *  - scope overlays/CTAs to the panel (absolute/sticky) instead of the viewport (fixed)
 *
 * This keeps the POS visible behind tool panels — the barista never loses the POS.
 */
interface PanelCtx {
  embedded: boolean
}

const PanelContext = createContext<PanelCtx>({ embedded: false })

export function PanelProvider({ children }: { children: React.ReactNode }) {
  return <PanelContext.Provider value={{ embedded: true }}>{children}</PanelContext.Provider>
}

export function useEmbedded(): boolean {
  return useContext(PanelContext).embedded
}
