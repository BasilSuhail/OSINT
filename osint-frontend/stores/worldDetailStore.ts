import { create } from "zustand"

/** The world detail side panel (#705).
 *
 *  Clicking the world tile's graph used to expand the deck over the page.
 *  Clicking a story on the situation tile opens a panel *beside* it. Same
 *  gesture, same kind of target, two different shapes — so the graph now opens
 *  a panel too, in the same slot the story detail already uses.
 *
 *  One rule: a click on a tile puts what you asked for next to what you were
 *  looking at, never on top of it. Map clicks are the other rule — those open a
 *  third tile and the deck moves to it.
 */
interface WorldDetailState {
  open: boolean
  openWorld: () => void
  closeWorld: () => void
}

export const useWorldDetailStore = create<WorldDetailState>((set) => ({
  open: false,
  openWorld: () => set({ open: true }),
  closeWorld: () => set({ open: false }),
}))
