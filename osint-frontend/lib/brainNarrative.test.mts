import { describe, expect, it, vi, afterEach } from "vitest"
import { fetchBrainNarrative } from "./apiClient"

afterEach(() => vi.restoreAllMocks())

describe("fetchBrainNarrative", () => {
  it("returns the parsed narrative", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        json: async () => ({
          present: true,
          payload: { headline: "quiet", watch: [] },
          model: "qwen2.5:1.5b-instruct-q4_K_M",
          created_at: "2026-07-12T12:00:00+00:00",
        }),
      })),
    )
    const out = await fetchBrainNarrative()
    expect(out.present).toBe(true)
    expect(out.payload?.headline).toBe("quiet")
  })
})
