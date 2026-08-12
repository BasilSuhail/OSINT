import { create } from "zustand"

import type { PanelSide } from "@/lib/panelKeys"

/** What is on screen at each of the four edges (#938).
 *
 *  These four booleans used to live in three different places: two `useState`
 *  hooks in the layout, and one inside the scrubber where nothing outside it
 *  could reach. That was fine while each panel had its own handle and nothing
 *  else touched it. One keymap that toggles all four needs one place to ask.
 *
 *  Deliberately only what is showing — not what the console is doing. Hiding
 *  the scrubber does not pause playback, and collapsing the omnibox does not
 *  clear what was asked; both of those live in their own stores, so putting a
 *  panel away is always safe.
 */
interface PanelLayoutState {
  /** The omnibox's result dropdown. The bar itself is always on screen. */
  top: boolean
  /** The card deck — world, situation, the analytical pages. */
  left: boolean
  /** The time scrubber's strip along the map's bottom edge. */
  bottom: boolean
  /** The map's filter rail, which is also its legend. */
  right: boolean
  /** Whether the reader is in the middle of a search — something typed, or a
   *  result open. The search results and the deck share the left column, so
   *  this is what decides which of the two is in it. Not a panel: the reader
   *  never toggles it, it follows from whether there is a query. */
  searchActive: boolean
  toggle: (side: PanelSide) => void
  setPanel: (side: PanelSide, open: boolean) => void
  setSearchActive: (active: boolean) => void
}

export const usePanelLayoutStore = create<PanelLayoutState>((set) => ({
  //: Open on arrival, but empty until something is typed — this says the
  //: results list is not collapsed, not that there is a list.
  top: true,
  left: true,
  bottom: true,
  //: Open on arrival. The filter panel is the map's legend as much as its
  //: controls — what each colour is, and how many of it there are.
  right: true,
  searchActive: false,
  toggle: (side) => set((s) => ({ [side]: !s[side] }) as Pick<PanelLayoutState, PanelSide>),
  setPanel: (side, open) => set({ [side]: open } as Pick<PanelLayoutState, PanelSide>),
  setSearchActive: (active) => set({ searchActive: active }),
}))
