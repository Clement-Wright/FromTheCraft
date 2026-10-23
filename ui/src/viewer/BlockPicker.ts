import * as T from "three";
import type { BlockIdentity, Display } from "../types";

export type HoveredBlock = BlockIdentity & {
  coordinate: number[];
  source_id?: string | null;
};
type Entry = {
  mesh: T.InstancedMesh;
  proxy: T.Mesh;
  instance: number;
  block: number;
  bounds: T.Box3;
  sourceId?: string | null;
};
type Bucket = { bounds: T.Box3; entries: Entry[] };

// Spatial buckets prune instances before exact triangle tests. Center-based buckets
// use the union of actual bounds, so long and rotated parts stay pickable.
export class BlockPicker {
  clippingPlanes: T.Plane[] = [];
  private buckets = new Map<string, Bucket>();
  private matrix = new T.Matrix4();
  private point = new T.Vector3();
  private raycaster = new T.Raycaster();
  private size: number;

  constructor(private model?: Display) {
    this.size = Math.max(1, ...(model?.dimensions ?? [1])) / 24;
  }

  add(
    mesh: T.InstancedMesh,
    blockIndices: number[],
    sourceIds: (string | null)[] = [],
  ) {
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
        sourceId: sourceIds[instance],
      });
    }
  }

  pick(
    pointer: T.Vector2,
    camera: T.Camera,
  ): { block: HoveredBlock; bounds: T.Box3 } | undefined {
    return this.pickAll(pointer, camera)[0];
  }

  pickAll(
    pointer: T.Vector2,
    camera: T.Camera,
  ): { block: HoveredBlock; bounds: T.Box3 }[] {
    this.raycaster.setFromCamera(pointer, camera);
    const selected: { entry: Entry; distance: number }[] = [];
    const hits: T.Intersection[] = [];
    for (const bucket of this.buckets.values()) {
      if (!this.raycaster.ray.intersectsBox(bucket.bounds)) continue;
      for (const entry of bucket.entries) {
        if (!this.raycaster.ray.intersectsBox(entry.bounds)) continue;
        entry.mesh.getMatrixAt(entry.instance, this.matrix);
        entry.proxy.matrixWorld.copy(this.matrix);
        hits.length = 0;
        entry.proxy.raycast(this.raycaster, hits);
        const visible = hits.filter((hit) =>
          this.clippingPlanes.every(
            (plane) => plane.distanceToPoint(hit.point) >= -1e-6,
          ),
        );
        if (visible.length)
          selected.push({
            entry,
            distance: Math.min(...visible.map((hit) => hit.distance)),
          });
      }
    }
    return selected
      .sort((a, b) => a.distance - b.distance)
      .slice(0, 128)
      .flatMap(({ entry }) => {
        const identity = this.model?.blocks[entry.block];
        if (!identity) return [];
        entry.mesh.getMatrixAt(entry.instance, this.matrix);
        return [
          {
            block: {
              ...identity,
              source_id: entry.sourceId,
              coordinate: this.matrix.elements
                .slice(12, 15)
                .map((n) => (Math.abs(n) < 1e-6 ? 0 : Number(n.toFixed(3)))),
            },
            bounds: entry.bounds,
          },
        ];
      });
  }
}
