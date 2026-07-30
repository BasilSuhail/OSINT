import { create } from "zustand"

/** Whether the deck covers the page (#699).
 *
 *  The expand state used to live inside CardDeck, which meant only its own
 *  chrome could open it. The world card's headline is a door — clicking the
 *  graph is meant to open the country detail and coverage underneath it — so
 *  the state has to be reachable from the card's own content.
 *
 *  Kept deliberately small: one boolean and two verbs. Anything richer would
 *  start competing with the deck's own paging.
 */
interface DeckExpandState {
  expanded: boolean
  setExpanded: (v: boolean) => void
  toggleExpanded: () => void
}

export const useDeckExpandStore = create<DeckExpandState>((set) => ({
  expanded: false,
  setExpanded: (v) => set({ expanded: v }),
  toggleExpanded: () => set((s) => ({ expanded: !s.expanded })),
}))
