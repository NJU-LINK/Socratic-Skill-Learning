import { cp, mkdir, readFile, readdir } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import YAML from "yaml";
import type { AssistantMessage } from "@earendil-works/pi-ai";
import { createModels } from "../agent/model.js";
import { createModelPool } from "../agent/model-pool.js";
import { providerEnvironment as providerEnv } from "../agent/env.js";
import {
  createEvaluatorSession,
  promptWithInfrastructureRecovery,
  reportWorkspaceBoundaryWarnings,
  type ManagedSession,
  type PromptCompletion,
  type WorkspaceBoundaryViolation,
} from "../agent/sessions.js";
import {
  NO_SKILL_EVALUATOR_SYSTEM,
  evaluateNoSkillPrompt,
} from "../agent/prompts.js";
import {
  assetFamilyPath,
  type AssetCatalog,
} from "../assets/catalog.js";
import { TaskEnvironment } from "../runtime/docker.js";
import { DeadlineExceededError, runWithDeadline } from "../runtime/deadline.js";
import { acquireProcessFileLock } from "../runtime/file-lock.js";
import type { FamilyConfig, PilotConfig } from "./types.js";
import {
  enumerateNoSkillTargets,
  noSkillResultPath,
  noSkillCondition,
  noSkillTargetKey,
  noSkillFamilyMacro,
  readNoSkillResult,
  sha256,
  summarizeNoSkillResults,
  writeJsonAtomic,
  type NoSkillModelResponse,
  type NoSkillResult,
  type NoSkillTarget,
  type NoSkillUsage,
} from "./no-skill-sweep.js";
import { implementationProvenance } from "./provenance.js";

export interface NoSkillSweepOptions {
  config: PilotConfig;
  catalog: AssetCatalog;
  families: FamilyConfig[];
  requestedVariants?: string[];
  sweepRoot: string;
  replicate: number;
  concurrency: number;
  heldoutOnly: boolean;
  agentSolveTimeoutMs: number;
  retryInvalid: boolean;
}

export interface NoSkillSweepSummary {
  schemaVersion: 1;
  generatedAt: string;
  sweepIdentitySha256: string;
  replicate: number;
  selectedTargets: number;
  missingTargets: number;
  targets: number;
  complete: number;
  taskTimeout: number;
  infrastructureInvalid: number;
  fullScore: number;
  partialScore: number;
  zeroScore: number;
  macroScore: number | null;
  familyMacroScore: number | null;
  microScore: number | null;
  totalPassed: number;
  totalTests: number;
  usage: NoSkillUsage;
  invalidByPhase: Record<string, number>;
}

interface PendingTarget {
  target: NoSkillTarget;
  previous?: NoSkillResult;
}

function targetsFor(options: NoSkillSweepOptions): NoSkillTarget[] {
  const enumerated = enumerateNoSkillTargets(
    options.families,
    options.requestedVariants,
  );
  const targets = options.heldoutOnly
    ? enumerated.filter((target) => target.variant !== target.family.train)
    : enumerated;
  if (targets.length === 0) throw new Error("No no-Skill sweep targets selected");
  return targets;
}

export function describeNoSkillSweep(options: NoSkillSweepOptions) {
  const targets = targetsFor(options);
  return {
    condition: noSkillCondition(options.config.provider.studentModel),
    families: options.families.length,
    targets: targets.length,
    replicate: options.replicate,
    concurrency: options.concurrency,
    split: options.heldoutOnly ? "heldout-only" : "train-and-heldout",
    agentSolveTimeoutMs: options.agentSolveTimeoutMs,
    sweepRoot: options.sweepRoot,
    targetListSha256: sha256(targets.map(noSkillTargetKey).join("\n")),
    countsByFamily: Object.fromEntries(
      options.families.map((family) => [
        family.name,
        targets.filter((target) => target.family.name === family.name).length,
      ]),
    ),
  };
}

async function mapLimit<T, R>(
  items: T[],
  concurrency: number,
  worker: (item: T, index: number) => Promise<R>,
): Promise<R[]> {
  const results = new Array<R>(items.length);
  let cursor = 0;
  await Promise.all(
    Array.from({ length: Math.min(concurrency, items.length) }, async () => {
      while (cursor < items.length) {
        const index = cursor++;
        results[index] = await worker(items[index]!, index);
      }
    }),
  );
  return results;
}

async function readJsonIfExists<T>(filePath: string): Promise<T | undefined> {
  return await readFile(filePath, "utf8")
    .then((text) => JSON.parse(text) as T)
    .catch((error: unknown) => {
      const code = error && typeof error === "object" && "code" in error
        ? String((error as { code?: unknown }).code)
        : "";
      if (code === "ENOENT") return undefined;
      throw error;
    });
}

async function providerEnvironment(
  projectRoot: string,
): Promise<{ baseUrl: string; apiKey: string }> {
  return await providerEnv(projectRoot);
}

export { providerEnvironment };

const ZERO_USAGE: NoSkillUsage = {
  input: 0,
  output: 0,
  cacheRead: 0,
  cacheWrite: 0,
  reasoning: 0,
  totalTokens: 0,
};

function assistantMessages(session: ManagedSession | undefined): AssistantMessage[] {
  if (!session) return [];
  return session.session.state.messages.filter(
    (message): message is AssistantMessage => message.role === "assistant",
  );
}

function modelResponses(session: ManagedSession | undefined): NoSkillModelResponse[] {
  return assistantMessages(session).map((message) => ({
    requestedModel: message.model,
    responseModel: message.responseModel ?? null,
    stopReason: message.stopReason,
    usage: {
      input: message.usage.input,
      output: message.usage.output,
      cacheRead: message.usage.cacheRead,
      cacheWrite: message.usage.cacheWrite,
      reasoning: message.usage.reasoning ?? 0,
      totalTokens: message.usage.totalTokens,
    },
    errorMessage: message.errorMessage ?? null,
  }));
}

function aggregateUsage(responses: NoSkillModelResponse[]): NoSkillUsage {
  return responses.reduce<NoSkillUsage>(
    (sum, response) => ({
      input: sum.input + response.usage.input,
      output: sum.output + response.usage.output,
      cacheRead: sum.cacheRead + response.usage.cacheRead,
      cacheWrite: sum.cacheWrite + response.usage.cacheWrite,
      reasoning: sum.reasoning + response.usage.reasoning,
      totalTokens: sum.totalTokens + response.usage.totalTokens,
    }),
    { ...ZERO_USAGE },
  );
}

async function nextAttempt(
  targetSessionRoot: string,
  previous: NoSkillResult | undefined,
): Promise<number> {
  const entries = await readdir(targetSessionRoot, { withFileTypes: true }).catch(
    (error: unknown) => {
      const code = error && typeof error === "object" && "code" in error
        ? String((error as { code?: unknown }).code)
        : "";
      if (code === "ENOENT") return [];
      throw error;
    },
  );
  const attempts = entries
    .filter((entry) => entry.isDirectory())
    .map((entry) => Number(entry.name.match(/^attempt-(\d+)$/)?.[1] ?? 0));
  return Math.max(previous?.attempt ?? 0, ...attempts, 0) + 1;
}

async function runTarget(options: {
  sweep: NoSkillSweepOptions;
  sweepIdentitySha256: string;
  replicateRoot: string;
  models: Awaited<ReturnType<typeof createModels>>;
  target: NoSkillTarget;
  previous?: NoSkillResult;
  targetIndex: number;
}): Promise<NoSkillResult> {
  const {
    sweep,
    sweepIdentitySha256,
    replicateRoot,
    models,
    target,
    previous,
    targetIndex,
  } = options;
  const { config, catalog, replicate } = sweep;
  const condition = noSkillCondition(config.provider.studentModel);
  const targetKey = noSkillTargetKey(target);
  const resultPath = noSkillResultPath(replicateRoot, target);
  const targetSessionRoot = path.join(
    replicateRoot,
    "sessions",
    target.family.name,
    target.variant,
  );
  const attempt = await nextAttempt(targetSessionRoot, previous);
  const attemptRoot = path.join(targetSessionRoot, `attempt-${attempt}`);
  const workspace = path.join(attemptRoot, "workspace");
  const sessionDir = path.join(attemptRoot, "session");
  const variantRoot = path.join(
    assetFamilyPath(catalog, target.family),
    target.variant,
  );
  const environment = new TaskEnvironment(
    `no-skill-r${replicate}-${process.pid}-${targetIndex}`,
    catalog.reuseDockerImages,
    catalog.dockerProxy,
  );
  const startedAt = new Date().toISOString();
  const startedMs = Date.now();
  let phase = "workspace-setup";
  let session: ManagedSession | undefined;
  let completion: PromptCompletion | undefined;
  let toolCallsBefore = 0;
  let boundaryViolations: WorkspaceBoundaryViolation[] = [];
  let result: NoSkillResult;

  try {
    await mkdir(workspace, { recursive: true });
    await cp(path.join(variantRoot, "task.yaml"), path.join(workspace, "task.yaml"));
    phase = "session-create";
    session = await createEvaluatorSession({
      label: `no-skill-r${replicate}-${target.family.name}-${target.variant}`,
      cwd: workspace,
      sessionDir,
      systemPrompt: NO_SKILL_EVALUATOR_SYSTEM,
      model: models.student,
      runtime: models.runtime,
      config,
      environment,
    });
    const loadedSkills = session.loadedSkills();
    if (loadedSkills.length !== 0) {
      throw new Error(
        `No-Skill solver loaded unexpected Skills: ${loadedSkills.map((skill) => skill.name).join(", ")}`,
      );
    }
    const task = YAML.parse(await readFile(path.join(variantRoot, "task.yaml"), "utf8")) as {
      max_test_timeout_sec?: number;
    };
    phase = "container-reset";
    await environment.reset(target.family.name, target.variant, variantRoot);
    phase = "agent-solve";
    session.trace.setPhase("no-skill-eval");
    toolCallsBefore = session.trace.getToolCallCount();
    completion = await runWithDeadline({
      label: `${targetKey} agent solve`,
      timeoutMs: sweep.agentSolveTimeoutMs,
      operation: async () => await promptWithInfrastructureRecovery(
        session!.session,
        evaluateNoSkillPrompt(target.family.name, target.variant),
        `${targetKey} no-Skill evaluation`,
      ),
      onTimeout: async () => {
        await Promise.allSettled([
          session!.session.abort(),
          environment.stop(),
        ]);
      },
    });
    boundaryViolations = reportWorkspaceBoundaryWarnings(
      session,
      `${targetKey} no-Skill evaluation`,
    );
    phase = "environment-check";
    environment.assertValid();
    phase = "scoring";
    const tests = await environment.runTests(Number(task.max_test_timeout_sec ?? 300));
    const responses = modelResponses(session);
    result = {
      schemaVersion: 3,
      sweepIdentitySha256,
      condition,
      family: target.family.name,
      variant: target.variant,
      replicate,
      attempt,
      status: "complete",
      startedAt,
      finishedAt: new Date().toISOString(),
      wallTimeMs: Date.now() - startedMs,
      agentSolveTimeoutMs: sweep.agentSolveTimeoutMs,
      requestedModel: config.provider.studentModel,
      loadedSkills: [],
      toolCalls: session.trace.getToolCallCount() - toolCallsBefore,
      agentAttempts: completion.attempts,
      recoveredFromInterruption: completion.recovered,
      workspaceBoundaryViolations: boundaryViolations,
      modelResponses: responses,
      usage: aggregateUsage(responses),
      sessionFile: session.session.sessionFile ?? null,
      tests,
    };
  } catch (error) {
    if (session) {
      boundaryViolations.push(...reportWorkspaceBoundaryWarnings(
        session,
        `${targetKey} no-Skill evaluation`,
      ));
    }
    const responses = modelResponses(session);
    const common = {
      schemaVersion: 3 as const,
      sweepIdentitySha256,
      condition,
      family: target.family.name,
      variant: target.variant,
      replicate,
      attempt,
      startedAt,
      finishedAt: new Date().toISOString(),
      wallTimeMs: Date.now() - startedMs,
      agentSolveTimeoutMs: sweep.agentSolveTimeoutMs,
      requestedModel: config.provider.studentModel,
      loadedSkills: session?.loadedSkills().map((skill) => skill.name) ?? [],
      toolCalls: session
        ? Math.max(0, session.trace.getToolCallCount() - toolCallsBefore)
        : 0,
      agentAttempts: completion?.attempts ?? 0,
      recoveredFromInterruption: completion?.recovered ?? false,
      workspaceBoundaryViolations: boundaryViolations,
      modelResponses: responses,
      usage: aggregateUsage(responses),
      sessionFile: session?.session.sessionFile ?? null,
    };
    result = error instanceof DeadlineExceededError ? {
      ...common,
      status: "task-timeout",
      failedPhase: "agent-solve",
      timeoutAt: error.timeoutAt,
      tests: {
        passed: 0,
        failed: 0,
        errors: 0,
        total: 0,
        score: 0,
        output: `Agent solve timed out after ${error.timeoutMs}ms; private scorer was not run.`,
        exitCode: 124,
        timedOut: true,
      },
    } : {
      ...common,
      status: "infrastructure-invalid",
      failedPhase: phase,
      errorName: error instanceof Error ? error.name : "UnknownError",
      errorMessage: error instanceof Error ? error.message : String(error),
    };
  }

  try {
    await session?.dispose();
  } catch (error) {
    console.warn(`[cleanup] ${targetKey} session: ${error instanceof Error ? error.message : String(error)}`);
  }
  try {
    await environment.stop();
  } catch (error) {
    console.warn(`[cleanup] ${targetKey} container: ${error instanceof Error ? error.message : String(error)}`);
  }

  await writeJsonAtomic(path.join(attemptRoot, "result.json"), result);
  await writeJsonAtomic(resultPath, result);
  return result;
}

export async function runNoSkillSweep(
  options: NoSkillSweepOptions,
): Promise<{ successful: boolean; summary: NoSkillSweepSummary }> {
  const { config, catalog, replicate, concurrency, sweepRoot } = options;
  const targets = targetsFor(options);
  const provenance = await implementationProvenance(config);
  if (provenance.git.dirty) {
    console.warn(
      "Warning: the working tree is dirty; recorded provenance identifies the last commit instead.",
    );
  }
  const identity = {
    condition: noSkillCondition(config.provider.studentModel),
    gitCommit: provenance.git.commit,
    implementationSha256: provenance.implementationSha256,
    promptSourceSha256: provenance.promptSourceSha256,
    configSha256: provenance.configSha256,
    catalogSha256: sha256(await readFile(catalog.catalogPath)),
    sourceManifestSha256: provenance.sourceManifestSha256,
    scorerManifestSha256: provenance.scorerManifestSha256,
    scorerPolicySha256: provenance.scorerPolicySha256,
    requestedModel: config.provider.studentModel,
    contextWindow: config.provider.contextWindow,
    maxCompletionTokens: config.provider.maxCompletionTokens,
    thinkingEnabled: config.provider.thinkingEnabled,
    reasoningEffort: config.provider.reasoningEffort ?? "high",
    split: options.heldoutOnly ? "heldout-only" : "train-and-heldout",
    agentSolveTimeoutMs: options.agentSolveTimeoutMs,
    dockerProxy: catalog.dockerProxy ?? null,
    reuseDockerImages: catalog.reuseDockerImages,
  };
  const sweepIdentitySha256 = sha256(JSON.stringify(identity));
  const sweepMetadataPath = path.join(sweepRoot, "sweep-metadata.json");
  const existingSweep = await readJsonIfExists<{
    sweepIdentitySha256?: string;
  }>(sweepMetadataPath);
  if (
    existingSweep?.sweepIdentitySha256
    && existingSweep.sweepIdentitySha256 !== sweepIdentitySha256
  ) {
    throw new Error(
      `Sweep identity mismatch at ${sweepRoot}; choose a new --sweep-root for changed code, assets, model, or config`,
    );
  }
  if (!existingSweep) {
    await writeJsonAtomic(sweepMetadataPath, {
      schemaVersion: 1,
      createdAt: new Date().toISOString(),
      sweepIdentitySha256,
      identity,
      configPath: config.configPath,
      catalogPath: catalog.catalogPath,
      assetsRoot: catalog.assetsRoot,
    });
  }

  const replicateRoot = path.join(sweepRoot, `replicate-${replicate}`);
  await mkdir(replicateRoot, { recursive: true });
  const releaseLock = await acquireProcessFileLock(
    path.join(replicateRoot, "run"),
    `No-Skill replicate ${replicate}`,
  );

  try {
    const targetKeys = targets.map(noSkillTargetKey);
    const targetListSha256 = sha256(targetKeys.join("\n"));
    const replicateMetadataPath = path.join(replicateRoot, "metadata.json");
    const previousMetadata = await readJsonIfExists<{
      sweepIdentitySha256?: string;
      targetListSha256?: string;
      createdAt?: string;
    }>(replicateMetadataPath);
    if (
      previousMetadata
      && (
        previousMetadata.sweepIdentitySha256 !== sweepIdentitySha256
        || previousMetadata.targetListSha256 !== targetListSha256
      )
    ) {
      throw new Error(
        `Replicate ${replicate} was initialized with a different sweep identity or target list`,
      );
    }
    const createdAt = previousMetadata?.createdAt ?? new Date().toISOString();
    await writeJsonAtomic(replicateMetadataPath, {
      schemaVersion: 1,
      createdAt,
      lastStartedAt: new Date().toISOString(),
      status: "running",
      sweepIdentitySha256,
      replicate,
      concurrency,
      targetListSha256,
      targetKeys,
    });

    const pending: PendingTarget[] = [];
    let alreadyComplete = 0;
    let retainedInvalid = 0;
    for (const target of targets) {
      const previous = await readNoSkillResult(noSkillResultPath(replicateRoot, target));
      if (previous && (
        previous.sweepIdentitySha256 !== sweepIdentitySha256
        || previous.replicate !== replicate
        || previous.family !== target.family.name
        || previous.variant !== target.variant
      )) {
        throw new Error(`Stored result identity mismatch for ${noSkillTargetKey(target)}`);
      }
      if (previous?.status === "complete" || previous?.status === "task-timeout") {
        alreadyComplete += 1;
      } else if (previous?.status === "infrastructure-invalid" && !options.retryInvalid) {
        retainedInvalid += 1;
      } else {
        pending.push({ target, ...(previous ? { previous } : {}) });
      }
    }

    console.log(JSON.stringify({
      event: "no-skill-replicate-start",
      replicate,
      targets: targets.length,
      alreadyComplete,
      retainedInvalid,
      pending: pending.length,
      concurrency,
      sweepIdentitySha256,
      replicateRoot,
    }));

    const { baseUrl, apiKey } = await providerEnvironment(config.projectRoot);
    const modelPool = await createModelPool(config, baseUrl, apiKey, concurrency);
    let finished = alreadyComplete + retainedInvalid;
    await mapLimit(pending, concurrency, async ({ target, previous }, targetIndex) => {
      const result = await modelPool.run(noSkillTargetKey(target), async models => runTarget({
        sweep: options,
        sweepIdentitySha256,
        replicateRoot,
        models,
        target,
        ...(previous ? { previous } : {}),
        targetIndex,
      }));
      finished += 1;
      const outcome = result.status === "complete"
        ? `${result.tests.passed}/${result.tests.total}`
        : result.status === "task-timeout"
          ? `agent-solve: timeout-zero after ${result.agentSolveTimeoutMs}ms`
          : `${result.failedPhase}: ${result.errorMessage}`;
      console.log(
        `[replicate ${replicate} ${finished}/${targets.length}] `
        + `${result.status} ${noSkillTargetKey(target)} ${outcome}`,
      );
      return result;
    });

    const results = (
      await Promise.all(targets.map(async (target) =>
        await readNoSkillResult(noSkillResultPath(replicateRoot, target))
      ))
    ).filter((result): result is NoSkillResult => result !== undefined);
    const summary: NoSkillSweepSummary = {
      schemaVersion: 1,
      generatedAt: new Date().toISOString(),
      sweepIdentitySha256,
      replicate,
      selectedTargets: targets.length,
      missingTargets: targets.length - results.length,
      ...summarizeNoSkillResults(results),
      familyMacroScore: noSkillFamilyMacro(results),
    };
    await writeJsonAtomic(path.join(replicateRoot, "summary.json"), summary);
    const successful = summary.missingTargets === 0
      && summary.infrastructureInvalid === 0
      && summary.complete + summary.taskTimeout === targets.length;
    await writeJsonAtomic(replicateMetadataPath, {
      schemaVersion: 1,
      createdAt,
      finishedAt: new Date().toISOString(),
      status: successful ? "complete" : "needs-infrastructure-review",
      sweepIdentitySha256,
      replicate,
      concurrency,
      targetListSha256,
      targetKeys,
      summary,
    });
    console.log(JSON.stringify({
      event: "no-skill-replicate-finish",
      replicateRoot,
      ...summary,
    }, null, 2));
    return { successful, summary };
  } finally {
    await releaseLock();
  }
}
