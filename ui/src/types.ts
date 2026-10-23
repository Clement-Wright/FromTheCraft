export type BlockIdentity = {
  type_key?: string;
  name: string;
  material: string;
  properties: Record<string, string>;
  copied_material?: { name: string; properties: Record<string, string> };
  copied_materials?: {
    slot: string;
    name: string;
    properties: Record<string, string>;
  }[];
  textures?: Record<string, string>;
};

export type TextureStatus = {
  available: boolean;
  minecraft: {
    available: boolean;
    sources: { name: string; kind: string; assets: number }[];
    reasons: string[];
  };
  ftd: {
    available: boolean;
    sources: { name: string; kind: string; assets: number }[];
    reasons: string[];
  };
  reasons: string[];
};

export type ModChoice = {
  slug: string;
  label: string;
  version: string;
  dependencies: string[];
};

export type Display = {
  source_hash?: string;
  records?: SourceRecord[];
  texture_coverage?: {
    resolved_faces: number;
    missing_faces: number;
    missing_blocks: string[];
  };
  blocks: BlockIdentity[];
  materials: (BlockIdentity & { count: number })[];
  groups: {
    shape: string;
    transparent: boolean;
    matrices: number[];
    colors: number[];
    block_indices: number[];
    source_ids?: (string | null)[];
    vertices?: number[];
  }[];
  count: number;
  bounds: [number[], number[]];
  dimensions: number[];
  format: string;
  version: string;
};

export type SourceRecord = {
  id: string;
  type_key: string;
  kind: string;
  path: string[];
  parent_path: string[];
  host_id?: string | null;
  name: string;
};
export type EditSnapshot = {
  revision: number;
  excluded: string[];
  hidden: string[];
  mappings: Record<
    string,
    { name: string; properties: Record<string, string>; full_block: boolean }
  >;
  can_undo: boolean;
  can_redo: boolean;
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
