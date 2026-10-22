import { useEffect, useRef, useState } from "react";
import * as T from "three";
import { blockStateText, copiedMaterialsText } from "../blockState";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { ConvexGeometry } from "three/addons/geometries/ConvexGeometry.js";
import type { Display } from "../types";
import { BlockPicker, type HoveredBlock } from "./BlockPicker";
import { surfaceGeometry, textureBatches } from "./TextureSurfaces";

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

function fitDistance(
  bounds: T.Box3,
  direction: T.Vector3,
  aspect: number,
  fov: number,
) {
  const center = bounds.getCenter(new T.Vector3());
  const away = direction.clone().normalize();
  const right = new T.Vector3()
    .crossVectors(new T.Vector3(0, 1, 0), away)
    .normalize();
  const up = new T.Vector3().crossVectors(away, right);
  const vertical = Math.tan(T.MathUtils.degToRad(fov / 2));
  const horizontal = vertical * aspect;
  let distance = 0.1;
  for (const x of [bounds.min.x, bounds.max.x]) {
    for (const y of [bounds.min.y, bounds.max.y]) {
      for (const z of [bounds.min.z, bounds.max.z]) {
        const corner = new T.Vector3(x, y, z).sub(center);
        distance = Math.max(
          distance,
          corner.dot(away) +
            1.12 *
              Math.max(
                Math.abs(corner.dot(right)) / horizontal,
                Math.abs(corner.dot(up)) / vertical,
              ),
        );
      }
    }
  }
  return distance;
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
  displayTextures?: boolean;
  textureToken?: string;
};

export default function PairedViewer({
  source,
  converted,
  linked,
  view,
  reset,
  displayTextures = false,
  textureToken = "",
}: Props) {
  const hosts = [useRef<HTMLDivElement>(null), useRef<HTMLDivElement>(null)];
  const views = useRef<View[]>([]);
  const linkedRef = useRef(linked);
  const [error, setError] = useState("");
  const [hovered, setHovered] = useState<(HoveredBlock | undefined)[]>([]);
  linkedRef.current = linked;

  useEffect(() => {
    setHovered([]);
    setError("");
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
        renderer.domElement.setAttribute(
          "aria-description",
          "Drag to orbit. Arrow keys pan. Hover a block to inspect it, or press I to inspect the center. Escape clears inspection.",
        );
        element.appendChild(renderer.domElement);
        const scene = new T.Scene();
        scene.add(new T.HemisphereLight(0xffffff, 0x8a9389, 2.6));
        const sun = new T.DirectionalLight(0xffffff, 2.2);
        sun.position.set(10, 20, 15);
        scene.add(sun);
        const commonAspect = () =>
          Math.min(
            ...hosts.map(
              (host) =>
                Math.max(1, host.current!.clientWidth) /
                Math.max(1, host.current!.clientHeight),
            ),
          );
        let frameAspect = commonAspect();
        const camera = new T.PerspectiveCamera(45, frameAspect, 0.01, 100000);
        const controls = new OrbitControls(camera, renderer.domElement);
        controls.enableDamping = false;
        controls.screenSpacePanning = true;
        controls.listenToKeyEvents(renderer.domElement);
        const resources: { dispose: () => void }[] = [];
        const picker = new BlockPicker(models[index]);
        let disposed = false;
        const textures = new Map<string, T.Texture>();
        const imageLoader = new T.ImageLoader();
        const textureQueue: { key: string; texture: T.Texture }[] = [];
        let activeImages = 0;
        let textureBytes = 0;
        const unavailableTexture = (key: string, message: string) => {
          if (disposed) return;
          scene.traverse((object) => {
            if (!(object instanceof T.Mesh)) return;
            const surfaces = Array.isArray(object.material)
              ? object.material
              : [object.material];
            for (const surface of surfaces) {
              if (
                surface instanceof T.MeshStandardMaterial &&
                surface.map === textures.get(key)
              ) {
                surface.map = null;
                surface.needsUpdate = true;
              }
            }
          });
          setError(message);
        };
        const loadImages = () => {
          while (!disposed && activeImages < 4 && textureQueue.length) {
            const { key, texture } = textureQueue.shift()!;
            activeImages++;
            imageLoader.load(
              `/api/textures/${encodeURIComponent(key)}?token=${encodeURIComponent(textureToken)}`,
              (image) => {
                activeImages--;
                const bytes = (image.width * image.height * 4 * 4) / 3;
                if (
                  !disposed &&
                  textureBytes + bytes <= 64 * 1024 * 1024 &&
                  image.width <= 2048 &&
                  image.height <= 2048
                ) {
                  textureBytes += bytes;
                  texture.image = image;
                  texture.needsUpdate = true;
                  scene.traverse((object) => {
                    if (!(object instanceof T.Mesh)) return;
                    const surfaces = Array.isArray(object.material)
                      ? object.material
                      : [object.material];
                    for (const surface of surfaces) {
                      if (
                        surface instanceof T.MeshStandardMaterial &&
                        surface.userData.previewTexture === texture
                      ) {
                        surface.map = texture;
                        surface.needsUpdate = true;
                      }
                    }
                  });
                } else
                  unavailableTexture(
                    key,
                    "Texture memory limit reached. Remaining surfaces use flat colors.",
                  );
                loadImages();
              },
              undefined,
              () => {
                activeImages--;
                unavailableTexture(
                  key,
                  "Some texture images could not load. Reload the texture archive to retry.",
                );
                loadImages();
              },
            );
          }
          if (!disposed && activeImages === 0 && textureQueue.length === 0)
            renderer.render(scene, camera);
        };
        for (const group of models[index]?.groups ?? []) {
          const geometry = group.vertices
            ? new ConvexGeometry(
                Array.from(
                  { length: group.vertices.length / 3 },
                  (_, i) =>
                    new T.Vector3(
                      ...(group.vertices!.slice(i * 3, i * 3 + 3) as [
                        number,
                        number,
                        number,
                      ]),
                    ),
                ),
              )
            : shapeGeometry(group.shape);
          const settings = {
            roughness: 0.84,
            metalness: 0.02,
            transparent: group.transparent,
            opacity: group.transparent ? 0.48 : 1,
            depthWrite: !group.transparent,
            side: T.DoubleSide,
          };
          const texturedGeometry = displayTextures
            ? surfaceGeometry(geometry)
            : geometry;
          resources.push(geometry);
          if (texturedGeometry !== geometry) resources.push(texturedGeometry);
          for (const batch of textureBatches(
            group,
            models[index]?.blocks ?? [],
            displayTextures,
          )) {
            const uniformTexture =
              batch.textures.length > 0 &&
              batch.textures.every((key) => key === batch.textures[0]);
            const surfaceKeys = uniformTexture
              ? batch.textures.slice(0, 1)
              : batch.textures;
            const materials = surfaceKeys.length
              ? surfaceKeys.map((key) => {
                  let texture = key ? textures.get(key) : undefined;
                  if (key && !texture) {
                    texture = new T.Texture();
                    textureQueue.push({ key, texture });
                    texture.colorSpace = T.SRGBColorSpace;
                    texture.magFilter = T.NearestFilter;
                    texture.minFilter = T.NearestMipmapNearestFilter;
                    texture.wrapS = texture.wrapT = T.RepeatWrapping;
                    textures.set(key, texture);
                    resources.push(texture);
                  }
                  const material = new T.MeshStandardMaterial({
                    ...settings,
                    map: null,
                  });
                  material.userData.previewTexture = texture;
                  if (texture && models[index]?.format !== "blueprint") {
                    // Minecraft PNGs already contain their surface colors; flat fallback
                    // faces still use the instance color, while FtD keeps its paint tint.
                    material.onBeforeCompile = (shader) => {
                      shader.fragmentShader = shader.fragmentShader.replace(
                        "#include <color_fragment>",
                        "#ifndef USE_MAP\n#include <color_fragment>\n#endif",
                      );
                    };
                  }
                  return material;
                })
              : [new T.MeshStandardMaterial(settings)];
            const mesh = new T.InstancedMesh(
              texturedGeometry,
              materials.length === 1 ? materials[0] : materials,
              batch.instances.length,
            );
            const matrix = new T.Matrix4();
            const color = new T.Color();
            for (let i = 0; i < mesh.count; i++) {
              const originalInstance = batch.instances[i];
              matrix.fromArray(group.matrices, originalInstance * 16);
              mesh.setMatrixAt(i, matrix);
              color.setRGB(
                group.colors[originalInstance * 3],
                group.colors[originalInstance * 3 + 1],
                group.colors[originalInstance * 3 + 2],
                T.SRGBColorSpace,
              );
              mesh.setColorAt(i, color);
            }
            mesh.instanceMatrix.needsUpdate = true;
            mesh.computeBoundingSphere();
            scene.add(mesh);
            picker.add(
              mesh,
              batch.instances.map((instance) => group.block_indices[instance]),
            );
            resources.push(mesh, ...materials);
          }
        }
        const outline = new T.Box3Helper(new T.Box3(), 0x285f40);
        outline.visible = false;
        const outlineMaterials = Array.isArray(outline.material)
          ? outline.material
          : [outline.material];
        outlineMaterials.forEach((material) => {
          material.depthTest = false;
        });
        outline.renderOrder = 1;
        scene.add(outline);
        resources.push(outline.geometry, ...outlineMaterials);
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
          .add(
            direction
              .normalize()
              .multiplyScalar(
                fitDistance(bounds, direction, frameAspect, camera.fov),
              ),
          );
        camera.up.set(0, 1, 0);
        controls.target.copy(center);
        controls.update();
        const render = () => renderer.render(scene, camera);
        const current: View = { camera, controls, render, renderer };
        views.current[index] = current;
        let pendingPick = 0;
        let selectedKey = "";
        let pointerX = 0;
        let pointerY = 0;
        const clearHover = () => {
          window.cancelAnimationFrame(pendingPick);
          pendingPick = 0;
          if (!selectedKey) return;
          selectedKey = "";
          outline.visible = false;
          setHovered((previous) => {
            const next = [...previous];
            next[index] = undefined;
            return next;
          });
          render();
        };
        const inspect = () => {
          pendingPick = 0;
          const rectangle = renderer.domElement.getBoundingClientRect();
          const hit = picker.pick(
            new T.Vector2(
              ((pointerX - rectangle.left) / rectangle.width) * 2 - 1,
              -((pointerY - rectangle.top) / rectangle.height) * 2 + 1,
            ),
            camera,
          );
          if (!hit) {
            clearHover();
            return;
          }
          const key = JSON.stringify(hit.block);
          if (key === selectedKey) return;
          selectedKey = key;
          outline.box.copy(hit.bounds);
          outline.visible = true;
          setHovered((previous) => {
            const next = [...previous];
            next[index] = hit.block;
            return next;
          });
          render();
        };
        const move = (event: PointerEvent) => {
          if (event.buttons) {
            clearHover();
            return;
          }
          pointerX = event.clientX;
          pointerY = event.clientY;
          if (!pendingPick) pendingPick = window.requestAnimationFrame(inspect);
        };
        const inspectKey = (event: KeyboardEvent) => {
          if (event.key === "Escape") clearHover();
          if (event.key.toLowerCase() !== "i") return;
          const rectangle = renderer.domElement.getBoundingClientRect();
          pointerX = rectangle.left + rectangle.width / 2;
          pointerY = rectangle.top + rectangle.height / 2;
          inspect();
        };
        renderer.domElement.addEventListener("pointermove", move);
        renderer.domElement.addEventListener("pointerleave", clearHover);
        renderer.domElement.addEventListener("pointerdown", clearHover);
        renderer.domElement.addEventListener("keydown", inspectKey);
        renderer.domElement.addEventListener("blur", clearHover);
        const change = () => {
          clearHover();
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
          const nextFrameAspect = commonAspect();
          if (Math.abs(nextFrameAspect - frameAspect) > 1e-6) {
            const offset = camera.position.clone().sub(controls.target);
            const ratio =
              fitDistance(bounds, offset, nextFrameAspect, camera.fov) /
              fitDistance(bounds, offset, frameAspect, camera.fov);
            camera.position
              .copy(controls.target)
              .add(offset.multiplyScalar(ratio));
            frameAspect = nextFrameAspect;
          }
          camera.aspect = width / height;
          camera.updateProjectionMatrix();
          render();
        });
        resize.observe(element);
        loadImages();
        cleanup.push(() => {
          disposed = true;
          window.cancelAnimationFrame(pendingPick);
          renderer.domElement.removeEventListener("pointermove", move);
          renderer.domElement.removeEventListener("pointerleave", clearHover);
          renderer.domElement.removeEventListener("pointerdown", clearHover);
          renderer.domElement.removeEventListener("keydown", inspectKey);
          renderer.domElement.removeEventListener("blur", clearHover);
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
  }, [source, converted, view, reset, displayTextures, textureToken]);

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
          {hovered[index] && (
            <div
              className="block-inspector"
              aria-live="polite"
              aria-atomic="true"
              data-testid={`${index === 0 ? "source" : "converted"}-block-inspector`}
            >
              <strong>{hovered[index].name}</strong>
              <span>{hovered[index].material}</span>
              {Object.keys(hovered[index].properties).length > 0 && (
                <span>
                  {Object.entries(hovered[index].properties)
                    .map(([key, value]) => `${key}=${value}`)
                    .join(" / ")}
                </span>
              )}
              {hovered[index].copied_material && (
                <span className="applied-material">
                  Applied material:{" "}
                  {blockStateText(hovered[index].copied_material)}
                </span>
              )}
              {Boolean(hovered[index].copied_materials?.length) && (
                <span className="applied-material">
                  Applied materials:{" "}
                  {copiedMaterialsText(hovered[index].copied_materials!)}
                </span>
              )}
              <span className="block-coordinate">
                Comparison origin XYZ: {hovered[index].coordinate.join(", ")}
              </span>
            </div>
          )}
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
