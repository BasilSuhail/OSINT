import { create } from "zustand"

/** What the reader asked about (#862).
 *
 * Two ways in, carrying different things. From the map it is a point, and the
 * country arrives with the server's answer — which may legitimately be
 * nothing, because open water is a real place to right-click. From the country
 * chip inside an event it is a code with no point at all, and that screen
 * shows every text block and no photograph rather than inventing a coordinate
 * from a centroid.
 */
export interface PlaceTarget {
  lat?: number
  lon?: number
  iso?: string
}

interface PlaceState {
  target: PlaceTarget | null
  openPoint: (lat: number, lon: number) => void
  openCountry: (iso: string) => void
  close: () => void
}

export const usePlaceStore = create<PlaceState>((set) => ({
  target: null,
  openPoint: (lat, lon) => set({ target: { lat, lon } }),
  openCountry: (iso) => set({ target: { iso } }),
  close: () => set({ target: null }),
}))
