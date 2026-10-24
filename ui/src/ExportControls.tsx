import { useEffect, useRef, useState } from "react";
import type { Status } from "./types";

type Props = {
  status: Status;
  disabled: boolean;
  canSave: boolean;
  request: (path: string, body?: BodyInit, json?: boolean) => Promise<unknown>;
  onExported: (id: string, state: "exported" | "saved") => void;
};

export default function ExportControls({
  status,
  disabled,
  canSave,
  request,
  onExported,
}: Props) {
  const [draft, setDraft] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [savedPath, setSavedPath] = useState("");
  const alive = useRef(true);
  const current = useRef(status.result_id);
  current.current = status.result_id;
  const suggested = status.filename ?? "";
  const name = draft ?? suggested;
  const extension = suggested.split(".").at(-1) ?? "";
  const ready =
    !!status.result_id && ["ready", "exported", "saved"].includes(status.state);
  const unavailable = disabled || saving || !ready;

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  useEffect(() => {
    setError("");
    setSavedPath("");
  }, [status.result_id]);
  useEffect(() => {
    if (extension)
      setDraft(
        (previous) =>
          previous?.replace(/\.(nbt|litematic|blueprint)$/i, `.${extension}`) ??
          null,
      );
  }, [extension]);

  async function exportFile(native: boolean) {
    if (unavailable) return;
    const id = status.result_id!;
    const stillCurrent = () => alive.current && current.current === id;
    setSaving(true);
    setError("");
    setSavedPath("");
    try {
      if (native) {
        const result = (await request(
          "/api/export/save",
          JSON.stringify({ result_id: id, filename: name }),
          true,
        )) as { saved: boolean; filename: string; path: string };
        if (!stillCurrent() || !result.saved) return;
        setDraft(result.filename);
        setSavedPath(result.path);
        onExported(id, "saved");
      } else {
        const response = await fetch(
          "/api/export?" +
            new URLSearchParams({ result_id: id, filename: name }),
        );
        if (!response.ok) {
          const body = await response.json().catch(() => ({}));
          throw new Error(
            body.detail || "Could not export this file. Try again.",
          );
        }
        const blob = await response.blob();
        if (!stillCurrent()) return;
        const encoded = /filename\*=UTF-8''([^;]+)/i.exec(
          response.headers.get("Content-Disposition") ?? "",
        );
        const filename = encoded ? decodeURIComponent(encoded[1]) : name;
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = filename;
        anchor.click();
        window.setTimeout(() => URL.revokeObjectURL(url), 1000);
        if (draft !== null) setDraft(filename);
        onExported(id, "exported");
      }
    } catch (failure) {
      if (stillCurrent()) setError((failure as Error).message);
    } finally {
      if (alive.current) setSaving(false);
    }
  }

  return (
    <div className="export-controls" aria-label="Export options">
      <div className="export-name">
        <div className="export-name-heading">
          <label htmlFor="output-filename">Output filename</label>
          {draft !== null && (
            <button
              type="button"
              className="reset-name"
              aria-label="Reset output filename"
              disabled={unavailable}
              onClick={() => {
                setDraft(null);
                setError("");
                setSavedPath("");
              }}
            >
              Reset
            </button>
          )}
        </div>
        <input
          id="output-filename"
          value={name}
          disabled={unavailable}
          maxLength={200}
          placeholder="Available after conversion"
          autoComplete="off"
          spellCheck={false}
          onBlur={() => {
            if (!name.trim()) setDraft(null);
          }}
          onChange={(event) => {
            setDraft(event.target.value);
            setError("");
            setSavedPath("");
          }}
        />
      </div>
      {canSave && (
        <button
          disabled={unavailable}
          onClick={() => void exportFile(true)}
          title="Choose a folder and save this file"
        >
          Save as…
        </button>
      )}
      <button
        className="primary"
        disabled={unavailable}
        onClick={() => void exportFile(false)}
      >
        Export file
      </button>
      {saving && (
        <span className="export-note">
          {canSave ? "Exporting…" : "Preparing download…"}
        </span>
      )}
      {error && (
        <span className="export-note warning" role="alert">
          {error}
        </span>
      )}
      {savedPath && (
        <span className="export-note" title={savedPath}>
          Saved to {savedPath}
        </span>
      )}
    </div>
  );
}
