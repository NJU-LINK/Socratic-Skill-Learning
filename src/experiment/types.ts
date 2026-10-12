import type { TraceSignal, TraceTreeView } from "../agent/trace-tree.js";

export const MODES = [
  "plus-compile-after",
  "max-compile-after",
  "plus-teach-after",
  "max-teach-after",
  "plus-develop-along",
  "max-develop-along",
] as const;
export const GUIDED_PRACTICE_MODES = [
  "max-guided-one-way",
  "max-guided-dialogue",
] as const;
export const GRANULARITY_CURVE_MODES = [
  "develop-g5",
  "develop-g10",
  "develop-g20",
  "develop-trajectory",
] as const;
export const ADAPTIVE_HORIZON_MODES = ["develop-adaptive"] as const;
export const ADAPTIVE_HORIZON_ONLY_MODES = ["develop-adaptive-horizon-only"] as const;
export const LEARNING_FRONTIER_MODES = ["develop-learning-frontier"] as const;
export const TRACE_TREE_MODES = ["develop-tree-triggered"] as const;
export const LEARNING_LOOP_MODES = ["develop-learning-loop-triggered"] as const;
export const LEARNING_DELTA_MODES = ["develop-learning-delta"] as const;
export const TREE_LEARNING_DELTA_MODES = ["develop-tree-learning-delta"] as const;
export const ALL_MODES = [
  ...MODES,
  ...GUIDED_PRACTICE_MODES,
  ...GRANULARITY_CURVE_MODES,
  ...ADAPTIVE_HORIZON_MODES,
  ...ADAPTIVE_HORIZON_ONLY_MODES,
  ...LEARNING_FRONTIER_MODES,
  ...TRACE_TREE_MODES,
  ...LEARNING_LOOP_MODES,
  ...LEARNING_DELTA_MODES,
  ...TREE_LEARNING_DELTA_MODES,
] as const;
export const PROTOCOL_MAIN_MODES = [
  "max-compile-after",
  "max-teach-after",
  "max-develop-along",
] as const;
export const MODEL_TIERS = ["plus", "max"] as const;
export const LEARNING_PROTOCOLS = [
  "compile-after",
  "teach-after",
  "develop-along",
] as const;
export const CORE_EDUCATION_INTENTS = [
  "knowledge_transfer",
  "reasoning_guidance",
  "exploration_verification",
  "error_diagnosis_recovery",
  "epistemic_calibration",
  "experience_consolidation",
] as const;
export const EDUCATION_INTENTS = [...CORE_EDUCATION_INTENTS, "other"] as const;
export const EDUCATION_TAXONOMY_VERSION = "learner-state-v1-open" as const;

export type Mode = (typeof ALL_MODES)[number];
export type V6Mode = (typeof MODES)[number];
export type ModelTier = (typeof MODEL_TIERS)[number];
export type LearningProtocol = (typeof LEARNING_PROTOCOLS)[number];
export type EducationIntent = (typeof EDUCATION_INTENTS)[number];
export type CoreEducationIntent = (typeof CORE_EDUCATION_INTENTS)[number];
export type ReasoningEffort = "minimal" | "low" | "medium" | "high" | "xhigh" | "max";
export type GuidedPracticeInteraction = "one-way" | "reciprocal" | "learning-delta" | null;
export type ObservationWindow = 5 | 10 | 20 | "trajectory-end";
export type NumericObservationWindow = Exclude<ObservationWindow, "trajectory-end">;
export type ObservationPolicy =
  | "none"
  | "fixed"
  | "adaptive"
  | "adaptive-horizon-only"
  | "learning-frontier"
  | "trace-tree"
  | "learning-loop"
  | "learning-delta"
  | "tree-learning-delta";
export const LEARNING_FRONTIER_STATES = [
  "verification_pending",
  "active_learning",
  "consolidated",
] as const;
export type LearningFrontierState = (typeof LEARNING_FRONTIER_STATES)[number];
export const AUTHOR_TOOL_NAMES = [
  "read",
  "write",
  "edit",
  "grep",
  "find",
  "ls",
  "task_shell",
] as const;
export type AuthorToolName = (typeof AUTHOR_TOOL_NAMES)[number];
export type WakeCondition =
  | { event: "tool_error" }
  | { event: "command_nonzero_exit" }
  | { event: "command_timeout" }
  | { event: "repeated_failure"; count: 2 | 3 }
  | { event: "skill_package_changed" }
  | { event: "tool_call"; tool: AuthorToolName };

export interface AdaptiveObservationSchedule {
  maxHorizon: NumericObservationWindow;
  wakeOn: WakeCondition[];
}

export interface AdaptiveEducationDecision {
  action: "teach" | "silence";
  schedule: AdaptiveObservationSchedule;
  intents: EducationIntent[];
  message: string;
  learningFrontier?: {
    state: LearningFrontierState;
    focus: string;
    evidence: string;
  };
}

export interface ExperimentCell {
  id: Mode;
  capabilitySourceTier: ModelTier;
  protocol: LearningProtocol;
  authorModelTier: ModelTier;
  educatorModelTier: ModelTier | null;
  targetStudentTier: "plus";
  guidedPracticeInteraction: GuidedPracticeInteraction;
  observationPolicy: ObservationPolicy;
  observationWindow: ObservationWindow | null;
}

export interface ProviderConfig {
  id: string;
  studentModel: string;
  teacherModel: string;
  contextWindow: number;
  maxCompletionTokens: number;
  thinkingEnabled: boolean;
  reasoningEffort?: ReasoningEffort;
  teacherLimits?: { contextWindow: number; maxCompletionTokens: number };
}

export interface FamilyConfig {
  name: string;
  train: string;
  heldout: string[];
}

export interface PilotConfig {
  configPath: string;
  projectRoot: string;
  assetsRoot: string;
  runsRoot: string;
  dockerProxy?: string;
  provider: ProviderConfig;
  protocolVersion: string;
  replicates: number;
  iterations: number;
  cellConcurrency: number;
  groupConcurrency: number;
  heldoutEachIteration: boolean;
  reuseDockerImages: boolean;
  agentSolveTimeoutMs?: number;
  families: FamilyConfig[];
}

export const CAPABILITY_PEER_MAIN_MODES = [
  "plus-compile-after",
  "plus-teach-after",
  "plus-develop-along",
] as const;

export const SCREEN_GUIDED_DIALOGUE_MODES = ["max-guided-dialogue"] as const;
export const GUIDED_DEVELOPMENT_MAIN_MODES = ["max-guided-dialogue"] as const;
export const RECIPROCITY_ABLATION_MODES = [
  "max-guided-one-way",
  "max-guided-dialogue",
] as const;

export interface TestResult {
  passed: number;
  failed: number;
  errors: number;
  total: number;
  score: number;
  output: string;
  exitCode: number;
  timedOut: boolean;
}

export interface EvalResult {
  family: string;
  variant: string;
  iteration: number;
  split: "train" | "heldout";
  tests: TestResult;
  toolCalls: number;
  agentAttempts?: number;
  recoveredFromInterruption?: boolean;
  sessionFile?: string;
  skillResourceReads: string[];
  skillResourceExecutions: string[];
  loadedSkill: {
    name: string;
    description: string;
    filePath: string;
    baseDir: string;
  };
}

export interface Intervention {
  id: string;
  checkpoint: number;
  toolCallCount: number;
  intents: EducationIntent[];
  message: string;
  delivered: "steer" | "prompt";
  dialogueId?: string;
  dialogueTurn?: 1 | 2;
  learningIssueId?: string;
}

export interface LearningIssueLesson {
  focus: string;
  acceptanceCriterion: string;
}

export interface LearningIssueCommit {
  summary: string;
  evidence: string;
  addressesIssueId?: string;
  issueResolution?: "verified" | "bounded" | "rejected";
}

export interface EducationCheckpoint {
  educationProtocol: "teach-after" | "develop-along";
  iteration: number;
  checkpoint: number;
  toolCallCount: number;
  toolCallStart: number;
  toolCallEnd: number;
  windowToolCalls: number;
  trigger:
    | "interval"
    | "early-wake"
    | "tree-transition"
    | "trajectory-end"
    | "bootstrap"
    | "skill-commit"
    | "evaluator-contradiction";
  observationWindow: number | "trajectory-end";
  observationPolicy?: ObservationPolicy;
  adaptiveAction?: "teach" | "silence";
  nextObservationWindow?: NumericObservationWindow;
  learningFrontier?: {
    state: LearningFrontierState;
    focus: string;
    evidence: string;
  };
  armedWakeConditions?: WakeCondition[];
  nextWakeConditions?: WakeCondition[];
  triggeredWakeConditions?: WakeCondition[];
  traceSignals?: TraceSignal[];
  traceTree?: TraceTreeView;
  observedTools: Array<{
    ordinal: number;
    toolName: string;
    isError: boolean;
    matchedWakeConditions?: WakeCondition[];
    completedAt: string;
  }>;
  lastStudentToolCompletedAt: string;
  checkpointStartedAt: string;
  checkpointFinishedAt: string;
  visibleContext: {
    specSha256: string;
    taskSha256: string;
    skillPackageSha256: string | null;
    skillPackageFiles: number;
    skillPackageBytes: number;
    previousFeedbackSha256: string | null;
  };
  skillRevision?: {
    explicitCommit: boolean;
    previousPackageSha256: string | null;
    currentPackageSha256: string | null;
    changes: import("../agent/skill-package.js").SkillPackageChange[];
  };
  priorTrainScore?: number;
  learningIssue?: {
    nodeId: string;
    transition: "opened" | "updated" | "reopened";
    focus: string;
    status: "active_learning" | "verification_pending" | "consolidated" | "contradicted";
    acceptanceCriterion: string | null;
  };
  intervened: boolean;
  interventionCount: number;
  decision: string;
  intervention?: {
    id: string;
    intents: EducationIntent[];
    message: string;
    delivered: "steer" | "prompt";
    deliveryStartedAt: string;
    deliveryCompletedAt?: string;
  };
  guidedDialogue?: {
    id: string;
    studentResponse?: {
      capturedAt: string;
      text: string;
    };
    followUpDecision?: string;
    followUp?: {
      id: string;
      intents: EducationIntent[];
      message: string;
      delivered: "steer" | "prompt";
      deliveryStartedAt: string;
      deliveryCompletedAt?: string;
    };
  };
  studentFollowUp?: {
    capturedAt: string;
    text: string;
  };
  nextStudentTool?: {
    ordinal: number;
    toolName: string;
    startedAt: string;
    completedAt?: string;
  };
  skillPackageSha256AtNextStudentTool?: string | null;
  postInterventionSkillPackageSha256?: string | null;
}

export interface IterationResult {
  iteration: number;
  train: EvalResult;
  heldout: EvalResult[];
  skillSnapshot: string;
  skillPackageManifest: import("../agent/skill-package.js").SkillPackageEntry[];
  skillPackageDiff: import("../agent/skill-package.js").SkillPackageChange[];
  skillValidation: { valid: true; diagnostics: string[] };
  /** Present only in historical schema-v2 runs that silently repaired metadata. */
  skillRepair?: { repaired: boolean; fields: string[] };
  educationCheckpoints: EducationCheckpoint[];
  interventions: Intervention[];
}

export interface RunResult {
  schemaVersion: 3;
  runId: string;
  mode: Mode;
  cell: ExperimentCell;
  replicate: number;
  family: string;
  startedAt: string;
  finishedAt: string;
  heldoutStatus: "not-run" | "partial" | "complete";
  iterations: IterationResult[];
}

export interface TraceEvent {
  sequence: number;
  at: string;
  session: string;
  phase: string;
  type: string;
  data: Record<string, unknown>;
}
