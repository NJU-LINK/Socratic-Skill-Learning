import { createHash } from "node:crypto";

export const LEARNING_TRACE_TREE_VERSION = "learning-state-trace-v1" as const;
export const TRACE_TREE_MINIMUM_GAP = 5;
export const TRACE_TREE_MAXIMUM_GAP = 20;

export const TRACE_SIGNAL_TYPES = [
  "verification_regression",
  "repeated_failure",
  "backtrack_or_oscillation",
  "unverified_change_chain",
  "consolidation_gap",
] as const;

export const LEARNING_LOOP_SIGNAL_TYPES = [
  "lesson_assimilation_pending",
] as const;

export type TraceSignalType =
  | (typeof TRACE_SIGNAL_TYPES)[number]
  | (typeof LEARNING_LOOP_SIGNAL_TYPES)[number];
export type TraceEventKind = "explore" | "task-change" | "skill-change" | "verification";
export type TraceEventOutcome = "ok" | "error" | "timeout";

export interface TraceSignal {
  type: TraceSignalType;
  eventId: string;
  stateId: string;
  evidenceEventIds: string[];
  summary: string;
}

export interface TraceEvent {
  id: string;
  iteration: number;
  ordinal: number;
  stateId: string;
  kind: TraceEventKind;
  toolName: string;
  target?: string;
  commandSignature?: string;
  failureSignature?: string;
  outcome: TraceEventOutcome;
  args: string;
  result: string;
  completedAt: string;
}

export interface TraceStateNode {
  id: string;
  iteration: number;
  parentId: string | null;
  childIds: string[];
  createdByEventId: string | null;
  taskVersion: number;
  skillVersion: number;
  skillPackageSha256: string | null;
  eventIds: string[];
}

export type PedagogicalLoopStatus =
  | "open"
  | "grounded"
  | "teacher-observed"
  | "iteration-ended";

export interface PedagogicalLoop {
  id: string;
  dialogueId: string | null;
  iteration: number;
  sourceCheckpoint: number;
  sourceStateId: string;
  lessonIds: string[];
  openedAtToolOrdinal: number;
  lastLessonAtToolOrdinal: number;
  skillVersionAtOpen: number;
  skillPackageSha256AtOpen: string | null;
  studentResponseObservedAt: string | null;
  postLessonEventIds: string[];
  skillChangeEventIds: string[];
  verificationEventIds: string[];
  status: PedagogicalLoopStatus;
  signalEventId: string | null;
  closedAtCheckpoint: number | null;
  closedAtToolOrdinal: number | null;
}

export interface TraceTreeView {
  version: typeof LEARNING_TRACE_TREE_VERSION;
  iteration: number;
  activeStateId: string;
  activePath: Array<{
    stateId: string;
    parentId: string | null;
    taskVersion: number;
    skillVersion: number;
    createdByEventId: string | null;
  }>;
  window: {
    toolCallStart: number;
    toolCallEnd: number;
    counts: Record<TraceEventKind, number>;
    events: Array<Pick<
      TraceEvent,
      | "id"
      | "ordinal"
      | "stateId"
      | "kind"
      | "toolName"
      | "target"
      | "commandSignature"
      | "failureSignature"
      | "outcome"
    >>;
  };
  triggeredSignals: TraceSignal[];
  pedagogicalLoops: {
    active: PedagogicalLoop | null;
    recent: PedagogicalLoop[];
  };
  openDynamics: {
    taskChangesSinceSuccessfulVerification: number;
    explorationsSinceStateTransition: number;
    unresolvedFailureSignatures: number;
  };
}

export interface TraceTreeSnapshot {
  version: typeof LEARNING_TRACE_TREE_VERSION;
  currentIteration: number;
  currentStateId: string | null;
  iterationRootIds: string[];
  states: TraceStateNode[];
  events: TraceEvent[];
  signals: TraceSignal[];
  pedagogicalLoops: PedagogicalLoop[];
}

export interface TraceToolEventInput {
  iteration: number;
  ordinal: number;
  toolName: string;
  args: string;
  result: string;
  isError: boolean;
  commandExitCode?: number;
  commandTimedOut: boolean;
  skillPackageSha256Before: string | null;
  skillPackageSha256After: string | null;
  completedAt: string;
}

export interface TraceTreeScheduleDecision {
  trigger: "tree-transition" | "interval";
  windowTools: number;
  signals: TraceSignal[];
}

interface VerificationRecord {
  eventId: string;
  passed: boolean;
}

export interface LessonLoopInput {
  lessonId: string;
  dialogueId?: string;
  checkpoint: number;
  toolOrdinal: number;
}

const VERIFY_RE = /(?:^|[;&|()\s])(?:pytest|py\.test|python\d*\s+-m\s+(?:pytest|unittest)|go\s+test|cargo\s+test|npm\s+(?:run\s+)?test|pnpm\s+(?:run\s+)?test|yarn\s+test|bun\s+test|ctest|make\s+(?:check|test)|mvn\s+(?:test|verify)|gradle\s+test|\.\/gradlew\s+test|bundle\s+exec\s+rspec|rspec|phpunit|dotnet\s+test|swift\s+test|mix\s+test|bats|prove)(?:$|\s)/i;
const MUTATION_RE = /(?:^|[;&|()\s])(?:cp|mv|rm|mkdir|rmdir|touch|chmod|chown|ln|patch|apply_patch|install|pip\s+install|npm\s+install|pnpm\s+install|yarn\s+install|apt(?:-get)?|yum|dnf|apk|make|cmake|git\s+(?:checkout|restore|reset|apply|am|merge|rebase|cherry-pick))\b|(?:^|\s)(?:sed\s+-i|perl\s+-pi)\b|(?:^|[^<])>{1,2}(?!=)/i;
const PATH_RE = /(?:\/app\/)?(?:\.?\.?\/)?[A-Za-z0-9_.-]+(?:\/[A-Za-z0-9_.-]+)*\.[A-Za-z0-9_.-]+/g;

function truncate(value: string, limit: number): string {
  return value.length > limit ? `${value.slice(0, limit)}…[truncated]` : value;
}

function hash(value: string): string {
  return createHash("sha256").update(value).digest("hex");
}

function parseArgs(args: string): Record<string, unknown> {
  try {
    const value = JSON.parse(args) as unknown;
    return value && typeof value === "object" && !Array.isArray(value)
      ? value as Record<string, unknown>
      : {};
  } catch {
    return {};
  }
}

function commandFromArgs(args: string): string {
  const parsed = parseArgs(args);
  return typeof parsed.command === "string" ? parsed.command.trim() : "";
}

function normalizedCommand(command: string): string {
  return command
    .replace(/\x1b\[[0-9;]*m/g, "")
    .replace(/\b0x[0-9a-f]+\b/gi, "<hex>")
    .replace(/\b\d+\b/g, "<n>")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 1_000);
}

function commandTarget(command: string): string | undefined {
  const paths = [...command.matchAll(PATH_RE)]
    .map((match) => match[0]!.replace(/^\/app\//, ""))
    .filter((value, index, values) => values.indexOf(value) === index)
    .slice(0, 3);
  return paths.length > 0 ? paths.join("|") : undefined;
}

function hostTarget(args: string): string | undefined {
  const parsed = parseArgs(args);
  for (const key of ["path", "filePath", "file_path"]) {
    const value = parsed[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return undefined;
}

function failureSignature(toolName: string, command: string, result: string): string {
  const diagnosticLines = result
    .replace(/\x1b\[[0-9;]*m/g, "")
    .split(/\r?\n/)
    .filter((line) => /error|fail|exception|traceback|denied|not found|timeout|timed out|invalid/i.test(line));
  const evidence = (diagnosticLines.length > 0 ? diagnosticLines.slice(-8) : result.split(/\r?\n/).slice(-8))
    .join("\n")
    .toLowerCase()
    .replace(/\/tmp\/[A-Za-z0-9_./-]+/g, "/tmp/<path>")
    .replace(/\b0x[0-9a-f]+\b/gi, "<hex>")
    .replace(/\b\d+(?:\.\d+)?\b/g, "<n>")
    .replace(/\s+/g, " ")
    .trim();
  return hash(`${toolName}\n${normalizedCommand(command)}\n${evidence.slice(0, 2_000)}`);
}

export function classifyTraceEvent(input: Pick<
  TraceToolEventInput,
  "toolName" | "args" | "skillPackageSha256Before" | "skillPackageSha256After"
>): { kind: TraceEventKind; target?: string; commandSignature?: string } {
  const packageChanged = input.skillPackageSha256Before !== input.skillPackageSha256After;
  if (packageChanged) {
    const target = hostTarget(input.args);
    return {
      kind: "skill-change",
      ...(target ? { target } : {}),
    };
  }
  if (input.toolName !== "task_shell") return { kind: "explore" };
  const command = commandFromArgs(input.args);
  if (VERIFY_RE.test(command)) {
    const target = commandTarget(command);
    return {
      kind: "verification",
      commandSignature: hash(normalizedCommand(command)),
      ...(target ? { target } : {}),
    };
  }
  if (MUTATION_RE.test(command)) {
    const target = commandTarget(command);
    return {
      kind: "task-change",
      ...(target ? { target } : {}),
    };
  }
  return { kind: "explore" };
}

/**
 * The shared deterministic scheduling policy used by both live runs and
 * read-only replay. Signal extraction belongs to LearningStateTraceTree;
 * this class only enforces the bounded observation cadence.
 */
export class TraceTreeCheckpointScheduler {
  private pendingSignals: Array<{ signal: TraceSignal; toolOffset: number }> = [];

  reset(): void {
    this.pendingSignals = [];
  }

  observe(signals: TraceSignal[], completedToolsInWindow: number): void {
    this.pendingSignals.push(...signals.map((signal) => ({
      signal,
      toolOffset: completedToolsInWindow,
    })));
  }

  decide(completedToolsInWindow: number): TraceTreeScheduleDecision | undefined {
    const firstSignalOffset = this.pendingSignals[0]?.toolOffset;
    const treeTransitionAt = firstSignalOffset === undefined
      ? undefined
      : Math.max(TRACE_TREE_MINIMUM_GAP, firstSignalOffset);
    if (
      treeTransitionAt !== undefined
      && treeTransitionAt <= TRACE_TREE_MAXIMUM_GAP
      && completedToolsInWindow >= treeTransitionAt
    ) {
      const signals = this.pendingSignals
        .filter((item) => item.toolOffset <= treeTransitionAt)
        .map((item) => item.signal);
      this.advanceWindow(treeTransitionAt);
      return {
        trigger: "tree-transition",
        windowTools: treeTransitionAt,
        signals,
      };
    }
    if (completedToolsInWindow >= TRACE_TREE_MAXIMUM_GAP) {
      this.advanceWindow(TRACE_TREE_MAXIMUM_GAP);
      return {
        trigger: "interval",
        windowTools: TRACE_TREE_MAXIMUM_GAP,
        signals: [],
      };
    }
    return undefined;
  }

  takePendingSignals(): TraceSignal[] {
    return this.pendingSignals.splice(0).map((item) => item.signal);
  }

  private advanceWindow(windowTools: number): void {
    this.pendingSignals = this.pendingSignals
      .filter((item) => item.toolOffset > windowTools)
      .map((item) => ({
        signal: item.signal,
        toolOffset: item.toolOffset - windowTools,
      }));
  }
}

export class LearningStateTraceTree {
  private currentIteration = 0;
  private currentStateId: string | null = null;
  private stateCounter = 0;
  private readonly iterationRootIds: string[] = [];
  private readonly states: TraceStateNode[] = [];
  private readonly events: TraceEvent[] = [];
  private readonly signals: TraceSignal[] = [];
  private readonly pedagogicalLoops: PedagogicalLoop[] = [];
  private readonly stateById = new Map<string, TraceStateNode>();
  private activePedagogicalLoopId: string | null = null;
  private verificationHistory = new Map<string, VerificationRecord>();
  private failureHistory = new Map<string, string[]>();
  private targetChangeHistory = new Map<string, string[]>();
  private taskChangesSinceSuccessfulVerification: string[] = [];
  private packageVersionAtFirstTaskChange: number | null = null;
  private explorationsSinceStateTransition: string[] = [];
  private failureSinceSuccessfulVerification = false;

  startIteration(iteration: number, skillPackageSha256: string | null): void {
    if (this.currentIteration === iteration && this.currentStateId) {
      this.setInitialPackageSha256(skillPackageSha256);
      return;
    }
    this.finishIteration();
    this.currentIteration = iteration;
    this.stateCounter = 0;
    const root: TraceStateNode = {
      id: `iteration-${iteration}-state-0`,
      iteration,
      parentId: null,
      childIds: [],
      createdByEventId: null,
      taskVersion: 0,
      skillVersion: 0,
      skillPackageSha256,
      eventIds: [],
    };
    this.currentStateId = root.id;
    this.iterationRootIds.push(root.id);
    this.states.push(root);
    this.stateById.set(root.id, root);
    this.verificationHistory = new Map();
    this.failureHistory = new Map();
    this.targetChangeHistory = new Map();
    this.taskChangesSinceSuccessfulVerification = [];
    this.packageVersionAtFirstTaskChange = null;
    this.explorationsSinceStateTransition = [];
    this.failureSinceSuccessfulVerification = false;
  }

  noteLesson(input: LessonLoopInput): void {
    const current = this.currentState();
    const active = this.activePedagogicalLoop();
    if (
      active
      && active.status === "open"
      && input.dialogueId
      && active.dialogueId === input.dialogueId
    ) {
      active.lessonIds.push(input.lessonId);
      active.lastLessonAtToolOrdinal = input.toolOrdinal;
      return;
    }
    if (active?.status === "open") {
      active.status = "teacher-observed";
      active.closedAtCheckpoint = input.checkpoint;
      active.closedAtToolOrdinal = input.toolOrdinal;
    }
    const loop: PedagogicalLoop = {
      // A reciprocal dialogue can resume after an earlier loop has already
      // grounded. Keep each learning episode independently addressable even
      // when the human-readable dialogue id is reused.
      id: `${input.dialogueId ?? input.lessonId}-loop-${this.pedagogicalLoops.length + 1}`,
      dialogueId: input.dialogueId ?? null,
      iteration: this.currentIteration,
      sourceCheckpoint: input.checkpoint,
      sourceStateId: current.id,
      lessonIds: [input.lessonId],
      openedAtToolOrdinal: input.toolOrdinal,
      lastLessonAtToolOrdinal: input.toolOrdinal,
      skillVersionAtOpen: current.skillVersion,
      skillPackageSha256AtOpen: current.skillPackageSha256,
      studentResponseObservedAt: null,
      postLessonEventIds: [],
      skillChangeEventIds: [],
      verificationEventIds: [],
      status: "open",
      signalEventId: null,
      closedAtCheckpoint: null,
      closedAtToolOrdinal: null,
    };
    this.pedagogicalLoops.push(loop);
    this.activePedagogicalLoopId = loop.id;
  }

  noteStudentResponse(dialogueId: string | undefined, observedAt: string): void {
    const active = this.activePedagogicalLoop();
    if (!active || active.status !== "open") return;
    if (dialogueId && active.dialogueId && active.dialogueId !== dialogueId) return;
    active.studentResponseObservedAt = observedAt;
  }

  observePedagogicalLoopAtCheckpoint(checkpoint: number, toolOrdinal: number): void {
    const active = this.activePedagogicalLoop();
    if (!active || active.status !== "open") return;
    if (toolOrdinal <= active.lastLessonAtToolOrdinal) return;
    active.status = "teacher-observed";
    active.closedAtCheckpoint = checkpoint;
    active.closedAtToolOrdinal = toolOrdinal;
    this.activePedagogicalLoopId = null;
  }

  finishIteration(): void {
    const active = this.activePedagogicalLoop();
    if (!active || active.status !== "open") return;
    active.status = "iteration-ended";
    active.closedAtToolOrdinal = this.events.at(-1)?.ordinal ?? active.lastLessonAtToolOrdinal;
    this.activePedagogicalLoopId = null;
  }

  setInitialPackageSha256(skillPackageSha256: string | null): void {
    const current = this.currentState();
    if (current.taskVersion === 0 && current.skillVersion === 0 && current.createdByEventId === null) {
      current.skillPackageSha256 = skillPackageSha256;
    }
  }

  ingest(input: TraceToolEventInput): { event: TraceEvent; signals: TraceSignal[] } {
    if (this.currentIteration !== input.iteration || !this.currentStateId) {
      this.startIteration(input.iteration, input.skillPackageSha256Before);
    } else {
      this.setInitialPackageSha256(input.skillPackageSha256Before);
    }

    const classification = classifyTraceEvent(input);
    const command = input.toolName === "task_shell" ? commandFromArgs(input.args) : "";
    const failed = input.isError
      || input.commandTimedOut
      || (input.commandExitCode !== undefined && input.commandExitCode !== 0);
    const outcome: TraceEventOutcome = input.commandTimedOut ? "timeout" : failed ? "error" : "ok";
    const eventId = `iteration-${input.iteration}-event-${input.ordinal}`;
    const parentState = this.currentState();
    let eventState = parentState;
    if (classification.kind === "task-change" || classification.kind === "skill-change") {
      this.stateCounter += 1;
      eventState = {
        id: `iteration-${input.iteration}-state-${this.stateCounter}`,
        iteration: input.iteration,
        parentId: parentState.id,
        childIds: [],
        createdByEventId: eventId,
        taskVersion: parentState.taskVersion + (classification.kind === "task-change" ? 1 : 0),
        skillVersion: parentState.skillVersion + (classification.kind === "skill-change" ? 1 : 0),
        skillPackageSha256: input.skillPackageSha256After,
        eventIds: [],
      };
      parentState.childIds.push(eventState.id);
      this.states.push(eventState);
      this.stateById.set(eventState.id, eventState);
      this.currentStateId = eventState.id;
    } else {
      eventState.skillPackageSha256 = input.skillPackageSha256After;
    }

    const signature = failed ? failureSignature(input.toolName, command, input.result) : undefined;
    const event: TraceEvent = {
      id: eventId,
      iteration: input.iteration,
      ordinal: input.ordinal,
      stateId: eventState.id,
      kind: classification.kind,
      toolName: input.toolName,
      ...(classification.target ? { target: classification.target } : {}),
      ...(classification.commandSignature ? { commandSignature: classification.commandSignature } : {}),
      ...(signature ? { failureSignature: signature } : {}),
      outcome,
      args: truncate(input.args, 1_000),
      result: truncate(input.result, 2_000),
      completedAt: input.completedAt,
    };
    eventState.eventIds.push(event.id);
    this.events.push(event);

    const emitted: TraceSignal[] = [];
    const emit = (
      type: TraceSignalType,
      evidenceEventIds: string[],
      summary: string,
    ) => {
      const signal: TraceSignal = {
        type,
        eventId: event.id,
        stateId: event.stateId,
        evidenceEventIds: [...new Set(evidenceEventIds)],
        summary,
      };
      emitted.push(signal);
      this.signals.push(signal);
    };

    if (classification.kind === "task-change") {
      if (this.taskChangesSinceSuccessfulVerification.length === 0) {
        this.packageVersionAtFirstTaskChange = eventState.skillVersion;
      }
      this.taskChangesSinceSuccessfulVerification.push(event.id);
      this.explorationsSinceStateTransition = [];
      if (this.taskChangesSinceSuccessfulVerification.length === 3) {
        emit(
          "unverified_change_chain",
          this.taskChangesSinceSuccessfulVerification,
          "Three task-state changes accumulated without a successful verification.",
        );
      }
      if (classification.target) {
        const history = this.targetChangeHistory.get(classification.target) ?? [];
        history.push(event.id);
        this.targetChangeHistory.set(classification.target, history);
        if (this.failureSinceSuccessfulVerification && history.length === 3) {
          emit(
            "backtrack_or_oscillation",
            history,
            `The same target (${classification.target}) was changed three times after unresolved failure evidence.`,
          );
        }
      }
    } else if (classification.kind === "skill-change") {
      this.explorationsSinceStateTransition = [];
    } else if (classification.kind === "explore") {
      this.explorationsSinceStateTransition.push(event.id);
      if (
        this.explorationsSinceStateTransition.length === 8
        && (this.failureSinceSuccessfulVerification || this.taskChangesSinceSuccessfulVerification.length > 0)
      ) {
        emit(
          "backtrack_or_oscillation",
          this.explorationsSinceStateTransition,
          "Eight exploratory actions followed a changed or failing state without forward state transition.",
        );
      }
    } else {
      this.explorationsSinceStateTransition = [];
      const commandSignature = classification.commandSignature!;
      const previous = this.verificationHistory.get(commandSignature);
      if (failed && previous?.passed) {
        emit(
          "verification_regression",
          [previous.eventId, event.id],
          "A verification that previously passed now fails in the current state.",
        );
      }
      this.verificationHistory.set(commandSignature, { eventId: event.id, passed: !failed });
      if (!failed) {
        if (
          this.taskChangesSinceSuccessfulVerification.length > 0
          && this.packageVersionAtFirstTaskChange === eventState.skillVersion
        ) {
          emit(
            "consolidation_gap",
            [...this.taskChangesSinceSuccessfulVerification, event.id],
            "A changed task path is now verified, but the Skill package has not changed along that path.",
          );
        }
        this.taskChangesSinceSuccessfulVerification = [];
        this.packageVersionAtFirstTaskChange = null;
        this.targetChangeHistory.clear();
        this.failureHistory.clear();
        this.failureSinceSuccessfulVerification = false;
      }
    }

    if (failed && signature) {
      this.failureSinceSuccessfulVerification = true;
      const history = this.failureHistory.get(signature) ?? [];
      history.push(event.id);
      this.failureHistory.set(signature, history);
      if (history.length === 2) {
        emit(
          "repeated_failure",
          history,
          "The same normalized failure signature appeared twice without successful recovery.",
        );
      }
    }

    const activeLoop = this.activePedagogicalLoop();
    if (activeLoop?.status === "open" && activeLoop.iteration === input.iteration) {
      activeLoop.postLessonEventIds.push(event.id);
      if (classification.kind === "skill-change") {
        activeLoop.skillChangeEventIds.push(event.id);
      }
      if (classification.kind === "verification") {
        activeLoop.verificationEventIds.push(event.id);
        if (!failed && activeLoop.skillChangeEventIds.length > 0) {
          activeLoop.status = "grounded";
          activeLoop.closedAtToolOrdinal = event.ordinal;
          this.activePedagogicalLoopId = null;
        }
      }
      if (
        activeLoop.status === "open"
        && activeLoop.signalEventId === null
        && event.ordinal - activeLoop.lastLessonAtToolOrdinal >= TRACE_TREE_MINIMUM_GAP
      ) {
        const evidence = [
          ...activeLoop.skillChangeEventIds,
          ...activeLoop.verificationEventIds,
          event.id,
        ];
        emit(
          "lesson_assimilation_pending",
          evidence,
          `The lesson-to-Skill learning loop remains open after ${TRACE_TREE_MINIMUM_GAP} tools `
            + `(studentResponse=${activeLoop.studentResponseObservedAt !== null}, `
            + `skillChanged=${activeLoop.skillChangeEventIds.length > 0}, `
            + `successfulPostSkillVerification=false).`,
        );
        activeLoop.signalEventId = event.id;
      }
    }

    return { event, signals: emitted };
  }

  view(toolCallStart: number, toolCallEnd: number, triggeredSignals: TraceSignal[]): TraceTreeView {
    const active = this.currentState();
    const activePath: TraceStateNode[] = [];
    let cursor: TraceStateNode | undefined = active;
    while (cursor) {
      activePath.push(cursor);
      cursor = cursor.parentId ? this.stateById.get(cursor.parentId) : undefined;
    }
    activePath.reverse();
    const events = this.events.filter((event) =>
      event.iteration === this.currentIteration
      && event.ordinal >= toolCallStart
      && event.ordinal <= toolCallEnd
    );
    const counts: Record<TraceEventKind, number> = {
      explore: 0,
      "task-change": 0,
      "skill-change": 0,
      verification: 0,
    };
    for (const event of events) counts[event.kind] += 1;
    return {
      version: LEARNING_TRACE_TREE_VERSION,
      iteration: this.currentIteration,
      activeStateId: active.id,
      activePath: activePath.slice(-12).map((state) => ({
        stateId: state.id,
        parentId: state.parentId,
        taskVersion: state.taskVersion,
        skillVersion: state.skillVersion,
        createdByEventId: state.createdByEventId,
      })),
      window: {
        toolCallStart,
        toolCallEnd,
        counts,
        events: events.map((event) => ({
          id: event.id,
          ordinal: event.ordinal,
          stateId: event.stateId,
          kind: event.kind,
          toolName: event.toolName,
          ...(event.target ? { target: event.target } : {}),
          ...(event.commandSignature ? { commandSignature: event.commandSignature } : {}),
          ...(event.failureSignature ? { failureSignature: event.failureSignature } : {}),
          outcome: event.outcome,
        })),
      },
      triggeredSignals,
      pedagogicalLoops: {
        active: this.clonePedagogicalLoop(this.activePedagogicalLoop()),
        recent: this.pedagogicalLoops.slice(-6).map((loop) => this.clonePedagogicalLoop(loop)!),
      },
      openDynamics: {
        taskChangesSinceSuccessfulVerification: this.taskChangesSinceSuccessfulVerification.length,
        explorationsSinceStateTransition: this.explorationsSinceStateTransition.length,
        unresolvedFailureSignatures: this.failureHistory.size,
      },
    };
  }

  snapshot(): TraceTreeSnapshot {
    return {
      version: LEARNING_TRACE_TREE_VERSION,
      currentIteration: this.currentIteration,
      currentStateId: this.currentStateId,
      iterationRootIds: [...this.iterationRootIds],
      states: this.states.map((state) => ({
        ...state,
        childIds: [...state.childIds],
        eventIds: [...state.eventIds],
      })),
      events: this.events.map((event) => ({ ...event })),
      signals: this.signals.map((signal) => ({
        ...signal,
        evidenceEventIds: [...signal.evidenceEventIds],
      })),
      pedagogicalLoops: this.pedagogicalLoops.map((loop) => this.clonePedagogicalLoop(loop)!),
    };
  }

  private activePedagogicalLoop(): PedagogicalLoop | undefined {
    if (!this.activePedagogicalLoopId) return undefined;
    return this.pedagogicalLoops.find((loop) => loop.id === this.activePedagogicalLoopId);
  }

  private clonePedagogicalLoop(loop: PedagogicalLoop | undefined): PedagogicalLoop | null {
    if (!loop) return null;
    return {
      ...loop,
      lessonIds: [...loop.lessonIds],
      postLessonEventIds: [...loop.postLessonEventIds],
      skillChangeEventIds: [...loop.skillChangeEventIds],
      verificationEventIds: [...loop.verificationEventIds],
    };
  }

  private currentState(): TraceStateNode {
    if (!this.currentStateId) throw new Error("Learning-state trace iteration has not started");
    const state = this.stateById.get(this.currentStateId);
    if (!state) throw new Error(`Missing active trace state ${this.currentStateId}`);
    return state;
  }
}
