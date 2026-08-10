import { create, type StoreApi, type UseBoundStore } from "zustand"
import { HAZARD_TYPE_FILTERS, type HazardTypeKey, type SourceKey } from "@/lib/types"

export interface FilterState {
  /** Enabled source toggles. */
  sources: Record<SourceKey, boolean>
  /** Enabled disaster-type toggles (earthquake / cyclone / flood / …). Hazard
   *  events are filtered by these instead of by their lump-sum source. */
  hazardTypes: Record<HazardTypeKey, boolean>
  severity: [number, number]
  /** Time scrubber: offset (ms) of the *end* of the visible window from "now".
   *  0 = window ends now. Positive = window ends in the past. */
  windowEndOffsetMs: number
  /** Visible window length in ms (fixed at 30 days span control, default 3 days view). */
  windowLengthMs: number
  playing: boolean
  speed: number

  toggleSource: (key: SourceKey) => void
  /** Turn sources on (select all) or off (clear all) at once. `keys` scopes it
   *  to the rows a section actually lists: the hazard sources are filtered by
   *  disaster type in their own section, and an unscoped "none" switched them
   *  off from a list that never showed them — the disaster rows stayed ticked
   *  while their events left the map. */
  setAllSources: (on: boolean, keys?: SourceKey[]) => void
  toggleHazardType: (key: HazardTypeKey) => void
  setAllHazardTypes: (on: boolean) => void
  setSeverity: (range: [number, number]) => void
  setWindowEndOffset: (ms: number) => void
  setPlaying: (playing: boolean) => void
  togglePlaying: () => void
  setSpeed: (speed: number) => void
  reset: () => void
}

const THIRTY_DAYS = 30 * 24 * 60 * 60 * 1000
const DEFAULT_WINDOW = 3 * 24 * 60 * 60 * 1000

const defaultSources: Record<SourceKey, boolean> = {
  GDELT: true,
  ACLED: true,
  EMDAT: true,
  yfinance: true,
  FRED: true,
  USGS: true,
  GDACS: true,
  EONET: true,
  NEWS: true,
  CYBER: true,
  POLYMARKET: true,
}

const defaultHazardTypes = Object.fromEntries(
  HAZARD_TYPE_FILTERS.map((h) => [h.key, true]),
) as Record<HazardTypeKey, boolean>

export type FilterStore = UseBoundStore<StoreApi<FilterState>>

export function createFilterStore(): FilterStore {
  return create<FilterState>((set) => ({
    sources: { ...defaultSources },
    hazardTypes: { ...defaultHazardTypes },
    severity: [0, 1],
    windowEndOffsetMs: 0,
    windowLengthMs: DEFAULT_WINDOW,
    playing: false,
    speed: 1,

    toggleSource: (key) =>
      set((s) => ({ sources: { ...s.sources, [key]: !s.sources[key] } })),
    setAllSources: (on, keys) =>
      set((s) => {
        const next = { ...s.sources }
        for (const k of keys ?? (Object.keys(next) as SourceKey[])) next[k] = on
        return { sources: next }
      }),
    toggleHazardType: (key) =>
      set((s) => ({ hazardTypes: { ...s.hazardTypes, [key]: !s.hazardTypes[key] } })),
    setAllHazardTypes: (on) =>
      set((s) => {
        const next = { ...s.hazardTypes }
        for (const k of Object.keys(next) as HazardTypeKey[]) next[k] = on
        return { hazardTypes: next }
      }),
    setSeverity: (range) => set({ severity: range }),
    setWindowEndOffset: (ms) =>
      set({ windowEndOffsetMs: Math.max(0, Math.min(THIRTY_DAYS, ms)) }),
    setPlaying: (playing) => set({ playing }),
    togglePlaying: () => set((s) => ({ playing: !s.playing })),
    setSpeed: (speed) => set({ speed }),
    reset: () =>
      set({
        sources: { ...defaultSources },
        hazardTypes: { ...defaultHazardTypes },
        severity: [0, 1],
        windowEndOffsetMs: 0,
        playing: false,
        speed: 1,
      }),
  }))
}

export const WINDOW_SPAN_MS = THIRTY_DAYS

/** The window length that counts as the normal live view. Exported so the
 *  status bar can tell a default window from a widened one (#501). */
export const DEFAULT_WINDOW_MS = DEFAULT_WINDOW
