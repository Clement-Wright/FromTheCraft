import { useRef, useState } from "react";

export default function ProjectControls({
  enabled,
  save,
  open,
}: {
  enabled: boolean;
  save: (kind: "project" | "preset") => Promise<unknown>;
  open: (kind: "project" | "preset", data: unknown) => Promise<void>;
}) {
  const input = useRef<HTMLInputElement>(null);
  const kind = useRef<"project" | "preset">("project");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  async function download(value: "project" | "preset") {
    setBusy(true);
    setMessage("");
    try {
      const data = await save(value);
      const url = URL.createObjectURL(
        new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }),
      );
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `conversion.${value}.json`;
      anchor.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      setMessage(
        `${value === "project" ? "Project" : "Preset"} saved. Native source unchanged.`,
      );
    } catch (e) {
      setMessage((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <details className="source-editor">
      <summary>Projects and presets</summary>
      <p className="editor-hint">
        Open the original source first, then its project. Projects keep edit
        history and view settings. Presets keep conversion settings and mappings
        applied to an entire block type.
      </p>
      <div className="editor-actions">
        {(["project", "preset"] as const).map((value) => (
          <span key={value}>
            <button
              disabled={!enabled || busy}
              onClick={() => void download(value)}
            >
              Save {value}
            </button>{" "}
            <button
              disabled={!enabled || busy}
              onClick={() => {
                kind.current = value;
                input.current?.click();
              }}
            >
              Open {value}
            </button>
          </span>
        ))}
      </div>
      <input
        hidden
        type="file"
        accept=".json"
        aria-label="Open conversion project or preset"
        ref={input}
        onChange={async (event) => {
          const file = event.target.files?.[0];
          event.target.value = "";
          if (!file) return;
          setBusy(true);
          setMessage("");
          try {
            if (file.size > 32 * 1024 * 1024)
              throw new Error("Project exceeds 32 MiB");
            await open(kind.current, JSON.parse(await file.text()));
            setMessage(`${kind.current} opened.`);
          } catch (e) {
            setMessage((e as Error).message);
          } finally {
            setBusy(false);
          }
        }}
      />
      {message && <p aria-live="polite">{message}</p>}
    </details>
  );
}
