import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import type { Display, Status } from "../src/types";

const demo = path.resolve("../examples/demo-hull.blueprint");
const convert = (page: Page) =>
  page.getByRole("button", { name: "Convert", exact: true }).click();
const mod = (page: Page, name: string) =>
  page.getByRole("checkbox", { name, exact: true });

async function open(page: Page, file = demo) {
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Open file", exact: true }),
  ).toBeEnabled();
  await page.getByLabel("Open structure file").setInputFiles(file);
  await expect(page.getByRole("status")).toHaveText(/Source ready/);
}

test("vanilla is the default conversion palette", async ({ page }) => {
  await open(page);
  await expect(page.locator(".mod-picker summary")).toContainText(
    "Vanilla only",
  );
  const request = page.waitForRequest("**/api/convert");
  await convert(page);
  expect((await request).postDataJSON().mods).toEqual([]);
  await expect(page.getByRole("status")).toHaveText(/ready to export/);
  const status = await page.request
    .get("/api/status")
    .then((response) => response.json());
  expect(status.converted.materials.length).toBeGreaterThan(0);
  expect(
    status.converted.materials.every((item: { name: string }) =>
      item.name.startsWith("minecraft:"),
    ),
  ).toBe(true);
});

test("real painted hull exports keep their materials with vanilla and Copycats", async ({
  page,
}) => {
  test.skip(
    !process.env.FROMTHECRAFT_PAINTED_SHIP,
    "Set FROMTHECRAFT_PAINTED_SHIP to the owner's red hull fixture.",
  );
  test.setTimeout(120000);
  await page.setViewportSize({ width: 1800, height: 1000 });
  await open(page, process.env.FROMTHECRAFT_PAINTED_SHIP!);
  await page.getByLabel("Material preference").selectOption("color");
  await convert(page);
  await expect(page.getByRole("status")).toHaveText(/ready to export/, {
    timeout: 60000,
  });
  const vanilla: Status = await page.request
    .get("/api/status")
    .then((response) => response.json());
  const rows = vanilla.converted!.materials;
  expect(
    rows.every((row) =>
      /^minecraft:.*_(concrete|stained_glass)$/.test(row.name),
    ),
  ).toBe(true);
  expect(rows.some((row) => row.name === "minecraft:red_concrete")).toBe(true);
  await page.screenshot({
    path: "../artifacts/painted-hull-vanilla.png",
    fullPage: true,
  });
  await page.locator(".mod-picker summary").click();
  await mod(page, "Create: Copycats+").check();
  await expect(
    page.getByRole("button", { name: "Export file" }),
  ).toBeDisabled();
  await convert(page);
  await expect(page.getByRole("status")).toHaveText(/ready to export/, {
    timeout: 60000,
  });
  const copied: Status = await page.request
    .get("/api/status")
    .then((response) => response.json());
  const shapes = copied.converted!.materials.filter(
    (row) => row.copied_material,
  );
  expect(shapes.length).toBeGreaterThan(0);
  expect(
    shapes.some(
      (row) => row.copied_material!.name === "minecraft:red_concrete",
    ),
  ).toBe(true);
  const expectedCount = (display: Display) =>
    display.materials.reduce((sum, row) => sum + row.count, 0);
  expect(expectedCount(copied.converted!)).toBe(copied.converted!.count);
  expect(copied.converted!.count).toBe(vanilla.converted!.count);
  const download = await page.request.get(
    "/api/export?result_id=" + encodeURIComponent(copied.result_id!),
  );
  const content = await download.body();
  expect(createHash("sha256").update(content).digest("hex")).toBe(
    copied.sha256,
  );
  await page.getByLabel("Search materials").fill("red_concrete");
  await expect(page.getByTestId("material-list")).toContainText(
    "Applied material: minecraft:red_concrete",
  );
  await page.screenshot({
    path: "../artifacts/painted-hull-copycats.png",
    fullPage: true,
  });
});

test("installed mods add dependencies and remove dependent selections", async ({
  page,
}) => {
  await open(page);
  const summary = page.locator(".mod-picker summary");
  await summary.focus();
  await page.keyboard.press("Enter");
  await expect(page.locator(".mod-picker input[type=checkbox]")).toHaveCount(8);
  await mod(page, "Chipped").check();
  await expect(mod(page, "Create")).not.toBeChecked();
  await mod(page, "Create: Copycats+").check();
  await expect(mod(page, "Create")).toBeChecked();
  await expect(summary).toContainText("3 selected");
  await mod(page, "Create: Chipped").check();
  await mod(page, "Chipped").uncheck();
  await expect(mod(page, "Create: Chipped")).not.toBeChecked();
  await expect(mod(page, "Create: Copycats+")).toBeChecked();
  await mod(page, "Create").uncheck();
  await expect(mod(page, "Create: Copycats+")).not.toBeChecked();
  await expect(summary).toContainText("Vanilla only");
  await mod(page, "Create: Design n' Decor").check();
  await mod(page, "Create Deco").check();
  await mod(page, "Create Encased").check();
  await mod(page, "Create: Bells & Whistles").check();
  await mod(page, "Create: Chipped").check();
  await expect(summary).toContainText("7 selected");
  await mod(page, "Create").uncheck();
  await expect(summary).toContainText("1 selected");
  await expect(mod(page, "Chipped")).toBeChecked();
  await expect(
    page.getByRole("button", { name: "Convert", exact: true }),
  ).toBeInViewport({ ratio: 1 });
  await page.setViewportSize({ width: 600, height: 850 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth > innerWidth,
    ),
  ).toBe(false);
  await expect(page.locator(".mod-picker .mod-hint")).toContainText("1.21.1");
  await page.screenshot({
    path: "../artifacts/mods-selector-mobile.png",
    fullPage: true,
  });
});

test("mod changes invalidate exported results and remain remembered for reverse conversion", async ({
  page,
}) => {
  await open(page, path.resolve("../tests/fixtures/painted-slopes.blueprint"));
  await page.getByLabel("Material preference").selectOption("color");
  await page.locator(".mod-picker summary").click();
  await mod(page, "Create: Copycats+").check();
  const request = page.waitForRequest("**/api/convert");
  await convert(page);
  expect((await request).postDataJSON().mods.sort()).toEqual([
    "copycats",
    "create",
  ]);
  await expect(page.getByRole("status")).toHaveText(/ready to export/);
  const status = await page.request
    .get("/api/status")
    .then((response) => response.json());
  expect(
    status.converted.materials.some(
      (item: { name: string; copied_material?: { name: string } }) =>
        item.name === "copycats:copycat_slab" &&
        item.copied_material?.name === "minecraft:red_concrete",
    ),
  ).toBe(true);
  await page.getByLabel("Search materials").fill("red_concrete");
  await expect(page.getByTestId("material-list")).toContainText(
    "copycats:copycat_slab",
  );
  await expect(page.getByTestId("material-list")).toContainText(
    "Applied material: minecraft:red_concrete",
  );
  await page.getByLabel("Search materials").fill("");
  await page.screenshot({
    path: "../artifacts/mods-copycats-converted.png",
    fullPage: true,
  });
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export file" }).click();
  const download = await downloadPromise;
  const bytes = fs.readFileSync((await download.path())!);
  expect(createHash("sha256").update(bytes).digest("hex")).toBe(status.sha256);
  await mod(page, "Chipped").check();
  await expect(
    page.getByRole("button", { name: "Export file" }),
  ).toBeDisabled();
  await expect(page.getByRole("status")).toHaveText(/Options changed/);
  expect(
    (await page.request.get(`/api/export?result_id=${status.result_id}`)).ok(),
  ).toBe(false);
  await page
    .getByLabel("Open structure file")
    .setInputFiles(path.resolve("../examples/demo-hull.nbt"));
  await expect(page.getByRole("status")).toHaveText(/Source ready/);
  await expect(mod(page, "Create: Copycats+")).toBeChecked();
  await expect(mod(page, "Create: Copycats+")).toBeDisabled();
  const reverse = page.waitForRequest("**/api/convert");
  await convert(page);
  expect((await reverse).postDataJSON()).toMatchObject({
    format: "blueprint",
    mods: [],
  });
  await expect(page.getByRole("status")).toHaveText(/ready to export/);
  await page.getByLabel("Open structure file").setInputFiles(demo);
  await expect(page.getByRole("status")).toHaveText(/Source ready/);
  await expect(mod(page, "Create: Copycats+")).toBeEnabled();
  await expect(mod(page, "Create: Copycats+")).toBeChecked();
});

test("copycat inspector and material rows show and search the applied block state", async ({
  page,
}) => {
  const warnings: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error" || message.type() === "warning")
      warnings.push(message.text());
  });
  const block = {
    name: "copycats:copycat_slab",
    material: "Metal",
    properties: { axis: "y", type: "bottom" },
  };
  const red = {
    ...block,
    copied_material: { name: "minecraft:red_concrete", properties: {} },
  };
  const oak = {
    ...block,
    copied_material: { name: "minecraft:oak_log", properties: { axis: "x" } },
  };
  const display = {
    format: "nbt",
    version: "1.21.1",
    count: 1,
    bounds: [
      [0, 0, 0],
      [1, 1, 1],
    ],
    dimensions: [1, 1, 1],
    blocks: [oak],
    materials: [
      { ...red, count: 2 },
      { ...oak, count: 1 },
    ],
    groups: [
      {
        shape: "cube",
        transparent: false,
        matrices: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
        colors: [0.5, 0.3, 0.2],
        block_indices: [0],
      },
    ],
  };
  await page.route("**/api/source", (route) =>
    route.fulfill({ json: { source: display, notices: {} } }),
  );
  await open(page);
  const rows = page.getByTestId("material-list").locator("tbody tr");
  await expect(rows).toHaveCount(2);
  await expect(rows.nth(0)).toContainText(
    "Applied material: minecraft:red_concrete",
  );
  await expect(rows.nth(1)).toContainText(
    "Applied material: minecraft:oak_log / axis=x",
  );
  const canvas = page.getByLabel("Source 3D structural preview");
  await canvas.focus();
  await page.keyboard.press("i");
  await expect(page.getByTestId("source-block-inspector")).toContainText(
    "Applied material: minecraft:oak_log / axis=x",
  );
  await page.getByLabel("Search materials").fill("axis=x");
  await expect(rows).toHaveCount(1);
  await expect(rows).toContainText("minecraft:oak_log");
  await page.getByLabel("Search materials").fill("red_concrete");
  await expect(rows).toHaveCount(1);
  await expect(rows).toContainText("minecraft:red_concrete");
  await page.getByLabel("Search materials").fill("");
  await expect(rows).toHaveCount(2);
  await canvas.focus();
  await page.keyboard.press("i");
  await expect(page.getByTestId("source-block-inspector")).toBeVisible();
  expect(
    warnings.filter((message) => /same key|unique.*key/i.test(message)),
  ).toEqual([]);
  await page.screenshot({
    path: "../artifacts/mods-applied-material.png",
    fullPage: true,
  });
});
