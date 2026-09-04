import { describe, expect, it } from "vitest"
import { createFilterStore } from "@/stores/createFilterStore"
import { HAZARD_SOURCE_KEYS, SOURCE_FILTERS, type SourceKey } from "@/lib/types"

/** The keys the panel's Layers section actually lists — the hazard sources are
 *  filtered by disaster type in their own section instead. */
const layerKeys: SourceKey[] = SOURCE_FILTERS.filter(
  (f) => !HAZARD_SOURCE_KEYS.includes(f.key),
).map((f) => f.key)

describe("setAllSources", () => {
  it("clears only the keys it is given", () => {
    const store = createFilterStore()
    store.getState().setAllSources(false, layerKeys)
    const { sources } = store.getState()
    for (const k of layerKeys) expect(sources[k]).toBe(false)
    //: The bug this test exists for: a "none" in the Layers section switched
    //: the hazard sources off as well, so the disaster rows stayed ticked
    //: while their events left the map.
    for (const k of HAZARD_SOURCE_KEYS) expect(sources[k]).toBe(true)
  })

  it("restores only the keys it is given", () => {
    const store = createFilterStore()
    store.getState().setAllSources(false)
    store.getState().setAllSources(true, layerKeys)
    const { sources } = store.getState()
    for (const k of layerKeys) expect(sources[k]).toBe(true)
    for (const k of HAZARD_SOURCE_KEYS) expect(sources[k]).toBe(false)
  })

  it("still covers every source when no keys are named", () => {
    const store = createFilterStore()
    store.getState().setAllSources(false)
    expect(Object.values(store.getState().sources).every((on) => !on)).toBe(true)
  })
})

describe("setScrubSpan", () => {
  const DAY = 24 * 60 * 60 * 1000

  it("lets the scrubber reach as far back as the database goes", () => {
    const store = createFilterStore()
    store.getState().setScrubSpan(200 * DAY)
    store.getState().setWindowEndOffset(150 * DAY)
    //: The bug this test exists for: the reach was a 30-day constant, so a
    //: board holding months of history could not be scrubbed into any of it.
    expect(store.getState().windowEndOffsetMs).toBe(150 * DAY)
  })

  it("never shortens a reach that is already longer", () => {
    const store = createFilterStore()
    store.getState().setScrubSpan(200 * DAY)
    store.getState().setScrubSpan(5 * DAY)
    expect(store.getState().scrubSpanMs).toBe(200 * DAY)
  })

  it("keeps the default reach when coverage asks for less", () => {
    const store = createFilterStore()
    store.getState().setScrubSpan(2 * DAY)
    expect(store.getState().scrubSpanMs).toBe(30 * DAY)
  })

  it("still refuses an offset past the current reach", () => {
    const store = createFilterStore()
    store.getState().setWindowEndOffset(90 * DAY)
    expect(store.getState().windowEndOffsetMs).toBe(30 * DAY)
  })
})
