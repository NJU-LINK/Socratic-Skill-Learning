import { createHash } from "node:crypto";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import path from "node:path";
import type { FamilyConfig, TestResult } from "./types.js";

export interface NoSkillTarget {
  family: FamilyConfig;
  variant: string;
}

export interface NoSkillUsage {
  input: number;
  output: number;
  cacheRead: number;
  cacheWrite: number;
  reasoning: number;
  totalTokens: number;
}

export interface NoSkillModelResponse {
  requestedModel: string;
  responseModel: string | null;
  stopReason: string;
  usage: NoSkillUsage;
  errorMessage: string | null;
}

interface NoSkillResultBase {
  schemaVersion: 3;
  sweepIdentitySha256: string;
  condition: string;
  family: string;
  variant: string;
  replicate: number;
  attempt: number;
  startedAt: string;
  finishedAt: string;
  wallTimeMs: number;
  agentSolveTimeoutMs: number;
  requestedModel: string;
  loadedSkills: string[];
  toolCalls: number;
  agentAttempts: number;
  recoveredFromInterruption: boolean;
  workspaceBoundaryViolations: Array<{
    toolName: string;
    requestedPath: string;
    reason: string;
  }>;
  modelResponses: NoSkillModelResponse[];
  usage: NoSkillUsage;
  sessionFile: string | null;
}

export interface NoSkillCompleteResult extends NoSkillResultBase {
  status: "complete";
  tests: TestResult;
}

export interface NoSkillInvalidResult extends NoSkillResultBase {
  status: "infrastructure-invalid";
  failedPhase: string;
  errorName: string;
  errorMessage: string;
}

export interface NoSkillTimeoutResult extends NoSkillResultBase {
  status: "task-timeout";
  failedPhase: "agent-solve";
  timeoutAt: string;
  tests: TestResult;
}

export type NoSkillResult =
  | NoSkillCompleteResult
  | NoSkillInvalidResult
  | NoSkillTimeoutResult;

export function noSkillCondition(modelId: string): string {
  return modelId === "qwen3.7-plus"
    ? "fresh-plus-no-agent-skill"
    : `fresh-${modelId}-no-agent-skill`;
}

export function enumerateNoSkillTargets(
  families: FamilyConfig[],
  requestedVariants?: string[],
): NoSkillTarget[] {
  return families.flatMap((family) => {
    const all = [family.train, ...family.heldout];
    if (!requestedVariants) {
      return all.map((variant) => ({ family, variant }));
    }
    const allowed = new Set(all);
    const missing = requestedVariants.filter((variant) => !allowed.has(variant));
    if (missing.length > 0) {
      throw new Error(`${family.name} does not configure variants: ${missing.join(", ")}`);
    }
    return requestedVariants.map((variant) => ({ family, variant }));
  });
}

export function noSkillTargetKey(target: NoSkillTarget): string {
  return `${target.family.name}/${target.variant}`;
}

export function noSkillResultPath(
  replicateRoot: string,
  target: NoSkillTarget,
): string {
  return path.join(
    replicateRoot,
    "results",
    target.family.name,
    `${target.variant}.json`,
  );
}

export function sha256(value: string | Buffer): string {
  return createHash("sha256").update(value).digest("hex");
}

export async function writeJsonAtomic(filePath: string, value: unknown): Promise<void> {
  await mkdir(path.dirname(filePath), { recursive: true });
  const temporary = `${filePath}.tmp-${process.pid}-${Date.now()}`;
  await writeFile(temporary, `${JSON.stringify(value, null, 2)}\n`, "utf8");
  await rename(temporary, filePath);
}

export async function readNoSkillResult(
  filePath: string,
): Promise<NoSkillResult | undefined> {
  return await readFile(filePath, "utf8")
    .then((text) => JSON.parse(text) as NoSkillResult)
    .catch((error: unknown) => {
      const code = error && typeof error === "object" && "code" in error
        ? String((error as { code?: unknown }).code)
        : "";
      if (code === "ENOENT") return undefined;
      throw error;
    });
}

export function summarizeNoSkillResults(results: NoSkillResult[]) {
  const complete = results.filter(
    (result): result is NoSkillCompleteResult => result.status === "complete",
  );
  const timedOut = results.filter(
    (result): result is NoSkillTimeoutResult => result.status === "task-timeout",
  );
  const invalid = results.filter(
    (result): result is NoSkillInvalidResult =>
      result.status === "infrastructure-invalid",
  );
  const scored = [...complete, ...timedOut];
  const scores = scored.map((result) => result.tests.score);
  const totalPassed = scored.reduce((sum, result) => sum + result.tests.passed, 0);
  const totalTests = scored.reduce((sum, result) => sum + result.tests.total, 0);
  const usage = scored.reduce<NoSkillUsage>(
    (sum, result) => ({
      input: sum.input + result.usage.input,
      output: sum.output + result.usage.output,
      cacheRead: sum.cacheRead + result.usage.cacheRead,
      cacheWrite: sum.cacheWrite + result.usage.cacheWrite,
      reasoning: sum.reasoning + result.usage.reasoning,
      totalTokens: sum.totalTokens + result.usage.totalTokens,
    }),
    {
      input: 0,
      output: 0,
      cacheRead: 0,
      cacheWrite: 0,
      reasoning: 0,
      totalTokens: 0,
    },
  );
  const invalidByPhase: Record<string, number> = {};
  for (const result of invalid) {
    invalidByPhase[result.failedPhase] =
      (invalidByPhase[result.failedPhase] ?? 0) + 1;
  }
  return {
    targets: results.length,
    complete: complete.length,
    taskTimeout: timedOut.length,
    infrastructureInvalid: invalid.length,
    fullScore: scores.filter((score) => score === 1).length,
    partialScore: scores.filter((score) => score > 0 && score < 1).length,
    zeroScore: scores.filter((score) => score === 0).length,
    macroScore: scores.length > 0
      ? scores.reduce((sum, score) => sum + score, 0) / scores.length
      : null,
    // A task-timeout is a valid variant-level zero, but private tests never run,
    // so its test-count denominator is unknown. Do not emit a deceptively
    // optimistic micro average that silently drops timed-out variants.
    microScore: timedOut.length === 0 && totalTests > 0
      ? totalPassed / totalTests
      : null,
    totalPassed,
    totalTests,
    usage,
    invalidByPhase,
  };
}

export function noSkillFamilyMacro(results: NoSkillResult[]): number | null {
  const byFamily = new Map<string, number[]>();
  for (const result of results) {
    if (result.status === "infrastructure-invalid") continue;
    const scores = byFamily.get(result.family) ?? [];
    scores.push(result.tests.score);
    byFamily.set(result.family, scores);
  }
  const familyScores = [...byFamily.values()].map(
    (scores) => scores.reduce((sum, score) => sum + score, 0) / scores.length,
  );
  return familyScores.length > 0
    ? familyScores.reduce((sum, score) => sum + score, 0) / familyScores.length
    : null;
}
