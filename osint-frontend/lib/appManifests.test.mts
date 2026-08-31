import { describe, expect, it } from "vitest"

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
})
