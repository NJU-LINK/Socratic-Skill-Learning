import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import YAML from "yaml";
import type { AssistantMessage } from "@earendil-works/pi-ai";
import type { ModelBundle } from "../agent/model.js";
import { createTextSession, lastAssistantMessage, promptWithInfrastructureRecovery } from "../agent/sessions.js";
import { familyPath } from "../experiment/config.js";
import { readJsonIfExists, writeJson } from "./trace2skill-io.js";
import type {
  Trace2SkillConfig,
  Trace2SkillRecord,
  Trace2SkillRecordItem,
  Trace2SkillTrajectoryArtifact,
} from "./trace2skill-types.js";

function assertString(value: unknown, label: string): asserts value is string {
  if (typeof value !== "string" || !value.trim()) throw new Error(`${label} must be a non-empty string`);
}

function textFromAssistant(message: AssistantMessage | undefined): string {
  if (!message) return "";
  return message.content
    .filter((item): item is Extract<typeof item, { type: "text" }> => item.type === "text")
    .map((item) => item.text)
    .join("\n")
    .trim();
}

function parseJsonObject(text: string): unknown {
  const withoutThinking = text.includes("</think>") ? text.slice(text.lastIndexOf("</think>") + 8) : text;
  const fenced = withoutThinking.match(/```(?:json)?\s*([\s\S]*?)```/i)?.[1];
  const candidate = fenced ?? withoutThinking.slice(withoutThinking.indexOf("{"), withoutThinking.lastIndexOf("}") + 1);
  if (!candidate.trim()) throw new Error("Trajectory analyst returned no JSON object");
  return JSON.parse(candidate);
}

export function parseTrace2SkillRecord(
  response: string,
  instanceId: string,
  sourceFile: string,
  outcome: "error" | "success",
): Trace2SkillRecord {
  const parsed = parseJsonObject(response) as { items?: unknown };
  if (!parsed || !Array.isArray(parsed.items) || parsed.items.length === 0) {
    throw new Error("Trajectory analyst returned no record items");
  }
  const allowed = outcome === "success"
    ? new Set(["success_memory"])
    : new Set(["failure_cause", "failure_memory"]);
  const items = parsed.items.map((raw, index): Trace2SkillRecordItem => {
    if (!raw || typeof raw !== "object") throw new Error(`Record item ${index + 1} is not an object`);
    const item = raw as Record<string, unknown>;
    if (typeof item.type !== "string" || !allowed.has(item.type)) {
      throw new Error(`Record item ${index + 1} has invalid type ${String(item.type)} for ${outcome}`);
    }
    for (const key of ["title", "description", "content"] as const) {
      assertString(item[key], `record item ${index + 1}.${key}`);
    }
    return {
      type: item.type as Trace2SkillRecordItem["type"],
      number: index + 1,
      title: item.title as string,
      description: item.description as string,
      content: item.content as string,
      ...(typeof item.relation_to_skill === "string" && item.relation_to_skill.trim()
        ? { relation_to_skill: item.relation_to_skill }
        : {}),
      ...(typeof item.skill_reflection === "string" && item.skill_reflection.trim()
        ? { skill_reflection: item.skill_reflection }
        : {}),
    };
  });
  return { instance_id: instanceId, source_file: sourceFile, items };
}

const TRACE_ANALYST_SYSTEM = `You are the trajectory-local analyst in an adapted Trace2Skill pipeline. Analyze one complete coding-agent execution from observable evidence only. Your output will be consumed by the official Trace2Skill MAP–MERGE–APPLY evolver.

For a fully successful run, extract one to three success_memory items: the lean, transferable decisions or procedures that causally supported success. Exclude dead ends and one-off values.

For a partial or failed run, extract concrete failure_cause items and at most three failure_memory items. Distinguish an observed causal mistake from an unsupported guess. Use the public family specification and anchor task to state transferable scope; do not invent held-out variants, hidden tests, reference solutions, or evaluator internals.

Return one JSON object and no prose:
{"items":[{"type":"success_memory|failure_cause|failure_memory","title":"...","description":"...","content":"...","relation_to_skill":"optional for failure_cause","skill_reflection":"optional for failure_memory"}]}`;

export function traceAnalystPrompt(options: {
  family: string;
  replicate: number;
  traceIndex: number;
  spec: string;
  task: string;
  artifact: Trace2SkillTrajectoryArtifact;
  rawSession: string;
}): string {
  const outcome = options.artifact.tests.score === 1 ? "success" : "error";
  return `Analyze this ${outcome} trajectory for ${options.family}/v01.

Replicate: ${options.replicate}
Pool trajectory: ${options.traceIndex}

<public_family_spec>\n${options.spec}\n</public_family_spec>

<public_anchor_task>\n${options.task}\n</public_anchor_task>

<training_verifier_result>\n${JSON.stringify(options.artifact.tests, null, 2)}\n</training_verifier_result>

<agent_trajectory_jsonl>\n${options.rawSession}\n</agent_trajectory_jsonl>`;
}

export async function analyzeTrajectory(options: {
  config: Trace2SkillConfig;
  models: ModelBundle;
  family: import("../experiment/types.js").FamilyConfig;
  replicate: number;
  traceIndex: number;
  runRoot: string;
  artifact: Trace2SkillTrajectoryArtifact;
  rawSession: string;
}): Promise<{ source: "error" | "success"; record: Trace2SkillRecord }> {
  const analysisRoot = path.join(options.runRoot, "analysis", `trajectory-${options.traceIndex}`);
  const recordPath = path.join(analysisRoot, "record.json");
  const existing = await readJsonIfExists<{ source: "error" | "success"; record: Trace2SkillRecord }>(recordPath);
  if (existing) return existing;
  const familyRoot = familyPath(options.config.experimentConfig, options.family);
  const rawSpec = YAML.parse(await readFile(path.join(familyRoot, "spec.yaml"), "utf8")) as Record<string, unknown>;
  delete rawSpec.seed_task_dir;
  const spec = YAML.stringify(rawSpec);
  const task = await readFile(path.join(familyRoot, options.family.train, "task.yaml"), "utf8");
  const session = await createTextSession({
    label: `trace2skill-analyst-${options.traceIndex}`,
    cwd: analysisRoot,
    sessionDir: path.join(analysisRoot, "session"),
    systemPrompt: TRACE_ANALYST_SYSTEM,
    model: options.models.teacher,
    runtime: options.models.runtime,
    config: options.config.experimentConfig,
  });
  try {
    const completion = await promptWithInfrastructureRecovery(
      session.session,
      traceAnalystPrompt({
        family: options.family.name,
        replicate: options.replicate,
        traceIndex: options.traceIndex,
        spec,
        task,
        artifact: options.artifact,
        rawSession: options.rawSession,
      }),
      `${options.family.name} Trace2Skill trajectory analysis`,
    );
    const rawResponse = textFromAssistant(lastAssistantMessage(session.session));
    await writeFile(path.join(analysisRoot, "response.txt"), `${rawResponse}\n`, "utf8");
    const source = options.artifact.tests.score === 1 ? "success" : "error";
    const record = parseTrace2SkillRecord(
      rawResponse,
      `${options.family.name}-v01-r${options.replicate}-t${options.traceIndex}`,
      path.join("train-solvers", `iteration-${options.traceIndex}`, "trajectory.json"),
      source,
    );
    await writeJson(recordPath, { source, record, analystAttempts: completion.attempts });
    return { source, record };
  } finally {
    await session.dispose();
  }
}
