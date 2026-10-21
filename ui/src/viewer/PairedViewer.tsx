import { useEffect, useRef, useState } from "react";
import * as T from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import type { Display } from "../types";

function boxes(pieces: [number[], number[]][]) {
  const positions: number[] = [];
  for (const [size, offset] of pieces) {
    const geometry = new T.BoxGeometry(
      size[0],
      size[1],
      size[2],
    ).toNonIndexed();
    geometry.translate(
      ...(offset.map((n, i) => n + size[i] / 2) as [number, number, number]),
    );
    positions.push(...geometry.getAttribute("position").array);
    geometry.dispose();
  }
  const geometry = new T.BufferGeometry();
  geometry.setAttribute("position", new T.Float32BufferAttribute(positions, 3));
  geometry.computeVertexNormals();
  return geometry;
}

function shapeGeometry(shape: string) {
  if (shape.startsWith("stairs")) {
    const pieces: [number[], number[]][] = [
      [
        [1, 0.5, 1],
        [0, 0, 0],
      ],
    ];
    if (shape.includes("outer")) {
      pieces.push([
        [0.5, 0.5, 0.5],
        [shape.endsWith("left") ? 0.5 : 0, 0.5, 0.5],
      ]);
    } else {
      pieces.push([
        [1, 0.5, 0.5],
        [0, 0.5, 0.5],
      ]);
      if (shape.includes("inner"))
        pieces.push([
          [0.5, 0.5, 0.5],
          [shape.endsWith("left") ? 0.5 : 0, 0.5, 0],
        ]);
    }
    return boxes(pieces);
  }
  if (shape === "wedge" || shape === "curve") {
    const polygon = new T.Shape();
    polygon.moveTo(0, 0);
    polygon.lineTo(1, 0);
    polygon.lineTo(1, 1);
    if (shape === "curve") {
      for (let i = 11; i >= 0; i--) {
        const angle = ((i / 12) * Math.PI) / 2;
        polygon.lineTo(1 - Math.cos(angle), Math.sin(angle));
      }
    }
    polygon.closePath();
    const geometry = new T.ExtrudeGeometry(polygon, {
      depth: 1,
      bevelEnabled: false,
      steps: 1,
    });
    // Shape x/y become local z/y; extrusion becomes local x.
    geometry.applyMatrix4(
      new T.Matrix4().set(0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0, 0, 0, 1),
    );
    return geometry;
  }
  if (shape === "corner") {
    const vertices = [0, 0, 0, 1, 0, 0, 1, 0, 1, 0, 0, 1, 1, 1, 1];
    const geometry = new T.BufferGeometry();
    geometry.setAttribute(
      "position",
      new T.Float32BufferAttribute(vertices, 3),
    );
    geometry.setIndex([0, 2, 1, 0, 3, 2, 0, 1, 4, 1, 2, 4, 2, 3, 4, 3, 0, 4]);
    geometry.computeVertexNormals();
    return geometry;
  }
  return boxes([
    [
      [1, 1, 1],
      [0, 0, 0],
    ],
  ]);
}

type View = {
  camera: T.PerspectiveCamera;
  controls: OrbitControls;
  render: () => void;
  renderer: T.WebGLRenderer;
};
type Props = {
  source?: Display;
  converted?: Display;
  linked: boolean;
  view: string;
  reset: number;
};

export default function PairedViewer({
  source,
  converted,
  linked,
  view,
  reset,
}: Props) {
  const hosts = [useRef<HTMLDivElement>(null), useRef<HTMLDivElement>(null)];
  const views = useRef<View[]>([]);
  const linkedRef = useRef(linked);
  const [error, setError] = useState("");
  linkedRef.current = linked;

  useEffect(() => {
    const cleanup: (() => void)[] = [];
    let syncing = false;
    const models = [source, converted];
    try {
      hosts.forEach((host, index) => {
        const element = host.current!;
        const renderer = new T.WebGLRenderer({ antialias: true, alpha: false });
        renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));
        renderer.setClearColor("#eceeea");
        renderer.domElement.setAttribute(
          "aria-label",
          index === 0
            ? "Source 3D structural preview"
            : "Converted 3D structural preview",
        );
        renderer.domElement.setAttribute("tabindex", "0");
        element.appendChild(renderer.domElement);
        const scene = new T.Scene();
        scene.add(new T.HemisphereLight(0xffffff, 0x8a9389, 2.6));
        const sun = new T.DirectionalLight(0xffffff, 2.2);
        sun.position.set(10, 20, 15);
        scene.add(sun);
        const camera = new T.PerspectiveCamera(45, 1, 0.01, 100000);
        const controls = new OrbitControls(camera, renderer.domElement);
        controls.enableDamping = false;
        controls.screenSpacePanning = true;
        controls.listenToKeyEvents(renderer.domElement);
        const resources: { dispose: () => void }[] = [];
        for (const group of models[index]?.groups ?? []) {
          const geometry = shapeGeometry(group.shape);
          const material = new T.MeshStandardMaterial({
            roughness: 0.84,
            metalness: 0.02,
            transparent: group.transparent,
            opacity: group.transparent ? 0.48 : 1,
            depthWrite: !group.transparent,
            side: T.DoubleSide,
          });
          const mesh = new T.InstancedMesh(
            geometry,
            material,
            group.colors.length / 3,
          );
          const matrix = new T.Matrix4();
          const color = new T.Color();
          for (let i = 0; i < mesh.count; i++) {
            matrix.fromArray(group.matrices, i * 16);
            mesh.setMatrixAt(i, matrix);
            color.setRGB(
              group.colors[i * 3],
              group.colors[i * 3 + 1],
              group.colors[i * 3 + 2],
              T.SRGBColorSpace,
            );
            mesh.setColorAt(i, color);
          }
          mesh.instanceMatrix.needsUpdate = true;
          mesh.computeBoundingSphere();
          scene.add(mesh);
          resources.push(mesh, geometry, material);
        }
        const bounds = new T.Box3();
        for (const model of models)
          if (model?.count) {
            bounds.expandByPoint(
              new T.Vector3(...(model.bounds[0] as [number, number, number])),
            );
            bounds.expandByPoint(
              new T.Vector3(...(model.bounds[1] as [number, number, number])),
            );
          }
        if (bounds.isEmpty())
          bounds.set(new T.Vector3(-5, 0, -5), new T.Vector3(5, 5, 5));
        const center = bounds.getCenter(new T.Vector3());
        const span = Math.max(5, bounds.getSize(new T.Vector3()).length());
        const grid = new T.GridHelper(
          Math.ceil(span * 2),
          20,
          0xb6c2b6,
          0xd6dcd3,
        );
        grid.position.set(center.x, bounds.min.y - 0.03, center.z);
        scene.add(grid);
        resources.push(
          grid.geometry,
          ...(Array.isArray(grid.material) ? grid.material : [grid.material]),
        );
        const axes = new T.AxesHelper(Math.min(span / 4, 8));
        axes.position.copy(bounds.min);
        scene.add(axes);
        resources.push(
          axes.geometry,
          ...(Array.isArray(axes.material) ? axes.material : [axes.material]),
        );
        const direction =
          view === "top"
            ? new T.Vector3(0, 1, 0.0001)
            : view === "front"
              ? new T.Vector3(0, 0, 1)
              : view === "side"
                ? new T.Vector3(1, 0, 0)
                : new T.Vector3(1, 0.7, 1);
        camera.position
          .copy(center)
          .add(direction.normalize().multiplyScalar(span * 1.45));
        camera.up.set(0, 1, 0);
        controls.target.copy(center);
        controls.update();
        const render = () => renderer.render(scene, camera);
        const current: View = { camera, controls, render, renderer };
        views.current[index] = current;
        const change = () => {
          if (syncing) return;
          render();
          if (linkedRef.current) {
            syncing = true;
            const other = views.current[1 - index];
            if (other) {
              other.camera.position.copy(camera.position);
              other.camera.quaternion.copy(camera.quaternion);
              other.controls.target.copy(controls.target);
              other.controls.update();
              other.render();
            }
            syncing = false;
          }
        };
        controls.addEventListener("change", change);
        const resize = new ResizeObserver(() => {
          const width = Math.max(1, element.clientWidth),
            height = Math.max(1, element.clientHeight);
          renderer.setSize(width, height);
          camera.aspect = width / height;
          camera.updateProjectionMatrix();
          render();
        });
        resize.observe(element);
        cleanup.push(() => {
          resize.disconnect();
          controls.dispose();
          for (const resource of resources) resource.dispose();
          renderer.dispose();
          renderer.forceContextLoss();
          renderer.domElement.remove();
        });
      });
    } catch (problem) {
      setError(
        `3D preview unavailable: ${problem instanceof Error ? problem.message : String(problem)}`,
      );
    }
    return () => {
      for (const dispose of cleanup) dispose();
      views.current = [];
    };
  }, [source, converted, view, reset]);

  useEffect(() => {
    if (linked && views.current.length === 2) {
      const [a, b] = views.current;
      b.camera.position.copy(a.camera.position);
      b.controls.target.copy(a.controls.target);
      b.controls.update();
      b.render();
    }
  }, [linked]);

  return (
    <div className="paired-views">
      {[source, converted].map((model, index) => (
        <section
          className="viewport"
          key={index}
          aria-label={index === 0 ? "Source view" : "Converted view"}
        >
          <header>
            <h2>{index === 0 ? "Source" : "Converted"}</h2>
            <span>
              {model
                ? model.format === "blueprint"
                  ? "From the Depths"
                  : model.format === "nbt"
                    ? "Create NBT"
                    : "Litematic"
                : "No file"}
            </span>
          </header>
          <div className="canvas-host" ref={hosts[index]} />
          {!model && (
            <div className="viewport-empty">
              <strong>
                {index === 0 ? "Open a structure" : "Your converted structure"}
              </strong>
              <p>
                {index === 0
                  ? "Drop a .blueprint, .nbt, or .litematic file here."
                  : "Convert to compare the exported geometry."}
              </p>
            </div>
          )}
          {model && model.count === 0 && (
            <div className="viewport-empty">
              No structural blocks to display.
            </div>
          )}
          <footer>
            <span>
              {model
                ? `${model.count.toLocaleString()} primitives / ${model.dimensions.join(" × ")}`
                : "Structural preview"}
            </span>
            <span>X right / Y up / Z forward</span>
          </footer>
        </section>
      ))}
      {error && (
        <p role="alert" className="viewer-error">
          {error}
        </p>
      )}
    </div>
  );
}
