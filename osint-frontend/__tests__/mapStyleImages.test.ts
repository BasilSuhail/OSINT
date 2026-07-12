import { describe, expect, it, vi } from "vitest"
import { addMissingStyleImagePlaceholder } from "@/lib/mapStyleImages"

function fakeMap(existing: string[] = []) {
  const images = new Set(existing)
  return {
    hasImage: (id: string) => images.has(id),
    addImage: vi.fn((id: string) => {
      images.add(id)
    }),
  }
}

describe("addMissingStyleImagePlaceholder", () => {
  it("registers a 1×1 transparent placeholder for a missing sprite id", () => {
    const map = fakeMap()
    const added = addMissingStyleImagePlaceholder(map, "circle-11")
    expect(added).toBe(true)
    expect(map.addImage).toHaveBeenCalledWith("circle-11", {
      width: 1,
      height: 1,
      data: new Uint8Array(4),
    })
  })

  it("is a no-op when the image already exists — no re-add, so no reload loop", () => {
    const map = fakeMap(["circle-11"])
    const added = addMissingStyleImagePlaceholder(map, "circle-11")
    expect(added).toBe(false)
    expect(map.addImage).not.toHaveBeenCalled()
  })

  it("handles the second known-missing id (wood-pattern)", () => {
    const map = fakeMap()
    expect(addMissingStyleImagePlaceholder(map, "wood-pattern")).toBe(true)
    // Same id again → already registered → no-op (event stops firing).
    expect(addMissingStyleImagePlaceholder(map, "wood-pattern")).toBe(false)
    expect(map.addImage).toHaveBeenCalledTimes(1)
  })

  it("ignores an empty / undefined id", () => {
    const map = fakeMap()
    expect(addMissingStyleImagePlaceholder(map, undefined)).toBe(false)
    expect(addMissingStyleImagePlaceholder(map, "")).toBe(false)
    expect(map.addImage).not.toHaveBeenCalled()
  })
})
