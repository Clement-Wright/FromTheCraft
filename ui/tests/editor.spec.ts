import { test, expect } from "@playwright/test";
import path from "node:path";

test("oversized original bounds do not prevent converting after exclusions", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Open file", exact: true }),
  ).toBeEnabled();
  const fs = await import("node:fs/promises");
  const document = JSON.parse(
    await fs.readFile("../tests/fixtures/asymmetric.blueprint", "utf8"),
  );
  const root = document.Blueprint;
  root.BLP = ["0,0,0", "2100,0,0"];
  root.BLR = [0, 0];
  root.BCI = [0, 0];
  root.BlockIds = [root.BlockIds[0], root.BlockIds[1]];
  root.SCs = [];
  await page.getByLabel("Open structure file").setInputFiles({
    name: "outlier.blueprint",
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify(document)),
  });
  await expect(page.getByRole("status")).toContainText("Source ready");
  await page
    .getByRole("button", { name: /Select all .*beam/i })
    .first()
    .click();
  await page
    .getByRole("button", { name: "Exclude selected", exact: true })
    .click();
  await page.getByRole("button", { name: "Convert", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("ready to export");
  const result = await page.request.get("/api/status").then((r) => r.json());
  expect(result.converted.count).toBe(1);
});

test("project roundtrip and target mapping preserve record selection", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Open file", exact: true }),
  ).toBeEnabled();
  await page
    .getByLabel("Open structure file")
    .setInputFiles("../tests/fixtures/asymmetric.blueprint");
  await expect(page.getByRole("status")).toContainText("Source ready");
  await page
    .getByRole("button", { name: /Select all .*beam/i })
    .first()
    .click();
  await page
    .getByRole("button", { name: "Exclude selected", exact: true })
    .click();
  await expect(page.getByTestId("excluded-count")).toHaveText("1 excluded");
  await page.getByText("Projects and presets", { exact: true }).click();
  const pending = page.waitForEvent("download");
  await page.getByRole("button", { name: "Save project", exact: true }).click();
  const download = await pending;
  const project = await download.path();
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await page.getByRole("button", { name: "Open project", exact: true }).click();
  await page
    .getByLabel("Open conversion project or preset")
    .setInputFiles(project!);
  await expect(page.getByTestId("excluded-count")).toHaveText("1 excluded");
  await page
    .getByRole("button", { name: /Select all .*beam/i })
    .first()
    .click();
  await page
    .getByRole("button", { name: "Restore selected", exact: true })
    .click();
  await page
    .getByText("Local block browser / Replace mapping", { exact: true })
    .click();
  await page.getByLabel("Search target blocks").fill("minecraft:gold_block");
  await page
    .getByLabel("Target block", { exact: true })
    .selectOption("minecraft:gold_block");
  await expect(
    page.getByText("Texture unavailable.", { exact: false }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Assign mapping to selected" })
    .click();
  await page.getByRole("button", { name: "Convert", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("ready to export");
  const status = await page.request.get("/api/status").then((r) => r.json());
  expect(
    status.converted.materials.some(
      (m: { name: string }) => m.name === "minecraft:gold_block",
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: "../artifacts/feature-editor-controls.png",
    fullPage: true,
  });
});

test("source type exclusion and undo invalidate export while hiding does not", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Open file", exact: true }),
  ).toBeEnabled();
  await page
    .getByLabel("Open structure file")
    .setInputFiles(path.resolve("../tests/fixtures/asymmetric.blueprint"));
  await expect(page.getByRole("status")).toHaveText(/Source ready/);
  await page.getByRole("button", { name: "Convert", exact: true }).click();
  await expect(page.getByRole("status")).toHaveText(/ready to export/);
  await page
    .getByRole("button", { name: "Source materials", exact: true })
    .click();
  await page
    .getByRole("button", { name: /Select all .*beam/ })
    .first()
    .click();
  await expect(page.getByTestId("selection-count")).toContainText("1 selected");
  await page
    .getByRole("button", { name: "Hide selected", exact: true })
    .click();
  await expect(page.getByRole("button", { name: "Export file" })).toBeEnabled();
  await page
    .getByRole("button", { name: "Exclude selected", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Export file" }),
  ).toBeDisabled();
  await expect(page.getByTestId("excluded-count")).toContainText("1 excluded");
  await page.getByRole("button", { name: "Convert", exact: true }).click();
  await expect(page.getByRole("status")).toHaveText(/ready to export/);
  const status = await page.request.get("/api/status").then((r) => r.json());
  expect(status.converted.count).toBeLessThan(7);
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await expect(page.getByTestId("excluded-count")).toContainText("0 excluded");
  await expect(
    page.getByRole("button", { name: "Export file" }),
  ).toBeDisabled();
});
