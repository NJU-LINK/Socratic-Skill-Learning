import { access, readFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";
import YAML from "yaml";
import { loadScorerPlan } from "../runtime/scorer.js";
import type { FamilyConfig, PilotConfig } from "./types.js";

interface RawConfig extends Omit<
  PilotConfig,
  "configPath" | "projectRoot" | "assetsRoot" | "runsRoot" | "cellConcurrency" | "groupConcurrency"
> {
  assetsRoot: string;
  runsRoot: string;
  cellConcurrency?: number;
  groupConcurrency?: number;
}

function assertPositiveInteger(value: number, label: string): void {
  if (!Number.isInteger(value) || value <= 0) {
    throw new Error(`${label} must be a positive integer; got ${value}`);
  }
}

function assertNonEmptyString(value: unknown, label: string): asserts value is string {
  if (typeof value !== "string" || !value.trim()) {
    throw new Error(`${label} must be a non-empty string`);
  }
}

/**
 * Load an experiment configuration from a scope file plus a model file.
 *
 * The scope file (configs/scopes/*.yaml) defines what to evaluate: families,
 * held-out variants, iteration/replicate counts, concurrency, and asset/run
 * roots. The model file (configs/models/*.yaml) defines what to run it with:
 * the provider block. Keeping them in separate files lets any scope run with
 * any model. A scope file that embeds its own provider block is still accepted
 * (used by the frozen baseline wrappers) when no model file is given.
 */
export async function loadConfig(scopePath: string, modelPath?: string): Promise<PilotConfig> {
  const absoluteConfig = path.resolve(scopePath);
  const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
  const raw = YAML.parse(await readFile(absoluteConfig, "utf8")) as RawConfig;
  if (modelPath !== undefined) {
    const modelDoc = YAML.parse(await readFile(path.resolve(modelPath), "utf8")) as {
      provider?: unknown;
    };
    if (!modelDoc || typeof modelDoc !== "object" || !modelDoc.provider) {
      throw new Error(`Model file ${modelPath} must contain a provider block`);
    }
    raw.provider = modelDoc.provider as RawConfig["provider"];
  }
  if (raw.provider === undefined) {
    throw new Error(
      `No provider configuration: pass a model file (--model) or embed provider in the scope file`,
    );
  }

  if (!raw || typeof raw !== "object") throw new Error("Config must be a YAML object");
  assertNonEmptyString(raw.protocolVersion, "protocolVersion");
  assertNonEmptyString(raw.assetsRoot, "assetsRoot");
  assertNonEmptyString(raw.runsRoot, "runsRoot");
  assertPositiveInteger(raw.iterations, "iterations");
  assertPositiveInteger(raw.replicates, "replicates");
  if (raw.agentSolveTimeoutMs !== undefined) {
    assertPositiveInteger(raw.agentSolveTimeoutMs, "agentSolveTimeoutMs");
  }
  const cellConcurrency = raw.cellConcurrency ?? 1;
  assertPositiveInteger(cellConcurrency, "cellConcurrency");
  const groupConcurrency = raw.groupConcurrency ?? 1;
  assertPositiveInteger(groupConcurrency, "groupConcurrency");
  if (groupConcurrency > 64) throw new Error("groupConcurrency must not exceed 64");
  if (typeof raw.heldoutEachIteration !== "boolean") {
    throw new Error("heldoutEachIteration must be an explicit boolean");
  }
  if (typeof raw.reuseDockerImages !== "boolean") throw new Error("reuseDockerImages must be explicit");
  if (!raw.provider || typeof raw.provider !== "object") throw new Error("provider is required");
  for (const forbidden of ["temperature", "topP", "top_p", "reasoning_effort"]) {
    if (forbidden in raw.provider) {
      throw new Error(`provider.${forbidden} is not supported; use service-default sampling`);
    }
  }
  assertNonEmptyString(raw.provider.id, "provider.id");
  assertNonEmptyString(raw.provider.studentModel, "provider.studentModel");
  assertNonEmptyString(raw.provider.teacherModel, "provider.teacherModel");
  if (typeof raw.provider.thinkingEnabled !== "boolean") {
    throw new Error("provider.thinkingEnabled must be an explicit boolean");
  }
  if (
    raw.provider.reasoningEffort !== undefined
    && !["minimal", "low", "medium", "high", "xhigh", "max"].includes(
      raw.provider.reasoningEffort,
    )
  ) {
    throw new Error("provider.reasoningEffort must be a supported Pi thinking level");
  }
  assertPositiveInteger(raw.provider.contextWindow, "provider.contextWindow");
  assertPositiveInteger(raw.provider.maxCompletionTokens, "provider.maxCompletionTokens");
  if (raw.provider.maxCompletionTokens >= raw.provider.contextWindow) {
    throw new Error("provider.maxCompletionTokens must be smaller than provider.contextWindow");
  }
  if (raw.provider.teacherLimits !== undefined) {
    assertPositiveInteger(raw.provider.teacherLimits.contextWindow, "provider.teacherLimits.contextWindow");
    assertPositiveInteger(
      raw.provider.teacherLimits.maxCompletionTokens,
      "provider.teacherLimits.maxCompletionTokens",
    );
  }
  if (!Array.isArray(raw.families) || raw.families.length < 1) {
    throw new Error("At least one family is required");
  }
  const familyNames = new Set<string>();
  for (const family of raw.families) {
    assertNonEmptyString(family.name, "family.name");
    assertNonEmptyString(family.train, `${family.name}.train`);
    if (familyNames.has(family.name)) throw new Error(`Duplicate family ${family.name}`);
    familyNames.add(family.name);
    if (!Array.isArray(family.heldout) || family.heldout.length === 0) {
      throw new Error(`${family.name}.heldout must be a non-empty array`);
    }
    const heldout = new Set<string>();
    for (const variant of family.heldout) {
      assertNonEmptyString(variant, `${family.name}.heldout variant`);
      if (variant === family.train) throw new Error(`${family.name}: train variant appears in heldout`);
      if (heldout.has(variant)) throw new Error(`${family.name}: duplicate heldout variant ${variant}`);
      heldout.add(variant);
    }
  }

  const dockerProxy = raw.dockerProxy ?? (process.env.DOCKER_PROXY?.trim() || undefined);
  const config: PilotConfig = {
    ...raw,
    ...(dockerProxy !== undefined ? { dockerProxy } : {}),
    cellConcurrency,
    groupConcurrency,
    configPath: absoluteConfig,
    projectRoot,
    assetsRoot: path.resolve(projectRoot, raw.assetsRoot),
    runsRoot: path.resolve(projectRoot, raw.runsRoot),
  };
  await validateAssets(config);
  return config;
}

export async function validateAssets(config: PilotConfig): Promise<void> {
  for (const family of config.families) {
    if (!family.name || !family.train || family.heldout.length === 0) {
      throw new Error(`Invalid family entry: ${JSON.stringify(family)}`);
    }
    const familyRoot = familyPath(config, family);
    await access(path.join(familyRoot, "spec.yaml"));
    for (const variant of [family.train, ...family.heldout]) {
      const variantRoot = path.join(familyRoot, variant);
      for (const required of ["Dockerfile", "task.yaml", "run-tests.sh", "tests"]) {
        await access(path.join(variantRoot, required));
      }
      await loadScorerPlan(variantRoot);
    }
  }
}

export function familyPath(config: PilotConfig, family: FamilyConfig): string {
  return path.join(config.assetsRoot, family.name);
}

export function selectFamilies(config: PilotConfig, names: string[]): FamilyConfig[] {
  if (names.length === 0) return config.families;
  const selected = config.families.filter((family) => names.includes(family.name));
  const missing = names.filter((name) => !selected.some((family) => family.name === name));
  if (missing.length > 0) throw new Error(`Families not in config: ${missing.join(", ")}`);
  return selected;
}
