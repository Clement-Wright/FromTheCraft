import { expect, test, type Page } from "@playwright/test";
import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";

async function convertFixture(page: Page) {
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Open file", exact: true }),
  ).toBeEnabled();
  await page
    .getByLabel("Open structure file")
    .setInputFiles(path.resolve("../tests/fixtures/asymmetric.blueprint"));
  await expect(page.getByRole("status")).toHaveText(/Source ready/);
  await page.getByLabel("Output scale", { exact: true }).selectOption("2");
  await page.getByRole("button", { name: "Convert", exact: true }).click();
  await expect(page.getByRole("status")).toHaveText(/ready to export/);
  return page.request.get("/api/status").then((r) => r.json());
}

test("upscaled and custom filenames export the same converted bytes", async ({
  page,
}) => {
  const ready = await convertFixture(page);
  const name = page.getByLabel("Output filename", { exact: true });
  await expect(name).toHaveValue("asymmetric_converted_2x.nbt", {
    timeout: 3000,
  });
  await name.fill("My ship 船");
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export file", exact: true }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe("My ship 船.nbt");
  expect(
    createHash("sha256")
      .update(fs.readFileSync((await download.path())!))
      .digest("hex"),
  ).toBe(ready.sha256);
  expect(
    (await page.request.get("/api/status").then((r) => r.json())).result_id,
  ).toBe(ready.result_id);
  await page.getByRole("button", { name: "Reset output filename" }).click();
  await expect(name).toHaveValue("asymmetric_converted_2x.nbt");
  await page.getByLabel("Output scale", { exact: true }).selectOption("3");
  await page.getByRole("button", { name: "Convert", exact: true }).click();
  await expect(page.getByRole("status")).toHaveText(/ready to export/);
  await expect(name).toHaveValue("asymmetric_converted_3x.nbt");
});

test("native save destination cancellation and errors keep the converted result usable", async ({
  page,
}) => {
  await page.route("**/api/session", async (route) => {
    const response = await route.fetch();
    await route.fulfill({
      response,
      json: { ...(await response.json()), can_save: true },
    });
  });
  let outcome = "cancel";
  let submitted: { result_id: string; filename: string } | undefined;
  await page.route("**/api/export/save", async (route) => {
    submitted = route.request().postDataJSON();
    if (outcome === "error") {
      await route.fulfill({
        status: 500,
        json: { detail: "Read-only destination" },
      });
    } else {
      await route.fulfill({
        json:
          outcome === "cancel"
            ? { saved: false }
            : {
                saved: true,
                filename: "Chosen ship.nbt",
                path: "C:\\Ships\\Chosen ship.nbt",
              },
      });
    }
  });
  const ready = await convertFixture(page);
  const save = page.getByRole("button", { name: "Save as…", exact: true });
  await save.click();
  await expect(save).toBeEnabled();
  await expect(
    page.getByRole("button", { name: "Export file", exact: true }),
  ).toBeEnabled();
  outcome = "error";
  await save.click();
  await expect(page.getByRole("alert")).toContainText("Read-only destination");
  await expect(save).toBeEnabled();
  outcome = "saved";
  await page
    .getByLabel("Output filename", { exact: true })
    .fill("Requested ship.nbt");
  await save.click();
  await expect(
    page.getByText("Saved to C:\\Ships\\Chosen ship.nbt", { exact: true }),
  ).toBeVisible();
  expect(submitted).toEqual({
    result_id: ready.result_id,
    filename: "Requested ship.nbt",
  });
  await expect(page.getByLabel("Output filename", { exact: true })).toHaveValue(
    "Chosen ship.nbt",
  );
  await expect(
    page.getByRole("button", { name: "Export file", exact: true }),
  ).toBeEnabled();
});

test("invalid output names can be corrected without reconversion", async ({
  page,
}) => {
  const ready = await convertFixture(page);
  const name = page.getByLabel("Output filename", { exact: true });
  await name.fill("folder/ship.nbt");
  await page.getByRole("button", { name: "Export file", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("filename");
  await expect(
    page.getByRole("button", { name: "Export file", exact: true }),
  ).toBeEnabled();
  expect(
    (await page.request.get("/api/status").then((r) => r.json())).result_id,
  ).toBe(ready.result_id);
  await name.fill("Fixed ship.nbt");
  await expect(page.getByRole("alert")).not.toBeVisible();
});
