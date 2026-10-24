import * as T from "three";
import type { Display } from "../types";

type Batch = { instances: number[]; textures: (string | undefined)[] };

export function orientedBatches(
  group: Display["groups"][number],
  batch: Batch,
) {
  const positive: number[] = [],
    reflected: number[] = [];
  const m = group.matrices;
  for (const index of batch.instances) {
    const o = index * 16;
    const determinant =
      m[o] * (m[o + 5] * m[o + 10] - m[o + 9] * m[o + 6]) -
      m[o + 4] * (m[o + 1] * m[o + 10] - m[o + 9] * m[o + 2]) +
      m[o + 8] * (m[o + 1] * m[o + 6] - m[o + 5] * m[o + 2]);
    (determinant < 0 ? reflected : positive).push(index);
  }
  const result = [];
  if (positive.length)
    result.push({
      instances: positive,
      textures: batch.textures,
      mirrored: false,
    });
  if (reflected.length) {
    result.push({
      instances: reflected,
      mirrored: true,
      // Geometry keeps its material groups. textureBatches already mapped each
      // original group through the reflected instance to its world-facing key.
      textures: batch.textures,
    });
  }
  return result;
}

export function reflectGeometry(source: T.BufferGeometry) {
  const geometry = source.clone().scale(-1, 1, 1);
  if (!geometry.index)
    geometry.setIndex(
      Array.from(
        { length: geometry.getAttribute("position").count },
        (_, i) => i,
      ),
    );
  const indices = geometry.index!;
  for (let i = 0; i < indices.count; i += 3) {
    const second = indices.getX(i + 1);
    indices.setX(i + 1, indices.getX(i + 2));
    indices.setX(i + 2, second);
  }
  indices.needsUpdate = true;
  return geometry;
}

const center = new T.Vector3(),
  size = new T.Vector3();
export function updateDepthRange(camera: T.PerspectiveCamera, bounds: T.Box3) {
  const distance = camera.position.distanceTo(bounds.getCenter(center));
  const radius = bounds.getSize(size).length() / 2;
  const near = Math.max(
    0.001,
    Math.min(distance * 0.02, bounds.distanceToPoint(camera.position) * 0.5),
  );
  const far = Math.max(10, near * 2, distance + radius * 4);
  if (near !== camera.near || far !== camera.far) {
    camera.near = near;
    camera.far = far;
    camera.updateProjectionMatrix();
  }
}
