import * as T from "three";
import type { BlockIdentity, Display } from "../types";

export const faces = ["east", "west", "up", "down", "south", "north"] as const;
const normals = [
  new T.Vector3(1, 0, 0),
  new T.Vector3(-1, 0, 0),
  new T.Vector3(0, 1, 0),
  new T.Vector3(0, -1, 0),
  new T.Vector3(0, 0, 1),
  new T.Vector3(0, 0, -1),
];

function faceIndex(normal: T.Vector3) {
  const axis = [Math.abs(normal.x), Math.abs(normal.y), Math.abs(normal.z)];
  const largest = axis.indexOf(Math.max(...axis));
  return largest * 2 + (normal.getComponent(largest) < 0 ? 1 : 0);
}

export function textureBatches(
  group: Display["groups"][number],
  blocks: BlockIdentity[],
  enabled: boolean,
) {
  const batches = new Map<
    string,
    { instances: number[]; textures: (string | undefined)[] }
  >();
  const matrix = new T.Matrix4();
  const normal = new T.Vector3();
  for (let instance = 0; instance < group.colors.length / 3; instance++) {
    const textures = enabled
      ? blocks[group.block_indices[instance]]?.textures
      : undefined;
    matrix.fromArray(group.matrices, instance * 16);
    const keys = textures
      ? normals.map(
          (axis) =>
            textures[
              faces[faceIndex(normal.copy(axis).transformDirection(matrix))]
            ],
        )
      : [];
    const signature = JSON.stringify(keys);
    let batch = batches.get(signature);
    if (!batch) {
      batch = { instances: [], textures: keys };
      batches.set(signature, batch);
    }
    batch.instances.push(instance);
  }
  return batches.values();
}

export function surfaceGeometry(original: T.BufferGeometry) {
  const geometry = original.index ? original.toNonIndexed() : original.clone();
  const positions = geometry.getAttribute("position");
  const normals = geometry.getAttribute("normal");
  const uv = new Float32Array(positions.count * 2);
  const normal = new T.Vector3();
  geometry.clearGroups();
  for (let vertex = 0; vertex < positions.count; vertex += 3) {
    const face = faceIndex(normal.fromBufferAttribute(normals, vertex));
    const previous = geometry.groups.at(-1);
    if (previous?.materialIndex === face) previous.count += 3;
    else geometry.addGroup(vertex, 3, face);
    for (let i = vertex; i < vertex + 3; i++) {
      const x = positions.getX(i),
        y = positions.getY(i),
        z = positions.getZ(i);
      const coordinates = face < 2 ? [z, y] : face < 4 ? [x, z] : [x, y];
      uv[i * 2] = coordinates[0];
      uv[i * 2 + 1] = coordinates[1];
    }
  }
  geometry.setAttribute("uv", new T.BufferAttribute(uv, 2));
  return geometry;
}
