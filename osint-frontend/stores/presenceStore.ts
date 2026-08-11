import { create } from "zustand"

/** Which live layers are drawn (#873).
 *
 * Presence is not evidence: these aircraft are where something is right now,
 * never stored and never citable. On by default all the same — every layer the
 * console can draw is drawn until the reader says otherwise, and a layer that
 * arrives switched off is a layer most readers never learn exists. It costs
 * nothing while the tab is hidden or the scrubber has left "now": both stop
 * the poll.
 */
interface PresenceState {
  aircraft: boolean
  toggleAircraft: () => void
}

export const usePresenceStore = create<PresenceState>((set) => ({
  aircraft: true,
  toggleAircraft: () => set((s) => ({ aircraft: !s.aircraft })),
}))
