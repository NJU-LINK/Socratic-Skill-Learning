import { spawn } from "node:child_process";
import { hostname } from "node:os";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import YAML from "yaml";
import type { ModelBundle } from "../agent/model.js";
import { skillPackageManifest, skillPackageSha256 } from "../agent/skill-package.js";
import { familyPath } from "../experiment/config.js";
import { RunOrchestrator, validateSkill } from "../experiment/orchestrator.js";
import type { EvalResult, FamilyConfig } from "../experiment/types.js";
import { skillKdRunId, type SkillKdConfig } from "./skill-kd-config.js";
import { sha256 } from "./skill-kd-rollout.js";
import { skillKdPythonEnv } from "./skill-kd-upstream.js";
import { readJsonIfExists, writeJson } from "./trace2skill-io.js";

export type SkillKdPhase = "induce" | "evaluate" | "all";
export interface SkillKdUsage {
  model: string; input_tokens: number; output_tokens: number; cached_tokens: number; requests: number;
}
interface Acquisition {
  fingerprint: string; upstreamCommit: string; anchorPasses: number; maxAdaptiveRounds: number;
  skillVersion: number; skillMarkdown: string; rules: string; groups: unknown[];
  usage: Record<string, SkillKdUsage>;
}
export interface SkillKdRunSummary {
  protocolVersion: string;
  family: string;
  replicate: number;
  runRoot: string;
  fingerprint: string;
  packageSha256: string;
  skillVersion: number;
  acquisitionUsage: Record<string, SkillKdUsage>;
  usageAuditFile?: string;
  heldout: { variant: string; score: number; passed: number; total: number }[];
}

export async function publicSkillKdTask(config: SkillKdConfig, family: FamilyConfig): Promise<string> {
  const root = familyPath(config.experimentConfig, family);
  const spec = YAML.parse(await readFile(path.join(root, "spec.yaml"), "utf8"));
  delete spec.seed_task_dir;
  const task = await readFile(path.join(root, family.train, "task.yaml"), "utf8");
  return `<family_spec>\n${YAML.stringify(spec)}</family_spec>\n<anchor_task>\n${task}</anchor_task>`;
}

export async function assertFingerprint(file: string, fingerprint: string): Promise<void> {
  const prior = await readJsonIfExists<{ fingerprint: string }>(file);
  if (prior && prior.fingerprint !== fingerprint) throw new Error(`Run inputs changed; use a new runsRoot. Mismatch: ${file}`);
}

async function runBridge(config: SkillKdConfig, requestPath: string, provider: { baseUrl: string; apiKey: string }): Promise<void> {
  await new Promise<void>((resolve, reject) => {
    const child = spawn(path.join(config.pythonVenv, "bin", "python"), [
      path.join(config.projectRoot, "scripts/skill-kd/bridge.py"), requestPath,
    ], { cwd: config.projectRoot, stdio: ["ignore", "inherit", "inherit"], env: {
      ...skillKdPythonEnv(config), SKILL_KD_BASE_URL: provider.baseUrl, SKILL_KD_API_KEY: provider.apiKey,
      url: provider.baseUrl, key: provider.apiKey,
    } });
    const interrupt = () => { child.kill("SIGTERM"); };
    process.once("SIGINT", interrupt);
    process.once("SIGTERM", interrupt);
    const clean = () => {
      process.removeListener("SIGINT", interrupt);
      process.removeListener("SIGTERM", interrupt);
    };
    child.once("error", (error) => { clean(); reject(error); });
    child.once("close", (code) => {
      clean();
      if (code === 0) resolve();
      else reject(new Error(`SKILL-KD acquisition exited ${code}; inspect artifacts under ${path.dirname(requestPath)}`));
    });
  });
}

export async function mapSkillKdLimit<T, R>(items: T[], limit: number, fn: (item: T) => Promise<R>): Promise<R[]> {
  let next = 0;
  let failure: unknown;
  const results = new Array<R>(items.length);
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (!failure) {
      const index = next++;
      if (index >= items.length) return;
      try { results[index] = await fn(items[index]!); }
      catch (error) { failure ??= error; }
    }
  }));
  if (failure) throw failure;
  return results;
}

export class SkillKdRunner {
  private implementation?: Promise<string>;
  constructor(private config: SkillKdConfig, private models: ModelBundle,
    private provider: { baseUrl: string; apiKey: string }) {}

  private implementationHash(): Promise<string> {
    this.implementation ??= (async () => {
      const manifests = await Promise.all(["src", "scripts/skill-kd"].map(async (dir) =>
        (await skillPackageManifest(path.join(this.config.projectRoot, dir)))
          .filter((entry) => !entry.path.includes("__pycache__") && !entry.path.endsWith(".pyc"))));
      return sha256(JSON.stringify({ manifests,
        lock: sha256(await readFile(path.join(this.config.projectRoot, "package-lock.json"))) }));
    })();
    return this.implementation;
  }

  async runFamily(family: FamilyConfig, replicate: number, phase: SkillKdPhase): Promise<SkillKdRunSummary> {
    const config = this.config;
    const runId = skillKdRunId(family.name, replicate);
    const runRoot = path.join(config.runsRoot, runId);
    await mkdir(runRoot, { recursive: true });
    const lock = path.join(runRoot, ".run-lock");
    try { await mkdir(lock); }
    catch (error) {
      if ((error as NodeJS.ErrnoException).code === "EEXIST") {
        throw new Error(`Run is locked; inspect ${path.join(lock, "owner.json")} before removing a stale lock`);
      }
      throw error;
    }
    try {
      await writeJson(path.join(lock, "owner.json"), { pid: process.pid, host: hostname(), at: new Date().toISOString() });
      const publicTask = await publicSkillKdTask(config, family);
      const inputs = {
        protocolVersion: config.protocolVersion, upstreamCommit: config.upstreamCommit, family, replicate,
        anchorPasses: config.anchorPasses, maxAdaptiveRounds: config.maxAdaptiveRounds,
        provider: config.experimentConfig.provider, endpointSha256: sha256(this.provider.baseUrl),
        agentSolveTimeoutMs: config.experimentConfig.agentSolveTimeoutMs ?? null,
        dockerProxy: config.experimentConfig.dockerProxy ?? null,
        reuseDockerImages: config.experimentConfig.reuseDockerImages,
        experimentConfigSha256: sha256(await readFile(config.experimentConfig.configPath)),
        implementationSha256: await this.implementationHash(),
        familyAssetsSha256: skillPackageSha256(await skillPackageManifest(familyPath(config.experimentConfig, family))),
        publicTaskSha256: sha256(publicTask),
      };
      const fingerprint = sha256(JSON.stringify(inputs));
      const metadataPath = path.join(runRoot, "run-metadata.json");
      await assertFingerprint(metadataPath, fingerprint);
      if (!(await readJsonIfExists(metadataPath))) {
        if (phase === "evaluate") throw new Error(`No acquisition metadata at ${runRoot}; run --phase induce first`);
        await writeJson(metadataPath, { fingerprint, ...inputs, createdAt: new Date().toISOString() });
      }
      const outDir = path.join(runRoot, "acquisition");
      const completePath = path.join(outDir, "complete.json");
      await assertFingerprint(completePath, fingerprint);
      let acquisition = await readJsonIfExists<Acquisition>(completePath);
      if (!acquisition) {
        if (phase === "evaluate") throw new Error(`Acquisition incomplete: ${runRoot}`);
        const requestPath = path.join(runRoot, "acquisition-request.json");
        await writeJson(requestPath, { fingerprint, upstreamCommit: config.upstreamCommit,
          configPath: config.configPath, projectRoot: config.projectRoot, outDir,
          family: family.name, train: family.train, publicTask,
          anchorPasses: config.anchorPasses, maxAdaptiveRounds: config.maxAdaptiveRounds,
          teacherModel: config.experimentConfig.provider.teacherModel,
          studentModel: config.experimentConfig.provider.studentModel,
          maxCompletionTokens: config.experimentConfig.provider.maxCompletionTokens,
          rolloutCommand: [process.execPath, "--import", "tsx", path.join(config.projectRoot, "src/commands/run-skill-kd-rollout.ts")],
        });
        console.log(`[${runId}] acquiring with pinned SKILL-KD`);
        await runBridge(config, requestPath, this.provider);
        acquisition = await readJsonIfExists<Acquisition>(completePath);
      }
      if (!acquisition || acquisition.fingerprint !== fingerprint
          || acquisition.upstreamCommit !== config.upstreamCommit || acquisition.anchorPasses !== config.anchorPasses
          || acquisition.maxAdaptiveRounds !== config.maxAdaptiveRounds || acquisition.groups.length !== config.anchorPasses) {
        throw new Error(`Invalid SKILL-KD completion: ${completePath}`);
      }
      const finalPackage = path.join(runRoot, "snapshots", "iteration-3", "skill", family.name);
      const frozenPath = path.join(runRoot, "frozen-package.json");
      const frozen = await readJsonIfExists<{ fingerprint: string; packageSha256: string; acquisitionSha256: string }>(frozenPath);
      const acquisitionSha256 = sha256(await readFile(completePath));
      if (frozen) {
        if (frozen.fingerprint !== fingerprint || frozen.acquisitionSha256 !== acquisitionSha256
            || skillPackageSha256(await skillPackageManifest(finalPackage)) !== frozen.packageSha256) {
          throw new Error(`Frozen acquisition/package changed: ${runRoot}`);
        }
      } else {
        await mkdir(finalPackage, { recursive: true });
        await writeFile(path.join(finalPackage, "SKILL.md"), acquisition.skillMarkdown, "utf8");
        await validateSkill(path.join(finalPackage, "SKILL.md"), family.name);
        await writeJson(frozenPath, { fingerprint, acquisitionSha256,
          packageSha256: skillPackageSha256(await skillPackageManifest(finalPackage)) });
      }
      let heldout: EvalResult[] = [];
      if (phase !== "induce") {
        heldout = await new RunOrchestrator(config.experimentConfig, this.models).evaluateFrozenPackage({
          evaluationRoot: path.join(runRoot, "heldout", "iteration-3"), evaluationId: `${runId}-heldout`,
          evaluationKind: "adapted-skill-kd-final-package-heldout", sourceRunId: runId,
          family, iteration: config.anchorPasses, snapshotPackage: finalPackage, variants: family.heldout,
          variantConcurrency: Math.min(config.heldoutVariantConcurrency, family.heldout.length),
        });
        for (const result of heldout) {
          if (result.family !== family.name || result.split !== "heldout" || result.iteration !== config.anchorPasses) {
            throw new Error("Cached held-out result belongs to a different run");
          }
        }
      }
      const summary: SkillKdRunSummary = {
        protocolVersion: config.protocolVersion, family: family.name, replicate, runRoot, fingerprint,
        packageSha256: skillPackageSha256(await skillPackageManifest(finalPackage)), skillVersion: acquisition.skillVersion,
        acquisitionUsage: acquisition.usage,
        usageAuditFile: path.join(outDir, "usage-audit.json"),
        heldout: heldout.map((r) => ({ variant: r.variant, score: r.tests.score, passed: r.tests.passed, total: r.tests.total })),
      };
      // Re-running induce must not erase a previously completed evaluation.
      await writeJson(path.join(runRoot, phase === "induce" ? "induction-summary.json" : "run-summary.json"), summary);
      return summary;
    } finally {
      await rm(lock, { recursive: true, force: true });
    }
  }
}

export function summarizeSkillKd(summaries: SkillKdRunSummary[], families: FamilyConfig[], replicates: number[],
  exclusions: SkillKdConfig["analysisExclusions"]) {
  const selected = new Set(replicates.flatMap((replicate) => families.map((f) => `${f.name}/${replicate}`)));
  if (summaries.length !== selected.size) throw new Error("Incomplete run matrix");
  for (const summary of summaries) {
    if (!selected.delete(`${summary.family}/${summary.replicate}`)) throw new Error("Unexpected or duplicate run");
    const variants = new Set(families.find((f) => f.name === summary.family)!.heldout);
    if (summary.heldout.length !== variants.size) throw new Error(`Incomplete held-out results: ${summary.family}`);
    for (const row of summary.heldout) {
      if (!variants.delete(row.variant) || !Number.isFinite(row.score) || row.score < 0 || row.score > 1) {
        throw new Error("Unexpected/duplicate held-out variant or invalid score");
      }
    }
  }
  const excluded = new Set(exclusions.map((r) => `${r.family}/${r.variant}`));
  const mean = (values: number[]) => values.reduce((a, b) => a + b, 0) / values.length;
  const metrics = (applyExclusions: boolean) => {
    const rows = summaries.flatMap((s) => s.heldout.filter((r) => !applyExclusions || !excluded.has(`${s.family}/${r.variant}`))
      .map((r) => ({ family: s.family, replicate: s.replicate, ...r })));
    const familyMean = Object.fromEntries(families.map((f) => {
      const scores = rows.filter((r) => r.family === f.name).map((r) => r.score);
      if (!scores.length) throw new Error(`No analyzed variants for ${f.name}`);
      return [f.name, mean(scores)];
    }));
    return { heldoutOutcomes: rows.length, distinctVariants: rows.length / replicates.length,
      familyMacro: mean(Object.values(familyMean)), variantMacro: mean(rows.map((r) => r.score)), familyMean };
  };
  return { runs: summaries.length, replicates, raw: metrics(false), analysis: metrics(true), analysisExclusions: exclusions };
}
