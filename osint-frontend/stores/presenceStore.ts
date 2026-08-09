import { create } from "zustand"

/** Which live layers are drawn (#873).
 *
 * Presence is not evidence: these aircraft are where something is right now,
 * never stored and never citable. Off by default, because the map's ordinary
 * appearance is not renegotiated by adding an option.
 */
interface PresenceState {
  aircraft: boolean
  toggleAircraft: () => void
}

export const usePresenceStore = create<PresenceState>((set) => ({
  aircraft: false,
  toggleAircraft: () => set((s) => ({ aircraft: !s.aircraft })),
}))
