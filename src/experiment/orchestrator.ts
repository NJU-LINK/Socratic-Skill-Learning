import { access, cp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import YAML from "yaml";
import type { ModelBundle } from "../agent/model.js";
import { familyPath } from "./config.js";
import { createRunId } from "./run-id.js";
import { withSolverBudget } from "./solver-budget.js";
import { TaskEnvironment } from "../runtime/docker.js";
import { EducationBridge } from "../agent/education.js";
import { acquireProcessFileLock } from "../runtime/file-lock.js";
import {
  beginHeldoutAttempt,
  completeHeldoutAttempt,
  completedHeldoutAttempt,
  invalidateHeldoutAttempt,
  loadHeldoutLedger,
  writeHeldoutLedger,
} from "./heldout-attempts.js";
import {
  ADAPTIVE_HORIZON_EDUCATOR_SYSTEM,
  ADAPTIVE_HORIZON_ONLY_EDUCATOR_SYSTEM,
  COMPILE_AFTER_AUTHOR_SYSTEM,
  DEVELOP_ALONG_EDUCATOR_SYSTEM,
  GUIDED_DIALOGUE_EDUCATOR_SYSTEM,
  GUIDED_DIALOGUE_STUDENT_SYSTEM,
  GUIDED_ONE_WAY_EDUCATOR_SYSTEM,
  GUIDED_ONE_WAY_STUDENT_SYSTEM,
  LEARNING_FRONTIER_EDUCATOR_SYSTEM,
  LEARNING_DELTA_EDUCATOR_SYSTEM,
  LEARNING_DELTA_STUDENT_SYSTEM,
  LEARNING_LOOP_EDUCATOR_SYSTEM,
  STUDENT_AUTHOR_SYSTEM,
  STUDENT_EVALUATOR_SYSTEM,
  TEACH_AFTER_EDUCATOR_SYSTEM,
  TRACE_TREE_EDUCATOR_SYSTEM,
  TREE_LEARNING_DELTA_EDUCATOR_SYSTEM,
  TREE_LEARNING_DELTA_STUDENT_SYSTEM,
  authorPrompt,
  evaluatePrompt,
  guidedPracticePrompt,
  learningDeltaPrompt,
  treeLearningDeltaPrompt,
} from "../agent/prompts.js";
import {
  LEARNING_LOOP_SIGNAL_TYPES,
  LEARNING_TRACE_TREE_VERSION,
  TRACE_SIGNAL_TYPES,
  TRACE_TREE_MAXIMUM_GAP,
  TRACE_TREE_MINIMUM_GAP,
} from "../agent/trace-tree.js";
import {
  skillResourceExecutions,
  skillResourceReads,
} from "../agent/trace.js";
import {
  experimentCell,
  hasAdaptiveWakeConditions,
  hasEducator,
  isAdaptiveHorizon,
  isDevelopAlong,
  isGuidedDialogue,
  isGuidedOneWay,
  isGuidedPractice,
  isLearningLoopTriggered,
  isLearningDeltaTriggered,
  isTreeLearningDelta,
  modelForTier,
  observationWindowFor,
  sessionTopology,
  usesLearningStateTrace,
} from "./protocol.js";
import { implementationProvenance } from "./provenance.js";
import {
  initializeRunState,
  readRunState,
  transitionRunState,
} from "./run-state.js";
import {
  createEducatorSession,
  createEvaluatorSession,
  createWorkspaceSession,
  promptWithInfrastructureRecovery,
  reportWorkspaceBoundaryWarnings,
  requireLoadedSkill,
  type ManagedSession,
} from "../agent/sessions.js";
import {
  diffSkillPackages,
  skillPackageManifest,
  skillPackageSha256,
  type SkillPackageEntry,
} from "../agent/skill-package.js";
import {
  EDUCATION_TAXONOMY_VERSION,
  type EvalResult,
  type FamilyConfig,
  type Intervention,
  type IterationResult,
  type Mode,
  type PilotConfig,
  type RunResult,
  type TraceEvent,
} from "./types.js";

const AUTHOR_TOOLS = ["read", "write", "edit", "grep", "find", "ls", "task_shell"];
const EVALUATOR_TOOLS = ["read", "grep", "find", "ls", "task_shell"];

interface TaskYaml {
  instruction?: string;
  max_test_timeout_sec?: number;
}

export function trainSolverLayout(runRoot: string, iteration: number): {
  root: string;
  workspace: string;
  session: string;
  trajectory: string;
} {
  const root = path.join(runRoot, "train-solvers", `iteration-${iteration}`);
  return {
    root,
    workspace: path.join(root, "workspace"),
    session: path.join(root, "session"),
    trajectory: path.join(root, "trajectory.json"),
  };
}

export class RunInvalidError extends Error {
  constructor(
    readonly runId: string,
    readonly runRoot: string,
    readonly mode: Mode,
    readonly family: string,
    readonly replicate: number,
    readonly invalidReason: string,
    readonly invalidErrorType: string,
  ) {
    super(`Run ${runId} is invalid: ${invalidReason}`);
    this.name = "RunInvalidError";
  }
}

export class HeldoutAttemptInvalidError extends Error {
  constructor(
    readonly runId: string,
    readonly variant: string,
    readonly attempt: number,
    readonly attemptRoot: string,
    readonly causeError: unknown,
  ) {
    super(
      `Held-out ${runId}/${variant} attempt ${attempt} is infrastructure-invalid: `
      + `${causeError instanceof Error ? causeError.message : String(causeError)}`,
    );
    this.name = "HeldoutAttemptInvalidError";
  }
}

async function writeJson(filePath: string, value: unknown): Promise<void> {
  await mkdir(path.dirname(filePath), { recursive: true });
  await writeFile(filePath, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

async function copyReplacing(source: string, destination: string): Promise<void> {
  await rm(destination, { recursive: true, force: true });
  await mkdir(path.dirname(destination), { recursive: true });
  await cp(source, destination, { recursive: true });
}

export async function validateSkill(
  skillPath: string,
  family: string,
): Promise<{ valid: true; diagnostics: string[] }> {
  await access(skillPath);
  const text = await readFile(skillPath, "utf8");
  const frontmatter = text.match(/^---\s*\n([\s\S]*?)\n---/);
  const diagnostics: string[] = [];
  if (!frontmatter) {
    diagnostics.push("SKILL.md must begin with YAML frontmatter");
  } else {
    let metadata: Record<string, unknown> = {};
    try {
      metadata = YAML.parse(frontmatter[1] ?? "") as Record<string, unknown>;
    } catch (error) {
      diagnostics.push(`frontmatter is not valid YAML: ${error instanceof Error ? error.message : String(error)}`);
    }
    if (metadata.name !== family) diagnostics.push(`frontmatter name must exactly equal ${family}`);
    if (typeof metadata.description !== "string" || metadata.description.trim() === "") {
      diagnostics.push("frontmatter description must be a non-empty string");
    }
  }
  const body = frontmatter ? text.slice(frontmatter[0].length).trim() : text.trim();
  if (!body) diagnostics.push("SKILL.md must contain non-empty instructions after frontmatter");
  if (diagnostics.length > 0) {
    throw new Error(
      `Invalid Agent Skill package authored for ${family}; the experiment does not repair model artifacts:\n`
      + diagnostics.map((item) => `- ${item}`).join("\n"),
    );
  }
  return { valid: true, diagnostics: [] };
}

async function taskTimeout(variantRoot: string): Promise<number> {
  const task = YAML.parse(await readFile(path.join(variantRoot, "task.yaml"), "utf8")) as TaskYaml;
  return Number(task.max_test_timeout_sec ?? 300);
}

function feedbackTrajectory(events: TraceEvent[]): TraceEvent[] {
  return events.filter((event) =>
    ["message_end", "tool_execution_start", "tool_execution_end", "turn_end"].includes(event.type),
  );
}

export class RunOrchestrator {
  private provenance?: ReturnType<typeof implementationProvenance>;

  constructor(
    private readonly config: PilotConfig,
    private readonly models: ModelBundle,
  ) {}

  private experimentProvenance(): ReturnType<typeof implementationProvenance> {
    this.provenance ??= implementationProvenance(this.config);
    return this.provenance;
  }

  async run(
    mode: Mode,
    family: FamilyConfig,
    replicate = 1,
    reservedRunId?: string,
  ): Promise<RunResult> {
    const cell = experimentCell(mode);
    const runId = reservedRunId ?? createRunId(mode, family.name, replicate);
    const runRoot = path.join(this.config.runsRoot, runId);
    const authorRoot = path.join(runRoot, "author-workspace");
    const familyRoot = familyPath(this.config, family);
    const skillPackage = path.join(authorRoot, "skill", family.name);
    const skillPath = path.join(skillPackage, "SKILL.md");
    const trainVariantRoot = path.join(familyRoot, family.train);
    const startedAt = new Date().toISOString();
    await mkdir(runRoot, { recursive: true });
    const releaseRunLock = await acquireProcessFileLock(path.join(runRoot, "phase"), "Run induction");
    const environment = new TaskEnvironment(runId, this.config.reuseDockerImages, this.config.dockerProxy);
    const managed: ManagedSession[] = [];
    let author: ManagedSession | undefined;
    let educator: ManagedSession | undefined;
    let education: EducationBridge | undefined;
    let stateInitialized = false;

    try {
      await initializeRunState(runRoot, runId);
      stateInitialized = true;
      const provenance = await this.experimentProvenance();
      const observationWindow = isDevelopAlong(mode)
        ? observationWindowFor(mode)
        : null;
      const authorTools = [
        ...AUTHOR_TOOLS,
        ...(isLearningDeltaTriggered(mode) ? ["commit_skill_revision"] : []),
      ];
      await this.prepareAuthorWorkspace(authorRoot, familyRoot, family);
      await writeJson(path.join(runRoot, "run-metadata.json"), {
        runId,
        mode,
        cell,
        replicate,
        family,
        startedAt,
        protocol: {
          continuousAuthorAcrossIterations: true,
          continuousEducatorAcrossIterations: hasEducator(mode),
          freshTrainSolverPerIteration: true,
          trainSolverWorkspacePerIteration: true,
          resetTaskContainerBeforeEverySolve: true,
          frozenSkillDuringSolve: true,
          freshSessionPerHeldoutVariant: true,
          agentSkillLoading: "pi-explicit-package-with-progressive-disclosure",
          dockerProxy: this.config.dockerProxy ?? null,
          observationWindow,
          observationPolicy: cell.observationPolicy,
          checkpointEveryTools: typeof observationWindow === "number"
            && cell.observationPolicy === "fixed"
            ? observationWindow
            : null,
          adaptiveObservationWindows: isAdaptiveHorizon(mode)
            ? [5, 10, 20]
            : null,
          adaptiveWakeConditionCatalog: hasAdaptiveWakeConditions(mode)
            ? [
                "tool_error",
                "command_nonzero_exit",
                "command_timeout",
                "repeated_failure(count=2|3)",
                "skill_package_changed",
                "tool_call(tool)",
              ]
            : null,
          adaptiveWakeConditionsAreTeacherSelected: hasAdaptiveWakeConditions(mode)
            ? true
            : null,
          traceTreeTrigger: usesLearningStateTrace(mode)
            ? {
                version: LEARNING_TRACE_TREE_VERSION,
                selectedBy: "runtime",
                ...(isLearningDeltaTriggered(mode)
                  ? {
                      representationOnly: !isTreeLearningDelta(mode),
                      triggerEvents: [
                        "iteration-1-bootstrap",
                        isTreeLearningDelta(mode)
                          ? "unresolved-learning-issue-transition"
                          : "student-skill-revision-commit",
                        "prior-clean-evaluator-contradiction",
                      ],
                      periodicFallback: false,
                      ...(isTreeLearningDelta(mode)
                        ? {
                            issueTreeVersion: "learning-issue-tree-v1",
                            verifiedAssimilationClosure: true,
                            evidenceBoundedClosure: true,
                            evidenceBackedRejectionClosure: true,
                            localFrontierOnly: true,
                          }
                        : {}),
                    }
                  : {
                      minimumToolGap: TRACE_TREE_MINIMUM_GAP,
                      maximumToolGap: TRACE_TREE_MAXIMUM_GAP,
                      signals: isLearningLoopTriggered(mode)
                        ? [...TRACE_SIGNAL_TYPES, ...LEARNING_LOOP_SIGNAL_TYPES]
                        : [...TRACE_SIGNAL_TYPES],
                      pedagogicalLoop: isLearningLoopTriggered(mode)
                        ? "lesson-uptake-skill-revision-verification"
                        : null,
                    }),
              }
            : null,
          trajectoryEndTeaching: cell.protocol === "teach-after"
            ? "one-opportunity-after-complete-authoring-trajectory"
            : cell.protocol === "develop-along"
              ? isLearningDeltaTriggered(mode)
                ? "one-implicit-skill-commit-only-when-final-package-changed"
              : observationWindow === "trajectory-end"
                ? "one-reciprocal-opportunity-after-complete-authoring-trajectory"
                : "one-tail-opportunity-only-when-unobserved-state-exists"
              : null,
          educationPolicy: hasEducator(mode)
            ? isLearningDeltaTriggered(mode)
              ? isTreeLearningDelta(mode)
                ? "student-owned-tree-structured-learning-delta"
                : "student-owned-learning-delta"
            : isGuidedDialogue(mode)
              ? "student-owned-guided-practice-dialogue"
              : isGuidedOneWay(mode)
                ? "student-owned-guided-practice-one-way"
                : "student-owned-open-bandwidth"
            : null,
          guidedDialogueMaxTeacherTurns: isGuidedDialogue(mode)
            ? 2
            : isGuidedOneWay(mode) ? 1 : null,
          educationTaxonomyVersion: hasEducator(mode)
            ? EDUCATION_TAXONOMY_VERSION
            : null,
          heldoutPhaseSeparated: true,
        },
        provider: this.config.provider,
        sessions: sessionTopology(cell, this.config.provider),
        toolPolicy: {
          author: authorTools,
          educator: hasEducator(mode)
            ? [
                "skill_list",
                "skill_read",
                "skill_search",
                "educate_student",
                ...(isAdaptiveHorizon(mode) ? ["education_decision"] : []),
              ]
            : [],
          solver: EVALUATOR_TOOLS,
        },
        agentSkillLoader: {
          piCatalog: true,
          ambientSkillsDisabled: true,
          explicitPackageOnly: true,
          packageReadOnlyDuringEvaluation: true,
        },
        provenance,
      });
      if (cell.protocol === "compile-after") {
        author = await createWorkspaceSession({
          label: `${cell.authorModelTier}-direct-author`,
          cwd: authorRoot,
          sessionDir: path.join(runRoot, "sessions", `${cell.authorModelTier}-direct-author`),
          systemPrompt: COMPILE_AFTER_AUTHOR_SYSTEM,
          model: modelForTier(cell.authorModelTier, this.models),
          runtime: this.models.runtime,
          config: this.config,
          environment,
        });
        managed.push(author);
      } else {
        author = await createWorkspaceSession({
          label: "student-author",
          cwd: authorRoot,
          sessionDir: path.join(runRoot, "sessions", "student-author"),
          systemPrompt: isGuidedDialogue(mode)
            ? GUIDED_DIALOGUE_STUDENT_SYSTEM
            : isLearningDeltaTriggered(mode)
              ? isTreeLearningDelta(mode)
                ? TREE_LEARNING_DELTA_STUDENT_SYSTEM
                : LEARNING_DELTA_STUDENT_SYSTEM
            : isGuidedOneWay(mode)
              ? GUIDED_ONE_WAY_STUDENT_SYSTEM
              : STUDENT_AUTHOR_SYSTEM,
          model: this.models.student,
          runtime: this.models.runtime,
          config: this.config,
          environment,
          ...(isLearningDeltaTriggered(mode) ? { enableSkillRevisionCommit: true } : {}),
          ...(isTreeLearningDelta(mode) ? { structuredLearningIssueCommit: true } : {}),
          ...(hasEducator(mode)
            ? {
                checkpointHooks: {
                  onToolStart: async (event: { toolCallId: string; toolName: string; args: unknown }) => {
                    await education?.onToolStart(event);
                  },
                  onToolEnd: async (event: {
                    toolCallId: string;
                    toolName: string;
                    result: unknown;
                    isError: boolean;
                  }) => {
                    await education?.onToolEnd(event);
                  },
                  onTurnEnd: async (event: { message: unknown }) => {
                    await education?.onTurnEnd(event);
                  },
                },
              }
            : {}),
        });
        managed.push(author);
      }

      if (hasEducator(mode) && cell.educatorModelTier) {
        let bridge: EducationBridge | undefined;
        educator = await createEducatorSession(
          {
            label: `${cell.educatorModelTier}-educator`,
            cwd: authorRoot,
            sessionDir: path.join(runRoot, "sessions", `${cell.educatorModelTier}-educator`),
            systemPrompt: cell.protocol === "teach-after"
              ? TEACH_AFTER_EDUCATOR_SYSTEM
              : cell.observationPolicy === "tree-learning-delta"
                ? TREE_LEARNING_DELTA_EDUCATOR_SYSTEM
              : cell.observationPolicy === "learning-delta"
                ? LEARNING_DELTA_EDUCATOR_SYSTEM
              : cell.observationPolicy === "learning-loop"
                ? LEARNING_LOOP_EDUCATOR_SYSTEM
              : cell.observationPolicy === "trace-tree"
                ? TRACE_TREE_EDUCATOR_SYSTEM
              : cell.observationPolicy === "learning-frontier"
                ? LEARNING_FRONTIER_EDUCATOR_SYSTEM
              : cell.observationPolicy === "adaptive-horizon-only"
                ? ADAPTIVE_HORIZON_ONLY_EDUCATOR_SYSTEM
              : isAdaptiveHorizon(mode)
                ? ADAPTIVE_HORIZON_EDUCATOR_SYSTEM
              : isGuidedDialogue(mode)
                ? GUIDED_DIALOGUE_EDUCATOR_SYSTEM
                : isGuidedOneWay(mode)
                  ? GUIDED_ONE_WAY_EDUCATOR_SYSTEM
                  : DEVELOP_ALONG_EDUCATOR_SYSTEM,
            model: modelForTier(cell.educatorModelTier, this.models),
            runtime: this.models.runtime,
            config: this.config,
            skillPackageRoot: skillPackage,
            ...(isTreeLearningDelta(mode) ? { structuredLearningIssueLesson: true } : {}),
            ...(cell.observationPolicy === "adaptive-horizon-only"
              ? { adaptiveDecisionPolicy: "horizon-only" as const }
              : cell.observationPolicy === "learning-frontier"
                ? { adaptiveDecisionPolicy: "learning-frontier" as const }
              : {}),
          },
          (message, intents, learningIssue) =>
            bridge?.receiveIntervention(message, intents, learningIssue) ?? false,
          isAdaptiveHorizon(mode)
            ? (decision) => bridge?.receiveAdaptiveDecision(decision) ?? false
            : undefined,
        );
        bridge = new EducationBridge(
          author,
          educator,
          cell.protocol === "teach-after"
            ? { protocol: "teach-after" }
            : {
                protocol: "develop-along",
                observationWindow: observationWindowFor(mode),
                ...(isGuidedDialogue(mode) ? { guidedDialogue: true } : {}),
                ...(isAdaptiveHorizon(mode) || usesLearningStateTrace(mode)
                  ? {
                      observationPolicy: cell.observationPolicy as
                        | "adaptive"
                        | "adaptive-horizon-only"
                        | "learning-frontier"
                        | "trace-tree"
                        | "learning-loop"
                        | "learning-delta"
                        | "tree-learning-delta",
                    }
                  : {}),
              },
          path.join(authorRoot, "spec.yaml"),
          path.join(authorRoot, "train", family.train, "task.yaml"),
          skillPackage,
          path.join(authorRoot, "feedback"),
          path.join(runRoot, "education", "checkpoints.json"),
          usesLearningStateTrace(mode)
            ? path.join(runRoot, "education", "trace-tree.json")
            : undefined,
          isTreeLearningDelta(mode)
            ? path.join(runRoot, "education", "learning-issue-tree.json")
            : undefined,
        );
        education = bridge;
        managed.push(educator);
      }

      const iterations: IterationResult[] = [];
      let previousPackageManifest: SkillPackageEntry[] = [];
      for (let iteration = 1; iteration <= this.config.iterations; iteration += 1) {
        console.log(`[${mode}/${family.name}] iteration ${iteration}: authoring skill`);
        await environment.reset(family.name, family.train, trainVariantRoot, skillPackage);
        author.trace.setPhase("authoring");
        author.session.setActiveToolsByName(authorTools);
        education?.startAuthoringIteration(
          iteration,
          iterations.at(-1)?.train.tests.score,
        );
        const interventionStart = education?.interventions.length ?? 0;
        const checkpointStart = education?.checkpoints.length ?? 0;
        await promptWithInfrastructureRecovery(
          author.session,
          isLearningDeltaTriggered(mode)
            ? isTreeLearningDelta(mode)
              ? treeLearningDeltaPrompt(family.name, iteration)
              : learningDeltaPrompt(family.name, iteration)
            : isGuidedPractice(mode)
            ? guidedPracticePrompt(family.name, iteration)
            : authorPrompt(family.name, iteration),
          `${mode}/${family.name} iteration ${iteration} authoring`,
        );
        await education?.finishAuthoringIteration();
        reportWorkspaceBoundaryWarnings(
          author,
          `${mode}/${family.name} iteration ${iteration} authoring`,
        );
        if (educator) {
          reportWorkspaceBoundaryWarnings(
            educator,
            `${mode}/${family.name} iteration ${iteration} education`,
          );
        }
        environment.assertValid();
        const skillValidation = await validateSkill(skillPath, family.name);

        const snapshotRoot = path.join(runRoot, "snapshots", `iteration-${iteration}`);
        const snapshotPackage = path.join(snapshotRoot, "skill", family.name);
        await copyReplacing(skillPackage, snapshotPackage);
        const packageManifest = await skillPackageManifest(snapshotPackage);
        const packageDiff = diffSkillPackages(previousPackageManifest, packageManifest);
        previousPackageManifest = packageManifest;

        console.log(`[${mode}/${family.name}] iteration ${iteration}: clean v01 evaluation`);
        const trainEvaluation = await this.evaluateTrainingPackage({
          runRoot,
          environment,
          family,
          familyRoot,
          snapshotPackage,
          iteration,
          artifactsRoot: path.join(runRoot, "artifacts", `iteration-${iteration}`, "train"),
        });
        const train = trainEvaluation.result;

        const feedbackFile = path.join(authorRoot, "feedback", `iteration-${iteration}.json`);
        await writeJson(feedbackFile, {
          iteration,
          train,
          trajectory: trainEvaluation.trajectory,
          note: "This is a one-shot evaluation by a fresh Plus session in a reset v01 container using only this iteration's frozen Skill snapshot.",
        });

        const interventions: Intervention[] = education
          ? education.interventions.slice(interventionStart)
          : [];
        const educationCheckpoints = education
          ? education.checkpoints.slice(checkpointStart)
          : [];
        const result: IterationResult = {
          iteration,
          train,
          heldout: [],
          skillSnapshot: snapshotPackage,
          skillPackageManifest: packageManifest,
          skillPackageDiff: packageDiff,
          skillValidation,
          educationCheckpoints,
          interventions,
        };
        iterations.push(result);
        await writeJson(path.join(runRoot, "results", `iteration-${iteration}.json`), result);
      }

      const result: RunResult = {
        schemaVersion: 3,
        runId,
        mode,
        cell,
        replicate,
        family: family.name,
        startedAt,
        finishedAt: new Date().toISOString(),
        heldoutStatus: "not-run",
        iterations,
      };
      await writeJson(path.join(runRoot, "result.json"), result);
      await transitionRunState(runRoot, "induction-running", "heldout-ready");
      return result;
    } catch (error) {
      const invalidReason = error instanceof Error ? error.message : String(error);
      const invalidErrorType = error instanceof Error ? error.name : typeof error;
      await writeJson(path.join(runRoot, "invalid.json"), {
        runId,
        mode,
        family: family.name,
        replicate,
        startedAt,
        invalidatedAt: new Date().toISOString(),
        reason: invalidReason,
        errorType: invalidErrorType,
      }).catch(() => {});
      if (stateInitialized) {
        await transitionRunState(
          runRoot,
          ["induction-running"],
          "invalid",
          `${invalidErrorType}: ${invalidReason}`,
        ).catch(() => {});
      }
      throw new RunInvalidError(
        runId,
        runRoot,
        mode,
        family.name,
        replicate,
        invalidReason,
        invalidErrorType,
      );
    } finally {
      try {
        education?.close();
        await environment.stop();
        for (const session of [...new Set(managed)].reverse()) await session.dispose();
      } finally {
        await releaseRunLock();
      }
    }
  }

  async evaluateExistingRun(
    runRoot: string,
    family: FamilyConfig,
    iteration: number,
    variants: string[],
  ): Promise<EvalResult[]> {
    const releaseRunLock = await acquireProcessFileLock(path.join(runRoot, "phase"), "Run held-out evaluation");
    let heldoutStarted = false;
    try {
      const state = await readRunState(runRoot);
      if (state.phase !== "heldout-ready") {
        throw new Error(`Held-out is locked for ${state.runId}: run phase is ${state.phase}, expected heldout-ready`);
      }
      const resultPath = path.join(runRoot, "result.json");
      const runResult = JSON.parse(await readFile(resultPath, "utf8")) as RunResult;
      const metadata = JSON.parse(await readFile(path.join(runRoot, "run-metadata.json"), "utf8")) as {
        provenance?: { lockSha256?: string };
      };
      const currentProvenance = await this.experimentProvenance();
      if (metadata.provenance?.lockSha256 !== currentProvenance.lockSha256) {
        throw new Error(
          `Held-out provenance lock mismatch for ${runResult.runId}: `
          + `${String(metadata.provenance?.lockSha256)} != ${currentProvenance.lockSha256}`,
        );
      }
      const iterationResult = runResult.iterations.find((item) => item.iteration === iteration);
      if (!iterationResult) throw new Error(`Iteration ${iteration} not found in ${resultPath}`);
      const familyRoot = familyPath(this.config, family);
      const snapshotPackage = iterationResult.skillSnapshot;
      await access(path.join(snapshotPackage, "SKILL.md"));
      const currentManifest = await skillPackageManifest(snapshotPackage);
      if (JSON.stringify(currentManifest) !== JSON.stringify(iterationResult.skillPackageManifest)) {
        throw new Error(`Frozen Skill package changed after induction: ${snapshotPackage}`);
      }
      const ledger = await loadHeldoutLedger({
        runRoot,
        runId: runResult.runId,
        iteration,
        frozenPackageManifestSha256: skillPackageSha256(currentManifest),
      });
      await writeHeldoutLedger(runRoot, ledger);
      await transitionRunState(runRoot, "heldout-ready", "heldout-running");
      heldoutStarted = true;
      const environment = new TaskEnvironment(
        `${runResult.runId}-heldout`,
        this.config.reuseDockerImages,
        this.config.dockerProxy,
      );
      const heldout: EvalResult[] = [];
      const byVariant = new Map(iterationResult.heldout.map((item) => [item.variant, item]));
      try {
        for (const variant of variants) {
          const completedAttempt = completedHeldoutAttempt(ledger, variant);
          if (completedAttempt?.resultPath) {
            const completed = JSON.parse(await readFile(completedAttempt.resultPath, "utf8")) as EvalResult;
            console.log(
              `[${runResult.mode}/${family.name}] reusing canonical heldout ${variant} `
              + `attempt ${completedAttempt.attempt}`,
            );
            heldout.push(completed);
            byVariant.set(variant, completed);
            continue;
          }
          const attempt = beginHeldoutAttempt(ledger, runRoot, variant);
          await writeHeldoutLedger(runRoot, ledger);
          console.log(
            `[${runResult.mode}/${family.name}] heldout ${variant} fresh attempt ${attempt.attempt}`,
          );
          try {
            const evaluated = await this.evaluateHeldout({
              attemptRoot: attempt.attemptRoot,
              environment,
              family,
              familyRoot,
              variant,
              iteration,
              snapshotPackage,
            });
            const attemptResultPath = path.join(attempt.attemptRoot, "result.json");
            completeHeldoutAttempt(attempt, attemptResultPath);
            await writeHeldoutLedger(runRoot, ledger);
            // This canonical file is a deterministic pointer copy of the first
            // valid attempt; later attempts are forbidden once it exists.
            await writeJson(
              path.join(runRoot, "heldout", `iteration-${iteration}`, variant, "result.json"),
              evaluated,
            );
            heldout.push(evaluated);
            byVariant.set(variant, evaluated);
            iterationResult.heldout = family.heldout.flatMap((name) => {
              const value = byVariant.get(name);
              return value ? [value] : [];
            });
            runResult.heldoutStatus = family.heldout.every((name) => byVariant.has(name))
              ? "complete"
              : "partial";
            runResult.finishedAt = new Date().toISOString();
            await writeJson(resultPath, runResult);
            await writeJson(path.join(runRoot, "results", `heldout-iteration-${iteration}.json`), {
              evaluatedAt: new Date().toISOString(),
              iteration,
              heldout: iterationResult.heldout,
              attemptLedger: path.join(runRoot, "heldout", `iteration-${iteration}`, "attempts.json"),
            });
          } catch (error) {
            invalidateHeldoutAttempt(attempt, error);
            await writeHeldoutLedger(runRoot, ledger);
            throw new HeldoutAttemptInvalidError(
              runResult.runId,
              variant,
              attempt.attempt,
              attempt.attemptRoot,
              error,
            );
          }
        }
      } finally {
        await environment.stop();
      }
      await transitionRunState(
        runRoot,
        "heldout-running",
        runResult.heldoutStatus === "complete" ? "complete" : "heldout-ready",
      );
      return heldout;
    } catch (error) {
      if (heldoutStarted) {
        const reason = error instanceof Error ? `${error.name}: ${error.message}` : String(error);
        await transitionRunState(
          runRoot,
          "heldout-running",
          error instanceof HeldoutAttemptInvalidError ? "heldout-ready" : "invalid",
          reason,
        ).catch(() => {});
      }
      throw error;
    } finally {
      await releaseRunLock();
    }
  }

  /**
   * Evaluate an already-frozen Skill package without requiring the induction
   * run to be complete. This is intentionally separate from the signed matrix
   * path: it supports expedited pilot evaluation after an external scheduler
   * is stopped, while preserving the exact package and fresh-solver semantics.
   */
  async evaluateFrozenPackage(options: {
    evaluationRoot: string;
    evaluationId: string;
    evaluationKind?: string;
    sourceRunId: string;
    family: FamilyConfig;
    iteration: number;
    snapshotPackage: string;
    variants: string[];
    variantConcurrency?: number;
  }): Promise<EvalResult[]> {
    const {
      evaluationRoot,
      evaluationId,
      evaluationKind = "expedited-frozen-package-heldout",
      sourceRunId,
      family,
      iteration,
      snapshotPackage,
      variants,
      variantConcurrency = 1,
    } = options;
    if (
      !Number.isInteger(variantConcurrency)
      || variantConcurrency < 1
      || variantConcurrency > variants.length
    ) {
      throw new Error(
        `variantConcurrency must be an integer from 1 to ${variants.length}`,
      );
    }
    await access(path.join(snapshotPackage, "SKILL.md"));
    const frozenManifest = await skillPackageManifest(snapshotPackage);
    const frozenPackageSha256 = skillPackageSha256(frozenManifest);
    const familyRoot = familyPath(this.config, family);
    await writeJson(path.join(evaluationRoot, "evaluation-metadata.json"), {
      schemaVersion: 1,
      evaluationKind,
      evaluationId,
      sourceRunId,
      family: family.name,
      iteration,
      variants,
      snapshotPackage,
      frozenPackageSha256,
      frozenManifest,
      protocolVersion: this.config.protocolVersion,
      variantConcurrency,
      startedAt: new Date().toISOString(),
    });

    const results = new Array<EvalResult | undefined>(variants.length);
    let nextIndex = 0;
    let firstError: unknown;
    const worker = async (): Promise<void> => {
      while (firstError === undefined) {
        const index = nextIndex;
        nextIndex += 1;
        if (index >= variants.length) return;
        const variant = variants[index]!;
        const attemptRoot = path.join(evaluationRoot, variant);
        const resultPath = path.join(attemptRoot, "result.json");
        const existing = await readFile(resultPath, "utf8")
          .then((text) => JSON.parse(text) as EvalResult)
          .catch(() => undefined);
        if (existing) {
          results[index] = existing;
          continue;
        }
        console.log(
          `[${evaluationId}/${family.name}] frozen heldout ${variant}`,
        );
        const environment = new TaskEnvironment(
          `${evaluationId}-heldout-${variant}`,
          this.config.reuseDockerImages,
          this.config.dockerProxy,
        );
        try {
          results[index] = await this.evaluateHeldout({
            attemptRoot,
            environment,
            family,
            familyRoot,
            variant,
            iteration,
            snapshotPackage,
          });
        } catch (error) {
          if (firstError === undefined) firstError = error;
        } finally {
          await environment.stop();
        }
      }
    };
    await Promise.all(
      Array.from(
        { length: Math.min(variantConcurrency, variants.length) },
        async () => await worker(),
      ),
    );
    if (firstError !== undefined) throw firstError;
    const completed = results.map((result, index) => {
      if (!result) throw new Error(`No frozen held-out result for ${variants[index]}`);
      return result;
    });

    const afterManifest = await skillPackageManifest(snapshotPackage);
    if (JSON.stringify(afterManifest) !== JSON.stringify(frozenManifest)) {
      throw new Error(`Frozen Skill package changed during evaluation: ${snapshotPackage}`);
    }
    await writeJson(path.join(evaluationRoot, "summary.json"), {
      schemaVersion: 1,
      evaluationKind,
      evaluationId,
      sourceRunId,
      family: family.name,
      iteration,
      frozenPackageSha256,
      finishedAt: new Date().toISOString(),
      results: completed.map((result) => ({
        variant: result.variant,
        score: result.tests.score,
        passed: result.tests.passed,
        total: result.tests.total,
      })),
    });
    return completed;
  }

  private async prepareAuthorWorkspace(root: string, familyRoot: string, family: FamilyConfig): Promise<void> {
    await mkdir(path.join(root, "skill", family.name), { recursive: true });
    await mkdir(path.join(root, "feedback"), { recursive: true });
    const rawSpec = YAML.parse(await readFile(path.join(familyRoot, "spec.yaml"), "utf8")) as Record<string, unknown>;
    delete rawSpec.seed_task_dir;
    await writeFile(path.join(root, "spec.yaml"), YAML.stringify(rawSpec), "utf8");
    const trainRoot = path.join(root, "train", family.train);
    await mkdir(trainRoot, { recursive: true });
    await cp(path.join(familyRoot, family.train, "task.yaml"), path.join(trainRoot, "task.yaml"));
  }

  private async prepareTrainSolverWorkspace(
    root: string,
    familyRoot: string,
    family: FamilyConfig,
    snapshotPackage: string,
  ): Promise<string> {
    await mkdir(root, { recursive: true });
    await cp(path.join(familyRoot, family.train, "task.yaml"), path.join(root, "task.yaml"));
    const frozenSkillPackage = path.join(root, "skill", family.name);
    await copyReplacing(snapshotPackage, frozenSkillPackage);
    return frozenSkillPackage;
  }

  /**
   * Run one fresh Plus solve of the public training member with a frozen
   * package. This public primitive is shared by native induction protocols and
   * external skill-learning baselines; it does not preserve a solver session
   * across calls.
   */
  async evaluateTrainingPackage(options: {
    runRoot: string;
    environment: TaskEnvironment;
    family: FamilyConfig;
    familyRoot: string;
    snapshotPackage: string;
    iteration: number;
    artifactsRoot: string;
    prompt?: string;
  }): Promise<{ result: EvalResult; trajectory: TraceEvent[]; rawSessionFile: string | null }> {
    const { runRoot, environment, family, familyRoot, snapshotPackage, iteration } = options;
    const layout = trainSolverLayout(runRoot, iteration);
    const frozenSkillPackage = await this.prepareTrainSolverWorkspace(
      layout.workspace,
      familyRoot,
      family,
      snapshotPackage,
    );
    const session = await createEvaluatorSession({
      label: `train-solver-iteration-${iteration}`,
      cwd: layout.workspace,
      sessionDir: layout.session,
      systemPrompt: STUDENT_EVALUATOR_SYSTEM,
      model: this.models.student,
      runtime: this.models.runtime,
      config: this.config,
      environment,
      skillPaths: [frozenSkillPackage],
    });
    const variantRoot = path.join(familyRoot, family.train);
    try {
      const loadedSkill = requireLoadedSkill(session, family.name);
      session.trace.takeSegment();
      const beforeTools = session.trace.getToolCallCount();
      session.trace.setPhase(`train-eval-${iteration}`);
      await environment.reset(family.name, family.train, variantRoot, frozenSkillPackage);
      const measured = await withSolverBudget({
        label: `${family.name}/${family.train} clean training evaluation`,
        timeoutMs: this.config.agentSolveTimeoutMs,
        operation: () => promptWithInfrastructureRecovery(session.session,
          options.prompt ?? evaluatePrompt(family.name, family.train, iteration),
          `${family.name}/${family.train} clean training evaluation`),
        stop: async () => { await Promise.allSettled([session.session.abort(), environment.stop()]); },
      });
      reportWorkspaceBoundaryWarnings(
        session,
        `${family.name}/${family.train} clean training evaluation`,
      );
      let tests = measured.timeout;
      if (!tests) {
        environment.assertValid();
        await environment.exportApp(options.artifactsRoot);
        tests = await environment.runTests(await taskTimeout(variantRoot));
        await environment.shell("rm -rf /tests", 60);
      }
      const traceEvents = session.trace.takeSegment();
      const trajectory = feedbackTrajectory(traceEvents);
      const result: EvalResult = {
        family: family.name,
        variant: family.train,
        iteration,
        split: "train",
        tests,
        toolCalls: session.trace.getToolCallCount() - beforeTools,
        ...(measured.completion ? {
          agentAttempts: measured.completion.attempts,
          recoveredFromInterruption: measured.completion.recovered,
        } : {}),
        skillResourceReads: skillResourceReads(traceEvents, family.name),
        skillResourceExecutions: skillResourceExecutions(traceEvents, family.name),
        loadedSkill,
        ...(session.session.sessionFile ? { sessionFile: session.session.sessionFile } : {}),
      };
      await writeJson(layout.trajectory, {
        ...result,
        trajectory,
      });
      return {
        result,
        trajectory,
        rawSessionFile: session.session.sessionFile ?? null,
      };
    } finally {
      await session.dispose();
    }
  }

  private async evaluateHeldout(options: {
    attemptRoot: string;
    environment: TaskEnvironment;
    family: FamilyConfig;
    familyRoot: string;
    variant: string;
    iteration: number;
    snapshotPackage: string;
  }): Promise<EvalResult> {
    const { attemptRoot, environment, family, familyRoot, variant, iteration, snapshotPackage } = options;
    const evalRoot = path.join(attemptRoot, "workspace");
    const sessionDir = path.join(attemptRoot, "session");
    const variantRoot = path.join(familyRoot, variant);
    await mkdir(evalRoot, { recursive: true });
    await cp(path.join(variantRoot, "task.yaml"), path.join(evalRoot, "task.yaml"));
    await copyReplacing(snapshotPackage, path.join(evalRoot, "skill", family.name));
    const session = await createEvaluatorSession({
      label: `heldout-${iteration}-${variant}`,
      cwd: evalRoot,
      sessionDir,
      systemPrompt: STUDENT_EVALUATOR_SYSTEM,
      model: this.models.student,
      runtime: this.models.runtime,
      config: this.config,
      environment,
      skillPaths: [path.join(evalRoot, "skill", family.name)],
    });
    try {
      const loadedSkill = requireLoadedSkill(session, family.name);
      session.trace.takeSegment();
      session.trace.setPhase("heldout-eval");
      await environment.reset(family.name, variant, variantRoot, path.join(evalRoot, "skill", family.name));
      const beforeTools = session.trace.getToolCallCount();
      const measured = await withSolverBudget({
        label: `${family.name}/${variant} heldout evaluation`,
        timeoutMs: this.config.agentSolveTimeoutMs,
        operation: () => promptWithInfrastructureRecovery(session.session,
          evaluatePrompt(family.name, variant, iteration),
          `${family.name}/${variant} heldout evaluation`),
        stop: async () => { await Promise.allSettled([session.session.abort(), environment.stop()]); },
      });
      reportWorkspaceBoundaryWarnings(
        session,
        `${family.name}/${variant} heldout evaluation`,
      );
      let tests = measured.timeout;
      if (!tests) {
        environment.assertValid();
        await environment.exportApp(path.join(attemptRoot, "artifacts"));
        tests = await environment.runTests(await taskTimeout(variantRoot));
        await environment.shell("rm -rf /tests", 60);
      }
      const traceEvents = session.trace.takeSegment();
      const result: EvalResult = {
        family: family.name,
        variant,
        iteration,
        split: "heldout",
        tests,
        toolCalls: session.trace.getToolCallCount() - beforeTools,
        ...(measured.completion ? {
          agentAttempts: measured.completion.attempts,
          recoveredFromInterruption: measured.completion.recovered,
        } : {}),
        skillResourceReads: skillResourceReads(traceEvents, family.name),
        skillResourceExecutions: skillResourceExecutions(traceEvents, family.name),
        loadedSkill,
        ...(session.session.sessionFile ? { sessionFile: session.session.sessionFile } : {}),
      };
      await writeJson(path.join(attemptRoot, "result.json"), result);
      return result;
    } finally {
      await session.dispose();
    }
  }
}
