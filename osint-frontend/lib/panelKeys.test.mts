import { describe, expect, it } from "vitest"
import { panelForKey } from "./panelKeys"

describe("panelForKey", () => {
  it("maps WASD onto the edge each key points at", () => {
    expect(panelForKey("w")).toBe("top")
    expect(panelForKey("a")).toBe("left")
    expect(panelForKey("s")).toBe("bottom")
    expect(panelForKey("d")).toBe("right")
  })

  it("keeps the bracket keys the console shipped with", () => {
    expect(panelForKey("[")).toBe("right")
    expect(panelForKey("]")).toBe("left")
  })

  it("treats a held shift as the same gesture", () => {
    expect(panelForKey("W")).toBe("top")
    expect(panelForKey("D")).toBe("right")
  })

  it("declines keys that belong to somebody else", () => {
    expect(panelForKey("q")).toBeNull()
    expect(panelForKey(" ")).toBeNull()
    expect(panelForKey("Escape")).toBeNull()
  })

  it("declines a modified key, which is another shortcut", () => {
    expect(panelForKey("s", { meta: true })).toBeNull()
    expect(panelForKey("a", { ctrl: true })).toBeNull()
    expect(panelForKey("d", { alt: true })).toBeNull()
  })
})
