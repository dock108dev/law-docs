import { defineConfig } from "vitest/config";
export default defineConfig({
  test: {
    environment: "jsdom",
    include: ["tests/web/*.test.js"],
    coverage: {
      provider: "v8",
      include: ["web/app.js"],
      reporter: ["text", "json", "html"],
      thresholds: { lines: 80, branches: 80, functions: 80, statements: 80 },
    },
  },
});
