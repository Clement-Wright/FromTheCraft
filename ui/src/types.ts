export type Display = {
  groups: {
    shape: string;
    transparent: boolean;
    matrices: number[];
    colors: number[];
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
