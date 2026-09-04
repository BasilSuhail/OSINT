import { describe, expect, it } from "vitest"

import nextConfig from "../next.config.mjs"

describe("same-origin API proxy", () => {
  it("keeps a slow Pi stream open through first token", () => {
    expect(nextConfig.experimental?.proxyTimeout).toBe(600_000)
  })

  it("forwards the browser API namespace to the local backend", async () => {
    const rewrites = await nextConfig.rewrites?.()
    expect(rewrites).toContainEqual({
      source: "/api/:path*",
      destination: "http://127.0.0.1:8000/:path*",
    })
  })
})
