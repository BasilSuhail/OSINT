import { create } from "zustand"

/** Which hazard the map is isolating, if any.
 *
 *  Hazards overlap. A quake's intensity rings sit on top of a neighbouring
 *  quake's rings, a flood extent, a fire scar — and once the reader has picked
 *  one out of that pile, the rest of the geometry is noise drawn over the thing
 *  they asked about. Focus is the answer: the clicked hazard keeps its
 *  footprint, everything else fades and drops its lines.
 *
 *  Deliberately separate from the selection. Selection is *what the reader is
 *  reading* and no keypress takes it away (#844); focus is only *how the map is
 *  drawn*, so Escape can undo it while the detail card stays open.
 */
interface MapFocusState {
  focusedEventId: string | null
  focus: (id: string) => void
  clearFocus: () => void
}

export const useMapFocusStore = create<MapFocusState>((set) => ({
  focusedEventId: null,
  focus: (id) => set({ focusedEventId: id }),
  clearFocus: () => set({ focusedEventId: null }),
}))
