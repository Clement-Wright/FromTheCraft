import { useEffect, useMemo, useRef, useState } from "react";
import PairedViewer from "./viewer/PairedViewer";
import Materials from "./Materials";
import ModPicker from "./ModPicker";
import SourceEditor, { type EditCommand } from "./SourceEditor";
import ViewFilters from "./ViewFilters";
import { emptyFilter, type ViewFilter } from "./viewer/ViewFilter";
import ProjectControls from "./ProjectControls";
import BlockBrowser from "./BlockBrowser";
import type { EditSnapshot } from "./types";
import type { Display, ModChoice, Status, TextureStatus } from "./types";

const labels: Record<string, string> = {
  empty: "Open a file to begin.",
  loading: "Reading source…",
  loaded: "Source ready. Choose your output and convert.",
  working: "Converting structure…",
  ready: "Converted file ready to export.",
  stale: "Options changed. Convert again before exporting.",
  cancelled: "Conversion cancelled. You can convert again.",
  exported: "Download started.",
  failed: "Conversion failed.",
};

export default function App() {
  const [source, setSource] = useState<Display>();
  const [edits, setEdits] = useState<EditSnapshot>();
  const [selected, setSelected] = useState<string[]>([]);
  const [candidates, setCandidates] = useState<string[]>([]);
  const [editBusy, setEditBusy] = useState(false);
  const [editError, setEditError] = useState("");
  const [filter, setFilter] = useState<ViewFilter>(emptyFilter);
  const [status, setStatus] = useState<Status>({
    state: "empty",
    progress: 0,
    error: "",
  });
  const [filename, setFilename] = useState("No file open");
  const [format, setFormat] = useState("nbt");
  const [scale, setScale] = useState(1);
  const [preference, setPreference] = useState("balanced");
  const [modChoices, setModChoices] = useState<ModChoice[]>([]);
  const [mods, setMods] = useState<string[]>([]);
  const [detailedCopycats, setDetailedCopycats] = useState(false);
  const [extremeDetail, setExtremeDetail] = useState(false);
  const [displayTextures, setDisplayTextures] = useState(false);
  const [showDecorations, setShowDecorations] = useState(false);
  const [decorationMode, setDecorationMode] = useState("structure");
  const [surfaceThickness, setSurfaceThickness] = useState(0.125);
  const [textureStatus, setTextureStatus] = useState<TextureStatus>();
  const [textureLoading, setTextureLoading] = useState(false);
  const [textureError, setTextureError] = useState("");
  const textureInput = useRef<HTMLInputElement>(null);
  const [hollow, setHollow] = useState(false);
  const [shellThickness, setShellThickness] = useState(1);
  const [sourceNotices, setSourceNotices] = useState<Record<string, number>>(
    {},
  );
  const [linked, setLinked] = useState(true);
  const [view, setView] = useState("orbit");
  const [reset, setReset] = useState(0);
  const [initialized, setInitialized] = useState(false);
  const [canClose, setCanClose] = useState(false);
  const [catalog, setCatalog] = useState("Bundled FtD catalog");
  const [dragging, setDragging] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const token = useRef("");
  const generation = useRef(0);
  const queue = useRef<Promise<unknown>>(Promise.resolve());
  const sourceRef = useRef<Display | undefined>(undefined);

  useEffect(() => {
    fetch("/api/session")
      .then(async (response) => {
        if (!response.ok) throw new Error("Could not start the local session.");
        const session = await response.json();
        token.current = session.token;
        setCanClose(session.can_close);
        setModChoices(session.mod_choices ?? []);
        setTextureStatus(session.textures);
        setCatalog(
          `FtD catalog: ${session.ftd_catalog ?? "bundled reference"}`,
        );
        setInitialized(true);
      })
      .catch((error) =>
        setStatus({
          state: "failed",
          progress: 0,
          error: String(error.message),
        }),
      );
  }, []);

  useEffect(() => {
    if (!initialized) return;
    const timer = window.setInterval(() => {
      void fetch("/api/heartbeat");
    }, 20000);
    return () => window.clearInterval(timer);
  }, [initialized]);

  async function request(path: string, body?: BodyInit, json = false) {
    const response = await fetch(path, {
      method: "POST",
      body,
      headers: {
        "X-FromTheCraft-Token": token.current,
        ...(json ? { "Content-Type": "application/json" } : {}),
      },
    });
    if (!response.ok) {
      const text = await response.text();
      let detail: unknown;
      try {
        detail = JSON.parse(text).detail;
      } catch {
        detail = text;
      }
      throw new Error(
        typeof detail === "string" ? detail : "Invalid conversion options.",
      );
    }
    return response.json();
  }

  function mutate<T>(operation: () => Promise<T>): Promise<T> {
    const pending = queue.current.then(operation);
    queue.current = pending.catch(() => undefined);
    return pending;
  }

  async function open(file?: File) {
    if (!file || !initialized) return;
    const current = ++generation.current;
    setSource(undefined);
    setSelected([]);
    setCandidates([]);
    setEdits(undefined);
    setEditError("");
    sourceRef.current = undefined;
    setFilter(emptyFilter);
    setSourceNotices({});
    setFilename(file.name);
    setStatus({ state: "loading", progress: 0, error: "" });
    const body = new FormData();
    body.append("file", file);
    try {
      const parsed = await mutate(() => request("/api/source", body));
      if (current !== generation.current) return;
      setSource(parsed.source);
      setEdits(parsed.edits);
      sourceRef.current = parsed.source;
      setSourceNotices(parsed.notices);
      setFormat(parsed.source.format === "blueprint" ? "nbt" : "blueprint");
      setStatus({ state: "loaded", progress: 0, error: "" });
    } catch (error) {
      if (current === generation.current)
        setStatus({
          state: "failed",
          progress: 0,
          error: (error as Error).message,
        });
    }
  }

  async function importTextures(files: File[]) {
    if (!files.length || !initialized) return;
    setTextureLoading(true);
    setTextureError("");
    const current = generation.current;
    const body = new FormData();
    for (const file of files) body.append("file", file);
    try {
      const refreshed = await mutate(() =>
        request(
          `/api/textures?token=${encodeURIComponent(token.current)}`,
          body,
        ),
      );
      setTextureStatus(refreshed.textures);
      if (current === generation.current) {
        setSource(refreshed.source ?? undefined);
        sourceRef.current = refreshed.source ?? undefined;
        setStatus((previous) => ({
          ...previous,
          converted: refreshed.converted ?? undefined,
        }));
      }
      setDisplayTextures(true);
    } catch (error) {
      setTextureError((error as Error).message);
    } finally {
      setTextureLoading(false);
    }
  }

  function invalidate() {
    if (!sourceRef.current) return;
    ++generation.current;
    setStatus({ state: "stale", progress: 0, error: "" });
    mutate(() => request("/api/invalidate")).catch((error) =>
      setStatus({ state: "failed", progress: 0, error: error.message }),
    );
  }

  async function run() {
    const current = ++generation.current;
    setStatus({ state: "working", progress: 0, error: "" });
    try {
      await mutate(() =>
        request(
          "/api/convert",
          JSON.stringify({
            format,
            scale,
            preference,
            mods: format === "blueprint" ? [] : mods,
            detailed_copycats:
              format !== "blueprint" &&
              mods.includes("copycats") &&
              detailedCopycats,
            extreme_detail:
              format !== "blueprint" &&
              mods.includes("copycats") &&
              extremeDetail,
            hollow,
            shell_thickness: shellThickness,
            decoration_mode: decorationMode,
            surface_thickness: surfaceThickness,
          }),
          true,
        ),
      );
      while (current === generation.current) {
        const response = await fetch("/api/status");
        if (!response.ok)
          throw new Error("The local service disconnected. Reload the page.");
        const update: Status = await response.json();
        if (current !== generation.current) return;
        setStatus(update);
        if (update.state !== "working") return;
        await new Promise((resolve) => window.setTimeout(resolve, 180));
      }
    } catch (error) {
      if (current === generation.current)
        setStatus({
          state: "failed",
          progress: 0,
          error: (error as Error).message,
        });
    }
  }

  async function cancel() {
    ++generation.current;
    setStatus({ state: "cancelled", progress: 0, error: "" });
    try {
      await mutate(() => request("/api/cancel"));
    } catch (error) {
      setStatus({
        state: "failed",
        progress: 0,
        error: (error as Error).message,
      });
    }
  }

  async function changeEdit(
    command?: EditCommand,
    direction?: "undo" | "redo",
  ) {
    if (editBusy) return;
    setEditBusy(true);
    setEditError("");
    const current = generation.current;
    try {
      const response = await mutate(() =>
        request(
          direction ? `/api/edits/${direction}` : "/api/edits",
          command ? JSON.stringify(command) : undefined,
          !!command,
        ),
      );
      if (current !== generation.current) return;
      setEdits(response.edits);
      if (response.invalidated) {
        ++generation.current;
        setStatus({ state: "stale", progress: 0, error: "" });
      }
    } catch (problem) {
      setEditError((problem as Error).message);
    } finally {
      setEditBusy(false);
    }
  }

  function settings() {
    return {
      format,
      scale,
      preference,
      mods: format === "blueprint" ? [] : mods,
      detailed_copycats:
        format !== "blueprint" && mods.includes("copycats") && detailedCopycats,
      extreme_detail:
        format !== "blueprint" && mods.includes("copycats") && extremeDetail,
      hollow,
      shell_thickness: shellThickness,
      decoration_mode: decorationMode,
      surface_thickness: surfaceThickness,
    };
  }

  async function restoreProject(kind: "project" | "preset", document: unknown) {
    setEditBusy(true);
    try {
      const current = generation.current;
      const response = await mutate(() =>
        request(`/api/${kind}/open`, JSON.stringify(document), true),
      );
      if (current !== generation.current) return;
      ++generation.current;
      const s = response.settings;
      setFormat(s.format);
      setScale(s.scale);
      setPreference(s.preference);
      setMods(s.mods);
      setDetailedCopycats(s.detailed_copycats);
      setExtremeDetail(s.extreme_detail ?? false);
      setHollow(s.hollow);
      setShellThickness(s.shell_thickness);
      setDecorationMode(s.decoration_mode);
      setSurfaceThickness(s.surface_thickness);
      setEdits(response.edits);
      setSelected([]);
      setCandidates([]);
      setEditError("");
      if (kind === "project") {
        const v = response.view;
        if (
          v.filter &&
          ["", "x", "y", "z"].includes(v.filter.axis) &&
          Number.isFinite(v.filter.lower) &&
          Number.isFinite(v.filter.upper)
        )
          setFilter(v.filter);
        if (typeof v.textures === "boolean") setDisplayTextures(v.textures);
        if (typeof v.linked === "boolean") setLinked(v.linked);
        if (typeof v.decorations === "boolean")
          setShowDecorations(v.decorations);
      }
      setStatus({ state: "stale", progress: 0, error: "" });
    } finally {
      setEditBusy(false);
    }
  }

  useEffect(() => {
    const historyKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement;
      if (
        target.closest("input,textarea,select,[contenteditable=true]") ||
        editBusy
      )
        return;
      if (!(event.ctrlKey || event.metaKey)) return;
      const key = event.key.toLowerCase();
      const direction =
        key === "y" || (key === "z" && event.shiftKey)
          ? "redo"
          : key === "z"
            ? "undo"
            : undefined;
      if (
        direction &&
        edits?.[direction === "undo" ? "can_undo" : "can_redo"]
      ) {
        event.preventDefault();
        void changeEdit(undefined, direction);
      }
    };
    window.addEventListener("keydown", historyKey);
    return () => window.removeEventListener("keydown", historyKey);
  }, [edits, editBusy]);

  const hiddenKey = (edits?.hidden ?? []).join("\n");
  const visibleSource = useMemo(() => {
    if (!source) return source;
    const hidden = new Set(hiddenKey ? hiddenKey.split("\n") : []);
    if (showDecorations)
      source.records?.forEach((r) => {
        if (r.hide_host && r.host_id && r.geometry_status !== "unresolved")
          hidden.add(r.host_id);
      });
    const groups = source.groups
      .filter((g) => showDecorations || !g.decoration)
      .map((group) => {
        const keep = group.block_indices
          .map((_, i) => i)
          .filter((i) => !hidden.has(group.source_ids?.[i] ?? ""));
        return {
          ...group,
          matrices: keep.flatMap((i) =>
            group.matrices.slice(i * 16, i * 16 + 16),
          ),
          colors: keep.flatMap((i) => group.colors.slice(i * 3, i * 3 + 3)),
          block_indices: keep.map((i) => group.block_indices[i]),
          source_ids: keep.map((i) => group.source_ids?.[i] ?? null),
        };
      });
    const low = [Infinity, Infinity, Infinity],
      high = [-Infinity, -Infinity, -Infinity];
    let count = 0;
    for (const group of groups)
      for (let i = 0; i < group.matrices.length; i += 16) {
        count++;
        for (let axis = 0; axis < 3; axis++) {
          let a = group.matrices[i + 12 + axis],
            b = a;
          for (let column = 0; column < 3; column++) {
            const delta = group.matrices[i + column * 4 + axis];
            a += Math.min(0, delta);
            b += Math.max(0, delta);
          }
          low[axis] = Math.min(low[axis], a);
          high[axis] = Math.max(high[axis], b);
        }
      }
    return {
      ...source,
      groups,
      count,
      bounds: count ? ([low, high] as [number[], number[]]) : source.bounds,
      dimensions: count
        ? high.map((n, i) => Math.round((n - low[i]) * 1000) / 1000)
        : source.dimensions,
    };
  }, [source, hiddenKey, showDecorations]);

  async function download() {
    const current = generation.current;
    try {
      const response = await fetch(
        "/api/export?result_id=" + encodeURIComponent(status.result_id ?? ""),
      );
      if (!response.ok)
        throw new Error("The result is stale. Convert again before exporting.");
      const blob = await response.blob();
      if (current !== generation.current) return;
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = status.filename ?? "structure.nbt";
      anchor.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      setStatus((previous) => ({ ...previous, state: "exported" }));
    } catch (error) {
      setStatus((previous) => ({
        ...previous,
        state: "failed",
        error: (error as Error).message,
      }));
    }
  }

  async function close() {
    try {
      await mutate(() => request("/api/close"));
      ++generation.current;
      setInitialized(false);
      setCanClose(false);
      setStatus({
        state: "closed",
        progress: 0,
        error: "Application stopped. You can close this tab.",
      });
    } catch (error) {
      setStatus((previous) => ({
        ...previous,
        error: (error as Error).message,
      }));
    }
  }

  const dimensions = source?.bounds[1].map((n, i) =>
    Math.max(
      1,
      Math.ceil(n * scale - 1e-6) -
        Math.floor(source.bounds[0][i] * scale + 1e-6),
    ),
  );
  const volume = dimensions?.reduce((a, b) => a * b, 1) ?? 0;
  const tooLarge = volume > 128_000_000 || dimensions?.some((n) => n > 2048);
  const notices = status.notices ?? sourceNotices;
  const noticeCount = Object.values(notices).reduce((a, b) => a + b, 0);
  const busy = status.state === "working" || status.state === "loading";

  return (
    <main
      className={dragging ? "app dragging" : "app"}
      onDragOver={(event) => {
        event.preventDefault();
        setDragging(true);
      }}
      onDragLeave={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node))
          setDragging(false);
      }}
      onDrop={(event) => {
        event.preventDefault();
        setDragging(false);
        void open(event.dataTransfer.files[0]);
      }}
    >
      <header className="app-header">
        <div className="identity">
          <h1>FromTheCraft</h1>
          <span>Structural converter</span>
        </div>
        <div className="file-actions">
          <input
            ref={fileInput}
            type="file"
            accept=".blueprint,.nbt,.litematic"
            aria-label="Open structure file"
            onChange={(event) => {
              void open(event.target.files?.[0]);
              event.target.value = "";
            }}
            hidden
          />
          <button
            disabled={!initialized}
            onClick={() => fileInput.current?.click()}
          >
            Open file
          </button>
          <span className="filename" title={filename}>
            {filename}
          </span>
        </div>
        <button
          className="primary"
          disabled={
            editBusy ||
            !status.result_id ||
            !["ready", "exported"].includes(status.state)
          }
          onClick={() => void download()}
        >
          Export file
        </button>
      </header>
      <div className="workbench">
        <aside className="settings">
          <div className="settings-content">
            <h2>Conversion</h2>
            <label htmlFor="format">Output format</label>
            <select
              id="format"
              value={format}
              disabled={!source}
              onChange={(event) => {
                setFormat(event.target.value);
                invalidate();
              }}
            >
              {source?.format === "blueprint" || !source ? (
                <>
                  <option value="nbt">Create NBT</option>
                  <option value="litematic">Litematic</option>
                </>
              ) : (
                <option value="blueprint">FtD blueprint</option>
              )}
            </select>
            {source?.format === "blueprint" && (
              <>
                <label htmlFor="decorations">Decorative geometry</label>
                <select
                  id="decorations"
                  value={decorationMode}
                  onChange={(e) => {
                    setDecorationMode(e.target.value);
                    invalidate();
                  }}
                >
                  <option value="structure">Structure only</option>
                  <option value="decorations">Structure + decorations</option>
                  <option value="appearance">Appearance-focused</option>
                </select>
                {decorationMode !== "structure" && (
                  <>
                    <p className="hint">
                      Supported local static meshes become sampled blocks. Open
                      surfaces use deliberate thickness. See notices for
                      unresolved records.
                    </p>
                    <label htmlFor="surface-thickness">
                      Open surface thickness
                    </label>
                    <select
                      id="surface-thickness"
                      value={surfaceThickness}
                      onChange={(e) => {
                        setSurfaceThickness(Number(e.target.value));
                        invalidate();
                      }}
                    >
                      {[0.0625, 0.125, 0.25, 0.5].map((n) => (
                        <option key={n} value={n}>
                          {n} blocks
                        </option>
                      ))}
                    </select>
                  </>
                )}
                {decorationMode === "appearance" && (
                  <p className="warning">
                    Appearance mode removes hosts explicitly hidden by supported
                    decorations. This changes physical occupancy.
                  </p>
                )}
              </>
            )}
            <label htmlFor="scale">Output scale</label>
            <select
              id="scale"
              value={scale}
              onChange={(event) => {
                setScale(Number(event.target.value));
                invalidate();
              }}
            >
              {[4, 2, 1, 0.5, 0.25].map((n) => (
                <option value={n} key={n}>
                  {n}×{n === 1 ? " (default)" : ""}
                </option>
              ))}
            </select>
            <p className="hint">
              1× = 1 Minecraft block per FtD meter. Scale applies to the output.
            </p>
            <label htmlFor="palette">Material preference</label>
            <select
              id="palette"
              value={preference}
              disabled={format === "blueprint"}
              onChange={(event) => {
                setPreference(event.target.value);
                invalidate();
              }}
            >
              <option value="balanced">Balanced</option>
              <option value="material">Material first</option>
              <option value="color">Color first</option>
            </select>
            {format === "blueprint" && (
              <p className="hint">FtD output uses source material and paint.</p>
            )}
            <ModPicker
              choices={modChoices}
              selected={mods}
              disabled={!initialized || format === "blueprint"}
              onChange={(selected) => {
                setMods(selected);
                invalidate();
              }}
            />
            <label className="check">
              <input
                type="checkbox"
                checked={extremeDetail}
                disabled={format === "blueprint" || !mods.includes("copycats")}
                onChange={(event) => {
                  setExtremeDetail(event.target.checked);
                  if (event.target.checked) setDetailedCopycats(true);
                  invalidate();
                }}
              />
              Extreme detail
            </label>
            <p className="hint">
              Includes Detailed Copycats, smooth slopes and separate colors for
              small pieces. Uses your selected decoration mode.
            </p>
            <label className="check">
              <input
                type="checkbox"
                checked={detailedCopycats || extremeDetail}
                disabled={
                  extremeDetail ||
                  format === "blueprint" ||
                  !mods.includes("copycats")
                }
                onChange={(event) => {
                  setDetailedCopycats(event.target.checked);
                  invalidate();
                }}
              />
              Detailed Copycats
            </label>
            <p className="hint">
              Use small Copycats pieces to retain finer structural detail.
              Requires Copycats in the output mod list.
            </p>
            <label className="check hollow-option">
              <input
                type="checkbox"
                checked={hollow}
                onChange={(event) => {
                  setHollow(event.target.checked);
                  invalidate();
                }}
              />
              Hollow interior
            </label>
            <p className="hint">
              Keep an exterior shell. Enclosed decks and internal parts are
              removed.
            </p>
            {hollow && (
              <>
                <label htmlFor="shell-thickness">Shell thickness</label>
                <select
                  id="shell-thickness"
                  value={shellThickness}
                  onChange={(event) => {
                    setShellThickness(Number(event.target.value));
                    invalidate();
                  }}
                >
                  {[1, 2, 3, 4].map((value) => (
                    <option key={value} value={value}>
                      {value} {value === 1 ? "block" : "blocks"}
                    </option>
                  ))}
                </select>
              </>
            )}
            <div className="estimate">
              <span>Estimated dimensions</span>
              <strong data-testid="dimensions">
                {dimensions ? dimensions.join(" × ") : "—"}
              </strong>
              <span>Output cells, before shape sampling</span>
            </div>
            {tooLarge && (
              <p className="warning">
                Original source bounds exceed the size estimate. Exclusions and
                structure-only mode may reduce it; conversion checks the
                remaining geometry.
              </p>
            )}
            {scale < 1 && (
              <p className="warning">
                Reduced scales merge cells. Small openings and thin details may
                be lost.
              </p>
            )}
            <div className="scope-note">
              {canClose && (
                <button className="close-app" onClick={() => void close()}>
                  Close app
                </button>
              )}
              <strong>Structural conversion</strong>
              <p>{catalog}</p>
              <p>
                Hulls, decks and building materials. Rotated constructs become
                static geometry.
              </p>
              <p>
                Supported static decorations are optional. Mechanisms and
                gameplay data are skipped.
              </p>
            </div>
          </div>
          <div className="settings-actions">
            <button
              className="primary convert"
              disabled={!source || busy || editBusy}
              onClick={() => void run()}
            >
              Convert
            </button>
            {status.state === "working" && (
              <button onClick={() => void cancel()}>Cancel conversion</button>
            )}
          </div>
        </aside>
        <section className="comparison" aria-label="Structure comparison">
          <div className="view-tools">
            <label className="check">
              <input
                type="checkbox"
                checked={linked}
                onChange={(event) => setLinked(event.target.checked)}
              />
              Linked cameras
            </label>
            <div className="view-buttons">
              <button
                onClick={() => {
                  setView("orbit");
                  setReset((n) => n + 1);
                }}
              >
                Fit both
              </button>
              {["top", "front", "side"].map((value) => (
                <button
                  key={value}
                  aria-pressed={view === value}
                  onClick={() => {
                    setView(value);
                    setReset((n) => n + 1);
                  }}
                >
                  {value[0].toUpperCase() + value.slice(1)}
                </button>
              ))}
            </div>
            <label className="check">
              <input
                type="checkbox"
                checked={displayTextures}
                onChange={(event) => setDisplayTextures(event.target.checked)}
              />
              Display textures
            </label>
            <input
              hidden
              ref={textureInput}
              type="file"
              multiple
              accept=".zip,.jar"
              aria-label="Load texture archive"
              onChange={(event) => {
                const files = Array.from(event.target.files ?? []);
                void importTextures(files);
                event.target.value = "";
              }}
            />
            <button
              disabled={!initialized || textureLoading || busy}
              onClick={() => textureInput.current?.click()}
            >
              {textureLoading ? "Loading textures…" : "Load textures"}
            </button>
            <span className="scale-label">Output {scale}×</span>
            {source && (
              <button
                disabled={!selected.length}
                onClick={() =>
                  document
                    .getElementById("conversion-edits")
                    ?.scrollIntoView({ block: "center", behavior: "smooth" })
                }
              >
                {selected.length.toLocaleString()} selected · Edit
              </button>
            )}
            {source?.format === "blueprint" && (
              <label className="check">
                <input
                  type="checkbox"
                  checked={showDecorations}
                  onChange={(e) => setShowDecorations(e.target.checked)}
                />
                Show decorations and mimics
              </label>
            )}
          </div>
          <PairedViewer
            source={visibleSource}
            converted={status.converted}
            linked={linked}
            view={view}
            reset={reset}
            displayTextures={displayTextures}
            textureToken={token.current}
            onSelect={(ids, additive) => {
              setCandidates(ids);
              const id = ids[0];
              setSelected((previous) =>
                !id
                  ? []
                  : additive
                    ? previous.includes(id)
                      ? previous.filter((v) => v !== id)
                      : [...previous, id]
                    : [id],
              );
            }}
            selectedIds={selected}
            excludedIds={edits?.excluded}
            filter={filter}
          />
          <div className="preview-context">
            <span>
              Structural previews use simplified shapes. Missing textures use
              flat colors.
            </span>
            <span>
              Orbit: drag / Pan: right-drag / Zoom: scroll / Inspect: hover or I
            </span>
          </div>
          <details className="texture-status">
            <summary>
              Texture assets: Minecraft{" "}
              {textureStatus?.minecraft.available ? "available" : "unavailable"}
              ; FtD {textureStatus?.ftd.available ? "available" : "unavailable"}
            </summary>
            <p>
              Load a local Minecraft client JAR, mod JAR or resource-pack ZIP.
              You can select your client and mod JARs together. Assets stay in
              this local session.
            </p>
            {textureStatus?.reasons?.map((reason) => (
              <p key={reason}>{reason}</p>
            ))}
          </details>
          {displayTextures &&
            status.converted?.texture_coverage &&
            status.converted.texture_coverage.missing_faces > 0 && (
              <p className="source-notice">
                Minecraft preview is missing textures for{" "}
                {status.converted.texture_coverage.missing_blocks.length} block
                types. Load your Minecraft 1.21.1 client JAR and the JARs for
                your selected mods with Load textures. FtD textures do not
                supply Minecraft textures.
              </p>
            )}
          {textureError && (
            <p className="texture-error" role="alert">
              {textureError}
            </p>
          )}
          {Object.keys(sourceNotices).length > 0 && (
            <p className="source-notice">
              Source preview omits or approximates some details. See notices
              below.
            </p>
          )}
          <ViewFilters source={source} value={filter} onChange={setFilter} />
          <ProjectControls
            enabled={!!source && !busy && !editBusy}
            save={(kind) =>
              mutate(() =>
                request(
                  `/api/${kind}/save`,
                  JSON.stringify({
                    settings: settings(),
                    view: {
                      filter,
                      textures: displayTextures,
                      linked,
                      decorations: showDecorations,
                    },
                  }),
                  true,
                ),
              )
            }
            open={restoreProject}
          />
          <Materials
            source={source}
            converted={status.converted}
            stale={status.state === "stale"}
            onSelectType={(key) => {
              setSelected(
                source?.records
                  ?.filter((r) => r.type_key === key)
                  .map((r) => r.id) ?? [],
              );
              setCandidates([]);
            }}
          />
          {source && (
            <SourceEditor
              records={source.records ?? []}
              selected={selected}
              onSelect={setSelected}
              edits={edits}
              onEdit={(command) => void changeEdit(command)}
              onHistory={(direction) => void changeEdit(undefined, direction)}
              busy={editBusy}
              candidates={candidates}
              error={editError}
            />
          )}
          {source && (
            <BlockBrowser
              target={format}
              mods={mods}
              selected={selected}
              token={token.current}
              request={request}
              onAssign={(command) => void changeEdit(command)}
              busy={editBusy}
            />
          )}
        </section>
      </div>
      <section className={`status-area ${status.state}`} aria-live="polite">
        <div className="status-line">
          <span className="status-dot" />
          <strong role="status">
            {status.error || labels[status.state] || status.state}
          </strong>
          {status.state === "working" && (
            <progress
              value={status.progress}
              max={1}
              aria-label="Conversion progress"
            />
          )}
          {status.sha256 && (
            <span className="file-check" title={status.sha256}>
              Preview and export use the same file
            </span>
          )}
        </div>
        {noticeCount > 0 && (
          <details>
            <summary>
              Conversion notices ({noticeCount.toLocaleString()})
            </summary>
            <ul>
              {Object.entries(notices).map(([message, count]) => (
                <li key={message}>
                  <span>{message}</span>
                  <strong>{count.toLocaleString()}</strong>
                </li>
              ))}
            </ul>
          </details>
        )}
      </section>
      {dragging && (
        <div className="drop-overlay">Drop to open this structure</div>
      )}
    </main>
  );
}
