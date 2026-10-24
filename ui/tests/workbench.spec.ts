import { expect, test } from "@playwright/test";
import path from "node:path";
import fs from "node:fs";

const fixture = path.resolve("../tests/fixtures/asymmetric.blueprint");

test("conversion and camera changes retain the source canvas and render context", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Open file", exact: true }),
  ).toBeEnabled();
  await page.getByLabel("Open structure file").setInputFiles(fixture);
  await expect(page.getByRole("status")).toHaveText(/Source ready/);
  const canvas = await page
    .getByLabel("Source 3D structural preview", { exact: true })
    .elementHandle();
  expect(canvas).not.toBeNull();
  await page.getByRole("button", { name: "Convert", exact: true }).click();
  await expect(page.getByRole("status")).toHaveText(/ready to export/);
  expect(await canvas!.evaluate((node) => node.isConnected)).toBe(true);
  for (const name of ["Top", "Front", "Side", "Fit both"]) {
    await page.getByRole("button", { name, exact: true }).click();
    expect(await canvas!.evaluate((node) => node.isConnected)).toBe(true);
  }
  expect(errors).toEqual([]);
});

test("scale changes during a real upload do not discard the source", async ({
  page,
}) => {
  await page.route("**/api/source", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 600));
    await route.continue();
  });
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Open file", exact: true }),
  ).toBeEnabled();
  await page.getByLabel("Open structure file").setInputFiles(fixture);
  await expect(page.getByRole("status")).toHaveText("Reading source…");
  await page.getByLabel("Output scale").selectOption("0.5");
  await expect(page.getByRole("status")).toHaveText(/Source ready/);
  await expect(
    page.getByRole("button", { name: "Convert", exact: true }),
  ).toBeEnabled();
});

test("open, compare serialized output, export, invalidate and recover", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Open file", exact: true }),
  ).toBeEnabled();
  await expect(
    page.getByRole("button", { name: "Export file" }),
  ).toBeDisabled();
  await page.getByLabel("Open structure file").setInputFiles(fixture);
  await expect(page.getByRole("status")).toHaveText(/Source ready/);
  await expect(page.getByLabel("Output scale").locator("option")).toHaveCount(
    5,
  );
  await expect(page.getByTestId("dimensions")).toHaveText("3 × 2 × 4");
  await page.getByRole("button", { name: "Convert", exact: true }).click();
  await expect(page.getByRole("status")).toHaveText(/ready to export/);
  const status = await page.request.get("/api/status").then((r) => r.json());
  expect(status.converted.count).toBe(7);
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export file" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/\.nbt$/);
  const bytes = fs.readFileSync((await download.path())!);
  const crypto = await import("node:crypto");
  expect(crypto.createHash("sha256").update(bytes).digest("hex")).toBe(
    status.sha256,
  );
  await expect(page.getByRole("status")).toHaveText("Download started.");
  await page.getByLabel("Output scale").selectOption("0.25");
  await expect(
    page.getByRole("button", { name: "Export file" }),
  ).toBeDisabled();
  await expect(page.getByRole("status")).toHaveText(/Options changed/);
  await page.getByLabel("Output format").selectOption("litematic");
  await page.getByRole("button", { name: "Convert", exact: true }).click();
  await expect(page.getByRole("status")).toHaveText(/ready to export/);
  await expect(page.getByRole("button", { name: "Export file" })).toBeEnabled();
  await page.screenshot({
    path: "../artifacts/workbench-laptop.png",
    fullPage: true,
  });
  expect(errors).toEqual([]);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth > innerWidth,
    ),
  ).toBe(false);
});

test("linked cameras move together, unlink and fixed views work", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Open file", exact: true }),
  ).toBeEnabled();
  await page.getByLabel("Open structure file").setInputFiles(fixture);
  await expect(page.getByRole("status")).toHaveText(/Source ready/);
  await page.getByRole("button", { name: "Convert", exact: true }).click();
  await expect(page.getByRole("status")).toHaveText(/ready to export/);
  const left = page.getByLabel("Source 3D structural preview");
  const right = page.getByLabel("Converted 3D structural preview");
  const beforeLeft = await left.screenshot(),
    beforeRight = await right.screenshot();
  const box = (await left.boundingBox())!;
  await page.mouse.move(box.x + box.width * 0.5, box.y + box.height * 0.5);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * 0.7, box.y + box.height * 0.6, {
    steps: 8,
  });
  await page.mouse.up();
  expect((await left.screenshot()).equals(beforeLeft)).toBe(false);
  expect((await right.screenshot()).equals(beforeRight)).toBe(false);
  await page.getByLabel("Linked cameras").uncheck();
  const unlinked = await right.screenshot();
  await page.mouse.move(box.x + box.width * 0.5, box.y + box.height * 0.5);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * 0.3, box.y + box.height * 0.4, {
    steps: 8,
  });
  await page.mouse.up();
  expect((await right.screenshot()).equals(unlinked)).toBe(true);
  for (const name of ["Top", "Front", "Side", "Fit both"])
    await page.getByRole("button", { name, exact: true }).click();
  await page.getByLabel("Linked cameras").check();
});

test("failed import, source replacement, cancellation and keyboard controls", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Open file", exact: true }),
  ).toBeEnabled();
  await page.getByLabel("Open structure file").setInputFiles({
    name: "bad.blueprint",
    mimeType: "application/json",
    buffer: Buffer.from("{bad"),
  });
  await expect(page.getByRole("status")).toHaveText(/Invalid FtD/);
  await page.getByLabel("Open structure file").setInputFiles(fixture);
  await expect(page.getByRole("status")).toHaveText(/Source ready/);
  await page.getByLabel("Output scale").selectOption("4");
  await page.getByRole("button", { name: "Convert", exact: true }).click();
  // An immediate option change invalidates an in-flight conversion too.
  await page.getByLabel("Output scale").selectOption("0.5");
  await expect(
    page.getByRole("button", { name: "Export file" }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Convert", exact: true }).click();
  await expect(page.getByRole("status")).toHaveText(/ready to export/);
  await page.getByLabel("Open structure file").setInputFiles(fixture);
  await expect(page.getByRole("status")).toHaveText(/Source ready/);
  await expect(
    page.getByRole("button", { name: "Export file" }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Top", exact: true }).focus();
  await page.keyboard.press("Enter");
  await expect(
    page.getByRole("button", { name: "Top", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
});

test("real medium ship with paired views", async ({ page }) => {
  test.skip(
    !process.env.FROMTHECRAFT_SHIP,
    "Set FROMTHECRAFT_SHIP to an owner-supplied 1.21.1 file.",
  );
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Open file", exact: true }),
  ).toBeEnabled();
  await page
    .getByLabel("Open structure file")
    .setInputFiles(process.env.FROMTHECRAFT_SHIP!);
  await expect(page.getByRole("status")).toHaveText(/Source ready/);
  await page.getByRole("button", { name: "Convert", exact: true }).click();
  await expect(page.getByRole("status")).toHaveText(/ready to export/, {
    timeout: 30000,
  });
  await expect(page.getByRole("button", { name: "Export file" })).toBeEnabled();
  await page.screenshot({
    path: "../artifacts/real-ship-paired.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Top", exact: true }).click();
  await page.getByRole("button", { name: "Fit both", exact: true }).click();
});

test("installed FtD Marauder converts through both Minecraft formats", async ({
  page,
}) => {
  test.skip(
    !process.env.FROMTHECRAFT_FTD_SHIP,
    "Set FROMTHECRAFT_FTD_SHIP to a local game blueprint.",
  );
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Open file", exact: true }),
  ).toBeEnabled();
  await page
    .getByLabel("Open structure file")
    .setInputFiles(process.env.FROMTHECRAFT_FTD_SHIP!);
  await expect(page.getByRole("status")).toHaveText(/Source ready/);
  await page.getByRole("button", { name: "Convert", exact: true }).click();
  await expect(page.getByRole("status")).toHaveText(/ready to export/, {
    timeout: 30000,
  });
  let status = await page.request
    .get("/api/status")
    .then((response) => response.json());
  expect(status.converted.count).toBeGreaterThan(6000);
  expect(
    Object.keys(status.notices).some((key) => key.includes("Unrecognized")),
  ).toBe(false);
  await page.screenshot({
    path: "../artifacts/ftd-marauder-paired.png",
    fullPage: true,
  });
  await page.getByLabel("Output format").selectOption("litematic");
  await page.getByRole("button", { name: "Convert", exact: true }).click();
  await expect(page.getByRole("status")).toHaveText(/ready to export/, {
    timeout: 30000,
  });
  status = await page.request
    .get("/api/status")
    .then((response) => response.json());
  expect(status.converted.format).toBe("litematic");
});

test("hard owner blueprint renders and exports beyond 200000 cells", async ({
  page,
}) => {
  test.skip(
    !process.env.FROMTHECRAFT_HARD_SHIP,
    "Set FROMTHECRAFT_HARD_SHIP to the owner Claymore fixture.",
  );
  test.setTimeout(120000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Open file", exact: true }),
  ).toBeEnabled();
  await page
    .getByLabel("Open structure file")
    .setInputFiles(process.env.FROMTHECRAFT_HARD_SHIP!);
  await expect(page.getByRole("status")).toHaveText(/Source ready/, {
    timeout: 30000,
  });
  const started = Date.now();
  await page.getByRole("button", { name: "Convert", exact: true }).click();
  await expect(page.getByRole("status")).toHaveText(/ready to export/, {
    timeout: 90000,
  });
  const status = await page.request
    .get("/api/status")
    .then((response) => response.json());
  expect(status.converted.count).toBeGreaterThan(200000);
  await expect(page.getByRole("button", { name: "Export file" })).toBeEnabled();
  await page.screenshot({
    path: "../artifacts/hard-claymore-paired.png",
    fullPage: true,
  });
  console.log(
    `Claymore paired UI: ${status.converted.count} output primitives in ${(Date.now() - started) / 1000}s including preview`,
  );
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export file" }).click();
  const download = await downloadPromise;
  await download.saveAs("../artifacts/claymore-ui-export.nbt");
  const bytes = fs.readFileSync((await download.path())!);
  const crypto = await import("node:crypto");
  expect(crypto.createHash("sha256").update(bytes).digest("hex")).toBe(
    status.sha256,
  );
  expect(errors).toEqual([]);
  for (const name of ["Top", "Front", "Side", "Fit both"])
    await page.getByRole("button", { name, exact: true }).click();
});
