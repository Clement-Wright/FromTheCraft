export type BlockIdentity = {
  name: string;
  material: string;
  properties: Record<string, string>;
  copied_material?: { name: string; properties: Record<string, string> };
};

export type ModChoice = {
  slug: string;
  label: string;
  version: string;
  dependencies: string[];
};

export type Display = {
  blocks: BlockIdentity[];
  materials: (BlockIdentity & { count: number })[];
  groups: {
    shape: string;
    transparent: boolean;
    matrices: number[];
    colors: number[];
    block_indices: number[];
    vertices?: number[];
  }[];
  count: number;
  bounds: [number[], number[]];
  dimensions: number[];
  format: string;
  version: string;
};

export type Status = {
  state: string;
  progress: number;
  error: string;
  converted?: Display;
  result_id?: string;
  offset?: number[];
  sha256?: string;
  notices?: Record<string, number>;
  filename?: string;
};
