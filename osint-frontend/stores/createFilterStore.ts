import { create, type StoreApi, type UseBoundStore } from "zustand"
import type { SourceKey } from "@/lib/types"

export interface FilterState {
  /** Enabled source toggles. */
  sources: Record<SourceKey, boolean>
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

  toggleSource: (key: SourceKey) => void
  setSeverity: (range: [number, number]) => void
  setCountries: (countries: string[]) => void
  toggleCountry: (country: string) => void
  setKeyword: (kw: string) => void
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
  yfinance: true,
  USGS: true,
  GDACS: true,
  FIRMS: true,
}

export type FilterStore = UseBoundStore<StoreApi<FilterState>>

export function createFilterStore(): FilterStore {
  return create<FilterState>((set) => ({
    sources: { ...defaultSources },
    severity: [0, 1],
    countries: [],
    keyword: "",
    windowEndOffsetMs: 0,
    windowLengthMs: DEFAULT_WINDOW,
    playing: false,
    speed: 1,

    toggleSource: (key) =>
      set((s) => ({ sources: { ...s.sources, [key]: !s.sources[key] } })),
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
    reset: () =>
      set({
        sources: { ...defaultSources },
        severity: [0, 1],
        countries: [],
        keyword: "",
        windowEndOffsetMs: 0,
        playing: false,
        speed: 1,
      }),
  }))
}

export const WINDOW_SPAN_MS = THIRTY_DAYS
