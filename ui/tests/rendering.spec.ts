import { expect, test } from "@playwright/test";
import { inflateSync } from "node:zlib";
import path from "node:path";
import * as T from "three";
import type { Display } from "../src/types";
import {
  faces,
  surfaceGeometry,
  textureBatches,
} from "../src/viewer/TextureSurfaces";
import {
  orientedBatches,
  reflectGeometry,
  updateDepthRange,
} from "../src/viewer/InstanceGeometry";

test("reflected instance batches preserve world vertices and source indices", () => {
  const matrix = new T.Matrix4()
    .makeRotationY(0.7)
    .scale(new T.Vector3(-2, 3, 4))
    .setPosition(10, 20, 30);
  const group = {
    matrices: [...new T.Matrix4().elements, ...matrix.elements],
  } as Display["groups"][number];
  const batches = orientedBatches(group, {
    instances: [1, 0],
    textures: ["e", "w", "u", "d", "s", "n"],
  });
  expect(batches.map((b) => b.instances)).toEqual([[0], [1]]);
  const source = new T.BoxGeometry(),
    reflected = reflectGeometry(source);
  const positive = matrix.clone().scale(new T.Vector3(-1, 1, 1));
  expect(positive.determinant()).toBeGreaterThan(0);
  const originalPositions = source.getAttribute("position"),
    newPositions = reflected.getAttribute("position");
  for (let i = 0; i < originalPositions.count; i++) {
    const before = new T.Vector3()
      .fromBufferAttribute(originalPositions, i)
      .applyMatrix4(matrix);
    const after = new T.Vector3()
      .fromBufferAttribute(newPositions, i)
      .applyMatrix4(positive);
    expect(before.distanceTo(after)).toBeLessThan(1e-10);
  }
  const indices = reflected.index!,
    normals = reflected.getAttribute("normal");
  for (let i = 0; i < indices.count; i += 3) {
    const a = new T.Vector3().fromBufferAttribute(
      newPositions,
      indices.getX(i),
    );
    const b = new T.Vector3().fromBufferAttribute(
      newPositions,
      indices.getX(i + 1),
    );
    const c = new T.Vector3().fromBufferAttribute(
      newPositions,
      indices.getX(i + 2),
    );
    const normal = new T.Vector3().fromBufferAttribute(
      normals,
      indices.getX(i),
    );
    expect(b.sub(a).cross(c.sub(a)).dot(normal)).toBeGreaterThan(0);
  }
});

test("textured reflected faces match their world directions after batching", () => {
  for (const axis of [0, 1, 2])
    for (const angle of [0, 0.7, Math.PI / 2]) {
      const scale = new T.Vector3(2, 3, 4);
      scale.setComponent(axis, -scale.getComponent(axis));
      const original = new T.Matrix4().makeRotationY(angle).scale(scale);
      const group = {
        matrices: original.elements,
        colors: [1, 1, 1],
        block_indices: [0],
      } as Display["groups"][number];
      const blocks = [
        {
          name: "directional",
          material: "Stone",
          properties: {},
          textures: Object.fromEntries(faces.map((face) => [face, face])),
        },
      ];
      const geometry = reflectGeometry(surfaceGeometry(new T.BoxGeometry()));
      const positive = original.clone().scale(new T.Vector3(-1, 1, 1));
      const normalMatrix = new T.Matrix3().getNormalMatrix(positive);
      const batch = [...textureBatches(group, blocks, true)].flatMap((b) =>
        orientedBatches(group, b),
      )[0];
      for (const surface of geometry.groups) {
        const normal = new T.Vector3()
          .fromBufferAttribute(geometry.getAttribute("normal"), surface.start)
          .applyNormalMatrix(normalMatrix);
        const magnitude = normal.toArray().map(Math.abs);
        const direction = magnitude.indexOf(Math.max(...magnitude));
        const expected =
          faces[direction * 2 + (normal.getComponent(direction) < 0 ? 1 : 0)];
        expect(batch.textures[surface.materialIndex!]).toBe(expected);
      }
    }
});

test("depth range follows the inspected ship without clipping an interior camera", () => {
  const camera = new T.PerspectiveCamera(45, 1, 0.01, 100000);
  const bounds = new T.Box3(
    new T.Vector3(-100, 0, -150),
    new T.Vector3(100, 40, 150),
  );
  camera.position.set(0, 800, 0);
  updateDepthRange(camera, bounds);
  expect(camera.near).toBeGreaterThan(1);
  expect(camera.far).toBeGreaterThan(1000);
  expect(camera.far / camera.near).toBeLessThan(1000);
  camera.position.set(0, 20, 0);
  updateDepthRange(camera, bounds);
  expect(camera.near).toBe(0.001);
  expect(camera.far).toBeGreaterThan(300);
});

function pixels(png: Buffer) {
  let width = 0,
    height = 0,
    channels = 0;
  const compressed: Buffer[] = [];
  for (let offset = 8; offset < png.length; ) {
    const size = png.readUInt32BE(offset),
      name = png.toString("ascii", offset + 4, offset + 8);
    const body = png.subarray(offset + 8, offset + 8 + size);
    if (name === "IHDR") {
      width = body.readUInt32BE(0);
      height = body.readUInt32BE(4);
      expect(body[8]).toBe(8);
      channels = body[9] === 6 ? 4 : 3;
      expect([2, 6]).toContain(body[9]);
    }
    if (name === "IDAT") compressed.push(body);
    offset += size + 12;
  }
  const raw = inflateSync(Buffer.concat(compressed)),
    stride = width * channels;
  const data = Buffer.alloc(stride * height);
  for (let y = 0; y < height; y++) {
    const filter = raw[y * (stride + 1)];
    for (let x = 0; x < stride; x++) {
      const a = x >= channels ? data[y * stride + x - channels] : 0;
      const b = y ? data[(y - 1) * stride + x] : 0;
      const c = y && x >= channels ? data[(y - 1) * stride + x - channels] : 0;
      const p = a + b - c,
        distances = [Math.abs(p - a), Math.abs(p - b), Math.abs(p - c)];
      const predictor = [
        0,
        a,
        b,
        Math.floor((a + b) / 2),
        [a, b, c][distances.indexOf(Math.min(...distances))],
      ][filter];
      data[y * stride + x] = (raw[y * (stride + 1) + 1 + x] + predictor) & 255;
    }
  }
  return { width, height, channels, data };
}

test("upside-down slope roofs retain the same upward lighting as a full block", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Open file", exact: true }),
  ).toBeEnabled();
  await page
    .getByLabel("Open structure file")
    .setInputFiles(path.resolve("../tests/fixtures/roof-reflections.nbt"));
  await expect(page.getByRole("status")).toHaveText(/Source ready/);
  await page.getByRole("button", { name: "Top", exact: true }).click();
  await page.evaluate(
    () =>
      new Promise<void>((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
      ),
  );
  const canvas = page.getByLabel("Source 3D structural preview", {
    exact: true,
  });
  const screenshot = await canvas.screenshot();
  const image = pixels(screenshot);
  const bright = [0, 0];
  for (let y = 60; y < image.height - 30; y++)
    for (let x = 0; x < image.width; x++) {
      const index = (y * image.width + x) * image.channels;
      if (
        image.data[index] > 250 &&
        image.data[index + 1] > 250 &&
        image.data[index + 2] > 250
      )
        bright[x < image.width / 2 ? 0 : 1]++;
    }
  console.log("white roof pixels", bright);
  await page.screenshot({
    path: `../artifacts/upscale-quality/reflected-roof-${process.env.RENDER_PHASE ?? "before"}.png`,
  });
  expect(Math.min(...bright) / Math.max(...bright)).toBeGreaterThan(0.85);
});
