import { access, readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import YAML from "yaml";
import { loadConfig } from "../experiment/config.js";
import {
  TRACE2SKILL_COMMIT,
  TRACE2SKILL_PROTOCOL,
  TRACE2SKILL_REPOSITORY,
  type RawTrace2SkillConfig,
  type Trace2SkillConfig,
} from "./trace2skill-types.js";

function assertInteger(value: number, label: string, minimum = 1): void {
  if (!Number.isInteger(value) || value < minimum) {
    throw new Error(`${label} must be an integer >= ${minimum}; got ${value}`);
  }
}

function assertString(value: unknown, label: string): asserts value is string {
  if (typeof value !== "string" || !value.trim()) throw new Error(`${label} must be a non-empty string`);
}

export async function loadTrace2SkillConfig(
  configPath = "configs/trace2skill-baseline.yaml",
): Promise<Trace2SkillConfig> {
  const absolute = path.resolve(configPath);
  const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
  const raw = YAML.parse(await readFile(absolute, "utf8")) as RawTrace2SkillConfig;
  if (!raw || typeof raw !== "object") throw new Error("Trace2Skill config must be a YAML object");
  if (raw.schemaVersion !== 1) throw new Error("Trace2Skill config schemaVersion must be 1");
  if (raw.protocolVersion !== TRACE2SKILL_PROTOCOL) {
    throw new Error(`protocolVersion must be ${TRACE2SKILL_PROTOCOL}`);
  }
  for (const key of [
    "experimentConfig", "runsRoot", "upstreamCheckout", "pythonVenv",
    "upstreamRepository", "upstreamCommit", "generationConfig",
  ] as const) assertString(raw[key], key);
  for (const key of [
    "tracesPerFamily", "replicates", "familyConcurrency", "trajectoryConcurrency",
    "heldoutVariantConcurrency", "evolverWorkers", "batchSize", "mergeBatchSize",
    "maxSkillLines", "maxTokens",
  ] as const) assertInteger(raw[key], key);
  if (!Number.isFinite(raw.temperature) || raw.temperature < 0 || raw.temperature > 2) {
    throw new Error("temperature must be between 0 and 2");
  }
  if (raw.upstreamRepository !== TRACE2SKILL_REPOSITORY) {
    throw new Error(`upstreamRepository must be the official ${TRACE2SKILL_REPOSITORY}`);
  }
  if (raw.upstreamCommit !== TRACE2SKILL_COMMIT) {
    throw new Error(`upstreamCommit must remain pinned to ${TRACE2SKILL_COMMIT}`);
  }
  const experimentConfig = await loadConfig(
    path.resolve(projectRoot, raw.experimentConfig),
    raw.experimentModel !== undefined
      ? path.resolve(projectRoot, raw.experimentModel)
      : undefined,
  );
  if (experimentConfig.families.length !== 22 || experimentConfig.iterations !== 3) {
    throw new Error("The adapted Trace2Skill baseline must use the frozen 22-family, 3-iteration cohort");
  }
  if (raw.replicates !== experimentConfig.replicates || raw.tracesPerFamily !== experimentConfig.iterations) {
    throw new Error("Trace2Skill replicates/tracesPerFamily must match the main experiment's 3 × 3 design");
  }
  if (raw.maxTokens !== experimentConfig.provider.maxCompletionTokens) {
    throw new Error("Trace2Skill maxTokens must match the experiment model configuration");
  }
  const generationConfig = path.resolve(projectRoot, raw.generationConfig);
  const generation = JSON.parse(await readFile(generationConfig, "utf8")) as Record<string, unknown>;
  if (generation.max_completion_tokens !== raw.maxTokens) {
    throw new Error("Trace2Skill generation config must set max_completion_tokens to maxTokens");
  }
  const extraBody = generation.extra_body;
  if (!extraBody || typeof extraBody !== "object" || (extraBody as Record<string, unknown>).enable_thinking !== true) {
    throw new Error("Trace2Skill generation config must explicitly enable thinking");
  }
  await access(generationConfig);
  return {
    ...raw,
    configPath: absolute,
    projectRoot,
    experimentConfig,
    runsRoot: path.resolve(projectRoot, raw.runsRoot),
    upstreamCheckout: path.resolve(projectRoot, raw.upstreamCheckout),
    pythonVenv: path.resolve(projectRoot, raw.pythonVenv),
    generationConfig,
  };
}

export function trace2SkillRunId(family: string, replicate: number): string {
  return `trace2skill-${family}-r${replicate}`;
}

export function trace2SkillRunRoot(
  config: Trace2SkillConfig,
  family: string,
  replicate: number,
): string {
  return path.join(config.runsRoot, trace2SkillRunId(family, replicate));
}
