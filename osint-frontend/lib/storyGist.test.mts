import { describe, expect, it, vi, afterEach } from "vitest"
import { fetchTopStories } from "./analytics"

afterEach(() => vi.restoreAllMocks())

describe("fetchTopStories carries gist fields", () => {
  it("parses gist/category/escalating", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        json: async () => [
          {
            id: "1", title: "Border clashes", first_seen: "x", last_seen: "y",
            member_count: 2, outlet_count: 2, owner_count: 1, corroboration: null,
            corroboration_components: null, sensor_checks: {}, method_version: "stories-v1.0",
            gist: "Clashes at the frontier.", category: "conflict", escalating: "yes",
          },
        ],
      })),
    )
    const rows = await fetchTopStories(24, 10)
    expect(rows[0].gist).toBe("Clashes at the frontier.")
    expect(rows[0].category).toBe("conflict")
  })
})
