import { test, expect } from "@playwright/test";
import path from "node:path";

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
