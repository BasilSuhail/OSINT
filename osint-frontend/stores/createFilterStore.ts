import { create, type StoreApi, type UseBoundStore } from "zustand"
import { HAZARD_TYPE_FILTERS, type HazardTypeKey, type SourceKey } from "@/lib/types"

export interface FilterState {
  /** Enabled source toggles. */
  sources: Record<SourceKey, boolean>
  /** Enabled disaster-type toggles (earthquake / cyclone / flood / …). Hazard
   *  events are filtered by these instead of by their lump-sum source. */
  hazardTypes: Record<HazardTypeKey, boolean>
  severity: [number, number]
  countries: string[]
  keyword: string
  /** Time scrubber: offset (ms) of the *end* of the visible window from "now".
   *  0 = window ends now. Positive = window ends in the past. */
  windowEndOffsetMs: number
  /** Visible window length in ms (fixed at 30 days span control, default 3 days view). */
  windowLengthMs: number
  playing: boolean
  speed: number
  /** Render live satellite orbits on the globe pane. Ignored on the map pane. */
  showSatellites: boolean
  /** Which CelesTrak group to load: "stations" (~20), "visual" (~250), "active" (~10k), etc. */
  satelliteGroup: string
  /** Render Sun + Moon (sub-stellar points) on the globe pane. Ignored on the map pane. */
  showCelestial: boolean

  toggleSource: (key: SourceKey) => void
  /** Turn every source on (select all) or off (clear all) at once. */
  setAllSources: (on: boolean) => void
  toggleHazardType: (key: HazardTypeKey) => void
  setAllHazardTypes: (on: boolean) => void
  setSeverity: (range: [number, number]) => void
  setCountries: (countries: string[]) => void
  toggleCountry: (country: string) => void
  setKeyword: (kw: string) => void
  setWindowEndOffset: (ms: number) => void
  setPlaying: (playing: boolean) => void
  togglePlaying: () => void
  setSpeed: (speed: number) => void
  toggleSatellites: () => void
  setSatelliteGroup: (group: string) => void
  toggleCelestial: () => void
  reset: () => void
}

const THIRTY_DAYS = 30 * 24 * 60 * 60 * 1000
const DEFAULT_WINDOW = 3 * 24 * 60 * 60 * 1000

const defaultSources: Record<SourceKey, boolean> = {
  GDELT: true,
  yfinance: true,
  FRED: true,
  USGS: true,
  GDACS: true,
  FIRMS: true,
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
    countries: [],
    keyword: "",
    windowEndOffsetMs: 0,
    windowLengthMs: DEFAULT_WINDOW,
    playing: false,
    speed: 1,
    showSatellites: true,
    satelliteGroup: "visual",
    showCelestial: true,

    toggleSource: (key) =>
      set((s) => ({ sources: { ...s.sources, [key]: !s.sources[key] } })),
    setAllSources: (on) =>
      set((s) => {
        const next = { ...s.sources }
        for (const k of Object.keys(next) as SourceKey[]) next[k] = on
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
    setCountries: (countries) => set({ countries }),
    toggleCountry: (country) =>
      set((s) => ({
        countries: s.countries.includes(country)
          ? s.countries.filter((c) => c !== country)
          : [...s.countries, country],
      })),
    setKeyword: (keyword) => set({ keyword }),
    setWindowEndOffset: (ms) =>
      set({ windowEndOffsetMs: Math.max(0, Math.min(THIRTY_DAYS, ms)) }),
    setPlaying: (playing) => set({ playing }),
    togglePlaying: () => set((s) => ({ playing: !s.playing })),
    setSpeed: (speed) => set({ speed }),
    toggleSatellites: () => set((s) => ({ showSatellites: !s.showSatellites })),
    setSatelliteGroup: (satelliteGroup) => set({ satelliteGroup }),
    toggleCelestial: () => set((s) => ({ showCelestial: !s.showCelestial })),
    reset: () =>
      set({
        sources: { ...defaultSources },
        hazardTypes: { ...defaultHazardTypes },
        severity: [0, 1],
        countries: [],
        keyword: "",
        windowEndOffsetMs: 0,
        playing: false,
        speed: 1,
        showSatellites: true,
        satelliteGroup: "visual",
        showCelestial: true,
      }),
  }))
}

export const WINDOW_SPAN_MS = THIRTY_DAYS
