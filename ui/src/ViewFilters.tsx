import type { Display } from "./types";
import { emptyFilter, type ViewFilter } from "./viewer/ViewFilter";

export default function ViewFilters({
  source,
  value,
  onChange,
}: {
  source?: Display;
  value: ViewFilter;
  onChange: (filter: ViewFilter) => void;
}) {
  return (
    <details className="source-editor" aria-label="View filters">
      <summary>
        Clipping and layers {value.axis ? `(${value.axis.toUpperCase()})` : ""}
      </summary>
      <p className="editor-hint">
        View only. Clipping does not remove exported blocks. Use Source
        materials to select hidden or clipped records.
      </p>
      <div className="editor-actions">
        <label>
          Clip axis{" "}
          <select
            aria-label="Clip axis"
            value={value.axis}
            onChange={(e) => {
              const axis = e.target.value as ViewFilter["axis"],
                i = "xyz".indexOf(axis);
              onChange({
                ...value,
                axis,
                lower: source?.bounds[0][i] ?? 0,
                upper: source?.bounds[1][i] ?? 1,
              });
            }}
          >
            <option value="">Off</option>
            {["x", "y", "z"].map((a) => (
              <option key={a}>{a}</option>
            ))}
          </select>
        </label>
        <label>
          From{" "}
          <input
            aria-label="Clip from"
            type="number"
            step="0.125"
            disabled={!value.axis}
            value={value.lower}
            onChange={(e) => {
              const lower = Number(e.target.value);
              if (Number.isFinite(lower))
                onChange({
                  ...value,
                  lower,
                  upper: Math.max(lower, value.upper),
                });
            }}
          />
        </label>
        <label>
          To{" "}
          <input
            aria-label="Clip to"
            type="number"
            step="0.125"
            disabled={!value.axis}
            value={value.upper}
            onChange={(e) => {
              const upper = Number(e.target.value);
              if (Number.isFinite(upper))
                onChange({
                  ...value,
                  upper,
                  lower: Math.min(upper, value.lower),
                });
            }}
          />
        </label>
        <button
          disabled={!value.axis}
          onClick={() => onChange({ ...value, upper: value.lower + 1 })}
        >
          One block layer
        </button>
        <label className="check">
          <input
            type="checkbox"
            checked={value.linked}
            onChange={(e) => onChange({ ...value, linked: e.target.checked })}
          />
          Apply to converted view
        </label>
        <button onClick={() => onChange(emptyFilter)}>
          Reset view filters
        </button>
      </div>
    </details>
  );
}
