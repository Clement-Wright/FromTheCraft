import { expect, test } from "@playwright/test";
import { deflateSync } from "node:zlib";

function png() {
  function crc(bytes: Buffer) {
    let value = 0xffffffff;
    for (const byte of bytes) {
      value ^= byte;
      for (let i = 0; i < 8; i++)
        value = (value >>> 1) ^ (value & 1 ? 0xedb88320 : 0);
    }
    return (value ^ 0xffffffff) >>> 0;
  }
  const chunk = (kind: string, content: Buffer) => {
    const size = Buffer.alloc(4);
    size.writeUInt32BE(content.length);
    const body = Buffer.concat([Buffer.from(kind), content]);
    const checksum = Buffer.alloc(4);
    checksum.writeUInt32BE(crc(body));
    return Buffer.concat([size, body, checksum]);
  };
  const header = Buffer.from([0, 0, 0, 1, 0, 0, 0, 1, 8, 6, 0, 0, 0]);
  return Buffer.concat([
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
    chunk("IHDR", header),
    chunk("IDAT", deflateSync(Buffer.from([0, 255, 0, 255, 255]))),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

const textureStatus = {
  available: true,
  minecraft: { available: true, sources: [], reasons: [] },
  ftd: {
    available: false,
    sources: [],
    reasons: ["FtD Unity Resources images unavailable."],
  },
  reasons: ["FtD Unity Resources images unavailable."],
};
const model = {
  format: "blueprint",
  version: "test",
  count: 1,
  bounds: [
    [0, 0, 0],
    [1, 1, 1],
  ],
  dimensions: [1, 1, 1],
  groups: [
    {
      shape: "cube",
      transparent: false,
      matrices: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
      colors: [0.5, 0.6, 0.7],
      block_indices: [0],
    },
  ],
  blocks: [
    {
      name: "minecraft:stone",
      material: "Stone",
      properties: {},
      textures: Object.fromEntries(
        ["east", "west", "up", "down", "north", "south"].map((face) => [
          face,
          "original-texture",
        ]),
      ),
    },
  ],
  materials: [
    { name: "minecraft:stone", material: "Stone", properties: {}, count: 1 },
  ],
};

test.beforeEach(async ({ page }) => {
  await page.route("**/api/session", (route) =>
    route.fulfill({
      json: {
        token: "test",
        can_close: false,
        textures: textureStatus,
        mod_choices: [
          {
            slug: "copycats",
            label: "Copycats",
            version: "test",
            dependencies: [],
          },
        ],
      },
    }),
  );
  await page.route("**/api/source", (route) =>
    route.fulfill({ json: { source: model, notices: {} } }),
  );
  await page.route("**/api/invalidate", (route) => route.fulfill({ json: {} }));
  await page.route("**/api/convert", (route) => route.fulfill({ json: {} }));
  await page.route("**/api/status", (route) =>
    route.fulfill({
      json: {
        state: "ready",
        progress: 1,
        error: "",
        result_id: "test",
        converted: { ...model, format: "nbt" },
      },
    }),
  );
  await page.route("**/api/textures/*?*", (route) =>
    route.fulfill({ contentType: "image/png", body: png() }),
  );
  await page.route("**/api/textures?*", (route) =>
    route.fulfill({
      json: {
        source: model,
        converted: { ...model, format: "nbt" },
        textures: textureStatus,
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

test("real image bytes change the texture view and loading assets preserves the export", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.getByRole("button", { name: "Convert", exact: true }).click();
  await expect(page.getByRole("status")).toHaveText(/ready to export/);
  const canvas = page.getByLabel("Converted 3D structural preview");
  const flat = await canvas.screenshot();
  const image = page.waitForResponse((response) =>
    response.url().includes("/api/textures/original-texture?token=test"),
  );
  await page.getByLabel("Display textures", { exact: true }).check();
  expect((await image).ok()).toBe(true);
  await expect
    .poll(async () => !(await canvas.screenshot()).equals(flat))
    .toBe(true);
  await page.getByLabel("Display textures", { exact: true }).uncheck();
  await expect
    .poll(async () => (await canvas.screenshot()).equals(flat))
    .toBe(true);
  await page.getByLabel("Load texture archive").setInputFiles({
    name: "original.zip",
    mimeType: "application/zip",
    buffer: Buffer.from("original test upload"),
  });
  await expect(
    page.getByLabel("Display textures", { exact: true }),
  ).toBeChecked();
  await expect(page.getByRole("button", { name: "Export file" })).toBeEnabled();
  await page
    .getByText("Texture assets: Minecraft available; FtD unavailable", {
      exact: true,
    })
    .click();
  await expect(
    page.getByText("FtD Unity Resources images unavailable.", { exact: true }),
  ).toBeVisible();
  expect(errors).toEqual([]);
});

test("Detailed Copycats is opt-in, requires the selected mod, and invalidates output", async ({
  page,
}) => {
  const option = page.getByLabel("Detailed Copycats", { exact: true });
  await expect(option).not.toBeChecked();
  await expect(option).toBeDisabled();
  await page.locator(".mod-picker summary").click();
  await page.getByLabel("Copycats", { exact: true }).check();
  await expect(option).toBeEnabled();
  await option.check();
  const request = page.waitForRequest("**/api/convert");
  await page.getByRole("button", { name: "Convert", exact: true }).click();
  expect((await request).postDataJSON()).toMatchObject({
    detailed_copycats: true,
    mods: ["copycats"],
  });
  await expect(page.getByRole("status")).toHaveText(/ready to export/);
  await option.uncheck();
  await expect(
    page.getByRole("button", { name: "Export file" }),
  ).toBeDisabled();
  await expect(page.getByRole("status")).toHaveText(/Options changed/);
});

test("unavailable image requests retain the flat-color fallback", async ({
  page,
}) => {
  await page.route("**/api/textures/*?*", (route) =>
    route.fulfill({ status: 404, body: "Missing texture" }),
  );
  const canvas = page.getByLabel("Source 3D structural preview");
  const box = (await canvas.boundingBox())!;
  const surface = () =>
    page.screenshot({
      clip: {
        x: box.x + box.width * 0.2,
        y: box.y + box.height * 0.2,
        width: box.width * 0.6,
        height: box.height * 0.4,
      },
    });
  const flat = await surface();
  await page.getByLabel("Display textures", { exact: true }).check();
  await expect(page.getByRole("alert")).toContainText(
    "Some texture images could not load",
  );
  await expect.poll(async () => (await surface()).equals(flat)).toBe(true);
});

test("mixed Copycat material slots remain searchable while counting one host block", async ({
  page,
}) => {
  const materials = [
    {
      slot: "bottom_northwest",
      name: "minecraft:red_concrete",
      properties: {},
    },
    { slot: "top_southeast", name: "minecraft:glass", properties: {} },
  ];
  const block = {
    name: "copycats:copycat_byte",
    material: "Mixed",
    properties: {},
    copied_materials: materials,
  };
  await page.route("**/api/status", (route) =>
    route.fulfill({
      json: {
        state: "ready",
        progress: 1,
        error: "",
        result_id: "mixed",
        converted: {
          ...model,
          format: "nbt",
          blocks: [block],
          materials: [{ ...block, count: 1 }],
        },
      },
    }),
  );
  await page.getByRole("button", { name: "Convert", exact: true }).click();
  await expect(page.getByRole("status")).toHaveText(/ready to export/);
  await expect(page.getByTestId("material-total")).toHaveText(
    "1 exported block",
  );
  await expect(page.getByTestId("material-list")).toContainText(
    "bottom_northwest: minecraft:red_concrete",
  );
  await page.getByLabel("Search materials").fill("top_southeast");
  await expect(page.getByTestId("material-list")).toContainText(
    "minecraft:glass",
  );
  await page.getByLabel("Converted 3D structural preview").focus();
  await page.keyboard.press("i");
  await expect(page.getByTestId("converted-block-inspector")).toContainText(
    "top_southeast: minecraft:glass",
  );
});
