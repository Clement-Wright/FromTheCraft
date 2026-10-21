import type { ModChoice } from "./types";

export default function ModPicker({
  choices,
  selected,
  disabled,
  onChange,
}: {
  choices: ModChoice[];
  selected: string[];
  disabled: boolean;
  onChange: (mods: string[]) => void;
}) {
  function toggle(slug: string, checked: boolean) {
    const next = new Set(selected);
    if (checked) {
      const add = (id: string) => {
        if (next.has(id)) return;
        next.add(id);
        choices.find((choice) => choice.slug === id)?.dependencies.forEach(add);
      };
      add(slug);
    } else {
      next.delete(slug);
      let removed: boolean;
      do {
        removed = false;
        for (const choice of choices) {
          if (
            next.has(choice.slug) &&
            choice.dependencies.some((id) => !next.has(id))
          ) {
            next.delete(choice.slug);
            removed = true;
          }
        }
      } while (removed);
    }
    onChange(
      choices
        .filter((choice) => next.has(choice.slug))
        .map((choice) => choice.slug),
    );
  }

  return (
    <details className="mod-picker">
      <summary>
        <span>Installed mods</span>
        <small>
          {selected.length ? `${selected.length} selected` : "Vanilla only"}
        </small>
      </summary>
      <p className="mod-hint">
        Select only mods installed in Minecraft 1.21.1 (NeoForge). This profile
        uses Create 6.0.10.
      </p>
      {disabled && (
        <p className="mod-hint">
          Mod palettes apply to Minecraft output. Your selection is kept.
        </p>
      )}
      <fieldset
        disabled={disabled || !choices.length}
        aria-label="Installed mods"
      >
        {choices.map((choice) => (
          <label className="mod-option" key={choice.slug}>
            <input
              type="checkbox"
              aria-label={choice.label}
              checked={selected.includes(choice.slug)}
              onChange={(event) => toggle(choice.slug, event.target.checked)}
            />
            <span>
              <span className="mod-name">{choice.label}</span>
              <small className="mod-version" title={choice.version}>
                {choice.version.replace(
                  /^CurseForge file (\d+).*/,
                  "CF file $1",
                )}
              </small>
              <small className="mod-dependencies">
                {choice.dependencies.length
                  ? `Requires ${choice.dependencies.map((slug) => choices.find((item) => item.slug === slug)?.label ?? slug).join(" + ")}`
                  : choice.slug === "chipped"
                    ? "Standalone"
                    : "Base mod"}
              </small>
            </span>
          </label>
        ))}
      </fieldset>
    </details>
  );
}
