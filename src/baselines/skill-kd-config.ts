import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import YAML from "yaml";
import { loadConfig } from "../experiment/config.js";
import type { PilotConfig } from "../experiment/types.js";

export const SKILL_KD_COMMIT = "f76b51c3e855578cbcf9251e64aff08c4e2283c5";
export const SKILL_KD_REPOSITORY = "https://github.com/KhanCold/SKILL-KD.git";
export const SKILL_KD_PROTOCOL = "adapted-skill-kd-v1";
export interface SkillKdConfig {
  schemaVersion: 1;
  protocolVersion: string;
  configPath: string;
  projectRoot: string;
  experimentConfig: PilotConfig;
  runsRoot: string;
  upstreamRepository: string;
  upstreamCommit: string;
  upstreamCheckout: string;
  pythonVenv: string;
  anchorPasses: number;
  maxAdaptiveRounds: number;
  replicates: number;
  familyConcurrency: number;
  heldoutVariantConcurrency: number;
  analysisExclusions: { family: string; variant: string }[];
}

export function positiveInteger(value: unknown, label: string, max = Number.MAX_SAFE_INTEGER): number {
  const n = typeof value === "string" && value.trim() ? Number(value) : value;
  if (typeof n !== "number" || !Number.isInteger(n) || n < 1 || n > max) {
    throw new Error(`${label} must be an integer from 1 to ${max}`);
  }
  return n;
}

export async function loadSkillKdConfig(configPath = "configs/skill-kd-baseline.yaml"): Promise<SkillKdConfig> {
  const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
  const absolute = path.resolve(configPath);
  const raw = YAML.parse(await readFile(absolute, "utf8"));
  if (raw?.schemaVersion !== 1 || raw.protocolVersion !== SKILL_KD_PROTOCOL) {
    throw new Error(`Expected schemaVersion: 1 and protocolVersion: ${SKILL_KD_PROTOCOL}`);
  }
  if (raw.upstreamRepository !== SKILL_KD_REPOSITORY || raw.upstreamCommit !== SKILL_KD_COMMIT) {
    throw new Error("SKILL-KD must use the pinned official repository and commit");
  }
  for (const key of ["experimentConfig", "runsRoot", "upstreamCheckout", "pythonVenv"]) {
    if (typeof raw[key] !== "string" || !raw[key].trim()) throw new Error(`Missing ${key}`);
  }
  const experimentConfig = await loadConfig(
    path.resolve(projectRoot, raw.experimentConfig),
    raw.experimentModel !== undefined
      ? path.resolve(projectRoot, raw.experimentModel)
      : undefined,
  );
  const provider = experimentConfig.provider;
  if (experimentConfig.families.length !== 22 || experimentConfig.iterations !== 3
      || experimentConfig.replicates !== 3 || raw.anchorPasses !== 3 || raw.replicates !== 3
      || raw.maxAdaptiveRounds !== 3 || provider.studentModel !== "qwen3.7-plus"
      || provider.teacherModel !== "qwen3.7-max" || !provider.thinkingEnabled
      || provider.maxCompletionTokens !== 65536) {
    throw new Error("adapted-skill-kd-v1 freezes the main Qwen 22-family, 3-pass, 3-replicate design with 3 adaptive rounds");
  }
  const analysisExclusions = raw.analysisExclusions === undefined ? [] : raw.analysisExclusions;
  if (!Array.isArray(analysisExclusions)) throw new Error("analysisExclusions must be an array");
  const keys = new Set<string>();
  for (const row of analysisExclusions) {
    const family = experimentConfig.families.find((f) => f.name === row?.family);
    const key = `${row?.family}/${row?.variant}`;
    if (!family?.heldout.includes(row.variant) || keys.has(key)) throw new Error(`Invalid/duplicate exclusion: ${key}`);
    keys.add(key);
  }
  return {
    schemaVersion: 1, protocolVersion: SKILL_KD_PROTOCOL, configPath: absolute, projectRoot,
    experimentConfig,
    runsRoot: path.resolve(projectRoot, raw.runsRoot),
    upstreamRepository: SKILL_KD_REPOSITORY, upstreamCommit: SKILL_KD_COMMIT,
    upstreamCheckout: path.resolve(projectRoot, raw.upstreamCheckout),
    pythonVenv: path.resolve(projectRoot, raw.pythonVenv),
    anchorPasses: raw.anchorPasses, maxAdaptiveRounds: raw.maxAdaptiveRounds, replicates: raw.replicates,
    familyConcurrency: positiveInteger(raw.familyConcurrency, "familyConcurrency", 8),
    heldoutVariantConcurrency: positiveInteger(raw.heldoutVariantConcurrency, "heldoutVariantConcurrency", 8),
    analysisExclusions,
  };
}

export function skillKdRunId(family: string, replicate: number): string {
  return `skill-kd-${family}-r${replicate}`;
}
