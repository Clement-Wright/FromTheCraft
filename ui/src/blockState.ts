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

export function copiedMaterialsText(
  materials: {
    slot: string;
    name: string;
    properties: Record<string, string>;
  }[],
) {
  return materials
    .map((material) => `${material.slot}: ${blockStateText(material)}`)
    .join("; ");
}
