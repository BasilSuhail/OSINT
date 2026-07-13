import { describe, expect, it, vi, afterEach } from "vitest"
import { fetchBrainAsk } from "./apiClient"

afterEach(() => vi.restoreAllMocks())

describe("fetchBrainAsk", () => {
  it("posts the question and returns the answer", async () => {
    const spy = vi.fn(async () => ({
      ok: true,
      json: async () => ({ answer: "Border clashes.", context_digest: "sha256:a" }),
    }))
    vi.stubGlobal("fetch", spy)
    const out = await fetchBrainAsk("what is loudest?")
    expect(out.answer).toBe("Border clashes.")
    const [, init] = spy.mock.calls[0]
    expect(init.method).toBe("POST")
    expect(JSON.parse(init.body)).toEqual({ question: "what is loudest?" })
  })
})
