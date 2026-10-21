import * as T from "three";
import type { BlockIdentity, Display } from "../types";

export type HoveredBlock = BlockIdentity & { coordinate: number[] };
type Entry = {
  mesh: T.InstancedMesh;
  proxy: T.Mesh;
  instance: number;
  block: number;
  bounds: T.Box3;
};
type Bucket = { bounds: T.Box3; entries: Entry[] };

// Spatial buckets prune instances before exact triangle tests. Center-based buckets
// use the union of actual bounds, so long and rotated parts stay pickable.
export class BlockPicker {
  private buckets = new Map<string, Bucket>();
  private matrix = new T.Matrix4();
  private point = new T.Vector3();
  private raycaster = new T.Raycaster();
  private size: number;

  constructor(private model?: Display) {
    this.size = Math.max(1, ...(model?.dimensions ?? [1])) / 24;
  }

  add(mesh: T.InstancedMesh, blockIndices: number[]) {
    mesh.geometry.computeBoundingBox();
    const proxy = new T.Mesh(mesh.geometry, mesh.material);
    proxy.matrixAutoUpdate = false;
    for (let instance = 0; instance < mesh.count; instance++) {
      mesh.getMatrixAt(instance, this.matrix);
      const bounds = mesh.geometry
        .boundingBox!.clone()
        .applyMatrix4(this.matrix);
      const center = bounds.getCenter(this.point);
      const key = [center.x, center.y, center.z]
        .map((n) => Math.floor(n / this.size))
        .join(":");
      let bucket = this.buckets.get(key);
      if (!bucket) {
        bucket = { bounds: new T.Box3(), entries: [] };
        this.buckets.set(key, bucket);
      }
      bucket.bounds.union(bounds);
      bucket.entries.push({
        mesh,
        proxy,
        instance,
        block: blockIndices[instance],
        bounds,
      });
    }
  }

  pick(
    pointer: T.Vector2,
    camera: T.Camera,
  ): { block: HoveredBlock; bounds: T.Box3 } | undefined {
    this.raycaster.setFromCamera(pointer, camera);
    let closest = Infinity;
    let selected: Entry | undefined;
    const hits: T.Intersection[] = [];
    for (const bucket of this.buckets.values()) {
      if (!this.raycaster.ray.intersectsBox(bucket.bounds)) continue;
      for (const entry of bucket.entries) {
        if (!this.raycaster.ray.intersectsBox(entry.bounds)) continue;
        entry.mesh.getMatrixAt(entry.instance, this.matrix);
        entry.proxy.matrixWorld.copy(this.matrix);
        hits.length = 0;
        entry.proxy.raycast(this.raycaster, hits);
        for (const hit of hits) {
          if (hit.distance < closest) {
            closest = hit.distance;
            selected = entry;
          }
        }
      }
    }
    if (!selected) return;
    const identity = this.model?.blocks[selected.block];
    if (!identity) return;
    selected.mesh.getMatrixAt(selected.instance, this.matrix);
    return {
      block: {
        ...identity,
        coordinate: this.matrix.elements
          .slice(12, 15)
          .map((n) => (Math.abs(n) < 1e-6 ? 0 : Number(n.toFixed(3)))),
      },
      bounds: selected.bounds,
    };
  }
}
