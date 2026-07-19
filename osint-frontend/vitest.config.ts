import { defineConfig } from "vitest/config"
import path from "node:path"

export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "."),
    },
  },
  test: {
    // Globs, not an enumerated list: naming each suite by hand meant a new
    // one silently ran nowhere until someone remembered to add it, which is
    // how lib/systemHealth.test.mts went unexecuted entirely (#505).
    include: ["__tests__/**/*.test.ts", "lib/**/*.test.mts"],
    environment: "node",
    globals: false,
  },
})
