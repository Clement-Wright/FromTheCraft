import { test, expect } from "@playwright/test";
import { createHash } from "node:crypto";

test("real detailed ship exports and displays local Minecraft and FtD textures", async ({
  page,
}) => {
  test.skip(
    !process.env.FROMTHECRAFT_PAINTED_SHIP ||
      !process.env.FROMTHECRAFT_TEXTURE_JAR,
    "Local owner ship and client JAR required",
  );
  test.setTimeout(180000);
  const errors: string[] = [];
  const imageResponses: number[] = [];
  page.on("response", (response) => {
    if (response.url().includes("/api/textures/"))
      imageResponses.push(response.status());
  });
  page.on("pageerror", (error) => errors.push(error.message));
  await page.setViewportSize({ width: 1800, height: 1000 });
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Open file", exact: true }),
  ).toBeEnabled();
  await page
    .getByLabel("Open structure file")
    .setInputFiles(process.env.FROMTHECRAFT_PAINTED_SHIP!);
  await expect(page.getByRole("status")).toHaveText(/Source ready/, {
    timeout: 30000,
  });
  await page.locator(".mod-picker summary").click();
  await page
    .getByRole("checkbox", { name: "Create: Copycats+", exact: true })
    .check();
  await page.getByLabel("Detailed Copycats", { exact: true }).check();
  await page.getByRole("button", { name: "Convert", exact: true }).click();
  await expect(page.getByRole("status")).toHaveText(/ready to export/, {
    timeout: 90000,
  });
  const before = await page.request.get("/api/status").then((r) => r.json());
  expect(
    before.converted.materials.some(
      (row: { name: string }) =>
        row.name.includes("half_layer") || row.name.includes("slice"),
    ),
  ).toBe(true);
  const exported = await page.request.get(
    "/api/export?result_id=" + before.result_id,
  );
  expect(
    createHash("sha256")
      .update(await exported.body())
      .digest("hex"),
  ).toBe(before.sha256);
  const flat = await page
    .getByLabel("Converted 3D structural preview")
    .screenshot();
  await page
    .getByLabel("Load texture archive")
    .setInputFiles(process.env.FROMTHECRAFT_TEXTURE_JAR!);
  await expect(
    page.getByLabel("Display textures", { exact: true }),
  ).toBeChecked({ timeout: 30000 });
  await expect(page.locator(".texture-status summary")).toContainText(
    "Minecraft available; FtD available",
  );
  const refreshed = await page.request.get("/api/status").then((r) => r.json());
  console.log(
    "Textured block records",
    refreshed.converted.blocks.filter(
      (block: { textures?: object }) => block.textures,
    ).length,
  );
  await page.screenshot({
    path: "../artifacts/v040-texture-load.png",
    fullPage: true,
  });
  await expect
    .poll(
      async () =>
        !(
          await page.getByLabel("Converted 3D structural preview").screenshot()
        ).equals(flat),
      { timeout: 30000 },
    )
    .toBe(true);
  await expect(page.getByRole("button", { name: "Export file" })).toBeEnabled();
  const after = await page.request.get("/api/status").then((r) => r.json());
  expect(after.sha256).toBe(before.sha256);
  expect(after.result_id).toBe(before.result_id);
  expect(
    after.converted.blocks.some(
      (block: { textures?: object }) => block.textures,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "../artifacts/v040-detailed-textures.png",
    fullPage: true,
  });
  expect(imageResponses.length).toBeGreaterThan(0);
  expect(imageResponses.every((status) => status === 200)).toBe(true);
  expect(errors).toEqual([]);
});
