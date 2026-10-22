import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  timeout: 45000,
  workers: 1,
  use: {
    baseURL: process.env.FROMTHECRAFT_TEST_URL ?? "http://127.0.0.1:8765",
    viewport: { width: 1366, height: 768 },
    headless: true,
    launchOptions: {
      args: [
        "--use-gl=angle",
        "--use-angle=swiftshader",
        "--enable-unsafe-swiftshader",
      ],
    },
  },
  reporter: "list",
});
