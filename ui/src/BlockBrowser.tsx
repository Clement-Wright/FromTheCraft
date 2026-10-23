import { useEffect, useMemo, useState } from "react";
import type { Display } from "./types";
import PairedViewer from "./viewer/PairedViewer";
import type { EditCommand } from "./SourceEditor";

type Block = {
  name: string;
  mod: string;
  material: string;
  properties: Record<string, string>;
  states: Record<string, string[]>;
};
export default function BlockBrowser({
  mods,
  selected,
  token,
  request,
  onAssign,
  busy,
}: {
  mods: string[];
  selected: string[];
  token: string;
  request: (path: string, body?: BodyInit, json?: boolean) => Promise<any>;
  onAssign: (command: EditCommand) => void;
  busy: boolean;
}) {
  const [blocks, setBlocks] = useState<Block[]>([]),
    [query, setQuery] = useState(""),
    [name, setName] = useState("");
  const [properties, setProperties] = useState<Record<string, string>>({}),
    [display, setDisplay] = useState<Display>();
  const [error, setError] = useState(""),
    [full, setFull] = useState(false);
  const key = mods.join(",");
  useEffect(() => {
    let alive = true;
    void fetch(`/api/palette?mods=${encodeURIComponent(key)}`)
      .then(async (r) => {
        if (!r.ok) throw new Error("Could not load palette");
        return r.json();
      })
      .then((data) => {
        if (alive) setBlocks(data.blocks);
      })
      .catch((e) => setError(e.message));
    return () => {
      alive = false;
    };
  }, [key]);
  const filtered = useMemo(
    () =>
      blocks.filter((b) =>
        `${b.name} ${b.material}`.includes(query.toLowerCase()),
      ),
    [blocks, query],
  );
  const block = blocks.find((b) => b.name === name);
  useEffect(() => {
    let alive = true;
    setDisplay(undefined);
    if (!block) return;
    void request(
      "/api/palette/preview",
      JSON.stringify({ name, properties }),
      true,
    )
      .then((data) => {
        if (alive) setDisplay(data);
      })
      .catch((e) => {
        if (alive) setError(e.message);
      });
    return () => {
      alive = false;
    };
  }, [name, properties, blocks]);
  return (
    <details className="source-editor block-browser">
      <summary>Local block browser / Replace mapping</summary>
      <p className="editor-hint">
        Verified building palette for your selected mods. Mapping retains the
        fitted source shape unless full-block replacement is selected.
      </p>
      <label>
        Search target blocks{" "}
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </label>
      <select
        size={5}
        aria-label="Target block"
        value={name}
        onChange={(e) => {
          const b = blocks.find((b) => b.name === e.target.value)!;
          setName(b.name);
          setProperties(b.properties);
          setError("");
        }}
      >
        {filtered.map((b) => (
          <option key={b.name} value={b.name}>
            {b.name} · {b.material}
          </option>
        ))}
      </select>
      <span>{filtered.length} available blocks</span>
      {block && (
        <div className="editor-actions">
          {Object.entries(block.states).map(([key, values]) => (
            <label key={key}>
              {key}
              <select
                aria-label={`Target ${key}`}
                value={properties[key] ?? values[0]}
                onChange={(e) =>
                  setProperties({ ...properties, [key]: e.target.value })
                }
              >
                {values.map((value) => (
                  <option key={value}>{value}</option>
                ))}
              </select>
            </label>
          ))}
        </div>
      )}
      {display && (
        <div className="block-thumbnail">
          <PairedViewer
            source={display}
            linked
            view="orbit"
            reset={0}
            displayTextures
            textureToken={token}
          />
          {display.texture_coverage?.missing_faces ? (
            <p>
              Texture unavailable. Load your client and mod JARs; this thumbnail
              uses a flat fallback.
            </p>
          ) : (
            <p>Local Minecraft texture preview</p>
          )}
        </div>
      )}
      <label className="check">
        <input
          type="checkbox"
          checked={full}
          onChange={(e) => setFull(e.target.checked)}
        />
        Replace fitted cells with full blocks
      </label>
      <button
        disabled={busy || !selected.length || !block}
        onClick={() =>
          onAssign({
            kind: "mapping",
            ids: selected,
            mapping: { name, properties, full_block: full },
          })
        }
      >
        Assign mapping to selected
      </button>
      {error && <p role="alert">{error}</p>}
    </details>
  );
}
