import path from "node:path";
import type { FamilyConfig } from "../experiment/types.js";

/** Benchmark settings resolved from an experiment scope. */
export interface AssetCatalog {
  schemaVersion: number;
  catalogPath: string;
  projectRoot: string;
  assetsRoot: string;
  dockerProxy?: string;
  reuseDockerImages: boolean;
  families: FamilyConfig[];
}

export function assetFamilyPath(catalog: AssetCatalog, family: FamilyConfig): string {
  return path.join(catalog.assetsRoot, family.name);
}
