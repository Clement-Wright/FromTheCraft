export function blockStateText(state: {
  name: string;
  properties: Record<string, string>;
}) {
  return (
    state.name +
    Object.entries(state.properties)
      .map(([key, value]) => ` / ${key}=${value}`)
      .join("")
  );
}
