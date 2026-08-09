import { afterEach, describe, expect, it, vi } from "vitest"
import { API_TIMEOUT_MS, ASK_TIMEOUT_MS, STREAM_IDLE_TIMEOUT_MS, streamBrainAsk } from "./apiClient"

afterEach(() => vi.restoreAllMocks())

const sse = (event: string, data: unknown) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`

const FINAL = {
  answer: "Netanyahu rejected it.",
  sources: [],
  closest_matches: [],
  claims: [],
  reasoning: null,
}

/** An answer that arrives in pieces, each after `gapMs` of silence.
 *
 * This is the shape of the real endpoint: retrieval lands almost immediately,
 * then the model thinks for a long time before the first token. Measured
 * against the live stack, `sources` arrived at 1.4s and the first `delta` at
 * 17.8s — a generation working perfectly that simply takes a while. */
function streamingResponse(blocks: string[], gapMs: number) {
  return (_input: string, init: RequestInit = {}) => {
    const body = new ReadableStream<Uint8Array>({
      async start(controller) {
        const encoder = new TextEncoder()
        for (const block of blocks) {
          await new Promise((resolve) => setTimeout(resolve, gapMs))
          if (init.signal?.aborted) {
            controller.error(Object.assign(new Error("aborted"), { name: "AbortError" }))
            return
          }
          controller.enqueue(encoder.encode(block))
        }
        controller.close()
      },
    })
    return Promise.resolve(new Response(body, { status: 200 }))
  }
}

/** Headers returned, then nothing ever again — a generation that died. */
function silentAfterHeaders() {
  return (_input: string, init: RequestInit = {}) => {
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        init.signal?.addEventListener("abort", () =>
          controller.error(Object.assign(new Error("aborted"), { name: "AbortError" })),
        )
      },
    })
    return Promise.resolve(new Response(body, { status: 200 }))
  }
}

describe("an ask that is slow but alive", () => {
  it("is judged on silence, not on how long the whole answer takes", async () => {
    // The guard has to be an idle window rather than a total budget. Written
    // as a total, this fails: six chunks 20ms apart outlive any 30ms deadline,
    // while never once going quiet for 30ms. The model's overall pace is not
    // the client's to predict; only its having stopped is knowable.
    const blocks = [
      sse("sources", { sources: [], context_digest: null }),
      sse("delta", { text: "Netanyahu " }),
      sse("delta", { text: "rejected " }),
      sse("delta", { text: "it." }),
      sse("final", FINAL),
    ]
    vi.stubGlobal("fetch", vi.fn(streamingResponse(blocks, 20)))

    const result = await streamBrainAsk("what were the 15 points?", {}, [], { idleMs: 30 })

    expect(result.answer).toBe("Netanyahu rejected it.")
  })

  it("hands the reader every chunk along the way", async () => {
    const blocks = [
      sse("sources", { sources: [{ id: 1, title: "Al Jazeera" }], context_digest: "abc" }),
      sse("delta", { text: "one " }),
      sse("delta", { text: "two" }),
      sse("final", FINAL),
    ]
    vi.stubGlobal("fetch", vi.fn(streamingResponse(blocks, 20)))
    const sources: unknown[] = []
    const deltas: string[] = []

    await streamBrainAsk(
      "q",
      { onSources: (s) => sources.push(s), onDelta: (t) => deltas.push(t) },
      [],
      { idleMs: 30 },
    )

    expect(sources).toHaveLength(1)
    expect(deltas).toEqual(["one ", "two"])
  })
})

describe("an ask that has genuinely stopped", () => {
  it("gives up once nothing has arrived for the idle window", async () => {
    // #839's protection has to survive the fix: a stream that stalls must
    // still fail rather than spin forever.
    vi.stubGlobal("fetch", vi.fn(silentAfterHeaders()))

    await expect(streamBrainAsk("q", {}, [], { idleMs: 30 })).rejects.toThrow()
  })

  it("does so quickly enough that the panel can show a failure", async () => {
    vi.stubGlobal("fetch", vi.fn(silentAfterHeaders()))
    const started = Date.now()

    await streamBrainAsk("q", {}, [], { idleMs: 30 }).catch(() => undefined)

    expect(Date.now() - started).toBeLessThan(2000)
  })
})

describe("the budgets", () => {
  it("gives inference its own, longer than a page load's", () => {
    // A page of panels and a local model answering a question are not the
    // same kind of wait, and one number cannot serve both. Measured on the
    // live stack, a non-streamed ask took 24s against a 15s page budget.
    expect(ASK_TIMEOUT_MS).toBeGreaterThan(API_TIMEOUT_MS)
  })

  it("bounds the idle window rather than waiting forever", () => {
    expect(STREAM_IDLE_TIMEOUT_MS).toBeGreaterThanOrEqual(10_000)
    expect(STREAM_IDLE_TIMEOUT_MS).toBeLessThanOrEqual(120_000)
  })
})
