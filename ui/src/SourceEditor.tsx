import type { EditSnapshot, SourceRecord } from "./types";
import { useMemo, useState } from "react";

export type EditCommand = {
  kind: string;
  ids?: string[];
  type_keys?: string[];
  attachments?: string;
  mapping?: {
    name: string;
    properties: Record<string, string>;
    full_block?: boolean;
  };
};

export default function SourceEditor({
  records,
  selected,
  onSelect,
  edits,
  onEdit,
  onHistory,
  busy,
  candidates,
  error,
}: {
  records: SourceRecord[];
  selected: string[];
  onSelect: (ids: string[]) => void;
  edits?: EditSnapshot;
  onEdit: (command: EditCommand) => void;
  onHistory: (direction: "undo" | "redo") => void;
  busy: boolean;
  candidates: string[];
  error: string;
}) {
  const selectedSet = useMemo(() => new Set(selected), [selected]);
  const selectedRecords = useMemo(
    () => records.filter((r) => selectedSet.has(r.id)),
    [records, selectedSet],
  );
  const types = useMemo(
    () => new Set(selectedRecords.map((r) => r.type_key)),
    [selectedRecords],
  );
  const [attachments, setAttachments] = useState("");
  const [query, setQuery] = useState("");
  const children = useMemo(
    () => records.some((r) => r.host_id && selectedSet.has(r.host_id)),
    [records, selectedSet],
  );
  const found = useMemo(() => {
    const matches: SourceRecord[] = [];
    const search = query.toLowerCase();
    for (const record of records) {
      if (
        `${record.name} ${record.type_key} ${record.path.join("/")}`
          .toLowerCase()
          .includes(search)
      ) {
        matches.push(record);
        if (matches.length === 100) break;
      }
    }
    return matches;
  }, [records, query]);
  return (
    <section
      id="conversion-edits"
      className="source-editor"
      aria-label="Conversion edits"
    >
      <div className="editor-heading">
        <h2>Conversion edits</h2>
        <span data-testid="selection-count">
          {selected.length.toLocaleString()} selected
        </span>
        <span data-testid="excluded-count">
          {edits?.excluded.length ?? 0} excluded
        </span>
        <span>{edits?.hidden.length ?? 0} hidden</span>
        <button
          disabled={busy || !edits?.can_undo}
          onClick={() => onHistory("undo")}
        >
          Undo
        </button>
        <button
          disabled={busy || !edits?.can_redo}
          onClick={() => onHistory("redo")}
        >
          Redo
        </button>
      </div>
      <p className="editor-hint">
        Click a source block or select it from Source materials. Ctrl-click adds
        to the selection. Edits affect conversion; your original file stays
        unchanged.
      </p>
      <div className="editor-actions">
        <button
          disabled={busy || !selected.length}
          onClick={() =>
            onSelect(
              records.filter((r) => types.has(r.type_key)).map((r) => r.id),
            )
          }
        >
          Select all of this type
        </button>
        <button
          disabled={busy || !selected.length}
          onClick={() =>
            onEdit({
              kind: "exclude",
              ids: selected,
              ...(attachments ? { attachments } : {}),
            })
          }
        >
          Exclude selected
        </button>
        <button
          disabled={busy || !selected.length}
          onClick={() =>
            onEdit({
              kind: "exclude",
              type_keys: [...types],
              ...(attachments ? { attachments } : {}),
            })
          }
        >
          Exclude all of this type
        </button>
        <button
          disabled={busy || !selected.length}
          onClick={() => onEdit({ kind: "restore", ids: selected })}
        >
          Restore selected
        </button>
        <button
          disabled={busy || !selected.length}
          onClick={() => onEdit({ kind: "hide", ids: selected })}
        >
          Hide selected
        </button>
        <button
          disabled={busy || !edits?.hidden.length}
          onClick={() => onEdit({ kind: "show", ids: edits?.hidden })}
        >
          Show hidden
        </button>
        <button disabled={!selected.length} onClick={() => onSelect([])}>
          Clear selection
        </button>
      </div>
      {children && (
        <label>
          Attached decorations{" "}
          <select
            aria-label="Attachment exclusion policy"
            value={attachments}
            onChange={(e) => setAttachments(e.target.value)}
          >
            <option value="">Choose before excluding host</option>
            <option value="host">Exclude host only</option>
            <option value="all">Exclude host and its decorations</option>
          </select>
        </label>
      )}
      <details>
        <summary>Source record browser ({records.length})</summary>
        <label>
          Find source records{" "}
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
        <div className="record-list">
          {found.map((r) => (
            <button
              key={r.id}
              aria-pressed={selectedSet.has(r.id)}
              onClick={(e) =>
                onSelect(
                  e.ctrlKey || e.metaKey
                    ? selectedSet.has(r.id)
                      ? selected.filter((id) => id !== r.id)
                      : [...selected, r.id]
                    : [r.id],
                )
              }
            >
              {r.name} · {r.kind} · {r.path.join("/")}
            </button>
          ))}
        </div>
        <p className="editor-hint">
          Showing up to 100 matches. Hidden and unresolved records remain
          selectable here.
        </p>
      </details>
      {selectedRecords.length > 0 && (
        <p>
          {selectedRecords
            .slice(0, 3)
            .map((r) => r.name)
            .join(", ")}
          {selectedRecords.length > 3 ? "…" : ""}
        </p>
      )}
      {candidates.length > 1 && (
        <details>
          <summary>Overlapping hits ({candidates.length})</summary>
          <div className="record-list">
            {candidates.map((id) => {
              const r = records.find((r) => r.id === id);
              return (
                <button
                  key={id}
                  aria-pressed={selected.includes(id)}
                  onClick={() => onSelect([id])}
                >
                  {r?.name ?? id} / {r?.path.join("/")}
                </button>
              );
            })}
          </div>
        </details>
      )}
      {error && <p role="alert">{error}</p>}
    </section>
  );
}
