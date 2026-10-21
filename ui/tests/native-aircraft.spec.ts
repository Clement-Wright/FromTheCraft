import { createHash } from "node:crypto";
import fs from "node:fs";
import { expect, test, type Page } from "@playwright/test";
import type { Display, Status } from "../src/types";

async function inspectRealBlock(
  page: Page,
  side: "source" | "converted",
  model: Display,
) {
  const canvas = page.getByLabel(
    `${side === "source" ? "Source" : "Converted"} 3D structural preview`,
  );
  const inspector = page.getByTestId(`${side}-block-inspector`);
  await canvas.focus();
  await page.keyboard.press("i");
  const box = (await canvas.boundingBox())!;
  for (const [x, y] of [
    [0.5, 0.5],
    [0.45, 0.5],
    [0.55, 0.5],
    [0.4, 0.5],
    [0.6, 0.5],
    [0.5, 0.45],
    [0.5, 0.55],
    [0.35, 0.5],
    [0.65, 0.5],
  ]) {
    if (await inspector.isVisible()) break;
    await page.mouse.move(box.x + box.width * x, box.y + box.height * y);
    await expect(inspector)
      .toBeVisible({ timeout: 250 })
      .catch(() => undefined);
  }
  await expect(inspector).toBeVisible();
  const text = (await inspector.textContent())!;
  const name = (await inspector.locator("strong").textContent())!;
  const material = (await inspector
    .locator(":scope > span")
    .first()
    .textContent())!;
  const coordinateText = (await inspector
    .locator(".block-coordinate")
    .textContent())!;
  const coordinate = coordinateText.split(":")[1].split(",").map(Number);
  let matched = false;
  for (const group of model.groups) {
    for (let instance = 0; instance < group.block_indices.length; instance++) {
      if (
        !coordinate.every(
          (value, axis) =>
            Math.abs(value - group.matrices[instance * 16 + 12 + axis]) <
            0.0011,
        )
      )
        continue;
      const block = model.blocks[group.block_indices[instance]];
      if (block.name !== name || block.material !== material) continue;
      if (
        !Object.entries(block.properties).every(([key, value]) =>
          text.includes(`${key}=${value}`),
        )
      )
        continue;
      matched = true;
      break;
    }
    if (matched) break;
  }
  expect(
    matched,
    `${side} inspector must match an actual instance origin and its block metadata`,
  ).toBe(true);
}

test("native aircraft inspection, build inventory, hollow export and checksum", async ({
  page,
}) => {
  test.skip(
    !process.env.FROMTHECRAFT_SLOPE_SHIP,
    "Set FROMTHECRAFT_SLOPE_SHIP to an owner-supplied native FtD aircraft.",
  );
  test.setTimeout(120000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Open file", exact: true }),
  ).toBeEnabled();
  const sourceResponse = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/source") &&
      response.request().method() === "POST",
  );
  await page
    .getByLabel("Open structure file")
    .setInputFiles(process.env.FROMTHECRAFT_SLOPE_SHIP!);
  const uploaded = await sourceResponse;
  const uploadText = await uploaded.text();
  expect(
    uploaded.ok(),
    `Source upload HTTP ${uploaded.status()}: ${uploadText.slice(0, 300)}`,
  ).toBe(true);
  const source: Display = JSON.parse(uploadText).source;
  await expect(page.getByRole("status")).toHaveText(/Source ready/, {
    timeout: 30000,
  });
  expect(source.groups.some((group) => group.vertices?.length)).toBe(true);
  await page.getByRole("button", { name: "Convert", exact: true }).click();
  await expect(page.getByRole("status")).toHaveText(/ready to export/, {
    timeout: 60000,
  });
  const baseline: Status = await page.request
    .get("/api/status")
    .then((response) => response.json());
  expect(
    baseline.converted!.materials.reduce((sum, item) => sum + item.count, 0),
  ).toBe(baseline.converted!.count);
  await expect(page.getByTestId("material-total")).toHaveText(
    `${baseline.converted!.count.toLocaleString()} exported blocks`,
  );
  await page.getByRole("button", { name: "Top", exact: true }).click();
  await inspectRealBlock(page, "source", source);
  await inspectRealBlock(page, "converted", baseline.converted!);
  await expect(
    page.getByRole("button", { name: "Build materials", exact: true }),
  ).toHaveAttribute("aria-expanded", "true");
  await page.locator(".settings-content").evaluate((element) => {
    element.scrollTop = 0;
  });
  await page.screenshot({
    path: "../artifacts/native-horten-normal.png",
    fullPage: true,
  });
  await page.getByLabel("Hollow interior", { exact: true }).check();
  await page.getByLabel("Shell thickness").selectOption("2");
  await expect(
    page.getByRole("button", { name: "Export file" }),
  ).toBeDisabled();
  await expect(page.getByRole("status")).toHaveText(/Options changed/);
  await expect(page.getByTestId("material-list")).toContainText(
    "Options changed. Convert again to update the build list.",
  );
  await page.getByLabel("Shell thickness").selectOption("1");
  await expect(
    page.getByRole("button", { name: "Convert", exact: true }),
  ).toBeInViewport({ ratio: 1 });
  await page.getByRole("button", { name: "Convert", exact: true }).click();
  await expect(page.getByRole("status")).toHaveText(/ready to export/, {
    timeout: 60000,
  });
  const hollow: Status = await page.request
    .get("/api/status")
    .then((response) => response.json());
  expect(hollow.converted!.count).toBeGreaterThan(0);
  expect(hollow.converted!.count).toBeLessThan(baseline.converted!.count);
  expect(
    hollow.converted!.materials.reduce((sum, item) => sum + item.count, 0),
  ).toBe(hollow.converted!.count);
  await expect(page.getByTestId("material-total")).toHaveText(
    `${hollow.converted!.count.toLocaleString()} exported blocks`,
  );
  await page.locator(".settings-content").evaluate((element) => {
    element.scrollTop = 0;
  });
  await page.screenshot({
    path: "../artifacts/native-horten-hollow.png",
    fullPage: true,
  });
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export file" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/\.nbt$/);
  const bytes = fs.readFileSync((await download.path())!);
  expect(createHash("sha256").update(bytes).digest("hex")).toBe(hollow.sha256);
  expect(errors).toEqual([]);
  console.log(
    `Horten: ${source.count} source primitives; ${baseline.converted!.count} normal / ${hollow.converted!.count} hollow exported blocks; exact export SHA-256 verified.`,
  );
});
