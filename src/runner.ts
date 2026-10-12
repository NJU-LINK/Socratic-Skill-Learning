import { access, readFile, readdir } from "node:fs/promises";
import path from "node:path";
import { createModels, type ModelBundle } from "./agent/model.js";
import { providerEnvironment } from "./agent/env.js";
import { loadConfig, selectFamilies, familyPath } from "./experiment/config.js";
import { RunOrchestrator } from "./experiment/orchestrator.js";
import { createRunId, parseRunId } from "./experiment/run-id.js";
import { runNoSkillSweep } from "./experiment/no-skill-runner.js";
import type { AssetCatalog } from "./assets/catalog.js";
import type { FamilyConfig, Mode, PilotConfig } from "./experiment/types.js";
import { ORCHESTRATED_METHODS, methodDirectoryNames, modeForMethod, type MethodName } from "./methods.js";

export interface AcquireOptions {
  configPath: string;
  /** Model file (provider block); defaults to the scope file's embedded provider. */
  modelPath?: string;
  /** Override the benchmark root (defaults to the scope file's assetsRoot). */
  benchRoot?: string;
  methods: MethodName[];
  families?: string[];
  replicates?: number[];
  dryRun?: boolean;
}

export interface EvaluateOptions extends AcquireOptions {
  /** Root with acquisition runs (default: runsRoot from the scope config). */
  runsRoot?: string;
  /** Root of released packages (e.g. experiments/cross-model/deepseek). */
  frozenRoot?: string;
}

export function catalogFromConfig(config: PilotConfig): AssetCatalog {
  return {
    schemaVersion: 1,
    catalogPath: config.configPath,
    projectRoot: config.projectRoot,
    assetsRoot: config.assetsRoot,
    ...(config.dockerProxy !== undefined ? { dockerProxy: config.dockerProxy } : {}),
    reuseDockerImages: config.reuseDockerImages,
    families: config.families,
  };
}

function selectReplicates(config: PilotConfig, requested?: number[]): number[] {
  const replicates = requested ?? Array.from({ length: config.replicates }, (_, i) => i + 1);
  if (replicates.length === 0) throw new Error("--replicates cannot be empty");
  for (const replicate of replicates) {
    if (!Number.isInteger(replicate) || replicate < 1 || replicate > config.replicates) {
      throw new Error(`--replicates must be integers between 1 and ${config.replicates}`);
    }
  }
  return replicates;
}

export async function loadExperiment(options: AcquireOptions | EvaluateOptions): Promise<PilotConfig> {
  const config = await loadConfig(options.configPath, options.modelPath);
  if (options.benchRoot !== undefined) {
    config.assetsRoot = path.resolve(options.benchRoot);
  }
  return config;
}

export async function acquire(options: AcquireOptions): Promise<void> {
  const config = await loadExperiment(options);
  const families = selectFamilies(config, options.families ?? []);
  const replicates = selectReplicates(config, options.replicates);
  const orchestrated = options.methods.filter((method): method is Exclude<MethodName, "no-skill" | "trace2skill" | "skill-kd"> =>
    (ORCHESTRATED_METHODS as readonly string[]).includes(method));
  const wantsNoSkill = options.methods.includes("no-skill");
  const unhandled = options.methods.filter((method) =>
    method === "trace2skill" || method === "skill-kd");
  if (unhandled.length > 0) {
    throw new Error(
      `${unhandled.join(", ")} use their own pipelines: run \`npm run ssl -- ${unhandled[0]!} --help\``,
    );
  }

  const plan: string[] = [];
  for (const method of orchestrated) {
    for (const family of families) {
      for (const replicate of replicates) {
        plan.push(`${method} ${family.name} r${replicate} -> ${createRunId(modeForMethod(method), family.name, replicate)}`);
      }
    }
  }
  if (wantsNoSkill) plan.push(`no-skill ${families.length} families x ${replicates.length} replicates (sweep)`);
  if (options.dryRun) {
    console.log(`scope: ${config.configPath}`);
    console.log(`model: ${options.modelPath ?? "(embedded in scope)"}`);
    console.log(`provider: ${config.provider.studentModel} / ${config.provider.teacherModel}`);
    console.log(`families: ${families.map((family) => family.name).join(", ")}`);
    console.log(`replicates: ${replicates.join(", ")}`);
    console.log(`runs root: ${config.runsRoot}`);
    for (const line of plan) console.log(`  ${line}`);
    return;
  }

  const { baseUrl, apiKey } = await providerEnvironment(config.projectRoot);
  const models: ModelBundle = await createModels(config, baseUrl, apiKey);
  const orchestrator = new RunOrchestrator(config, models);
  for (const method of orchestrated) {
    for (const family of families) {
      for (const replicate of replicates) {
        console.log(`[acquire] ${method} ${family.name} r${replicate}`);
        const result = await orchestrator.run(modeForMethod(method), family, replicate);
        console.log(`[acquire] done runId=${result.runId}`);
      }
    }
  }
  if (wantsNoSkill) {
    for (const replicate of replicates) {
      console.log(`[acquire] no-skill sweep r${replicate}`);
      const outcome = await runNoSkillSweep({
        config,
        catalog: catalogFromConfig(config),
        families,
        sweepRoot: path.join(config.runsRoot, "no-skill"),
        replicate,
        concurrency: config.cellConcurrency * config.groupConcurrency,
        heldoutOnly: true,
        agentSolveTimeoutMs: config.agentSolveTimeoutMs ?? 3_600_000,
        retryInvalid: false,
      });
      if (!outcome.successful) throw new Error("No-Skill sweep reported failures");
    }
  }
}

/** Discover an existing acquisition run directory; run ids embed a creation
 *  timestamp, so the latest matching run wins. */
async function findRunRoot(
  runsRoot: string,
  mode: Mode,
  familyName: string,
  replicate: number,
): Promise<string | undefined> {
  const entries = await readdir(runsRoot, { withFileTypes: true }).catch(() => []);
  const matches: Array<{ id: string; ts: number }> = [];
  for (const entry of entries) {
    if (!entry.isDirectory()) continue;
    const parsed = parseRunId(entry.name);
    if (parsed && parsed.mode === mode && parsed.family === familyName && parsed.replicate === replicate) {
      matches.push({ id: entry.name, ts: Number(entry.name.slice(0, 14)) });
    }
  }
  matches.sort((a, b) => b.ts - a.ts);
  return matches.length ? path.join(runsRoot, matches[0]!.id) : undefined;
}

export async function evaluate(options: EvaluateOptions): Promise<void> {
  const config = await loadExperiment(options);
  const families = selectFamilies(config, options.families ?? []);
  const replicates = selectReplicates(config, options.replicates);
  const orchestrated = options.methods.filter((method) =>
    (ORCHESTRATED_METHODS as readonly string[]).includes(method));
  const wantsNoSkill = options.methods.includes("no-skill");
  const unhandled = options.methods.filter((method) =>
    method === "trace2skill" || method === "skill-kd");
  if (unhandled.length > 0) {
    throw new Error(`${unhandled.join(", ")} evaluate through their own pipelines`);
  }

  const { baseUrl, apiKey } = await providerEnvironment(config.projectRoot);
  const models: ModelBundle = await createModels(config, baseUrl, apiKey);
  const orchestrator = new RunOrchestrator(config, models);

  if (options.frozenRoot) {
    await evaluateFrozenFromTraj(orchestrator, config, families, orchestrated, wantsNoSkill, options);
    return;
  }

  const runsRoot = options.runsRoot ?? config.runsRoot;
  for (const method of orchestrated) {
    for (const family of families) {
      for (const replicate of replicates) {
        const mode = modeForMethod(method);
        const runRoot = await findRunRoot(runsRoot, mode, family.name, replicate);
        if (!runRoot) {
          throw new Error(
            `No acquisition run for ${method} ${family.name} r${replicate} under ${runsRoot}; run 'ssl acquire' first`,
          );
        }
        const result = JSON.parse(await readFile(path.join(runRoot, "result.json"), "utf8")) as {
          family: string;
          iterations: Array<{ iteration: number }>;
        };
        const iteration = result.iterations.at(-1)?.iteration;
        if (!iteration) throw new Error(`No iterations recorded for ${path.basename(runRoot)}`);
        console.log(`[evaluate] ${method} ${family.name} r${replicate} (iteration ${iteration})`);
        const results = await orchestrator.evaluateExistingRun(runRoot, family, iteration, family.heldout);
        const mean = results.length
          ? results.reduce((sum, r) => sum + r.tests.score, 0) / results.length
          : 0;
        console.log(`[evaluate] ${path.basename(runRoot)}: ${results.length} variants, mean score ${mean.toFixed(3)}`);
        for (const result of results) {
          console.log(`    ${result.variant}: ${result.tests.score.toFixed(3)} (${result.tests.passed}/${result.tests.total})`);
        }
      }
    }
  }
  if (wantsNoSkill) {
    console.log("[evaluate] no-skill: re-run the sweep via `ssl acquire --methods no-skill`");
  }
}

async function evaluateFrozenFromTraj(
  orchestrator: RunOrchestrator,
  config: PilotConfig,
  families: FamilyConfig[],
  orchestrated: MethodName[],
  wantsNoSkill: boolean,
  options: EvaluateOptions,
): Promise<void> {
  const frozenRoot = path.resolve(options.frozenRoot!);
  const replicates = selectReplicates(config, options.replicates);
  for (const method of orchestrated) {
    for (const family of families) {
      for (const replicate of replicates) {
        const packageRoots = await candidateFrozenPackages(frozenRoot, method, replicate, family.name);
        const snapshotPackage = packageRoots[0];
        if (!snapshotPackage) {
          throw new Error(`No frozen skill package for ${method} r${replicate} ${family.name} under ${frozenRoot}`);
        }
        console.log(`[evaluate] frozen ${method} ${family.name} r${replicate} <- ${snapshotPackage}`);
        const iterationMatch = snapshotPackage.match(/iteration-(\d+)$/);
        const evaluationRoot = path.join(config.runsRoot, "frozen-eval", method, `r${replicate}`, family.name);
        const results = await orchestrator.evaluateFrozenPackage({
          evaluationRoot,
          evaluationId: `frozen-${method}-${family.name}-r${replicate}`,
          sourceRunId: `frozen-${method}-${family.name}-r${replicate}`,
          family,
          iteration: iterationMatch ? Number(iterationMatch[1]) : 1,
          snapshotPackage,
          variants: family.heldout,
        });
        for (const result of results) {
          console.log(`    ${result.variant}: ${result.tests.score.toFixed(3)} (${result.tests.passed}/${result.tests.total})`);
        }
      }
    }
  }
  if (wantsNoSkill) {
    console.log("[evaluate] no-skill has no frozen package; run `ssl acquire --methods no-skill` instead");
  }
}

/**
 * Frozen packages live either as <cohort>/<method>/r<N>/<family>/skill/ (flat,
 * cross-model cohorts) or with an iteration layer
 * <cohort>/<method>/r<N>/<family>/skill/iteration-N/ (main Qwen); the latest
 * iteration wins when the layer is present.
 */
export async function candidateFrozenPackages(
  frozenRoot: string,
  method: MethodName,
  replicate: number,
  family: string,
): Promise<string[]> {
  const candidates = methodDirectoryNames(method).flatMap((name) => [
    path.join(frozenRoot, name, `r${replicate}`, family, "skill"),
    path.join(frozenRoot, `r${replicate}`, name, family, "skill"),
  ]);
  const existing: string[] = [];
  for (const candidate of candidates) {
    const entries = await readdir(candidate).catch(() => undefined);
    if (entries === undefined) continue;
    const iterations = entries
      .filter((entry) => /^iteration-\d+$/.test(entry))
      .sort((a, b) => Number(b.slice("iteration-".length)) - Number(a.slice("iteration-".length)));
    if (iterations.length > 0) {
      const latest = path.join(candidate, iterations[0]!);
      if (await access(path.join(latest, "SKILL.md")).then(() => true, () => false)) {
        existing.push(latest);
      }
      continue;
    }
    existing.push(candidate);
  }
  return existing;
}

export { familyPath };
