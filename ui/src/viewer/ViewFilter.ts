import * as T from "three";

export type ViewFilter = {
  axis: "" | "x" | "y" | "z";
  lower: number;
  upper: number;
  linked: boolean;
};
export const emptyFilter: ViewFilter = {
  axis: "",
  lower: 0,
  upper: 1,
  linked: true,
};

export function filterPlanes(filter: ViewFilter, index: number): T.Plane[] {
  if (!filter.axis || (index === 1 && !filter.linked)) return [];
  const axis = new T.Vector3(
    filter.axis === "x" ? 1 : 0,
    filter.axis === "y" ? 1 : 0,
    filter.axis === "z" ? 1 : 0,
  );
  return [
    new T.Plane(axis, -filter.lower),
    new T.Plane(axis.clone().negate(), filter.upper),
  ];
}
