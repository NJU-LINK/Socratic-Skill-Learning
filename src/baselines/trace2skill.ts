import { createHash } from "node:crypto";
import { access, cp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import type { ModelBundle } from "../agent/model.js";
import { skillPackageManifest, skillPackageSha256 } from "../agent/skill-package.js";
import { familyPath } from "../experiment/config.js";
import { RunOrchestrator } from "../experiment/orchestrator.js";
import type { EvalResult, FamilyConfig } from "../experiment/types.js";
import { TaskEnvironment } from "../runtime/docker.js";
import { trace2SkillRunId, trace2SkillRunRoot } from "./trace2skill-config.js";
import { readJsonIfExists, writeJson } from "./trace2skill-io.js";
import { analyzeTrajectory } from "./trace2skill-records.js";
import type {
  Trace2SkillConfig,
  Trace2SkillMatrixMetrics,
  Trace2SkillRunSummary,
  Trace2SkillTrajectoryArtifact,
} from "./trace2skill-types.js";
import { TRACE2SKILL_PROTOCOL } from "./trace2skill-types.js";
import { evolveTracePool } from "./trace2skill-upstream.js";

export * from "./trace2skill-config.js";
export * from "./trace2skill-io.js";
export * from "./trace2skill-records.js";
export * from "./trace2skill-types.js";
export * from "./trace2skill-upstream.js";

function sha256(value: string | Buffer): string {
  return createHash("sha256").update(value).digest("hex");
}

export async function createWeakSeedPackage(
  packageRoot: string,
  family: FamilyConfig,
): Promise<void> {
  await rm(packageRoot, { recursive: true, force: true });
  await mkdir(packageRoot, { recursive: true });
  await writeFile(path.join(packageRoot, "SKILL.md"), `---
name: ${family.name}
description: General starting point for solving tasks in the ${family.name} family.
---

# ${family.name}

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.
`, "utf8");
}

export function assertFrozenSeedManifest(
  metadata: unknown,
  packageSha256: string,
): void {
  if (!metadata || typeof metadata !== "object") return;
  const recorded = (metadata as { seedPackageSha256?: unknown }).seedPackageSha256;
  if (typeof recorded === "string" && recorded !== packageSha256) {
    throw new Error(`Weak seed package changed after run creation: ${packageSha256} != ${recorded}`);
  }
}

export function tracePoolSolverPrompt(family: string, traceIndex: number): string {
  return `Generate complete trajectory ${traceIndex} for the Trace2Skill training pool by solving ${family}/v01 with the supplied weak seed Agent Skill. Load the Skill through Pi's available-skills metadata. First read the host-workspace file \`task.yaml\` with the \`read\` tool; it is not inside \`/app\`. Then use \`task_shell\` for all work in the fresh isolated \`/app\` environment. Do not edit the Skill. Finish only after checking your work against the public task; hidden tests are not present.`;
}

async function collectTrajectory(options: {
  config: Trace2SkillConfig;
  orchestrator: RunOrchestrator;
  family: FamilyConfig;
  replicate: number;
  traceIndex: number;
  runRoot: string;
  seedPackage: string;
}): Promise<Trace2SkillTrajectoryArtifact> {
  const trajectoryPath = path.join(
    options.runRoot,
    "train-solvers",
    `iteration-${options.traceIndex}`,
    "trajectory.json",
  );
  const existing = await readJsonIfExists<Trace2SkillTrajectoryArtifact>(trajectoryPath);
  if (existing) {
    const rawSessionFile = existing.rawSessionFile ?? existing.sessionFile;
    if (!rawSessionFile) {
      throw new Error(`Trace2Skill trajectory lacks a raw Pi session file: ${trajectoryPath}`);
    }
    const rawSession = await readFile(rawSessionFile);
    const enriched = {
      ...existing,
      rawSessionFile,
      rawSessionSha256: existing.rawSessionSha256 ?? sha256(rawSession),
    };
    if (!existing.rawSessionFile || !existing.rawSessionSha256) await writeJson(trajectoryPath, enriched);
    return enriched;
  }
  const environment = new TaskEnvironment(
    `${trace2SkillRunId(options.family.name, options.replicate)}-t${options.traceIndex}`,
    options.config.experimentConfig.reuseDockerImages,
    options.config.experimentConfig.dockerProxy,
  );
  try {
    const evaluated = await options.orchestrator.evaluateTrainingPackage({
      runRoot: options.runRoot,
      environment,
      family: options.family,
      familyRoot: familyPath(options.config.experimentConfig, options.family),
      snapshotPackage: options.seedPackage,
      iteration: options.traceIndex,
      artifactsRoot: path.join(options.runRoot, "artifacts", `trajectory-${options.traceIndex}`),
      prompt: tracePoolSolverPrompt(options.family.name, options.traceIndex),
    });
    if (!evaluated.rawSessionFile) throw new Error("Pi did not persist the fresh v01 solver session");
    const rawSession = await readFile(evaluated.rawSessionFile);
    const artifact: Trace2SkillTrajectoryArtifact = {
      ...evaluated.result,
      trajectory: evaluated.trajectory,
      rawSessionFile: evaluated.rawSessionFile,
      rawSessionSha256: sha256(rawSession),
    };
    await writeJson(trajectoryPath, artifact);
    return artifact;
  } finally {
    await environment.stop();
  }
}

async function mapLimit<T, R>(items: T[], concurrency: number, worker: (item: T) => Promise<R>): Promise<R[]> {
  const results = new Array<R>(items.length);
  let cursor = 0;
  await Promise.all(Array.from({ length: Math.min(concurrency, items.length) }, async () => {
    while (cursor < items.length) {
      const index = cursor++;
      results[index] = await worker(items[index]!);
    }
  }));
  return results;
}

function mean(values: number[]): number {
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

export function summarizeTrace2SkillMatrix(
  summaries: Trace2SkillRunSummary[],
  families: FamilyConfig[],
  replicates: number[],
): Trace2SkillMatrixMetrics {
  const expectedRuns = families.length * replicates.length;
  const expectedOutcomes = replicates.length
    * families.reduce((sum, family) => sum + family.heldout.length, 0);
  const expected = new Map(families.map((family) => [family.name, family]));
  const keys = new Set<string>();
  let complete = summaries.length === expectedRuns;
  for (const summary of summaries) {
    const key = `${summary.family}/r${summary.replicate}`;
    if (keys.has(key) || !expected.has(summary.family) || !replicates.includes(summary.replicate)) complete = false;
    keys.add(key);
    const family = expected.get(summary.family);
    if (!family || summary.heldout.length !== family.heldout.length) complete = false;
    if (family && summary.heldout.some((row) => !family.heldout.includes(row.variant))) complete = false;
  }
  const familyScores = new Map<string, number>();
  for (const summary of summaries) {
    if (summary.heldout.length > 0) {
      familyScores.set(`${summary.family}/r${summary.replicate}`, mean(summary.heldout.map((row) => row.score)));
    }
  }
  const replicateFamilyMacro: Record<string, number> = {};
  for (const replicate of replicates) {
    const scores = families.flatMap((family) => {
      const score = familyScores.get(`${family.name}/r${replicate}`);
      return score === undefined ? [] : [score];
    });
    if (scores.length === families.length) replicateFamilyMacro[String(replicate)] = mean(scores);
  }
  const familyAvg3: Record<string, number> = {};
  for (const family of families) {
    const scores = replicates.flatMap((replicate) => {
      const score = familyScores.get(`${family.name}/r${replicate}`);
      return score === undefined ? [] : [score];
    });
    if (scores.length === replicates.length) familyAvg3[family.name] = mean(scores);
  }
  const allOutcomes = summaries.flatMap((summary) => summary.heldout);
  return {
    complete: complete && allOutcomes.length === expectedOutcomes,
    runs: summaries.length,
    heldoutOutcomes: allOutcomes.length,
    familyMacroAvg3: Object.keys(familyAvg3).length === families.length ? mean(Object.values(familyAvg3)) : null,
    variantMacroAvg3: allOutcomes.length === expectedOutcomes ? mean(allOutcomes.map((row) => row.score)) : null,
    replicateFamilyMacro,
    familyAvg3,
  };
}

export class Trace2SkillBaselineRunner {
  private readonly orchestrator: RunOrchestrator;

  constructor(
    private readonly config: Trace2SkillConfig,
    private readonly models: ModelBundle,
    private readonly provider: { baseUrl: string; apiKey: string },
  ) {
    this.orchestrator = new RunOrchestrator(config.experimentConfig, models);
  }

  async runFamily(
    family: FamilyConfig,
    replicate: number,
    phase: "induce" | "evaluate" | "all",
  ): Promise<Trace2SkillRunSummary> {
    const runId = trace2SkillRunId(family.name, replicate);
    const runRoot = trace2SkillRunRoot(this.config, family.name, replicate);
    const seedPackage = path.join(runRoot, "seed-skill", family.name);
    await mkdir(runRoot, { recursive: true });
    if (!(await access(path.join(seedPackage, "SKILL.md")).then(() => true).catch(() => false))) {
      await createWeakSeedPackage(seedPackage, family);
    }
    const seedManifest = await skillPackageManifest(seedPackage);
    const seedPackageSha256 = skillPackageSha256(seedManifest);
    const metadataPath = path.join(runRoot, "run-metadata.json");
    assertFrozenSeedManifest(await readJsonIfExists<unknown>(metadataPath), seedPackageSha256);
    await writeJson(metadataPath, {
      schemaVersion: 1,
      protocolVersion: TRACE2SKILL_PROTOCOL,
      runId,
      family: family.name,
      replicate,
      trainingMember: family.train,
      heldoutVariants: family.heldout,
      tracesPerFamily: this.config.tracesPerFamily,
      poolSemantics: "independent-fresh-plus-rollouts-from-one-identical-weak-seed-package",
      compilationSemantics: "one-official-map-merge-apply-over-the-complete-trajectory-local-record-pool",
      selectionSemantics: "no-best-of-selection-every-replicate-is-evaluated",
      solverModel: this.config.experimentConfig.provider.studentModel,
      analystAndEvolverModel: this.config.experimentConfig.provider.teacherModel,
      upstreamRepository: this.config.upstreamRepository,
      upstreamCommit: this.config.upstreamCommit,
      configSha256: sha256(await readFile(this.config.configPath)),
      seedPackageSha256,
      seedManifest,
    });

    const finalPackage = path.join(
      runRoot,
      "snapshots",
      `iteration-${this.config.tracesPerFamily}`,
      "skill",
      family.name,
    );
    let traceRows: Trace2SkillRunSummary["traces"] = [];
    if (phase !== "evaluate") {
      const indices = Array.from({ length: this.config.tracesPerFamily }, (_, index) => index + 1);
      const artifacts = await mapLimit(indices, this.config.trajectoryConcurrency, async (traceIndex) => {
        console.log(`[trace2skill/${family.name}/r${replicate}] collect v01 trajectory ${traceIndex}`);
        return await collectTrajectory({
          config: this.config,
          orchestrator: this.orchestrator,
          family,
          replicate,
          traceIndex,
          runRoot,
          seedPackage,
        });
      });
      const analyzed = await mapLimit(indices, this.config.trajectoryConcurrency, async (traceIndex) => {
        console.log(`[trace2skill/${family.name}/r${replicate}] analyze trajectory ${traceIndex}`);
        const artifact = artifacts[traceIndex - 1]!;
        if (!artifact.rawSessionFile) throw new Error(`Missing raw session for trajectory ${traceIndex}`);
        const rawSession = await readFile(artifact.rawSessionFile, "utf8");
        if (artifact.rawSessionSha256 && sha256(rawSession) !== artifact.rawSessionSha256) {
          throw new Error(`Raw solver session changed before analysis: ${artifact.rawSessionFile}`);
        }
        return await analyzeTrajectory({
          config: this.config,
          models: this.models,
          family,
          replicate,
          traceIndex,
          runRoot,
          artifact,
          rawSession,
        });
      });
      console.log(`[trace2skill/${family.name}/r${replicate}] official MAP–MERGE–APPLY`);
      await evolveTracePool({
        config: this.config,
        family,
        runRoot,
        seedPackage,
        errorRecords: analyzed.filter((item) => item.source === "error").map((item) => item.record),
        successRecords: analyzed.filter((item) => item.source === "success").map((item) => item.record),
        baseUrl: this.provider.baseUrl,
        apiKey: this.provider.apiKey,
      });
      traceRows = artifacts.map((artifact, index) => ({
        index: index + 1,
        score: artifact.tests.score,
        passed: artifact.tests.passed,
        total: artifact.tests.total,
        recordSource: analyzed[index]!.source,
      }));
      await writeJson(path.join(runRoot, "induction-summary.json"), { traces: traceRows });
    } else {
      await access(path.join(finalPackage, "SKILL.md"));
      traceRows = (await readJsonIfExists<{ traces: Trace2SkillRunSummary["traces"] }>(
        path.join(runRoot, "induction-summary.json"),
      ))?.traces ?? [];
    }

    let heldout: EvalResult[] = [];
    if (phase !== "induce") {
      console.log(`[trace2skill/${family.name}/r${replicate}] fresh held-out evaluation`);
      heldout = await this.orchestrator.evaluateFrozenPackage({
        evaluationRoot: path.join(runRoot, "heldout", `iteration-${this.config.tracesPerFamily}`),
        evaluationId: `${runId}-heldout`,
        evaluationKind: "adapted-trace2skill-final-package-heldout",
        sourceRunId: runId,
        family,
        iteration: this.config.tracesPerFamily,
        snapshotPackage: finalPackage,
        variants: family.heldout,
        variantConcurrency: Math.min(this.config.heldoutVariantConcurrency, family.heldout.length),
      });
    }
    const manifest = await skillPackageManifest(finalPackage);
    const summary: Trace2SkillRunSummary = {
      schemaVersion: 1,
      protocolVersion: TRACE2SKILL_PROTOCOL,
      family: family.name,
      replicate,
      runId,
      runRoot,
      traces: traceRows,
      finalSkillPackage: finalPackage,
      finalSkillPackageSha256: skillPackageSha256(manifest),
      heldout: heldout.map((result) => ({
        variant: result.variant,
        score: result.tests.score,
        passed: result.tests.passed,
        total: result.tests.total,
      })),
    };
    await writeJson(path.join(runRoot, "summary.json"), summary);
    return summary;
  }

  async runMatrix(options: {
    families: FamilyConfig[];
    replicates: number[];
    phase: "induce" | "evaluate" | "all";
    familyConcurrency?: number;
  }): Promise<Trace2SkillRunSummary[]> {
    const groups = options.replicates.flatMap((replicate) =>
      options.families.map((family) => ({ family, replicate }))
    );
    return await mapLimit(
      groups,
      options.familyConcurrency ?? this.config.familyConcurrency,
      async ({ family, replicate }) => await this.runFamily(family, replicate, options.phase),
    );
  }
}
