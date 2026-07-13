import { defineConfig } from "vitest/config"
import path from "node:path"

export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "."),
    },
  },
  test: {
    include: [
      "__tests__/**/*.test.ts",
      "lib/apiClient.test.mts",
      "lib/brainNarrative.test.mts",
      "lib/brainAsk.test.mts",
      "lib/storyGist.test.mts",
    ],
    environment: "node",
    globals: false,
  },
})
