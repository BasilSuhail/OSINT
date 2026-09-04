import { readFileSync } from "node:fs"
import { describe, expect, it } from "vitest"

function source(path: string): string {
  return readFileSync(new URL(`../${path}`, import.meta.url), "utf8")
}

describe("installed mobile app shell", () => {
  it("uses WebKit's full standalone height without changing browser-tab height", () => {
    const css = source("app/globals.css")
    const layout = source("components/SplitLayout.tsx")

    expect(css).toContain(".console-viewport {\n  height: 100dvh;")
    expect(css).toContain("@media (display-mode: standalone)")
    expect(css).toContain(".console-viewport {\n    height: 100vh;")
    expect(layout).toContain('className="console-viewport relative')
  })

  it("centres both console edge handles against the same full screen", () => {
    const rail = source("components/FilterRail.tsx")

    expect(rail).toContain('narrow ? "inset-y-0" : "bottom-3"')
  })

  it("reserves a top rail for the standalone News status area", () => {
    const news = source("app/news/page.tsx")

    expect(news).toContain("pt-[env(safe-area-inset-top)]")
  })
})
