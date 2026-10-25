import { expect, test } from "@playwright/test";

test("Optimized Conversion toggles, invalidates export and survives a saved preset", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Open file", exact: true }),
  ).toBeEnabled();
  await page
    .getByLabel("Open structure file")
    .setInputFiles("../tests/fixtures/asymmetric.blueprint");
  await expect(page.getByRole("status")).toHaveText(/Source ready/);
  const optimized = page.getByRole("button", {
    name: "Optimized Conversion",
    exact: true,
  });
  await expect(optimized).toHaveAttribute("aria-pressed", "false");
  await page.getByRole("button", { name: "Convert", exact: true }).click();
  await expect(page.getByRole("status")).toHaveText(/ready to export/);
  const original = await page.request.get("/api/status").then((r) => r.json());
  await optimized.click();
  await expect(optimized).toHaveAttribute("aria-pressed", "true");
  await expect(
    page.getByRole("button", { name: "Export file", exact: true }),
  ).toBeDisabled();
  const pending = page.waitForRequest(
    (r) => r.url().endsWith("/api/convert") && r.method() === "POST",
  );
  await page.getByRole("button", { name: "Convert", exact: true }).click();
  expect((await pending).postDataJSON().optimized_conversion).toBe(true);
  await expect(page.getByRole("status")).toHaveText(/ready to export/);
  const updated = await page.request.get("/api/status").then((r) => r.json());
  expect(updated.sha256).toBe(original.sha256);
  await page.getByText("Projects and presets", { exact: true }).click();
  const downloaded = page.waitForEvent("download");
  await page.getByRole("button", { name: "Save preset", exact: true }).click();
  const preset = await (await downloaded).path();
  await optimized.click();
  await page.getByRole("button", { name: "Open preset", exact: true }).click();
  await page
    .getByLabel("Open conversion project or preset")
    .setInputFiles(preset!);
  await expect(optimized).toHaveAttribute("aria-pressed", "true");
});
