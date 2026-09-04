import { describe, expect, it } from "vitest"
import { readFileSync } from "node:fs"

import { consoleManifest, newsManifest } from "./appManifests"

describe("installable app manifests", () => {
  it("gives the console and News separate installed identities", () => {
    expect(consoleManifest.id).toBe("/")
    expect(consoleManifest.start_url).toBe("/")
    expect(newsManifest.id).toBe("/news")
    expect(newsManifest.start_url).toBe("/news")
    expect(newsManifest.scope).toBe("/news")
  })

  it.each([consoleManifest, newsManifest])("launches standalone with complete PNG icons", (app) => {
    expect(app.display).toBe("standalone")
    expect(app.icons).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ sizes: "192x192", type: "image/png", purpose: "any" }),
        expect.objectContaining({ sizes: "512x512", type: "image/png", purpose: "any" }),
        expect.objectContaining({ sizes: "512x512", type: "image/png", purpose: "maskable" }),
      ]),
    )
  })

  it("uses a plain O for both app identities and keeps News lines separate", () => {
    const consoleIcon = readFileSync(new URL("../icons-src/osint.svg", import.meta.url), "utf8")
    const newsIcon = readFileSync(new URL("../icons-src/news.svg", import.meta.url), "utf8")

    expect(consoleIcon).toContain('<ellipse cx="90" cy="90"')
    expect(consoleIcon).not.toContain("<path")
    expect(newsIcon).toContain('<ellipse cx="90" cy="68"')
    expect(newsIcon).toContain('fill="#67e8f9"')
    expect(newsIcon).not.toContain("<path")
  })
})
