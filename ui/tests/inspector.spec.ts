import { expect, test } from "@playwright/test";

const display = {
  format: "blueprint",
  version: "test",
  count: 1,
  bounds: [
    [0, 0, 0],
    [1, 1, 1],
  ],
  dimensions: [1, 1, 1],
  blocks: [
    { name: "Wrong block", material: "wood", properties: {} },
    { name: "Steel beam", material: "metal", properties: { facing: "north" } },
  ],
  groups: [
    {
      shape: "cube",
      transparent: false,
      matrices: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
      colors: [0.5, 0.6, 0.7],
      block_indices: [1],
    },
  ],
  materials: [
    {
      name: "Steel beam",
      material: "metal",
      properties: { facing: "north" },
      count: 1,
    },
  ],
};

test.beforeEach(async ({ page }) => {
  await page.route("**/api/session", (route) =>
    route.fulfill({ json: { token: "test", can_close: false } }),
  );
  await page.route("**/api/source", (route) =>
    route.fulfill({ json: { source: display, notices: {} } }),
  );
  await page.route("**/api/convert", (route) => route.fulfill({ json: {} }));
  await page.route("**/api/invalidate", (route) => route.fulfill({ json: {} }));
  await page.route("**/api/status", (route) =>
    route.fulfill({
      json: {
        state: "ready",
        progress: 1,
        error: "",
        result_id: "test-result",
        converted: {
          ...display,
          format: "nbt",
          blocks: [
            display.blocks[0],
            { name: "minecraft:iron_block", material: "metal", properties: {} },
          ],
          materials: [
            {
              name: "minecraft:iron_block",
              material: "metal",
              properties: {},
              count: 1,
            },
          ],
        },
      },
    }),
  );
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Open file", exact: true }),
  ).toBeEnabled();
  await page.getByLabel("Open structure file").setInputFiles({
    name: "test.blueprint",
    mimeType: "application/json",
    buffer: Buffer.from("{}"),
  });
  await expect(page.getByRole("status")).toHaveText(/Source ready/);
});

test("hover resolves the instance block index and clears on leaving or replacing the scene", async ({
  page,
}) => {
  const canvas = page.getByLabel("Source 3D structural preview");
  const box = (await canvas.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  const inspector = page.getByTestId("source-block-inspector");
  await expect(inspector).toContainText("Steel beam");
  await expect(inspector).toContainText("metal");
  await expect(inspector).toContainText("facing=north");
  await expect(inspector).toContainText("0, 0, 0");
  await expect(inspector).not.toContainText("Wrong block");
  await page.mouse.move(10, 10);
  await expect(inspector).not.toBeVisible();
  await canvas.focus();
  await page.keyboard.press("i");
  await expect(inspector).toBeVisible();
  await page.getByRole("button", { name: "Convert", exact: true }).click();
  await expect(page.getByRole("status")).toHaveText(/ready to export/);
  const convertedCanvas = page.getByLabel("Converted 3D structural preview");
  await convertedCanvas.focus();
  await page.keyboard.press("i");
  await expect(page.getByTestId("converted-block-inspector")).toContainText(
    "minecraft:iron_block",
  );
  await page.getByLabel("Open structure file").setInputFiles({
    name: "replacement.blueprint",
    mimeType: "application/json",
    buffer: Buffer.from("{}"),
  });
  await expect(page.getByRole("status")).toHaveText(/Source ready/);
  await expect(inspector).not.toBeVisible();
  await expect(page.getByTestId("converted-block-inspector")).not.toBeVisible();
});

test("Minecraft sources offer hollowing for FtD output", async ({ page }) => {
  await page.route("**/api/source", (route) =>
    route.fulfill({
      json: { source: { ...display, format: "nbt" }, notices: {} },
    }),
  );
  await page.getByLabel("Open structure file").setInputFiles({
    name: "test.nbt",
    mimeType: "application/octet-stream",
    buffer: Buffer.from("test"),
  });
  await expect(page.getByRole("status")).toHaveText(/Source ready/);
  await expect(page.getByLabel("Output format")).toHaveValue("blueprint");
  await page.getByLabel("Hollow interior", { exact: true }).check();
  const request = page.waitForRequest("**/api/convert");
  await page.getByRole("button", { name: "Convert", exact: true }).click();
  expect((await request).postDataJSON()).toMatchObject({
    format: "blueprint",
    hollow: true,
    shell_thickness: 1,
  });
});

test("click selection, Ctrl toggle and overlapping source identities remain independent", async ({
  page,
}) => {
  const records = ["first", "second"].map((id) => ({
    id,
    name: `${id} beam`,
    type_key: "beam",
    kind: "block",
    path: [id],
    parent_path: [],
  }));
  await page.route("**/api/source", (route) =>
    route.fulfill({
      json: {
        notices: {},
        source: {
          ...display,
          source_hash: "overlap",
          records,
          count: 2,
          groups: [
            {
              ...display.groups[0],
              source_ids: ["first", "second"],
              block_indices: [1, 1],
              matrices: [
                ...display.groups[0].matrices,
                ...display.groups[0].matrices,
              ],
              colors: [
                ...display.groups[0].colors,
                ...display.groups[0].colors,
              ],
            },
          ],
        },
      },
    }),
  );
  await page
    .getByLabel("Open structure file")
    .setInputFiles({
      name: "overlap.blueprint",
      mimeType: "application/json",
      buffer: Buffer.from("{}"),
    });
  await expect(page.getByRole("status")).toContainText("Source ready");
  const canvas = page.getByLabel("Source 3D structural preview");
  const bounds = (await canvas.boundingBox())!;
  await page.mouse.click(
    bounds.x + bounds.width / 2,
    bounds.y + bounds.height / 2,
  );
  await expect(page.getByTestId("selection-count")).toHaveText("1 selected");
  await page.keyboard.down("Control");
  await page.mouse.click(
    bounds.x + bounds.width / 2,
    bounds.y + bounds.height / 2,
  );
  await page.keyboard.up("Control");
  await expect(page.getByTestId("selection-count")).toHaveText("0 selected");
  await page.getByText("Overlapping hits (2)", { exact: true }).click();
  await page
    .getByRole("button", { name: "second beam / second", exact: true })
    .click();
  await expect(page.getByTestId("selection-count")).toHaveText("1 selected");
  await expect(
    page.getByRole("button", { name: "second beam / second", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
});

test("clipped triangles cannot be inspected and clipping preserves the export", async ({
  page,
}) => {
  await page.getByRole("button", { name: "Convert", exact: true }).click();
  await expect(page.getByRole("status")).toHaveText(/ready to export/);
  const canvas = page.getByLabel("Source 3D structural preview");
  await canvas.focus();
  await page.keyboard.press("i");
  await expect(page.getByTestId("source-block-inspector")).toBeVisible();
  await page.getByText("Clipping and layers", { exact: false }).click();
  await page.getByLabel("Clip axis", { exact: true }).selectOption("y");
  await page.getByLabel("Clip from", { exact: true }).fill("2");
  await canvas.focus();
  await page.keyboard.press("i");
  await expect(page.getByTestId("source-block-inspector")).not.toBeVisible();
  await expect(page.getByRole("button", { name: "Export file" })).toBeEnabled();
  await page.getByRole("button", { name: "Reset view filters" }).click();
  await canvas.focus();
  await page.keyboard.press("i");
  await expect(page.getByTestId("source-block-inspector")).toBeVisible();
});

test("materials can collapse by keyboard to give the previews more height", async ({
  page,
}) => {
  const toggle = page.getByRole("button", {
    name: "Build materials",
    exact: true,
  });
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  const canvas = page.getByLabel("Source 3D structural preview");
  const before = (await canvas.boundingBox())!.height;
  await toggle.focus();
  await page.keyboard.press("Enter");
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByTestId("material-list")).not.toBeVisible();
  await expect
    .poll(async () => (await canvas.boundingBox())!.height)
    .toBeGreaterThan(before);
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("material-list")).toBeVisible();
});

test("conversion actions stay fully visible with hollow settings and notices", async ({
  page,
}) => {
  await page.route("**/api/source", (route) =>
    route.fulfill({
      json: { source: display, notices: { "Example omitted detail": 4 } },
    }),
  );
  await page.getByLabel("Open structure file").setInputFiles({
    name: "notices.blueprint",
    mimeType: "application/json",
    buffer: Buffer.from("{}"),
  });
  await expect(page.getByRole("status")).toHaveText(/Source ready/);
  await page.getByLabel("Hollow interior", { exact: true }).check();
  await page.getByLabel("Shell thickness").selectOption("4");
  await page.getByText("Conversion notices (4)", { exact: true }).click();
  await expect(
    page.getByText("Example omitted detail", { exact: true }),
  ).toBeVisible();
  const convert = page.getByRole("button", { name: "Convert", exact: true });
  await expect(convert).toBeInViewport({ ratio: 1 });
  const before = (await convert.boundingBox())!;
  await page.locator(".settings-content").evaluate((element) => {
    element.scrollTop = element.scrollHeight;
  });
  await expect(convert).toBeInViewport({ ratio: 1 });
  expect((await convert.boundingBox())!.y).toBe(before.y);
  await page.route("**/api/status", (route) =>
    route.fulfill({ json: { state: "working", progress: 0.2, error: "" } }),
  );
  await page.route("**/api/cancel", (route) => route.fulfill({ json: {} }));
  await convert.click();
  const cancel = page.getByRole("button", {
    name: "Cancel conversion",
    exact: true,
  });
  await expect(cancel).toBeInViewport({ ratio: 1 });
  await expect(convert).toBeInViewport({ ratio: 1 });
  const convertBox = (await convert.boundingBox())!;
  const cancelBox = (await cancel.boundingBox())!;
  expect(convertBox.y + convertBox.height).toBeLessThanOrEqual(cancelBox.y);
  await cancel.click();
  await page.setViewportSize({ width: 600, height: 850 });
  await expect(convert).toBeInViewport({ ratio: 1 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth > innerWidth,
    ),
  ).toBe(false);
});

test("materials follow the selected preview and hollow options invalidate the result", async ({
  page,
}) => {
  await page
    .getByRole("button", { name: "Source materials", exact: true })
    .click();
  await expect(page.getByTestId("material-list")).toContainText("Steel beam");
  await expect(page.getByTestId("material-total")).toHaveText("1 source part");
  await page.getByRole("button", { name: "Convert", exact: true }).click();
  await expect(page.getByRole("status")).toHaveText(/ready to export/);
  await expect(
    page.getByRole("button", { name: "Converted materials", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("material-list")).toContainText(
    "minecraft:iron_block",
  );
  await expect(page.getByTestId("material-total")).toHaveText(
    "1 exported block",
  );
  await page.screenshot({
    path: "../artifacts/inspector-materials-laptop.png",
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth > innerWidth,
    ),
  ).toBe(false);
  await page.getByLabel("Search materials").fill("missing");
  await expect(page.getByText("No materials match your search.")).toBeVisible();
  await page.getByLabel("Hollow interior", { exact: true }).check();
  await expect(
    page.getByRole("button", { name: "Export file" }),
  ).toBeDisabled();
  await expect(page.getByRole("status")).toHaveText(/Options changed/);
  await expect(page.getByTestId("material-list")).not.toContainText(
    "minecraft:iron_block",
  );
  await page.getByLabel("Shell thickness").selectOption("2");
  const request = page.waitForRequest("**/api/convert");
  await page.getByRole("button", { name: "Convert", exact: true }).click();
  expect((await request).postDataJSON()).toMatchObject({
    hollow: true,
    shell_thickness: 2,
  });
});
