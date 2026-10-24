import { expect, test } from "@playwright/test";
import * as T from "three";
import { faces, textureBatches } from "../src/viewer/TextureSurfaces";
import type { Display, BlockIdentity } from "../src/types";

function reference(
  group: Display["groups"][number],
  blocks: BlockIdentity[],
  enabled: boolean,
) {
  const batches = new Map<
    string,
    { instances: number[]; textures: (string | undefined)[] }
  >();
  const normals = [
    [1, 0, 0],
    [-1, 0, 0],
    [0, 1, 0],
    [0, -1, 0],
    [0, 0, 1],
    [0, 0, -1],
  ];
  for (let i = 0; i < group.colors.length / 3; i++) {
    const textures = enabled
      ? blocks[group.block_indices[i]]?.textures
      : undefined;
    const matrix = new T.Matrix4().fromArray(group.matrices, i * 16);
    const keys = textures
      ? normals.map((axis) => {
          const normal = new T.Vector3(...axis).transformDirection(matrix);
          const values = [
            Math.abs(normal.x),
            Math.abs(normal.y),
            Math.abs(normal.z),
          ];
          const largest = values.indexOf(Math.max(...values));
          return textures[
            faces[largest * 2 + (normal.getComponent(largest) < 0 ? 1 : 0)]
          ];
        })
      : [];
    const key = JSON.stringify(keys);
    if (!batches.has(key)) batches.set(key, { instances: [], textures: keys });
    batches.get(key)!.instances.push(i);
  }
  return [...batches.values()];
}

function group(count: number): Display["groups"][number] {
  const matrices: number[] = [];
  for (let i = 0; i < count; i++) {
    const matrix = new T.Matrix4().makeRotationY(((i % 8) * Math.PI) / 4);
    matrix.setPosition(i, -i, 3 * i);
    matrices.push(...matrix.elements);
  }
  return {
    shape: "box",
    transparent: false,
    matrices,
    colors: Array(count * 3).fill(0.5),
    block_indices: Array(count).fill(0),
  };
}

test("uniform textures avoid orientation work and keep exact batching", () => {
  const sample = group(1000);
  const blocks = [
    {
      name: "test:block",
      material: "Stone",
      properties: {},
      textures: Object.fromEntries(faces.map((face) => [face, "same"])),
    },
  ];
  const expected = reference(sample, blocks, true);
  const original = T.Vector3.prototype.transformDirection;
  let calls = 0;
  T.Vector3.prototype.transformDirection = function (matrix) {
    calls++;
    return original.call(this, matrix);
  };
  try {
    expect([...textureBatches(sample, blocks, true)]).toEqual(expected);
    expect(calls).toBe(0);
  } finally {
    T.Vector3.prototype.transformDirection = original;
  }
});

test("texture batches preserve order and orientation for partial and varied faces", () => {
  const sample = group(100);
  const variants = [
    undefined,
    {},
    { east: "one" },
    Object.fromEntries(faces.map((face, i) => [face, String(i)])),
  ];
  for (const textures of variants) {
    const blocks = [
      { name: "test:block", material: "Stone", properties: {}, textures },
    ];
    for (const enabled of [true, false])
      expect([...textureBatches(sample, blocks, enabled)]).toEqual(
        reference(sample, blocks, enabled),
      );
  }
});
