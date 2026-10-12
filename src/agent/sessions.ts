import { access, lstat, mkdir, readFile, readdir, realpath } from "node:fs/promises";
import path from "node:path";
import { Type } from "typebox";
import {
  createAgentSession,
  DefaultResourceLoader,
  defineTool,
  SessionManager,
  SettingsManager,
  type AgentSession,
  type InlineExtension,
  type ModelRuntime,
} from "@earendil-works/pi-coding-agent";
import type { AssistantMessage, Model, StopReason } from "@earendil-works/pi-ai";
import type { TaskEnvironment } from "../runtime/docker.js";
import { TraceRecorder } from "./trace.js";
import {
  AUTHOR_TOOL_NAMES,
  EDUCATION_INTENTS,
  LEARNING_FRONTIER_STATES,
  type AdaptiveEducationDecision,
  type EducationIntent,
  type LearningIssueLesson,
  type LearningFrontierState,
  type PilotConfig,
  type WakeCondition,
} from "../experiment/types.js";

export interface ManagedSession {
  session: AgentSession;
  trace: TraceRecorder;
  reloadResources(): Promise<void>;
  loadedSkills(): LoadedSkill[];
  skillDiagnostics(): Array<{ type: string; message: string }>;
  takeWorkspaceBoundaryWarnings(): WorkspaceBoundaryViolation[];
  dispose(): Promise<void>;
}

export interface LoadedSkill {
  name: string;
  description: string;
  filePath: string;
  baseDir: string;
}

export interface PromptCompletion {
  attempts: number;
  recovered: boolean;
  stopReason: StopReason;
  errors: string[];
}

export interface WorkspaceBoundaryViolation {
  toolName: string;
  requestedPath: string;
  reason: string;
}

const EDUCATOR_READ_TOOLS = ["skill_list", "skill_read", "skill_search"] as const;
const WORKSPACE_PATH_TOOLS = new Set(["read", "write", "edit", "grep", "find", "ls"]);

function uniqueWakeConditions(conditions: WakeCondition[]): WakeCondition[] {
  const seen = new Set<string>();
  return conditions.filter((condition) => {
    const key = JSON.stringify(condition);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function structuredToolArgument(value: unknown, label: string): unknown {
  if (typeof value !== "string") return value;
  try {
    return JSON.parse(value);
  } catch {
    throw new Error(`${label} must be structured JSON, not an arbitrary string`);
  }
}

function validWakeCondition(value: unknown): value is WakeCondition {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const item = value as Record<string, unknown>;
  if (["tool_error", "command_nonzero_exit", "command_timeout", "skill_package_changed"].includes(String(item.event))) {
    return Object.keys(item).length === 1;
  }
  if (item.event === "repeated_failure") {
    return (item.count === 2 || item.count === 3) && Object.keys(item).length === 2;
  }
  if (item.event === "tool_call") {
    return typeof item.tool === "string"
      && (AUTHOR_TOOL_NAMES as readonly string[]).includes(item.tool)
      && Object.keys(item).length === 2;
  }
  return false;
}

export function normalizeLearningIssueLessonParams(value: unknown): LearningIssueLesson {
  const parsed = structuredToolArgument(value, "learningIssue");
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("learningIssue must be an object");
  }
  const item = parsed as Record<string, unknown>;
  if (typeof item.focus !== "string" || !item.focus.trim()) {
    throw new Error("learningIssue.focus must be a non-empty string");
  }
  if (typeof item.acceptanceCriterion !== "string" || !item.acceptanceCriterion.trim()) {
    throw new Error("learningIssue.acceptanceCriterion must be a non-empty string");
  }
  return {
    focus: item.focus.trim(),
    acceptanceCriterion: item.acceptanceCriterion.trim(),
  };
}

/** Normalize the JSON-stringified structured arguments emitted by some
 * OpenAI-compatible tool-call adapters while retaining the canonical nested
 * decision in the experiment audit. */
export function normalizeAdaptiveEducationDecisionParams(
  params: unknown,
  allowWakeConditions = true,
): AdaptiveEducationDecision {
  if (!params || typeof params !== "object" || Array.isArray(params)) {
    throw new Error("education_decision arguments must be an object");
  }
  const raw = params as Record<string, unknown>;
  if (raw.action !== "teach" && raw.action !== "silence") {
    throw new Error("education_decision action must be teach or silence");
  }
  const scheduleValue = structuredToolArgument(raw.schedule, "schedule");
  if (!scheduleValue || typeof scheduleValue !== "object" || Array.isArray(scheduleValue)) {
    throw new Error("education_decision schedule must be an object");
  }
  const scheduleRaw = scheduleValue as Record<string, unknown>;
  const allowedScheduleFields = allowWakeConditions
    ? new Set(["maxHorizon", "wakeOn"])
    : new Set(["maxHorizon"]);
  if (Object.keys(scheduleRaw).some((key) => !allowedScheduleFields.has(key))) {
    throw new Error("education_decision schedule contains an unsupported field");
  }
  if (scheduleRaw.maxHorizon !== 5 && scheduleRaw.maxHorizon !== 10 && scheduleRaw.maxHorizon !== 20) {
    throw new Error("education_decision maxHorizon must be 5, 10, or 20");
  }
  const wakeOn = allowWakeConditions
    ? structuredToolArgument(scheduleRaw.wakeOn, "schedule.wakeOn")
    : [];
  if (
    !Array.isArray(wakeOn)
    || wakeOn.length > 6
    || !wakeOn.every(validWakeCondition)
  ) throw new Error("education_decision wakeOn contains an invalid condition");
  const schedule: AdaptiveEducationDecision["schedule"] = {
    maxHorizon: scheduleRaw.maxHorizon as 5 | 10 | 20,
    wakeOn: uniqueWakeConditions(wakeOn),
  };
  if (raw.action === "silence") {
    return { action: "silence", schedule, intents: [], message: "" };
  }
  const intentsValue = structuredToolArgument(raw.intents, "intents");
  if (
    !Array.isArray(intentsValue)
    || intentsValue.length === 0
    || !intentsValue.every((intent) => typeof intent === "string" && (EDUCATION_INTENTS as readonly string[]).includes(intent))
  ) {
    throw new Error("education_decision teach intents are invalid");
  }
  if (typeof raw.message !== "string" || raw.message.length === 0) {
    throw new Error("education_decision teach message must be non-empty");
  }
  return {
    action: "teach",
    schedule,
    intents: [...new Set(intentsValue)] as EducationIntent[],
    message: raw.message,
  };
}

export function learningFrontierObservationWindow(
  state: LearningFrontierState,
): 5 | 10 | 20 {
  if (state === "verification_pending") return 5;
  if (state === "active_learning") return 10;
  return 20;
}

/** Parse a pedagogical-state decision and deterministically derive timing.
 * The Teacher judges the learning state; it does not choose a raw number. */
export function normalizeLearningFrontierDecisionParams(
  params: unknown,
): AdaptiveEducationDecision {
  if (!params || typeof params !== "object" || Array.isArray(params)) {
    throw new Error("education_decision arguments must be an object");
  }
  const raw = params as Record<string, unknown>;
  if (raw.action !== "teach" && raw.action !== "silence") {
    throw new Error("education_decision action must be teach or silence");
  }
  const frontierValue = structuredToolArgument(raw.frontier, "frontier");
  if (!frontierValue || typeof frontierValue !== "object" || Array.isArray(frontierValue)) {
    throw new Error("education_decision frontier must be an object");
  }
  const frontierRaw = frontierValue as Record<string, unknown>;
  if (
    Object.keys(frontierRaw).some((key) => !["state", "focus", "evidence"].includes(key))
    || typeof frontierRaw.state !== "string"
    || !(LEARNING_FRONTIER_STATES as readonly string[]).includes(frontierRaw.state)
    || typeof frontierRaw.focus !== "string"
    || frontierRaw.focus.trim().length === 0
    || typeof frontierRaw.evidence !== "string"
    || frontierRaw.evidence.trim().length === 0
  ) {
    throw new Error("education_decision frontier is invalid");
  }
  const state = frontierRaw.state as LearningFrontierState;
  const learningFrontier = {
    state,
    focus: frontierRaw.focus.trim(),
    evidence: frontierRaw.evidence.trim(),
  };
  const schedule: AdaptiveEducationDecision["schedule"] = {
    maxHorizon: learningFrontierObservationWindow(state),
    wakeOn: [],
  };
  if (raw.action === "silence") {
    return { action: "silence", schedule, intents: [], message: "", learningFrontier };
  }
  const intentsValue = structuredToolArgument(raw.intents, "intents");
  if (
    !Array.isArray(intentsValue)
    || intentsValue.length === 0
    || !intentsValue.every((intent) =>
      typeof intent === "string"
      && (EDUCATION_INTENTS as readonly string[]).includes(intent)
    )
  ) {
    throw new Error("education_decision teach intents are invalid");
  }
  if (typeof raw.message !== "string" || raw.message.length === 0) {
    throw new Error("education_decision teach message must be non-empty");
  }
  return {
    action: "teach",
    schedule,
    intents: [...new Set(intentsValue)] as EducationIntent[],
    message: raw.message,
    learningFrontier,
  };
}

function isInside(root: string, candidate: string): boolean {
  return candidate === root || candidate.startsWith(`${root}${path.sep}`);
}

/**
 * Pi's general-purpose file tools accept absolute paths. Experiment sessions
 * are narrower: all host file access must remain inside the prepared workspace.
 */
export async function assertWorkspacePath(root: string, requestedPath: string): Promise<string> {
  if (!requestedPath || requestedPath.includes("\0")) {
    throw new Error("path must be a non-empty filesystem path");
  }
  if (requestedPath.startsWith("~") || requestedPath.startsWith("@")) {
    throw new Error("home and @-prefixed expansion are outside the experiment workspace");
  }
  const canonicalRoot = await realpath(root);
  const candidate = path.resolve(canonicalRoot, requestedPath);
  if (!isInside(canonicalRoot, candidate)) {
    throw new Error(`path escapes the experiment workspace: ${requestedPath}`);
  }

  // For a not-yet-created write target, resolve the nearest existing ancestor.
  // This rejects writes through a symlink that points outside the workspace.
  let ancestor = candidate;
  while (!(await access(ancestor).then(() => true).catch(() => false))) {
    const parent = path.dirname(ancestor);
    if (parent === ancestor) break;
    ancestor = parent;
  }
  const canonicalAncestor = await realpath(ancestor);
  if (!isInside(canonicalRoot, canonicalAncestor)) {
    throw new Error(`path resolves through a symlink outside the experiment workspace: ${requestedPath}`);
  }
  return candidate;
}

export async function resolvePackagePath(packageRoot: string, relativePath: string): Promise<string> {
  if (path.isAbsolute(relativePath)) throw new Error("Skill package paths must be relative");
  const root = await realpath(packageRoot);
  const candidate = path.resolve(root, relativePath || ".");
  if (candidate !== root && !candidate.startsWith(`${root}${path.sep}`)) {
    throw new Error(`Path escapes the read-only Skill package: ${relativePath}`);
  }
  const resolved = await realpath(candidate);
  if (resolved !== root && !resolved.startsWith(`${root}${path.sep}`)) {
    throw new Error(`Symlink escapes the read-only Skill package: ${relativePath}`);
  }
  return resolved;
}

export async function packageFiles(packageRoot: string): Promise<string[]> {
  const root = await realpath(packageRoot);
  const files: string[] = [];
  const walk = async (directory: string): Promise<void> => {
    for (const entry of await readdir(directory, { withFileTypes: true })) {
      const full = path.join(directory, entry.name);
      const relative = path.relative(root, full).split(path.sep).join("/");
      if (entry.isSymbolicLink()) {
        files.push(`${relative} [symlink omitted]`);
      } else if (entry.isDirectory()) {
        await walk(full);
      } else if (entry.isFile()) {
        files.push(relative);
      }
    }
  };
  await walk(root);
  return files.sort();
}

function readOnlySkillPackageTools(
  packageRoot: string,
  onViolation?: (violation: WorkspaceBoundaryViolation) => void,
) {
  const list = defineTool({
    name: "skill_list",
    label: "List Skill package",
    description: "List every file in the live Student-authored Skill package. This tool is read-only.",
    parameters: Type.Object({}),
    execute: async () => {
      const files = await packageFiles(packageRoot);
      const details = await Promise.all(files.map(async (relative) => {
        if (relative.endsWith(" [symlink omitted]")) return relative;
        const file = await resolvePackagePath(packageRoot, relative);
        return `${relative}\t${(await lstat(file)).size} bytes`;
      }));
      return { content: [{ type: "text", text: details.join("\n") || "[empty Skill package]" }], details: {} };
    },
  });
  const read = defineTool({
    name: "skill_read",
    label: "Read Skill resource",
    description:
      "Read one package-relative file from the live Student-authored Skill package. Absolute paths and path escapes are rejected.",
    parameters: Type.Object({
      path: Type.String({ minLength: 1, description: "Package-relative path such as SKILL.md or references/api.md" }),
    }),
    execute: async (_toolCallId, params) => {
      let file: string;
      try {
        file = await resolvePackagePath(packageRoot, params.path);
      } catch (error) {
        const reason = error instanceof Error ? error.message : String(error);
        onViolation?.({ toolName: "skill_read", requestedPath: params.path, reason });
        throw error;
      }
      const content = await readFile(file);
      if (content.includes(0)) throw new Error(`Binary Skill resource cannot be rendered as text: ${params.path}`);
      const text = content.toString("utf8");
      const rendered = text.length > 200_000 ? `${text.slice(0, 200_000)}\n…[truncated]` : text;
      return { content: [{ type: "text", text: rendered }], details: { path: params.path, bytes: content.byteLength } };
    },
  });
  const search = defineTool({
    name: "skill_search",
    label: "Search Skill package",
    description: "Search all text resources in the live Skill package for a literal string. This tool is read-only.",
    parameters: Type.Object({
      query: Type.String({ minLength: 1 }),
    }),
    execute: async (_toolCallId, params) => {
      const query = params.query.toLowerCase();
      const matches: string[] = [];
      for (const relative of await packageFiles(packageRoot)) {
        if (relative.endsWith(" [symlink omitted]")) continue;
        const file = await resolvePackagePath(packageRoot, relative);
        const content = await readFile(file);
        if (content.includes(0)) continue;
        for (const [index, line] of content.toString("utf8").split("\n").entries()) {
          if (line.toLowerCase().includes(query)) matches.push(`${relative}:${index + 1}: ${line}`);
          if (matches.length >= 200) break;
        }
        if (matches.length >= 200) break;
      }
      return {
        content: [{ type: "text", text: matches.join("\n") || `[no matches for ${params.query}]` }],
        details: { matches: matches.length },
      };
    },
  });
  return [list, read, search];
}

export function lastAssistantMessage(session: AgentSession): AssistantMessage | undefined {
  return session.state.messages
    .slice()
    .reverse()
    .find((message): message is AssistantMessage => message.role === "assistant");
}

/**
 * Run one logical phase without changing session identity. pi already retries an
 * individual provider request; this adds a workflow-level continuation when all
 * provider retries end in an interrupted assistant response. Existing task
 * artifacts and conversation state are preserved.
 */
export async function promptWithInfrastructureRecovery(
  session: AgentSession,
  prompt: string,
  phase: string,
  maxAttempts = 3,
): Promise<PromptCompletion> {
  const errors: string[] = [];
  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    const message = attempt === 1
      ? prompt
      : `The previous model response was interrupted by the provider/runtime during ${phase}. Continue in this same session from the existing environment and artifacts. Do not restart work that already succeeded. Inspect the required output artifact, finish any incomplete action, verify the task requirements, and then end normally.`;
    await session.prompt(message);
    const assistant = lastAssistantMessage(session);
    if (assistant?.stopReason === "stop") {
      return {
        attempts: attempt,
        recovered: attempt > 1,
        stopReason: assistant.stopReason,
        errors,
      };
    }
    const stopReason = assistant?.stopReason ?? "error";
    errors.push(assistant?.errorMessage ?? `assistant ended with stopReason=${stopReason}`);
  }
  const assistant = lastAssistantMessage(session);
  const stopReason = assistant?.stopReason ?? "error";
  throw new Error(
    `Infrastructure-invalid ${phase}: assistant did not complete after ${maxAttempts} workflow attempts `
    + `(last stopReason=${stopReason}; ${errors.join(" | ")})`,
  );
}

interface CreateSessionOptions {
  label: string;
  cwd: string;
  sessionDir: string;
  systemPrompt: string;
  model: Model<any>;
  runtime: ModelRuntime;
  config: PilotConfig;
  tools: string[];
  skillPaths?: string[];
  customTools?: ReturnType<typeof defineTool>[];
  boundaryViolations?: WorkspaceBoundaryViolation[];
  checkpointHooks?: {
    onToolStart(event: { toolCallId: string; toolName: string; args: unknown }): void | Promise<void>;
    onToolEnd(event: { toolCallId: string; toolName: string; result: unknown; isError: boolean }): void | Promise<void>;
    onTurnEnd(event: { message: unknown }): void | Promise<void>;
  };
}

export async function createExperimentResourceLoader(options: {
  cwd: string;
  agentDir: string;
  settingsManager: SettingsManager;
  systemPrompt: string;
  skillPaths?: string[];
  checkpointHooks?: CreateSessionOptions["checkpointHooks"];
  onWorkspaceBoundaryViolation?: (violation: WorkspaceBoundaryViolation) => void;
}): Promise<DefaultResourceLoader> {
  const workspaceRoot = await realpath(options.cwd);
  const extensionFactories: InlineExtension[] = [
    {
      name: "experiment-workspace-boundary",
      hidden: true,
      factory: (pi) => {
        pi.on("tool_call", async (event) => {
          if (!WORKSPACE_PATH_TOOLS.has(event.toolName)) return;
          const input = event.input as { path?: unknown };
          const requestedPath = input.path === undefined ? "." : String(input.path);
          try {
            await assertWorkspacePath(workspaceRoot, requestedPath);
          } catch (error) {
            const reason = error instanceof Error ? error.message : String(error);
            options.onWorkspaceBoundaryViolation?.({
              toolName: event.toolName,
              requestedPath,
              reason,
            });
            return { block: true, reason: `WORKSPACE_BOUNDARY: ${reason}` };
          }
        });
      },
    },
  ];
  if (options.checkpointHooks) {
    extensionFactories.push({
      name: "education-checkpoint-gate",
      hidden: true,
      factory: (pi) => {
        pi.on("tool_execution_start", async (event) => {
          await options.checkpointHooks?.onToolStart({
            toolCallId: event.toolCallId,
            toolName: event.toolName,
            args: event.args,
          });
        });
        pi.on("tool_execution_end", async (event) => {
          await options.checkpointHooks?.onToolEnd({
            toolCallId: event.toolCallId,
            toolName: event.toolName,
            result: event.result,
            isError: event.isError,
          });
        });
        pi.on("turn_end", async (event) => {
          await options.checkpointHooks?.onTurnEnd({ message: event.message });
        });
      },
    });
  }
  const loader = new DefaultResourceLoader({
    cwd: options.cwd,
    agentDir: options.agentDir,
    settingsManager: options.settingsManager,
    noExtensions: true,
    // Disable ambient/global discovery while still loading the experiment's
    // explicitly supplied Agent Skill package through additionalSkillPaths.
    noSkills: true,
    additionalSkillPaths: options.skillPaths ?? [],
    noPromptTemplates: true,
    noThemes: true,
    noContextFiles: true,
    systemPrompt: options.systemPrompt,
    extensionFactories,
  });
  await loader.reload();
  return loader;
}

async function createManagedSession(options: CreateSessionOptions): Promise<ManagedSession> {
  const agentDir = path.join(options.sessionDir, ".pi-agent");
  await mkdir(options.cwd, { recursive: true });
  await mkdir(options.sessionDir, { recursive: true });
  await mkdir(agentDir, { recursive: true });

  const settingsManager = SettingsManager.inMemory({
    compaction: { enabled: true },
    retry: {
      enabled: true,
      maxRetries: 3,
      baseDelayMs: 1_000,
      provider: { maxRetries: 2, timeoutMs: 10 * 60_000, maxRetryDelayMs: 60_000 },
    },
    steeringMode: "one-at-a-time",
    followUpMode: "one-at-a-time",
    enableAnalytics: false,
    enableInstallTelemetry: false,
  });
  const workspaceViolations = options.boundaryViolations ?? [];
  const loader = await createExperimentResourceLoader({
    cwd: options.cwd,
    agentDir,
    settingsManager,
    systemPrompt: options.systemPrompt,
    ...(options.skillPaths ? { skillPaths: options.skillPaths } : {}),
    ...(options.checkpointHooks ? { checkpointHooks: options.checkpointHooks } : {}),
    onWorkspaceBoundaryViolation: (violation) => workspaceViolations.push(violation),
  });

  const result = await createAgentSession({
    cwd: options.cwd,
    agentDir,
    model: options.model,
    thinkingLevel: options.config.provider.thinkingEnabled
      ? options.config.provider.reasoningEffort ?? "high"
      : "off",
    modelRuntime: options.runtime,
    tools: options.tools,
    ...(options.customTools ? { customTools: options.customTools } : {}),
    resourceLoader: loader,
    sessionManager: SessionManager.create(options.cwd, options.sessionDir),
    settingsManager,
  });
  const trace = new TraceRecorder(options.label, path.join(options.sessionDir, "events.jsonl"));
  const unsubscribe = await trace.attach(result.session);

  return {
    session: result.session,
    trace,
    async reloadResources() {
      await result.session.reload();
    },
    loadedSkills() {
      return result.session.resourceLoader.getSkills().skills.map((skill) => ({
        name: skill.name,
        description: skill.description,
        filePath: skill.filePath,
        baseDir: skill.baseDir,
      }));
    },
    skillDiagnostics() {
      return result.session.resourceLoader.getSkills().diagnostics.map((diagnostic) => ({
        type: diagnostic.type,
        message: diagnostic.message,
      }));
    },
    takeWorkspaceBoundaryWarnings() {
      return workspaceViolations.splice(0).map((violation) => ({ ...violation }));
    },
    async dispose() {
      unsubscribe();
      await trace.flush();
      result.session.dispose();
    },
  };
}

export function requireLoadedSkill(session: ManagedSession, expectedName: string): LoadedSkill {
  const skill = session.loadedSkills().find((candidate) => candidate.name === expectedName);
  if (skill) return skill;
  const loaded = session.loadedSkills().map((candidate) => candidate.name).join(", ") || "none";
  const diagnostics = session.skillDiagnostics().map((item) => `${item.type}: ${item.message}`).join(" | ");
  throw new Error(
    `Agent Skill ${expectedName} was not loaded through Pi (loaded=${loaded}; diagnostics=${diagnostics || "none"})`,
  );
}

export function reportWorkspaceBoundaryWarnings(
  session: ManagedSession,
  phase: string,
): WorkspaceBoundaryViolation[] {
  const violations = session.takeWorkspaceBoundaryWarnings();
  if (violations.length === 0) return violations;
  console.warn(
    `Blocked host-path attempt during ${phase}; the Agent can continue with the correct task tool:\n`
    + violations.map((violation) =>
      `- ${violation.toolName} ${JSON.stringify(violation.requestedPath)}: ${violation.reason}`
    ).join("\n"),
  );
  return violations;
}

function taskShellTool(environment: TaskEnvironment) {
  return defineTool({
    name: "task_shell",
    label: "Task shell",
    description:
      "Run a shell command inside the current isolated task container. Its working directory is /app. Use this instead of host bash for all task exploration and solution work.",
    parameters: Type.Object({
      command: Type.String({ description: "Bash command to run inside the task container" }),
      timeoutSeconds: Type.Optional(Type.Number({ minimum: 1, description: "Optional command timeout" })),
    }),
    execute: async (_toolCallId, params) => {
      const result = await environment.shell(params.command, params.timeoutSeconds);
      const output = [result.stdout, result.stderr].filter(Boolean).join("\n");
      const text = output.length > 40_000 ? `${output.slice(0, 40_000)}\n…[truncated]` : output;
      return {
        content: [{ type: "text", text: `${text}\n[exit=${result.exitCode}${result.timedOut ? ", timed out" : ""}]` }],
        details: { exitCode: result.exitCode, timedOut: result.timedOut },
      };
    },
  });
}

function skillRevisionCommitTool(structuredLearningIssue = false) {
  const parameters = structuredLearningIssue
    ? Type.Object({
        summary: Type.String({
          minLength: 1,
          description: "Concise reusable family-level knowledge changed by this complete package revision",
        }),
        evidence: Type.String({
          minLength: 1,
          description: "Visible task, experiment, lesson, or reasoning evidence supporting the revision",
        }),
        addressesIssueId: Type.Optional(Type.String({
          minLength: 1,
          description: "Exact active learning-issue ID when this revision addresses a Teacher lesson; omit for an independent learning delta",
        })),
        issueResolution: Type.Optional(Type.Union([
          Type.Literal("verified"),
          Type.Literal("bounded"),
          Type.Literal("rejected"),
        ], {
          description: "How the cited issue is closed: verified by a post-revision check, bounded by an explicit mechanism/scope argument when local execution is unavailable, or rejected from contradictory evidence. Omit while the issue remains unresolved.",
        })),
      }, { additionalProperties: false })
    : Type.Object({}, { additionalProperties: false });
  return defineTool({
    name: "commit_skill_revision",
    label: "Commit Skill revision",
    description:
      structuredLearningIssue
        ? "Declare one coherent Student-authored knowledge revision, its visible evidence, and the active learning issue it addresses when applicable. An addressed issue may be closed as verified, bounded, or rejected only when that disposition is supported by the changed package and evidence; otherwise omit issueResolution and keep it open."
        : "Declare that the current complete Agent Skill directory is one coherent Student-authored knowledge revision. Use this after making a meaningful package revision, not after every file write. The declaration may open an evidence-grounded Teacher checkpoint; it does not transfer authorship or modify the package.",
    parameters,
    execute: async (_toolCallId, params) => ({
      content: [{
        type: "text",
        text: structuredLearningIssue
          ? `SKILL_REVISION_COMMITTED. summary=${String((params as { summary?: unknown }).summary ?? "")}; addressedIssueId=${String((params as { addressesIssueId?: unknown }).addressesIssueId ?? "independent")}; issueResolution=${String((params as { issueResolution?: unknown }).issueResolution ?? "open")}.`
          : "SKILL_REVISION_COMMITTED. The current complete Skill package has been declared as one coherent revision.",
      }],
      details: structuredLearningIssue ? params : {},
    }),
  });
}

export async function createWorkspaceSession(options: Omit<CreateSessionOptions, "tools" | "customTools"> & {
  environment: TaskEnvironment;
  enableSkillRevisionCommit?: boolean;
  structuredLearningIssueCommit?: boolean;
}): Promise<ManagedSession> {
  const shell = taskShellTool(options.environment);
  const commit = options.enableSkillRevisionCommit
    ? skillRevisionCommitTool(options.structuredLearningIssueCommit === true)
    : undefined;
  return await createManagedSession({
    ...options,
    tools: [
      "read",
      "write",
      "edit",
      "grep",
      "find",
      "ls",
      "task_shell",
      ...(commit ? ["commit_skill_revision"] : []),
    ],
    customTools: [shell, ...(commit ? [commit] : [])],
  });
}

export async function createEvaluatorSession(options: Omit<CreateSessionOptions, "tools" | "customTools"> & {
  environment: TaskEnvironment;
}): Promise<ManagedSession> {
  const shell = taskShellTool(options.environment);
  return await createManagedSession({
    ...options,
    tools: ["read", "grep", "find", "ls", "task_shell"],
    customTools: [shell],
  });
}

/**
 * Create an isolated, tool-free session for transformations over supplied
 * text. Baseline trajectory analysts use this rather than inheriting ambient
 * filesystem, shell, or Agent Skill access.
 */
export async function createTextSession(
  options: Omit<CreateSessionOptions, "tools" | "customTools">,
): Promise<ManagedSession> {
  return await createManagedSession({
    ...options,
    tools: [],
  });
}

export async function createEducatorSession(
  options: Omit<CreateSessionOptions, "tools" | "customTools"> & {
    skillPackageRoot: string;
    adaptiveDecisionPolicy?: "horizon-and-events" | "horizon-only" | "learning-frontier";
    structuredLearningIssueLesson?: boolean;
  },
  onIntervention: (
    message: string,
    intents: EducationIntent[],
    learningIssue?: LearningIssueLesson,
  ) => boolean,
  onAdaptiveDecision?: (decision: AdaptiveEducationDecision) => boolean,
): Promise<ManagedSession> {
  const {
    skillPackageRoot,
    adaptiveDecisionPolicy = "horizon-and-events",
    structuredLearningIssueLesson = false,
    ...sessionOptions
  } = options;
  const boundaryViolations: WorkspaceBoundaryViolation[] = [];
  const educateStudent = defineTool({
    name: "educate_student",
    label: "Educate Student",
    description:
      "Deliver one coherent lesson in the Student's live conversation. Select every applicable learning intent. The lesson may directly teach knowledge, reasoning, examples, implementation mechanisms, or a worked visible-case solution. If no material learning delta exists, remain silent.",
    parameters: Type.Object({
      intents: Type.Array(
        Type.Union(EDUCATION_INTENTS.map((intent) => Type.Literal(intent))),
        {
          minItems: 1,
          uniqueItems: true,
          description: "One or more intended Student-state changes; these are learning intents, not delivery styles",
        },
      ),
      message: Type.String({ minLength: 1, description: "The coherent lesson delivered verbatim to Student" }),
      ...(structuredLearningIssueLesson
        ? {
            learningIssue: Type.Union([
              Type.Object({
                focus: Type.String({
                  minLength: 1,
                  description: "The single unresolved family-level knowledge issue targeted by this lesson",
                }),
                acceptanceCriterion: Type.String({
                  minLength: 1,
                  description: "Observable evidence that would justify closing this issue after the Student revises the Skill",
                }),
              }, { additionalProperties: false }),
              Type.String({ description: "JSON-encoded learningIssue accepted for provider compatibility" }),
            ]),
          }
        : {}),
    }),
    execute: async (_toolCallId, params) => {
      const rawIssue = (params as { learningIssue?: unknown }).learningIssue;
      const issue = rawIssue === undefined
        ? undefined
        : normalizeLearningIssueLessonParams(rawIssue);
      const accepted = onIntervention(
        params.message,
        params.intents as EducationIntent[],
        issue,
      );
      return {
        content: [{
          type: "text",
          text: accepted
            ? "CHECKPOINT_COMPLETE. Lesson delivered; no Student response has occurred yet. End your turn now."
            : "DUPLICATE_IGNORED. This checkpoint already has a lesson. End your turn now.",
        }],
        details: {},
        // Pi's native terminate flag ends this agent turn after the tool result
        // without manufacturing an aborted assistant response.
        terminate: true,
      };
    },
  });
  const wakeCondition = Type.Union([
    Type.Object({ event: Type.Literal("tool_error") }, { additionalProperties: false }),
    Type.Object({ event: Type.Literal("command_nonzero_exit") }, { additionalProperties: false }),
    Type.Object({ event: Type.Literal("command_timeout") }, { additionalProperties: false }),
    Type.Object({
      event: Type.Literal("repeated_failure"),
      count: Type.Union([Type.Literal(2), Type.Literal(3)]),
    }, { additionalProperties: false }),
    Type.Object({ event: Type.Literal("skill_package_changed") }, { additionalProperties: false }),
    Type.Object({
      event: Type.Literal("tool_call"),
      tool: Type.Union(AUTHOR_TOOL_NAMES.map((tool) => Type.Literal(tool))),
    }, { additionalProperties: false }),
  ]);
  const adaptiveScheduleWithEvents = Type.Object({
    maxHorizon: Type.Union([Type.Literal(5), Type.Literal(10), Type.Literal(20)]),
    wakeOn: Type.Array(wakeCondition, {
      maxItems: 6,
      description: "One-shot observable conditions that may wake the next checkpoint before maxHorizon",
    }),
  }, { additionalProperties: false });
  const adaptiveHorizonOnlySchedule = Type.Object({
    maxHorizon: Type.Union([Type.Literal(5), Type.Literal(10), Type.Literal(20)]),
  }, { additionalProperties: false });
  const adaptiveSchedule = adaptiveDecisionPolicy === "horizon-only"
    ? adaptiveHorizonOnlySchedule
    : adaptiveScheduleWithEvents;
  const intentParameters = Type.Optional(Type.Union([
    Type.Array(
      Type.Union(EDUCATION_INTENTS.map((intent) => Type.Literal(intent))),
      {
        minItems: 1,
        uniqueItems: true,
        description: "Every intended Student-state change targeted by this lesson",
      },
    ),
    Type.String({ description: "JSON-encoded intent array accepted for provider compatibility" }),
  ]));
  const learningFrontier = Type.Union([
    Type.Object({
      state: Type.Union(LEARNING_FRONTIER_STATES.map((state) => Type.Literal(state))),
      focus: Type.String({ minLength: 1, description: "The most material family-level learning frontier" }),
      evidence: Type.String({ minLength: 1, description: "Observed evidence supporting this learning-state judgment" }),
    }, { additionalProperties: false }),
    Type.String({ description: "JSON-encoded frontier object accepted for provider compatibility" }),
  ]);
  const decisionParameters = adaptiveDecisionPolicy === "learning-frontier"
    ? Type.Object({
        action: Type.Union([Type.Literal("teach"), Type.Literal("silence")]),
        frontier: learningFrontier,
        intents: intentParameters,
        message: Type.Optional(Type.String({ minLength: 1, description: "The opening lesson delivered verbatim" })),
      }, { additionalProperties: false })
    : Type.Object({
        action: Type.Union([Type.Literal("teach"), Type.Literal("silence")]),
        schedule: Type.Union([
          adaptiveSchedule,
          Type.String({ description: "JSON-encoded schedule accepted for provider compatibility" }),
        ]),
        intents: intentParameters,
        message: Type.Optional(Type.String({ minLength: 1, description: "The opening lesson delivered verbatim" })),
      }, { additionalProperties: false });
  const educationDecision = onAdaptiveDecision
    ? defineTool({
        name: "education_decision",
        label: "Education decision",
        description:
          adaptiveDecisionPolicy === "learning-frontier"
            ? "Identify the Student's current family-level learning frontier and choose teach or silence. The frontier state deterministically schedules the next observation."
            : "Make the checkpoint's single joint decision: teach or remain silent, and choose the next Student observation horizon. Teaching requires intents and a lesson; silence carries neither.",
        parameters: decisionParameters,
        execute: async (_toolCallId, params) => {
          const decision = adaptiveDecisionPolicy === "learning-frontier"
            ? normalizeLearningFrontierDecisionParams(params)
            : normalizeAdaptiveEducationDecisionParams(
                params,
                adaptiveDecisionPolicy === "horizon-and-events",
              );
          const accepted = onAdaptiveDecision(decision);
          return {
            content: [{
              type: "text",
              text: accepted
                ? `CHECKPOINT_COMPLETE. ${decision.action === "teach" ? "Lesson delivered" : "Silence recorded"}; ${decision.learningFrontier ? `frontier=${decision.learningFrontier.state}, ` : ""}max horizon=${decision.schedule.maxHorizon}${adaptiveDecisionPolicy === "horizon-and-events" ? `, wake conditions=${decision.schedule.wakeOn.length}` : ""}. End your turn now.`
                : "DUPLICATE_IGNORED. This checkpoint already has a decision. End your turn now.",
            }],
            details: {},
            terminate: true,
          };
        },
      })
    : undefined;
  return await createManagedSession({
    ...sessionOptions,
    boundaryViolations,
    tools: [
      ...EDUCATOR_READ_TOOLS,
      "educate_student",
      ...(educationDecision ? ["education_decision"] : []),
    ],
    customTools: [
      ...readOnlySkillPackageTools(
        skillPackageRoot,
        (violation) => boundaryViolations.push(violation),
      ),
      educateStudent,
      ...(educationDecision ? [educationDecision] : []),
    ],
  });
}
