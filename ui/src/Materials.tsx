import { useEffect, useId, useState } from "react";
import type { Display } from "./types";

export default function Materials({
  source,
  converted,
  stale,
}: {
  source?: Display;
  converted?: Display;
  stale: boolean;
}) {
  const [selected, setSelected] = useState("converted");
  const [search, setSearch] = useState("");
  const [expanded, setExpanded] = useState(true);
  const contentId = useId();
  useEffect(() => {
    if (source) setSelected("source");
    setSearch("");
  }, [source]);
  useEffect(() => {
    if (converted) {
      setSelected("converted");
      setSearch("");
    }
  }, [converted]);
  const model = selected === "source" ? source : converted;
  const materials = model?.materials ?? [];
  const total = materials.reduce((sum, item) => sum + item.count, 0);
  const query = search.trim().toLowerCase();
  const filtered = materials.filter((item) =>
    `${item.name} ${item.material} ${Object.entries(item.properties)
      .map(([key, value]) => `${key}=${value}`)
      .join(" ")}`
      .toLowerCase()
      .includes(query),
  );
  const noun = selected === "source" ? "source part" : "exported block";
  return (
    <section className="materials" aria-label="Build materials">
      <div className="materials-heading">
        <h2>
          <button
            className="materials-toggle"
            aria-expanded={expanded}
            aria-controls={contentId}
            onClick={() => setExpanded((value) => !value)}
          >
            <span className="materials-chevron" aria-hidden="true">
              {expanded ? "▾" : "▸"}
            </span>
            Build materials
          </button>
        </h2>
        <div
          className="material-tabs"
          role="group"
          aria-label="Material preview"
        >
          {["source", "converted"].map((value) => (
            <button
              key={value}
              aria-label={`${value === "source" ? "Source" : "Converted"} materials`}
              aria-pressed={selected === value}
              onClick={() => {
                setSelected(value);
                setSearch("");
              }}
            >
              {value === "source" ? "Source" : "Converted"}
            </button>
          ))}
        </div>
        <span className="material-total" data-testid="material-total">
          {model
            ? `${total.toLocaleString()} ${noun}${total === 1 ? "" : "s"}`
            : ""}
        </span>
        <input
          type="search"
          aria-label="Search materials"
          placeholder="Search materials"
          value={search}
          disabled={!materials.length}
          onChange={(event) => setSearch(event.target.value)}
        />
      </div>
      <div id={contentId} hidden={!expanded}>
        <div
          className="material-list"
          data-testid="material-list"
          tabIndex={0}
          aria-label="Material counts"
        >
          {!model ? (
            <p className="materials-empty">
              {selected === "source"
                ? "Open a structure to see its parts."
                : stale
                  ? "Options changed. Convert again to update the build list."
                  : "Convert to see the blocks in your exported file."}
            </p>
          ) : !materials.length ? (
            <p className="materials-empty">
              No structural materials in this preview.
            </p>
          ) : !filtered.length ? (
            <p className="materials-empty">No materials match your search.</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th scope="col">Block / material</th>
                  <th scope="col">Count</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((item) => (
                  <tr
                    key={`${item.name}:${item.material}:${JSON.stringify(item.properties)}`}
                  >
                    <td>
                      <strong>{item.name}</strong>
                      <span>
                        {item.material}
                        {Object.entries(item.properties)
                          .map(([key, value]) => ` / ${key}=${value}`)
                          .join("")}
                      </span>
                    </td>
                    <td>{item.count.toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        {model && (
          <p className="materials-note">
            {selected === "source"
              ? "Source counts include parts at their anchors."
              : "Counts match the blocks saved in the exported file."}
          </p>
        )}
      </div>
    </section>
  );
}
