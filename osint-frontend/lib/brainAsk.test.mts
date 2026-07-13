import { describe, expect, it, vi, afterEach } from "vitest"
import { fetchBrainAsk } from "./apiClient"

afterEach(() => vi.restoreAllMocks())

describe("fetchBrainAsk", () => {
  it("posts the question and returns the answer", async () => {
    const spy = vi.fn(async () => ({
      ok: true,
      json: async () => ({ answer: "Border clashes.", context_digest: "sha256:a", sources: [] }),
    }))
    vi.stubGlobal("fetch", spy)
    const out = await fetchBrainAsk("what is loudest?")
    expect(out.answer).toBe("Border clashes.")
    const [, init] = spy.mock.calls[0]
    expect(init.method).toBe("POST")
    expect(JSON.parse(init.body)).toEqual({ question: "what is loudest?" })
  })

  it("parses sources", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        json: async () => ({
          answer: "x [1]",
          context_digest: "sha256:a",
          sources: [
            {
              n: 1,
              story_id: 5,
              title: "Border clashes",
              outlets: ["Reuters"],
              corroboration: 0.8,
              contested: false,
            },
          ],
        }),
      })),
    )
    const out = await fetchBrainAsk("q")
    expect(out.sources[0].outlets[0]).toBe("Reuters")
  })
})
