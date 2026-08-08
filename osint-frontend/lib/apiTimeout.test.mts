import { afterEach, describe, expect, it, vi } from "vitest"
import { API_TIMEOUT_MS, apiFetch } from "./apiClient"

afterEach(() => vi.restoreAllMocks())

/** A server that accepted the connection and will never answer — exactly what
 *  a bound socket with no worker behind it looks like (#839). */
const neverAnswers = () =>
  vi.fn((_input: string, init: RequestInit = {}) =>
    new Promise<Response>((_resolve, reject) => {
      init.signal?.addEventListener("abort", () =>
        reject(Object.assign(new Error("aborted"), { name: "AbortError" })),
      )
    }),
  )

describe("a request that is never answered", () => {
  it("gives up instead of hanging forever", async () => {
    vi.stubGlobal("fetch", neverAnswers())
    await expect(apiFetch("/events", {}, { timeoutMs: 20 })).rejects.toThrow()
  })

  it("does so quickly enough that a panel can show a failure", async () => {
    vi.stubGlobal("fetch", neverAnswers())
    const started = Date.now()
    await apiFetch("/events", {}, { timeoutMs: 20 }).catch(() => undefined)
    expect(Date.now() - started).toBeLessThan(2000)
  })
})

describe("the caller's own cancellation", () => {
  it("still aborts an in-flight request", async () => {
    // A viewport change must cancel its predecessor; the timeout must not
    // take that ability away.
    vi.stubGlobal("fetch", neverAnswers())
    const controller = new AbortController()
    const inFlight = apiFetch("/events", { signal: controller.signal }, { timeoutMs: 10_000 })
    controller.abort()
    await expect(inFlight).rejects.toThrow()
  })

  it("is passed through to fetch alongside the timeout", async () => {
    const spy = vi.fn(async () => new Response("[]"))
    vi.stubGlobal("fetch", spy)
    const controller = new AbortController()
    await apiFetch("/events", { signal: controller.signal })
    const [, init] = spy.mock.calls[0] as [string, RequestInit]
    expect(init.signal).toBeInstanceOf(AbortSignal)
  })
})

describe("the default", () => {
  it("is bounded and generous enough for a wide page", () => {
    // Unbounded is not patience; it is a missing error state. A few seconds
    // is a real page, a quarter of a minute is a dead server.
    expect(API_TIMEOUT_MS).toBeGreaterThanOrEqual(10_000)
    expect(API_TIMEOUT_MS).toBeLessThanOrEqual(30_000)
  })

  it("applies without the caller asking", async () => {
    const spy = vi.fn(async () => new Response("[]"))
    vi.stubGlobal("fetch", spy)
    await apiFetch("/events")
    const [, init] = spy.mock.calls[0] as [string, RequestInit]
    expect(init.signal).toBeInstanceOf(AbortSignal)
  })
})
