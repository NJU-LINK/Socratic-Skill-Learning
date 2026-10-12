import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import {
  lastAssistantMessage,
  promptWithInfrastructureRecovery,
  type ManagedSession,
} from "./sessions.js";
import {
  diffSkillPackages,
  skillPackageManifest,
  skillPackageSummary,
  type SkillPackageEntry,
} from "./skill-package.js";
import {
  LEARNING_LOOP_SIGNAL_TYPES,
  LearningStateTraceTree,
  TRACE_SIGNAL_TYPES,
  TRACE_TREE_MAXIMUM_GAP,
  TRACE_TREE_MINIMUM_GAP,
  TraceTreeCheckpointScheduler,
  type TraceSignal,
} from "./trace-tree.js";
import {
  LearningIssueTree,
  type LearningIssueCheckpointDecision,
} from "./learning-issue-tree.js";
import type {
  AdaptiveEducationDecision,
  EducationCheckpoint,
  EducationIntent,
  Intervention,
  LearningIssueCommit,
  LearningIssueLesson,
  NumericObservationWindow,
  WakeCondition,
} from "../experiment/types.js";

interface PendingToolCall {
  toolName: string;
  args: unknown;
  skillPackageSha256Before?: string | null;
  followUpCheckpoint?: EducationCheckpoint;
}

interface CompletedToolCall {
  ordinal: number;
  toolName: string;
  args: string;
  result: string;
  isError: boolean;
  completedAt: string;
  matchedWakeConditions?: WakeCondition[];
}

interface TeacherProposal {
  message: string;
  intents: EducationIntent[];
  learningIssue?: LearningIssueLesson;
}

type CheckpointTrigger = EducationCheckpoint["trigger"];
const EDUCATOR_READ_TOOLS = ["skill_list", "skill_read", "skill_search"];
const FIXED_EDUCATOR_TOOLS = [...EDUCATOR_READ_TOOLS, "educate_student"];
const ADAPTIVE_EDUCATOR_TOOLS = [...EDUCATOR_READ_TOOLS, "education_decision"];
const ADAPTIVE_HORIZONS = new Set<NumericObservationWindow>([5, 10, 20]);

export type EducationSchedule =
  | { protocol: "teach-after" }
  | {
      protocol: "develop-along";
      observationWindow: number | "trajectory-end";
      guidedDialogue?: boolean;
      observationPolicy?: "fixed" | "adaptive" | "adaptive-horizon-only" | "learning-frontier" | "trace-tree" | "learning-loop" | "learning-delta" | "tree-learning-delta";
    };

function usesAdaptiveObservation(schedule: EducationSchedule): boolean {
  return schedule.protocol === "develop-along"
    && (schedule.observationPolicy === "adaptive"
      || schedule.observationPolicy === "adaptive-horizon-only"
      || schedule.observationPolicy === "learning-frontier");
}

function adaptiveObservationPolicy(
  schedule: EducationSchedule,
): "adaptive" | "adaptive-horizon-only" | "learning-frontier" | undefined {
  if (schedule.protocol !== "develop-along") return undefined;
  return schedule.observationPolicy === "adaptive"
    || schedule.observationPolicy === "adaptive-horizon-only"
    || schedule.observationPolicy === "learning-frontier"
    ? schedule.observationPolicy
    : undefined;
}

function usesAdaptiveWakeConditions(schedule: EducationSchedule): boolean {
  return schedule.protocol === "develop-along" && schedule.observationPolicy === "adaptive";
}

function usesTraceTreeScheduling(schedule: EducationSchedule): boolean {
  return schedule.protocol === "develop-along"
    && (schedule.observationPolicy === "trace-tree" || schedule.observationPolicy === "learning-loop");
}

function usesTraceRepresentation(schedule: EducationSchedule): boolean {
  return usesTraceTreeScheduling(schedule)
    || (schedule.protocol === "develop-along"
      && (schedule.observationPolicy === "learning-delta"
        || schedule.observationPolicy === "tree-learning-delta"));
}

function usesLearningLoop(schedule: EducationSchedule): boolean {
  return schedule.protocol === "develop-along" && schedule.observationPolicy === "learning-loop";
}

function usesLearningDelta(schedule: EducationSchedule): boolean {
  return schedule.protocol === "develop-along"
    && (schedule.observationPolicy === "learning-delta"
      || schedule.observationPolicy === "tree-learning-delta");
}

function usesTreeLearningDelta(schedule: EducationSchedule): boolean {
  return schedule.protocol === "develop-along"
    && schedule.observationPolicy === "tree-learning-delta";
}

function truncate(value: unknown, limit: number): string {
  let text: string;
  try {
    text = typeof value === "string" ? value : JSON.stringify(value);
  } catch {
    text = String(value);
  }
  return text.length > limit ? `${text.slice(0, limit)}…[truncated]` : text;
}

function hash(text: string): string {
  return createHash("sha256").update(text).digest("hex");
}

function learningIssueCommit(value: unknown): LearningIssueCommit | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  const item = value as Record<string, unknown>;
  if (typeof item.summary !== "string" || !item.summary.trim()) return undefined;
  if (typeof item.evidence !== "string" || !item.evidence.trim()) return undefined;
  return {
    summary: item.summary.trim(),
    evidence: item.evidence.trim(),
    ...(typeof item.addressesIssueId === "string" && item.addressesIssueId.trim()
      ? { addressesIssueId: item.addressesIssueId.trim() }
      : {}),
    ...(item.issueResolution === "verified"
      || item.issueResolution === "bounded"
      || item.issueResolution === "rejected"
      ? { issueResolution: item.issueResolution }
      : {}),
  };
}

function shellFailure(result: unknown): { exitCode?: number; timedOut: boolean } {
  if (!result || typeof result !== "object") return { timedOut: false };
  const details = (result as { details?: unknown }).details;
  if (details && typeof details === "object") {
    const exitCode = (details as { exitCode?: unknown }).exitCode;
    const timedOut = (details as { timedOut?: unknown }).timedOut === true;
    return {
      ...(typeof exitCode === "number" ? { exitCode } : {}),
      timedOut,
    };
  }
  const rendered = truncate(result, 40_000);
  const match = rendered.match(/\[exit=(-?\d+)(, timed out)?\]/);
  return {
    ...(match ? { exitCode: Number(match[1]) } : {}),
    timedOut: Boolean(match?.[2]),
  };
}

function wakeConditionMatches(
  condition: WakeCondition,
  facts: {
    toolName: string;
    toolError: boolean;
    commandExitCode?: number;
    commandTimedOut: boolean;
    repeatedFailureCount: number;
    skillPackageChanged: boolean;
  },
): boolean {
  switch (condition.event) {
    case "tool_error":
      return facts.toolError;
    case "command_nonzero_exit":
      return facts.commandExitCode !== undefined && facts.commandExitCode !== 0;
    case "command_timeout":
      return facts.commandTimedOut;
    case "repeated_failure":
      return facts.repeatedFailureCount >= condition.count;
    case "skill_package_changed":
      return facts.skillPackageChanged;
    case "tool_call":
      return facts.toolName === condition.tool;
  }
}

function uniqueWakeConditions(conditions: WakeCondition[]): WakeCondition[] {
  const seen = new Set<string>();
  return conditions.filter((condition) => {
    const key = JSON.stringify(condition);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function turnNote(value: unknown): string {
  if (!value || typeof value !== "object") return truncate(value, 6_000);
  const content = (value as { content?: unknown }).content;
  if (!Array.isArray(content)) return truncate(value, 6_000);
  const text = content
    .filter((item): item is { type: string; text?: string; thinking?: string } => Boolean(item && typeof item === "object"))
    .flatMap((item) => {
      if (item.type === "text" && item.text) return [item.text];
      if (item.type === "thinking" && item.thinking) return [item.thinking];
      return [];
    })
    .join("\n");
  return truncate(text, 6_000);
}

export function formatObservationWindow(calls: CompletedToolCall[], turns: string[]): string {
  const callRecords = calls.map((call) => ({
    toolCall: call.ordinal,
    tool: call.toolName,
    status: call.isError ? "error" : "ok",
    matchedWakeConditions: call.matchedWakeConditions ?? [],
    args: call.args,
    result: call.result,
  }));
  return `<completed_tool_calls>\n${JSON.stringify(callRecords, null, 2)}\n</completed_tool_calls>\n` +
    `<recent_student_reasoning>\n${turns.join("\n\n") || "[none captured]"}\n</recent_student_reasoning>`;
}

export function formatCausalObservationWindow(calls: CompletedToolCall[], turns: string[]): string {
  const selected = calls.length <= 14
    ? calls
    : [...new Map([
        ...calls.slice(0, 2),
        ...calls.filter((call) => call.isError).slice(-4),
        ...calls.slice(-8),
      ].map((call) => [call.ordinal, call])).values()].sort((a, b) => a.ordinal - b.ordinal);
  const records = selected.map((call) => ({
    toolCall: call.ordinal,
    tool: call.toolName,
    status: call.isError ? "error" : "ok",
    args: truncate(call.args, 1_000),
    result: truncate(call.result, 2_000),
  }));
  return `<causal_tool_window summary=${JSON.stringify({
    total: calls.length,
    shown: records.length,
    omitted: calls.length - records.length,
    errors: calls.filter((call) => call.isError).length,
  })}>\n${JSON.stringify(records, null, 2)}\n</causal_tool_window>\n`
    + `<recent_student_reasoning>\n${turns.slice(-4).join("\n\n") || "[none captured]"}\n</recent_student_reasoning>`;
}

export class EducationBridge {
  private authoringToolCalls = 0;
  private checkpoint = 0;
  private currentIteration = 1;
  private pendingToolCalls = new Map<string, PendingToolCall>();
  private completedToolCalls: CompletedToolCall[] = [];
  private recentTurns: string[] = [];
  private checkpointChain: Promise<void> = Promise.resolve();
  private tailCheckpointRun = false;
  private acceptingIntervention = false;
  private pendingFollowUp: EducationCheckpoint | undefined;
  private guidedFollowUpPendingCompletion = false;
  private currentObservationWindow: number | "trajectory-end";
  private armedWakeConditions: WakeCondition[] = [];
  private packageSha256WhenArmed: string | null | undefined;
  private consecutiveSilences = 0;
  private failureFingerprints = new Map<string, number>();
  private acceptingAdaptiveDecision = false;
  private learningDeltaBootstrapDone = false;
  private pendingEvaluatorContradictionScore: number | undefined;
  private lastReviewedPackageManifest: SkillPackageEntry[] = [];
  private lastReviewedPackageSha256: string | null = null;
  private runningCheckpoint = false;
  private readonly traceTree: LearningStateTraceTree | undefined;
  private readonly traceTreeScheduler: TraceTreeCheckpointScheduler | undefined;
  private readonly learningIssueTree: LearningIssueTree | undefined;
  private pendingStudentFollowUp: {
    checkpoint: EducationCheckpoint;
    skipTurnEnds: number;
    guidedDialogue: boolean;
  } | undefined;
  readonly interventions: Intervention[] = [];
  readonly checkpoints: EducationCheckpoint[] = [];

  constructor(
    private readonly student: ManagedSession,
    private readonly teacher: ManagedSession,
    private readonly schedule: EducationSchedule,
    private readonly specPath: string,
    private readonly taskPath: string,
    private readonly skillPackageRoot: string,
    private readonly feedbackRoot?: string,
    private readonly auditPath?: string,
    private readonly traceAuditPath?: string,
    private readonly learningIssueAuditPath?: string,
  ) {
    this.currentObservationWindow = schedule.protocol === "teach-after"
      ? "trajectory-end"
      : schedule.observationWindow;
    if (
      schedule.protocol === "develop-along"
      && usesAdaptiveObservation(schedule)
      && (
        schedule.observationWindow === "trajectory-end"
        || !ADAPTIVE_HORIZONS.has(schedule.observationWindow as NumericObservationWindow)
      )
    ) {
      throw new Error("Adaptive education requires an initial observation window of 5, 10, or 20");
    }
    if (
      schedule.protocol === "develop-along"
      && (schedule.observationPolicy === "trace-tree" || schedule.observationPolicy === "learning-loop")
      && schedule.observationWindow !== TRACE_TREE_MAXIMUM_GAP
    ) {
      throw new Error(`Trace-tree education requires a ${TRACE_TREE_MAXIMUM_GAP}-tool fallback window`);
    }
    this.traceTree = usesTraceRepresentation(schedule) ? new LearningStateTraceTree() : undefined;
    this.traceTreeScheduler = usesTraceTreeScheduling(schedule)
      ? new TraceTreeCheckpointScheduler()
      : undefined;
    this.learningIssueTree = usesTreeLearningDelta(schedule)
      ? new LearningIssueTree()
      : undefined;
  }

  startAuthoringIteration(iteration: number, priorTrainScore?: number): void {
    this.currentIteration = iteration;
    this.tailCheckpointRun = false;
    this.pendingStudentFollowUp = undefined;
    this.guidedFollowUpPendingCompletion = false;
    this.consecutiveSilences = 0;
    this.failureFingerprints.clear();
    this.armedWakeConditions = [];
    this.packageSha256WhenArmed = undefined;
    this.pendingEvaluatorContradictionScore = usesLearningDelta(this.schedule)
      && iteration > 1
      && priorTrainScore !== undefined
      && priorTrainScore < 1
      ? priorTrainScore
      : undefined;
    this.traceTreeScheduler?.reset();
    this.currentObservationWindow = this.schedule.protocol === "teach-after"
      ? "trajectory-end"
      : this.schedule.observationWindow;
    this.traceTree?.startIteration(iteration, null);
  }

  async onToolStart(event: { toolCallId: string; toolName: string; args: unknown }): Promise<void> {
    if (this.student.trace.getPhase() !== "authoring") return;
    const followUpCheckpoint = this.pendingFollowUp;
    if (followUpCheckpoint) {
      this.pendingFollowUp = undefined;
      followUpCheckpoint.nextStudentTool = {
        ordinal: this.authoringToolCalls + 1,
        toolName: event.toolName,
        startedAt: new Date().toISOString(),
      };
      followUpCheckpoint.skillPackageSha256AtNextStudentTool = (await this.packageSummary()).sha256;
      await this.persistAudit();
    }
    const skillPackageSha256Before = this.traceTree
      ? (await this.packageSummary()).sha256
      : undefined;
    this.traceTree?.startIteration(this.currentIteration, skillPackageSha256Before ?? null);
    this.pendingToolCalls.set(event.toolCallId, {
      toolName: event.toolName,
      args: event.args,
      ...(skillPackageSha256Before !== undefined ? { skillPackageSha256Before } : {}),
      ...(followUpCheckpoint ? { followUpCheckpoint } : {}),
    });
  }

  async onTurnEnd(event: { message: unknown }): Promise<void> {
    if (this.student.trace.getPhase() !== "authoring") return;
    const completedGuidedFollowUp = this.guidedFollowUpPendingCompletion;
    if (completedGuidedFollowUp) this.guidedFollowUpPendingCompletion = false;
    const note = turnNote(event.message);
    if (!note) return;
    this.recentTurns.push(note);
    if (this.pendingStudentFollowUp?.skipTurnEnds) {
      this.pendingStudentFollowUp.skipTurnEnds -= 1;
    } else if (this.pendingStudentFollowUp) {
      const pending = this.pendingStudentFollowUp;
      pending.checkpoint.studentFollowUp = {
        capturedAt: new Date().toISOString(),
        text: note,
      };
      if (usesLearningLoop(this.schedule) || usesTreeLearningDelta(this.schedule)) {
        this.traceTree?.noteStudentResponse(
          pending.checkpoint.guidedDialogue?.id,
          pending.checkpoint.studentFollowUp.capturedAt,
        );
      }
      if (pending.checkpoint.learningIssue) {
        this.learningIssueTree?.noteStudentResponse(
          pending.checkpoint.learningIssue.nodeId,
          pending.checkpoint.checkpoint,
          this.currentIteration,
          this.authoringToolCalls,
          note,
        );
      }
      this.pendingStudentFollowUp = undefined;
      await this.persistAudit();
      if (pending.guidedDialogue) {
        await this.runGuidedDialogueFollowUp(pending.checkpoint, note);
      }
    }
  }

  async onToolEnd(event: { toolCallId: string; toolName: string; result: unknown; isError: boolean }): Promise<void> {
    if (this.student.trace.getPhase() !== "authoring") return;
    // This timestamp is deliberately captured on entry. The Pi extension gate
    // awaits Teacher work before later trace subscribers observe tool_end.
    const completedAt = new Date().toISOString();
    const pending = this.pendingToolCalls.get(event.toolCallId);
    this.pendingToolCalls.delete(event.toolCallId);
    this.authoringToolCalls += 1;
    const toolName = pending?.toolName ?? event.toolName;
    const args = truncate(pending?.args ?? "[arguments unavailable]", 2_000);
    const result = truncate(event.result, 6_000);
    const shell = event.toolName === "task_shell"
      ? shellFailure(event.result)
      : { timedOut: false };
    let matchedWakeConditions: WakeCondition[] = [];
    if (usesAdaptiveWakeConditions(this.schedule)) {
      const failed = event.isError || shell.timedOut || (shell.exitCode !== undefined && shell.exitCode !== 0);
      let repeatedFailureCount = 0;
      if (failed) {
        const fingerprint = hash(`${toolName}\n${args}\n${result}`);
        const priorCount = this.failureFingerprints.get(fingerprint) ?? 0;
        repeatedFailureCount = priorCount + 1;
        this.failureFingerprints.set(fingerprint, repeatedFailureCount);
      }
      const watchesPackage = this.armedWakeConditions.some(
        (condition) => condition.event === "skill_package_changed",
      );
      const currentPackageSha256 = watchesPackage
        ? (await this.packageSummary()).sha256
        : this.packageSha256WhenArmed;
      const skillPackageChanged = watchesPackage
        && this.packageSha256WhenArmed !== undefined
        && currentPackageSha256 !== this.packageSha256WhenArmed;
      matchedWakeConditions = this.armedWakeConditions.filter((condition) =>
        wakeConditionMatches(condition, {
          toolName,
          toolError: event.isError,
          ...(shell.exitCode !== undefined ? { commandExitCode: shell.exitCode } : {}),
          commandTimedOut: shell.timedOut,
          repeatedFailureCount,
          skillPackageChanged,
        })
      );
    }
    let traceSignals: TraceSignal[] = [];
    if (this.traceTree) {
      const currentPackageSha256 = (await this.packageSummary()).sha256;
      const traced = this.traceTree.ingest({
        iteration: this.currentIteration,
        ordinal: this.authoringToolCalls,
        toolName,
        args,
        result,
        isError: event.isError,
        ...(shell.exitCode !== undefined ? { commandExitCode: shell.exitCode } : {}),
        commandTimedOut: shell.timedOut,
        skillPackageSha256Before: pending?.skillPackageSha256Before ?? currentPackageSha256,
        skillPackageSha256After: currentPackageSha256,
        completedAt,
      });
      traceSignals = traced.signals;
      this.traceTreeScheduler?.observe(traceSignals, this.completedToolCalls.length + 1);
    }
    this.completedToolCalls.push({
      ordinal: this.authoringToolCalls,
      toolName,
      args,
      result,
      isError: event.isError,
      completedAt,
      ...(matchedWakeConditions.length > 0 ? { matchedWakeConditions } : {}),
    });
    if (pending?.followUpCheckpoint?.nextStudentTool) {
      pending.followUpCheckpoint.nextStudentTool.completedAt = completedAt;
      pending.followUpCheckpoint.postInterventionSkillPackageSha256 = (await this.packageSummary()).sha256;
      await this.persistAudit();
    }

    // A terminal learning-delta lesson may run the Student once more in a
    // non-streaming prompt. Record those actions, but never recursively open a
    // second Teacher checkpoint from inside the checkpoint that caused them.
    if (usesLearningDelta(this.schedule) && this.runningCheckpoint) return;

    const scheduled = this.checkpointChain.then(async () => {
      if (this.schedule.protocol !== "develop-along") return;
      if (usesLearningDelta(this.schedule)) {
        let trigger: CheckpointTrigger | undefined;
        let explicitCommit = false;
        let priorTrainScore: number | undefined;
        if (this.pendingEvaluatorContradictionScore !== undefined) {
          trigger = "evaluator-contradiction";
          priorTrainScore = this.pendingEvaluatorContradictionScore;
          this.pendingEvaluatorContradictionScore = undefined;
        } else if (
          this.currentIteration === 1
          && !this.learningDeltaBootstrapDone
          && (this.authoringToolCalls >= 10 || toolName === "commit_skill_revision")
        ) {
          trigger = "bootstrap";
          explicitCommit = toolName === "commit_skill_revision";
          this.learningDeltaBootstrapDone = true;
        } else if (toolName === "commit_skill_revision") {
          const currentPackage = await this.packageSummary();
          if (currentPackage.sha256 !== this.lastReviewedPackageSha256) {
            trigger = "skill-commit";
            explicitCommit = true;
          }
        }
        if (!trigger) return;
        const calls = this.completedToolCalls.splice(0);
        const turns = this.recentTurns.splice(0);
        const issueDecision = usesTreeLearningDelta(this.schedule)
          ? await this.observeLearningIssue(
              trigger,
              explicitCommit,
              learningIssueCommit(pending?.args),
            )
          : undefined;
        if (issueDecision && !issueDecision.checkpointRequired) {
          await this.persistAudit();
          return;
        }
        await this.runCheckpoint(trigger, calls, turns, [], {
          explicitCommit,
          ...(priorTrainScore !== undefined ? { priorTrainScore } : {}),
          ...(issueDecision ? { issueDecision } : {}),
        });
        return;
      }
      // A guided dialogue gets one Student response and optional Teacher
      // follow-up before another observation window can open a new topic.
      if (
        this.schedule.guidedDialogue
        && (this.pendingStudentFollowUp || this.guidedFollowUpPendingCompletion)
      ) return;
      while (true) {
        const window = this.currentObservationWindow;
        if (window === "trajectory-end") break;
        const traceTreeDecision = this.traceTreeScheduler?.decide(
          this.completedToolCalls.length,
        );
        const earlyWakeIndex = usesAdaptiveWakeConditions(this.schedule)
          ? this.completedToolCalls.findIndex((call) => (call.matchedWakeConditions?.length ?? 0) > 0)
          : -1;
        const trigger: CheckpointTrigger | undefined = earlyWakeIndex >= 0
          ? "early-wake"
          : traceTreeDecision?.trigger
            ?? (this.completedToolCalls.length >= window ? "interval" : undefined);
        if (!trigger) break;
        const callCount = trigger === "early-wake"
          ? earlyWakeIndex + 1
          : traceTreeDecision?.windowTools ?? window;
        const calls = this.completedToolCalls.splice(0, callCount);
        const turns = this.recentTurns.splice(0);
        const traceSignals = traceTreeDecision?.signals ?? [];
        await this.runCheckpoint(trigger, calls, turns, traceSignals);
        if (
          this.schedule.guidedDialogue
          && (this.pendingStudentFollowUp || this.guidedFollowUpPendingCompletion)
        ) break;
      }
    });
    this.checkpointChain = scheduled.catch(() => {});
    await scheduled;
  }

  async finishAuthoringIteration(): Promise<void> {
    await this.checkpointChain;
    const currentPackageHash = (await this.packageSummary()).sha256;
    if (usesLearningDelta(this.schedule)) {
      let trigger: CheckpointTrigger | undefined;
      let priorTrainScore: number | undefined;
      if (this.pendingEvaluatorContradictionScore !== undefined) {
        trigger = "evaluator-contradiction";
        priorTrainScore = this.pendingEvaluatorContradictionScore;
        this.pendingEvaluatorContradictionScore = undefined;
      } else if (this.currentIteration === 1 && !this.learningDeltaBootstrapDone) {
        trigger = "bootstrap";
        this.learningDeltaBootstrapDone = true;
      } else if (currentPackageHash !== this.lastReviewedPackageSha256) {
        trigger = "skill-commit";
      }
      if (trigger && !this.tailCheckpointRun) {
        this.tailCheckpointRun = true;
        const calls = this.completedToolCalls.splice(0);
        const turns = this.recentTurns.splice(0);
        const issueDecision = usesTreeLearningDelta(this.schedule)
          ? await this.observeLearningIssue(trigger, false)
          : undefined;
        if (issueDecision && !issueDecision.checkpointRequired) {
          this.completedToolCalls = [];
          this.recentTurns = [];
          this.traceTree?.finishIteration();
          await this.persistAudit();
          return;
        }
        await this.runCheckpoint(trigger, calls, turns, [], {
          explicitCommit: false,
          ...(priorTrainScore !== undefined ? { priorTrainScore } : {}),
          ...(issueDecision ? { issueDecision } : {}),
        });
        await this.checkpointChain;
      }
      this.completedToolCalls = [];
      this.recentTurns = [];
      this.traceTree?.finishIteration();
      await this.persistAudit();
      return;
    }
    const last = this.checkpoints.at(-1);
    const lastObservedThisIteration = last?.iteration === this.currentIteration ? last : undefined;
    const hasUnobservedState =
      this.completedToolCalls.length > 0 ||
      this.recentTurns.length > 0 ||
      currentPackageHash !== (lastObservedThisIteration?.visibleContext.skillPackageSha256 ?? null);
    const checkpointRequired = this.schedule.protocol === "teach-after" || hasUnobservedState;
    if (checkpointRequired && !this.tailCheckpointRun) {
      this.tailCheckpointRun = true;
      const calls = this.completedToolCalls.splice(0);
      const turns = this.recentTurns.splice(0);
      const traceSignals = this.traceTreeScheduler?.takePendingSignals() ?? [];
      await this.runCheckpoint("trajectory-end", calls, turns, traceSignals);
      await this.checkpointChain;
    }
    // A tail lesson may lead to additional Student work. That work is retained
    // in the Skill and trace, but does not recursively create a terminal-review
    // loop; the frozen protocol permits at most one tail checkpoint.
    this.completedToolCalls = [];
    this.recentTurns = [];
    this.traceTree?.finishIteration();
    await this.persistAudit();
  }

  private async observeLearningIssue(
    trigger: CheckpointTrigger,
    explicitCommit: boolean,
    commit?: LearningIssueCommit,
  ): Promise<LearningIssueCheckpointDecision> {
    if (!this.learningIssueTree) {
      throw new Error("Tree learning-delta checkpoint requested without a Learning-Issue Tree");
    }
    const packageState = await this.packageSummary();
    const changes = diffSkillPackages(this.lastReviewedPackageManifest, packageState.manifest);
    const active = this.learningIssueTree.activeIssue();
    const lastLessonCheckpoint = active?.lessons.at(-1)?.checkpoint;
    const successfulPostLessonVerification = lastLessonCheckpoint !== undefined
      && this.traceTree?.snapshot().pedagogicalLoops.some((loop) =>
        loop.sourceCheckpoint === lastLessonCheckpoint && loop.status === "grounded"
      ) === true;
    const decision = this.learningIssueTree.observeCheckpoint({
      trigger,
      iteration: this.currentIteration,
      toolOrdinal: this.authoringToolCalls,
      packageSha256: packageState.sha256,
      changedPaths: changes.map((change) => change.path),
      explicitCommit,
      ...(commit ? { commit } : {}),
      successfulPostLessonVerification,
    });
    if (!decision.checkpointRequired) {
      this.lastReviewedPackageManifest = packageState.manifest;
      this.lastReviewedPackageSha256 = packageState.sha256;
    }
    return decision;
  }

  private async previousFeedback(): Promise<string> {
    if (!this.feedbackRoot || this.currentIteration <= 1) return "[No previous training evaluation]";
    const feedbackPath = path.join(this.feedbackRoot, `iteration-${this.currentIteration - 1}.json`);
    return await readFile(feedbackPath, "utf8").catch(() => "[Previous feedback unavailable]");
  }

  private async packageSummary(): Promise<{
    sha256: string | null;
    files: number;
    bytes: number;
    manifest: Awaited<ReturnType<typeof skillPackageManifest>>;
  }> {
    const manifest = await skillPackageManifest(this.skillPackageRoot).catch(() => []);
    const summary = skillPackageSummary(manifest);
    return {
      ...summary,
      sha256: summary.files > 0 ? summary.sha256 : null,
    };
  }

  private async persistAudit(): Promise<void> {
    if (this.auditPath) {
      await mkdir(path.dirname(this.auditPath), { recursive: true });
      await writeFile(this.auditPath, `${JSON.stringify(this.checkpoints, null, 2)}\n`, "utf8");
    }
    if (this.traceAuditPath && this.traceTree) {
      await mkdir(path.dirname(this.traceAuditPath), { recursive: true });
      await writeFile(this.traceAuditPath, `${JSON.stringify(this.traceTree.snapshot(), null, 2)}\n`, "utf8");
    }
    if (this.learningIssueAuditPath && this.learningIssueTree) {
      await mkdir(path.dirname(this.learningIssueAuditPath), { recursive: true });
      await writeFile(
        this.learningIssueAuditPath,
        `${JSON.stringify(this.learningIssueTree.snapshot(), null, 2)}\n`,
        "utf8",
      );
    }
  }

  private async askTeacher(
    prompt: string,
    phase: string,
    adaptiveOpening = false,
  ): Promise<{
    proposals: TeacherProposal[];
    decision: string;
    adaptiveDecision?: AdaptiveEducationDecision;
  }> {
    const proposals: TeacherProposal[] = [];
    let adaptiveDecision: AdaptiveEducationDecision | undefined;
    const originalSink = this.pendingSink;
    const originalAdaptiveSink = this.pendingAdaptiveSink;
    this.pendingSink = (message, intents, learningIssue) => proposals.push({
      message,
      intents,
      ...(learningIssue ? { learningIssue } : {}),
    });
    this.pendingAdaptiveSink = (value) => {
      adaptiveDecision = value;
      if (value.action === "teach") {
        proposals.push({ message: value.message, intents: value.intents });
      }
    };
    this.acceptingIntervention = true;
    this.acceptingAdaptiveDecision = adaptiveOpening;
    this.teacher.session.setActiveToolsByName(
      adaptiveOpening ? ADAPTIVE_EDUCATOR_TOOLS : FIXED_EDUCATOR_TOOLS,
    );
    this.teacher.trace.setPhase(phase);
    try {
      for (let attempt = 1; attempt <= 3; attempt += 1) {
        await this.teacher.session.prompt(
          attempt === 1
            ? prompt
            : adaptiveOpening
              ? this.schedule.protocol === "develop-along"
                  && this.schedule.observationPolicy === "learning-frontier"
                ? `Complete the same pedagogical decision for ${phase} from the evidence already in this continuous session. You must call education_decision exactly once, choosing teach or silence and the post-decision learning-frontier state. The runtime derives timing from that state.`
                : `Complete the same pedagogical decision for ${phase} from the evidence already in this continuous session. You must call education_decision exactly once, choosing teach or silence and a maximum horizon${usesAdaptiveWakeConditions(this.schedule) ? ", plus any one-shot observable wake conditions" : ""}.`
              : usesTreeLearningDelta(this.schedule)
                ? `Your previous response for ${phase} was interrupted by the provider/runtime. Complete the same decision from the existing evidence: if teaching, call educate_student once with intents, message, learningIssue.focus, and learningIssue.acceptanceCriterion; otherwise end silently.`
                : `Your previous response for ${phase} was interrupted by the provider/runtime. Complete the same pedagogical decision from the evidence already in this continuous session: call educate_student once if a lesson is useful, otherwise end silently.`,
        );
        const assistant = lastAssistantMessage(this.teacher.session);
        if (adaptiveOpening ? adaptiveDecision !== undefined : proposals.length > 0 || assistant?.stopReason === "stop") {
          break;
        }
        if (attempt === 3) {
          throw new Error(
            `Infrastructure-invalid ${phase}: Teacher did not complete `
            + `(last stopReason=${assistant?.stopReason ?? "missing"}; ${assistant?.errorMessage ?? "no message"})`,
          );
        }
      }
      return {
        proposals,
        decision: this.teacher.session.getLastAssistantText() ?? "",
        ...(adaptiveDecision ? { adaptiveDecision } : {}),
      };
    } finally {
      this.acceptingIntervention = false;
      this.acceptingAdaptiveDecision = false;
      this.teacher.session.setActiveToolsByName(
        adaptiveOpening ? ADAPTIVE_EDUCATOR_TOOLS : FIXED_EDUCATOR_TOOLS,
      );
      this.pendingSink = originalSink;
      this.pendingAdaptiveSink = originalAdaptiveSink;
    }
  }

  private async runGuidedDialogueFollowUp(
    checkpoint: EducationCheckpoint,
    studentResponse: string,
  ): Promise<void> {
    const dialogue = checkpoint.guidedDialogue;
    if (!dialogue || !checkpoint.intervention) return;
    dialogue.studentResponse = {
      capturedAt: new Date().toISOString(),
      text: studentResponse,
    };
    const postLessonCalls = this.completedToolCalls.filter(
      (call) => call.ordinal > checkpoint.toolCallCount,
    );
    const prompt = `Guided dialogue ${dialogue.id}: optional final Teacher follow-up.

<opening_lesson>\n${checkpoint.intervention.message}\n</opening_lesson>
<student_response>\n${studentResponse}\n</student_response>
<student_actions_since_lesson>\n${formatObservationWindow(postLessonCalls, [])}\n</student_actions_since_lesson>

The Student has now interpreted, challenged, or acted on your opening. If one short adaptive follow-up would materially improve its understanding, call educate_student once. You may clarify, correct yourself, deepen the mechanism, answer the Student's objection, or suggest the next discriminating action. Otherwise remain silent and let the Student continue. This is the final Teacher turn in this dialogue; do not start an unrelated review.`;
    const { proposals, decision } = await this.askTeacher(
      prompt,
      `guided dialogue ${dialogue.id} follow-up`,
    );
    dialogue.followUpDecision = decision;
    checkpoint.interventionCount += proposals.length;
    const proposal = proposals[0];
    if (!proposal) {
      await this.persistAudit();
      return;
    }

    const interventionId = `lesson-${this.currentIteration}-${checkpoint.checkpoint}-follow-up`;
    const delivered = this.student.session.isStreaming ? "steer" : "prompt";
    const rendered = `[Teacher dialogue ${dialogue.id}, turn 2 — ${proposal.intents.join(", ")}] ${proposal.message}`;
    dialogue.followUp = {
      id: interventionId,
      intents: proposal.intents,
      message: proposal.message,
      delivered,
      deliveryStartedAt: new Date().toISOString(),
    };
    this.guidedFollowUpPendingCompletion = true;
    await this.persistAudit();
    if (delivered === "steer") {
      await this.student.session.steer(rendered);
    } else {
      await promptWithInfrastructureRecovery(
        this.student.session,
        rendered,
        `guided dialogue ${dialogue.id} Student continuation`,
      );
    }
    dialogue.followUp.deliveryCompletedAt = new Date().toISOString();
    if (usesLearningLoop(this.schedule)) {
      this.traceTree?.noteLesson({
        lessonId: interventionId,
        dialogueId: dialogue.id,
        checkpoint: checkpoint.checkpoint,
        toolOrdinal: this.authoringToolCalls,
      });
    }
    this.interventions.push({
      id: interventionId,
      checkpoint: checkpoint.checkpoint,
      toolCallCount: this.authoringToolCalls,
      intents: proposal.intents,
      message: proposal.message,
      delivered,
      dialogueId: dialogue.id,
      dialogueTurn: 2,
    });
    await this.persistAudit();
  }

  private async runCheckpoint(
    trigger: CheckpointTrigger,
    calls: CompletedToolCall[],
    turns: string[],
    traceSignals: TraceSignal[] = [],
    learningDelta: {
      explicitCommit?: boolean;
      priorTrainScore?: number;
      issueDecision?: LearningIssueCheckpointDecision;
    } = {},
  ): Promise<void> {
    this.runningCheckpoint = true;
    const checkpointStartedAt = new Date().toISOString();
    const checkpoint = ++this.checkpoint;
    const toolCallCount = calls.at(-1)?.ordinal ?? this.authoringToolCalls;
    const observationWindow = this.currentObservationWindow;
    const adaptivePolicy = adaptiveObservationPolicy(this.schedule);
    const adaptiveOpening = adaptivePolicy !== undefined;
    const adaptiveWakeConditions = usesAdaptiveWakeConditions(this.schedule);
    const armedWakeConditions = [...this.armedWakeConditions];
    const triggeredWakeConditions = trigger === "early-wake"
      ? uniqueWakeConditions(calls.flatMap((call) => call.matchedWakeConditions ?? []))
      : [];
    const traceTreeView = this.traceTree?.view(
      calls[0]?.ordinal ?? toolCallCount,
      toolCallCount,
      traceSignals,
    );
    const [spec, task, packageState, previousFeedback] = await Promise.all([
      readFile(this.specPath, "utf8"),
      readFile(this.taskPath, "utf8"),
      this.packageSummary(),
      this.previousFeedback(),
    ]);
    const packageChanges = usesLearningDelta(this.schedule)
      ? diffSkillPackages(this.lastReviewedPackageManifest, packageState.manifest)
      : [];
    const skillRevision = usesLearningDelta(this.schedule) && packageChanges.length > 0
      ? {
          explicitCommit: learningDelta.explicitCommit === true,
          previousPackageSha256: this.lastReviewedPackageSha256,
          currentPackageSha256: packageState.sha256,
          changes: packageChanges,
        }
      : undefined;
    const historicalContext = usesTreeLearningDelta(this.schedule)
      ? `<active_learning_issue_tree>\n${JSON.stringify(this.learningIssueTree?.localView() ?? {}, null, 2)}\n</active_learning_issue_tree>`
      : `<prior_teacher_interventions>\n${JSON.stringify(this.interventions.map((item) => ({ checkpoint: item.checkpoint, intents: item.intents, message: item.message })), null, 2)}\n</prior_teacher_interventions>
<prior_lesson_uptake>\n${JSON.stringify(this.checkpoints.filter((item) => item.intervened).slice(-8).map((item) => ({
  checkpoint: item.checkpoint,
  lesson: item.intervention?.message,
  studentFollowUp: item.studentFollowUp?.text ?? "[no post-lesson response captured]",
  nextStudentTool: item.nextStudentTool?.toolName ?? null,
  skillChanged: item.postInterventionSkillPackageSha256 !== undefined && item.visibleContext.skillPackageSha256 !== null
    ? item.postInterventionSkillPackageSha256 !== item.visibleContext.skillPackageSha256
    : null,
})), null, 2)}\n</prior_lesson_uptake>
<prior_learning_frontiers>\n${JSON.stringify(this.checkpoints.filter((item) => item.learningFrontier).slice(-8).map((item) => ({
  checkpoint: item.checkpoint,
  action: item.adaptiveAction,
  frontier: item.learningFrontier,
  nextObservationWindow: item.nextObservationWindow,
})), null, 2)}\n</prior_learning_frontiers>`;
    const traceContext = traceTreeView && !usesTreeLearningDelta(this.schedule)
      ? `<learning_state_trace>\n${JSON.stringify(traceTreeView, null, 2)}\n</learning_state_trace>\n`
      : "";
    const observedStudentContext = usesTreeLearningDelta(this.schedule)
      ? formatCausalObservationWindow(calls, turns)
      : formatObservationWindow(calls, turns);
    const checkpointPrompt = `Education checkpoint ${checkpoint} (${trigger}), after Student tool call ${toolCallCount}.

<family_spec>\n${spec}\n</family_spec>
<training_task>\n${task}\n</training_task>
<previous_training_feedback>\n${previousFeedback}\n</previous_training_feedback>
${historicalContext}
<current_skill_package>
The live package root is available through the read-only skill_list,
skill_read, and skill_search tools. Inspect any relevant SKILL.md, scripts/,
references/, or assets/ resource before deciding. The Student may change this
directory between checkpoints, so do not rely on a remembered older copy.
${JSON.stringify(packageState, null, 2)}
</current_skill_package>
${usesLearningDelta(this.schedule)
  ? `<learning_delta>
${JSON.stringify({
    trigger,
    priorTrainScore: learningDelta.priorTrainScore ?? null,
    skillRevision: skillRevision ?? null,
    ...(learningDelta.issueDecision
      ? {
          issueTransition: learningDelta.issueDecision.transition,
          issue: {
            id: learningDelta.issueDecision.node.id,
            parentId: learningDelta.issueDecision.node.parentId,
            status: learningDelta.issueDecision.node.status,
            focus: learningDelta.issueDecision.node.focus,
            acceptanceCriterion: learningDelta.issueDecision.node.acceptanceCriterion,
            latestRevision: learningDelta.issueDecision.node.revisions.at(-1) ?? null,
          },
        }
      : {}),
    rule: usesTreeLearningDelta(this.schedule)
      ? "Teacher is invoked only when the Learning-Issue Tree opens, updates, or reopens an unresolved frontier. A changed package with an evidence-backed verified, bounded, or rejected Student disposition closes a frontier without redundant review."
      : "Teacher is invoked only for the one-time bootstrap, a coherent Student Skill revision, or contradictory fresh clean-v01 feedback.",
  }, null, 2)}
</learning_delta>
`
  : ""}
${traceContext}<observed_student_window>\n${observedStudentContext}\n</observed_student_window>

<observation_control>
${JSON.stringify({
  policy: adaptivePolicy
    ?? (this.schedule.protocol === "develop-along"
      ? this.schedule.observationPolicy ?? "fixed"
      : "none"),
  trigger,
  currentHorizon: observationWindow,
  ...(adaptiveWakeConditions ? { armedWakeConditions, triggeredWakeConditions } : {}),
  consecutiveSilences: this.consecutiveSilences,
  allowedNextHorizons: adaptiveOpening && adaptivePolicy !== "learning-frontier"
    ? [5, 10, 20]
    : null,
  learningFrontierSchedule: adaptivePolicy === "learning-frontier"
    ? {
        verification_pending: 5,
        active_learning: 10,
        consolidated: 20,
      }
    : null,
  availableWakeConditions: adaptiveWakeConditions
    ? [
        "tool_error",
        "command_nonzero_exit",
        "command_timeout",
        "repeated_failure(count=2|3)",
        "skill_package_changed",
        "tool_call(tool)",
      ]
    : null,
  traceTreeSchedule: usesTraceTreeScheduling(this.schedule)
    ? {
        minimumToolGap: TRACE_TREE_MINIMUM_GAP,
        maximumToolGap: TRACE_TREE_MAXIMUM_GAP,
        runtimeSelected: true,
        signalTypes: usesLearningLoop(this.schedule)
          ? [...TRACE_SIGNAL_TYPES, ...LEARNING_LOOP_SIGNAL_TYPES]
          : [...TRACE_SIGNAL_TYPES],
        pedagogicalLoop: usesLearningLoop(this.schedule)
          ? "lesson -> Student uptake -> Skill revision -> successful verification"
          : null,
      }
    : null,
  learningDeltaSchedule: usesLearningDelta(this.schedule)
    ? {
        runtimeSelected: true,
        bootstrap: "iteration 1 at tool 10 or first Skill commit, whichever comes first",
        skillRevision: "Student-declared coherent package commit; uncommitted final changes are reconciled once at iteration end",
        evaluatorContradiction: "previous fresh clean-v01 score below 1",
        periodicFallback: false,
        immediateTeacherFollowUp: false,
        ...(usesTreeLearningDelta(this.schedule)
          ? {
              controller: "persistent-learning-issue-tree",
              verifiedAssimilationClosure: true,
              evidenceBoundedClosure: true,
              evidenceBackedRejectionClosure: true,
              teacherSeesOnlyBoundedActiveSubtree: true,
            }
          : {}),
      }
    : null,
}, null, 2)}
</observation_control>

${adaptiveOpening
  ? adaptivePolicy === "learning-frontier"
    ? "Identify the most material family-level learning frontier. Call education_decision exactly once: teach or silence, then classify the post-decision frontier as verification_pending, active_learning, or consolidated. The runtime derives the next horizon."
    : `Assess whether the evidence is mature and whether a material learning delta exists. Call education_decision exactly once: teach or silence, then set the maximum horizon${adaptiveWakeConditions ? " and any one-shot observable conditions that should wake you sooner" : ""}.`
  : usesLearningDelta(this.schedule)
    ? usesTreeLearningDelta(this.schedule)
      ? "Judge only the active unresolved learning issue. Inspect package resources as needed. If a material lesson is needed, call educate_student once with the lesson, all applicable intents, a concise learningIssue.focus, and an observable learningIssue.acceptanceCriterion. Otherwise remain silent, which consolidates this node. The next Teacher opportunity requires another unresolved or contradicted Tree transition."
      : "Judge the highest-impact change in the Student's reusable family knowledge from the package diff, its evidence lineage, the public family definition, and any fresh evaluator contradiction. Inspect package resources as needed. Use educate_student once for a material lesson, or remain silent. Do not request an immediate follow-up; the next Teacher opportunity requires another learning delta."
  : "Decide whether a pedagogical intervention is useful now. Base the decision only on this training-time evidence. Use educate_student to intervene, or stay silent."}`;
    const { proposals, decision, adaptiveDecision } = await this.askTeacher(
      checkpointPrompt,
      `checkpoint-${checkpoint}`,
      adaptiveOpening,
    );
    if (adaptiveOpening && !adaptiveDecision) {
      throw new Error(`Adaptive checkpoint ${checkpoint} completed without an education decision`);
    }
    let learningIssueNode = learningDelta.issueDecision?.node;
    if (usesTreeLearningDelta(this.schedule)) {
      if (!learningDelta.issueDecision || !this.learningIssueTree) {
        throw new Error(`Tree learning-delta checkpoint ${checkpoint} has no issue transition`);
      }
      const proposal = proposals[0];
      if (proposal && !proposal.learningIssue) {
        throw new Error(
          `Infrastructure-invalid checkpoint ${checkpoint}: Teacher lesson omitted required learningIssue metadata`,
        );
      }
      learningIssueNode = this.learningIssueTree.applyTeacherDecision({
        nodeId: learningDelta.issueDecision.node.id,
        checkpoint,
        iteration: this.currentIteration,
        toolOrdinal: toolCallCount,
        ...(proposal
          ? {
              lessonId: `lesson-${this.currentIteration}-${checkpoint}`,
              lesson: proposal.learningIssue!,
            }
          : {}),
      });
    }
    if (usesLearningLoop(this.schedule)) {
      this.traceTree?.observePedagogicalLoopAtCheckpoint(checkpoint, toolCallCount);
    }
    if (adaptiveDecision) {
      this.currentObservationWindow = adaptiveDecision.schedule.maxHorizon;
      this.armedWakeConditions = [...adaptiveDecision.schedule.wakeOn];
      this.packageSha256WhenArmed = packageState.sha256;
      this.consecutiveSilences = adaptiveDecision.action === "silence"
        ? this.consecutiveSilences + 1
        : 0;
    } else {
      this.consecutiveSilences = proposals.length === 0
        ? this.consecutiveSilences + 1
        : 0;
    }
    const checkpointFinishedAt = new Date().toISOString();
    const audit: EducationCheckpoint = {
      educationProtocol: this.schedule.protocol,
      iteration: this.currentIteration,
      checkpoint,
      toolCallCount,
      toolCallStart: calls[0]?.ordinal ?? toolCallCount,
      toolCallEnd: toolCallCount,
      windowToolCalls: calls.length,
      trigger,
      observationWindow,
      observationPolicy: adaptivePolicy
        ?? (this.schedule.protocol === "develop-along"
          ? this.schedule.observationPolicy ?? "fixed"
          : "none"),
      ...(adaptiveDecision ? { adaptiveAction: adaptiveDecision.action } : {}),
      ...(adaptiveDecision ? { nextObservationWindow: adaptiveDecision.schedule.maxHorizon } : {}),
      ...(adaptiveDecision?.learningFrontier
        ? { learningFrontier: adaptiveDecision.learningFrontier }
        : {}),
      ...(adaptiveWakeConditions ? { armedWakeConditions } : {}),
      ...(adaptiveDecision && adaptiveWakeConditions
        ? { nextWakeConditions: adaptiveDecision.schedule.wakeOn }
        : {}),
      ...(triggeredWakeConditions.length > 0 ? { triggeredWakeConditions } : {}),
      ...(traceSignals.length > 0 ? { traceSignals } : {}),
      ...(traceTreeView ? { traceTree: traceTreeView } : {}),
      observedTools: calls.map((call) => ({
        ordinal: call.ordinal,
        toolName: call.toolName,
        isError: call.isError,
        ...(call.matchedWakeConditions ? { matchedWakeConditions: call.matchedWakeConditions } : {}),
        completedAt: call.completedAt,
      })),
      lastStudentToolCompletedAt: calls.at(-1)?.completedAt ?? checkpointStartedAt,
      checkpointStartedAt,
      checkpointFinishedAt,
      visibleContext: {
        specSha256: hash(spec),
        taskSha256: hash(task),
        skillPackageSha256: packageState.sha256,
        skillPackageFiles: packageState.files,
        skillPackageBytes: packageState.bytes,
        previousFeedbackSha256: previousFeedback.startsWith("[No previous") || previousFeedback.startsWith("[Previous feedback unavailable")
          ? null
          : hash(previousFeedback),
      },
      ...(skillRevision ? { skillRevision } : {}),
      ...(learningDelta.priorTrainScore !== undefined
        ? { priorTrainScore: learningDelta.priorTrainScore }
        : {}),
      ...(learningDelta.issueDecision && learningIssueNode
        ? {
            learningIssue: {
              nodeId: learningIssueNode.id,
              transition: learningDelta.issueDecision.transition as "opened" | "updated" | "reopened",
              focus: learningIssueNode.focus,
              status: learningIssueNode.status,
              acceptanceCriterion: learningIssueNode.acceptanceCriterion,
            },
          }
        : {}),
      intervened: proposals.length > 0,
      interventionCount: proposals.length,
      decision,
    };
    const guidedDialogue = this.schedule.protocol === "develop-along"
      && this.schedule.guidedDialogue === true;
    if (guidedDialogue && proposals.length > 0) {
      audit.guidedDialogue = {
        id: `dialogue-${this.currentIteration}-${checkpoint}`,
      };
    }
    this.checkpoints.push(audit);
    if (proposals.length > 0) {
      this.pendingFollowUp = audit;
    }
    await this.persistAudit();

    for (const proposal of proposals) {
      const interventionId = `lesson-${this.currentIteration}-${checkpoint}`;
      const dialogueId = audit.guidedDialogue?.id;
      const baseIntervention = dialogueId
        ? `[Teacher dialogue ${dialogueId}, turn 1 — ${proposal.intents.join(", ")}] ${proposal.message}`
        : `[Teacher lesson ${interventionId} — ${proposal.intents.join(", ")}] ${proposal.message}`;
      const intervention = audit.learningIssue && proposal.learningIssue
        ? `[Learning issue ${audit.learningIssue.nodeId}]\nFocus: ${proposal.learningIssue.focus}\nAcceptance criterion: ${proposal.learningIssue.acceptanceCriterion}\n${baseIntervention}\nWhen your own changed package genuinely disposes of this issue, cite addressesIssueId=${audit.learningIssue.nodeId} and declare issueResolution as verified, bounded, or rejected with the corresponding evidence. Otherwise keep the issue open.`
        : baseIntervention;
      const delivered = this.student.session.isStreaming ? "steer" : "prompt";
      this.pendingStudentFollowUp = {
        checkpoint: audit,
        // An interval checkpoint runs inside the Student's current tool turn.
        // The queued lesson is delivered only after that turn ends, so the
        // first subsequent turn_end still belongs to pre-lesson reasoning.
        skipTurnEnds: delivered === "steer" ? 1 : 0,
        guidedDialogue,
      };
      audit.intervention = {
        id: interventionId,
        intents: proposal.intents,
        message: proposal.message,
        delivered,
        deliveryStartedAt: new Date().toISOString(),
      };
      await this.persistAudit();
      if (delivered === "steer") {
        await this.student.session.steer(intervention);
      } else {
        await promptWithInfrastructureRecovery(
          this.student.session,
          intervention,
          `education checkpoint ${checkpoint} Student follow-up`,
        );
      }
      audit.intervention.deliveryCompletedAt = new Date().toISOString();
      if (usesLearningLoop(this.schedule) || usesTreeLearningDelta(this.schedule)) {
        this.traceTree?.noteLesson({
          lessonId: interventionId,
          ...(dialogueId ? { dialogueId } : {}),
          checkpoint,
          toolOrdinal: this.authoringToolCalls,
        });
      }
      this.interventions.push({
        id: interventionId,
        checkpoint,
        toolCallCount,
        intents: proposal.intents,
        message: proposal.message,
        delivered,
        ...(audit.learningIssue ? { learningIssueId: audit.learningIssue.nodeId } : {}),
        ...(dialogueId ? { dialogueId, dialogueTurn: 1 as const } : {}),
      });
      await this.persistAudit();
    }
    if (usesLearningDelta(this.schedule)) {
      this.lastReviewedPackageManifest = packageState.manifest;
      this.lastReviewedPackageSha256 = packageState.sha256;
    }
    this.runningCheckpoint = false;
  }

  private pendingSink: (
    message: string,
    intents: EducationIntent[],
    learningIssue?: LearningIssueLesson,
  ) => void = () => {};
  private pendingAdaptiveSink: (decision: AdaptiveEducationDecision) => void = () => {};

  receiveIntervention(
    message: string,
    intents: EducationIntent[],
    learningIssue?: LearningIssueLesson,
  ): boolean {
    if (!this.acceptingIntervention) return false;
    this.acceptingIntervention = false;
    this.pendingSink(message, intents, learningIssue);
    return true;
  }

  receiveAdaptiveDecision(decision: AdaptiveEducationDecision): boolean {
    if (!this.acceptingAdaptiveDecision) return false;
    this.acceptingAdaptiveDecision = false;
    this.acceptingIntervention = false;
    this.pendingAdaptiveSink(decision);
    return true;
  }

  close(): void {
    // No external subscription: lifecycle is owned by the Student session extension.
  }
}
