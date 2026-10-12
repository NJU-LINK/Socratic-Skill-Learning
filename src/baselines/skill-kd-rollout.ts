import { createHash, randomUUID } from "node:crypto";
import { access, mkdir, readFile } from "node:fs/promises";
import path from "node:path";
import { createModels, normalizeProviderBaseUrl, type ModelBundle } from "../agent/model.js";
import { providerEnvironment as providerEnv } from "../agent/env.js";
import { skillPackageManifest, skillPackageSha256 } from "../agent/skill-package.js";
import { familyPath } from "../experiment/config.js";
import { RunOrchestrator } from "../experiment/orchestrator.js";
import type { TestResult } from "../experiment/types.js";
import { TaskEnvironment } from "../runtime/docker.js";
import { loadSkillKdConfig } from "./skill-kd-config.js";
import { writeJson } from "./trace2skill-io.js";

export const sha256 = (text: string | Buffer): string => createHash("sha256").update(text).digest("hex");

export async function skillKdProvider(projectRoot: string): Promise<{ baseUrl: string; apiKey: string }> {
  return await providerEnv(projectRoot);
}

export function modelsForSkillKdRole(models: ModelBundle, role: string): ModelBundle {
  if (!["student", "student_retry", "teacher"].includes(role)) throw new Error(`Unknown rollout role: ${role}`);
  return role === "teacher" ? { ...models, student: models.teacher } : models;
}

// Match native training feedback: scalar verifier outcome plus its emitted
// report. No scorer source, reference solution, or held-out files are supplied.
export function skillKdEvaluation(tests: TestResult): Record<string, unknown> {
  if (!Number.isFinite(tests.score) || tests.score < 0 || tests.score > 1) throw new Error("Invalid verifier score");
  // Preserve native zero scores, including collection/import errors caused by
  // the student's code. Docker/provider failures throw in the shared harness.
  if (!tests.timedOut && tests.total < 1 && tests.exitCode === 0) throw new Error("Training verifier ran no tests");
  const success = tests.score === 1 && !tests.timedOut && tests.errors === 0 && tests.exitCode === 0;
  return { success, score: tests.score, soft_restriction: tests.score, hard_restriction: Number(success),
    passed: tests.passed, total: tests.total, errors: tests.errors, exit_code: tests.exitCode,
    timed_out: tests.timedOut, feedback: tests.output };
}

export function skillKdSession(raw: string, model: string): {
  raw: string; final_answer: string;
  usage: { model: string; input_tokens: number; output_tokens: number; cached_tokens: number; requests: number };
} {
  const records = raw.trim().split("\n").filter(Boolean).map((line) => JSON.parse(line));
  const usage = { model, input_tokens: 0, output_tokens: 0, cached_tokens: 0, requests: 0 };
  let final_answer = "";
  for (const record of records) {
    const message = record.type === "message" ? record.message : undefined;
    if (message?.role !== "assistant") continue;
    if (message.usage) {
      const u = message.usage;
      for (const value of [u.input, u.output, u.cacheRead, u.cacheWrite]) {
        if (typeof value !== "number" || !Number.isFinite(value) || value < 0) throw new Error("Missing/invalid Pi token usage");
      }
      // Pi input excludes cache reads/writes; OpenAI prompt_tokens includes them.
      usage.input_tokens += u.input + u.cacheRead + u.cacheWrite;
      usage.output_tokens += u.output;
      usage.cached_tokens += u.cacheRead;
      usage.requests += 1;
    }
    const content = message.content;
    if (Array.isArray(content)) {
      const text = content.filter((c) => c.type === "text").map((c) => c.text).join("\n");
      if (text) final_answer = text;
    }
  }
  if (!usage.requests) throw new Error("Raw Pi session has no assistant usage records");
  // Keep unabridged observations, reasoning and tool arguments. Do not use
  // dashboard/feedbackTrajectory events, which truncate long tool results.
  return { raw, final_answer, usage };
}

export interface SkillKdRolloutRequest {
  configPath: string;
  family: string;
  train: string;
  role: string;
  packageRoot: string;
  outputRoot: string;
  fingerprint: string;
}

export async function executeSkillKdRollout(request: SkillKdRolloutRequest): Promise<void> {
  const config = await loadSkillKdConfig(request.configPath);
  const family = config.experimentConfig.families.find((f) => f.name === request.family);
  if (!family || request.train !== family.train) throw new Error("Only the configured training anchor may be acquired");
  const provider = await skillKdProvider(config.projectRoot);
  const models = modelsForSkillKdRole(await createModels(config.experimentConfig, provider.baseUrl, provider.apiKey), request.role);
  const attemptRoot = path.join(request.outputRoot, "attempts", randomUUID());
  await mkdir(attemptRoot, { recursive: true });
  const before = skillPackageSha256(await skillPackageManifest(request.packageRoot));
  const environment = new TaskEnvironment(`skd-${randomUUID()}`, config.experimentConfig.reuseDockerImages,
    config.experimentConfig.dockerProxy);
  const stop = () => { void environment.stop().finally(() => process.exit(130)); };
  process.once("SIGTERM", stop);
  process.once("SIGINT", stop);
  try {
    const evaluated = await new RunOrchestrator(config.experimentConfig, models).evaluateTrainingPackage({
      runRoot: attemptRoot, environment, family, familyRoot: familyPath(config.experimentConfig, family),
      snapshotPackage: request.packageRoot, iteration: 1, artifactsRoot: path.join(attemptRoot, "artifacts"),
      prompt: `Solve ${family.name}/${family.train} in the fresh task environment. Read task.yaml using read. `
        + "Use the loaded Skill and task_shell to inspect and modify /app, and verify your solution. "
        + "Do not edit the Skill package. Complete the actual task, not a plan.",
    });
    await writeJson(path.join(attemptRoot, "result.json"), evaluated.result);
    if (!evaluated.rawSessionFile) throw new Error("Pi did not persist the full solver session");
    const raw = await readFile(evaluated.rawSessionFile, "utf8");
    const rollout = skillKdSession(raw, models.student.id);
    if (skillPackageSha256(await skillPackageManifest(request.packageRoot)) !== before) throw new Error("Input Skill mutated");
    const result = {
      ...rollout, evaluation: skillKdEvaluation(evaluated.result.tests),
      rawSessionFile: evaluated.rawSessionFile, rawSessionSha256: sha256(raw),
      packageSha256: before, fingerprint: request.fingerprint, attemptRoot,
    };
    await writeJson(path.join(request.outputRoot, "response.json"), result);
  } finally {
    await environment.stop();
    process.removeListener("SIGTERM", stop);
    process.removeListener("SIGINT", stop);
  }
}
