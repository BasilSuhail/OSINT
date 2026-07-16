import { describe, expect, it, vi, afterEach } from "vitest"
import { fetchBrainAsk, streamBrainAsk } from "./apiClient"

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
    expect(JSON.parse(init.body)).toEqual({ question: "what is loudest?", history: [] })
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

  it("streams deltas and returns final answer", async () => {
    const encoder = new TextEncoder()
    const body = new ReadableStream({
      start(controller) {
        controller.enqueue(
          encoder.encode(
            [
              'event: sources\ndata: {"context_digest":"sha256:a","sources":[]}\n\n',
              'event: delta\ndata: {"text":"Border "}\n\n',
              'event: delta\ndata: {"text":"clashes"}\n\n',
              'event: final\ndata: {"answer":"Border clashes [1].","context_digest":"sha256:a","sources":[]}\n\n',
            ].join(""),
          ),
        )
        controller.close()
      },
    })
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        body,
      })),
    )
    const chunks: string[] = []
    const out = await streamBrainAsk("q", { onDelta: (text) => chunks.push(text) })

    expect(chunks.join("")).toBe("Border clashes")
    expect(out.answer).toBe("Border clashes [1].")
  })
})
