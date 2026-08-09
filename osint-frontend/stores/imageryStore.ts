import { create } from "zustand"

/** Which satellite backdrop is drawn under the markers (#875).
 *
 * One at a time, and off by default. Two rasters stacked on a dark style is
 * mud, and the map's current appearance is not being renegotiated as a side
 * effect of adding an option.
 *
 * `missing` records that the publisher had no tiles for the day being shown.
 * Gaps are normal — whole days are absent from an archive that otherwise goes
 * back years — and a blank backdrop with no explanation reads as a broken map.
 */
interface ImageryState {
  active: string | null
  missing: boolean
  toggle: (id: string) => void
  setMissing: (missing: boolean) => void
}

export const useImageryStore = create<ImageryState>((set) => ({
  active: null,
  missing: false,
  //: Selecting the layer already shown turns it off, so the control is its own
  //: undo and there is no separate "none" to hunt for.
  toggle: (id) => set((s) => ({ active: s.active === id ? null : id, missing: false })),
  setMissing: (missing) => set({ missing }),
}))
