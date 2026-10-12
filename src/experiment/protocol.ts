import type {
  ExperimentCell,
  Mode,
  ModelTier,
  ObservationWindow,
  ProviderConfig,
} from "./types.js";
import {
  LEARNING_LOOP_SIGNAL_TYPES,
  TRACE_SIGNAL_TYPES,
  TRACE_TREE_MAXIMUM_GAP,
  TRACE_TREE_MINIMUM_GAP,
} from "../agent/trace-tree.js";

const CELLS: Record<Mode, ExperimentCell> = {
  "plus-compile-after": {
    id: "plus-compile-after",
    capabilitySourceTier: "plus",
    protocol: "compile-after",
    authorModelTier: "plus",
    educatorModelTier: null,
    targetStudentTier: "plus",
    guidedPracticeInteraction: null,
    observationPolicy: "none",
    observationWindow: null,
  },
  "max-compile-after": {
    id: "max-compile-after",
    capabilitySourceTier: "max",
    protocol: "compile-after",
    authorModelTier: "max",
    educatorModelTier: null,
    targetStudentTier: "plus",
    guidedPracticeInteraction: null,
    observationPolicy: "none",
    observationWindow: null,
  },
  "plus-teach-after": {
    id: "plus-teach-after",
    capabilitySourceTier: "plus",
    protocol: "teach-after",
    authorModelTier: "plus",
    educatorModelTier: "plus",
    targetStudentTier: "plus",
    guidedPracticeInteraction: null,
    observationPolicy: "none",
    observationWindow: null,
  },
  "max-teach-after": {
    id: "max-teach-after",
    capabilitySourceTier: "max",
    protocol: "teach-after",
    authorModelTier: "plus",
    educatorModelTier: "max",
    targetStudentTier: "plus",
    guidedPracticeInteraction: null,
    observationPolicy: "none",
    observationWindow: null,
  },
  "plus-develop-along": {
    id: "plus-develop-along",
    capabilitySourceTier: "plus",
    protocol: "develop-along",
    authorModelTier: "plus",
    educatorModelTier: "plus",
    targetStudentTier: "plus",
    guidedPracticeInteraction: null,
    observationPolicy: "fixed",
    observationWindow: 10,
  },
  "max-develop-along": {
    id: "max-develop-along",
    capabilitySourceTier: "max",
    protocol: "develop-along",
    authorModelTier: "plus",
    educatorModelTier: "max",
    targetStudentTier: "plus",
    guidedPracticeInteraction: null,
    observationPolicy: "fixed",
    observationWindow: 10,
  },
  "max-guided-one-way": {
    id: "max-guided-one-way",
    capabilitySourceTier: "max",
    protocol: "develop-along",
    authorModelTier: "plus",
    educatorModelTier: "max",
    targetStudentTier: "plus",
    guidedPracticeInteraction: "one-way",
    observationPolicy: "fixed",
    observationWindow: 10,
  },
  "max-guided-dialogue": {
    id: "max-guided-dialogue",
    capabilitySourceTier: "max",
    protocol: "develop-along",
    authorModelTier: "plus",
    educatorModelTier: "max",
    targetStudentTier: "plus",
    guidedPracticeInteraction: "reciprocal",
    observationPolicy: "fixed",
    observationWindow: 10,
  },
  "develop-g5": {
    id: "develop-g5",
    capabilitySourceTier: "max",
    protocol: "develop-along",
    authorModelTier: "plus",
    educatorModelTier: "max",
    targetStudentTier: "plus",
    guidedPracticeInteraction: "reciprocal",
    observationPolicy: "fixed",
    observationWindow: 5,
  },
  "develop-g10": {
    id: "develop-g10",
    capabilitySourceTier: "max",
    protocol: "develop-along",
    authorModelTier: "plus",
    educatorModelTier: "max",
    targetStudentTier: "plus",
    guidedPracticeInteraction: "reciprocal",
    observationPolicy: "fixed",
    observationWindow: 10,
  },
  "develop-g20": {
    id: "develop-g20",
    capabilitySourceTier: "max",
    protocol: "develop-along",
    authorModelTier: "plus",
    educatorModelTier: "max",
    targetStudentTier: "plus",
    guidedPracticeInteraction: "reciprocal",
    observationPolicy: "fixed",
    observationWindow: 20,
  },
  "develop-trajectory": {
    id: "develop-trajectory",
    capabilitySourceTier: "max",
    protocol: "develop-along",
    authorModelTier: "plus",
    educatorModelTier: "max",
    targetStudentTier: "plus",
    guidedPracticeInteraction: "reciprocal",
    observationPolicy: "fixed",
    observationWindow: "trajectory-end",
  },
  "develop-adaptive": {
    id: "develop-adaptive",
    capabilitySourceTier: "max",
    protocol: "develop-along",
    authorModelTier: "plus",
    educatorModelTier: "max",
    targetStudentTier: "plus",
    guidedPracticeInteraction: "reciprocal",
    observationPolicy: "adaptive",
    observationWindow: 10,
  },
  "develop-adaptive-horizon-only": {
    id: "develop-adaptive-horizon-only",
    capabilitySourceTier: "max",
    protocol: "develop-along",
    authorModelTier: "plus",
    educatorModelTier: "max",
    targetStudentTier: "plus",
    guidedPracticeInteraction: "reciprocal",
    observationPolicy: "adaptive-horizon-only",
    observationWindow: 10,
  },
  "develop-learning-frontier": {
    id: "develop-learning-frontier",
    capabilitySourceTier: "max",
    protocol: "develop-along",
    authorModelTier: "plus",
    educatorModelTier: "max",
    targetStudentTier: "plus",
    guidedPracticeInteraction: "reciprocal",
    observationPolicy: "learning-frontier",
    observationWindow: 10,
  },
  "develop-tree-triggered": {
    id: "develop-tree-triggered",
    capabilitySourceTier: "max",
    protocol: "develop-along",
    authorModelTier: "plus",
    educatorModelTier: "max",
    targetStudentTier: "plus",
    guidedPracticeInteraction: "reciprocal",
    observationPolicy: "trace-tree",
    observationWindow: TRACE_TREE_MAXIMUM_GAP,
  },
  "develop-learning-loop-triggered": {
    id: "develop-learning-loop-triggered",
    capabilitySourceTier: "max",
    protocol: "develop-along",
    authorModelTier: "plus",
    educatorModelTier: "max",
    targetStudentTier: "plus",
    guidedPracticeInteraction: "reciprocal",
    observationPolicy: "learning-loop",
    observationWindow: TRACE_TREE_MAXIMUM_GAP,
  },
  "develop-learning-delta": {
    id: "develop-learning-delta",
    capabilitySourceTier: "max",
    protocol: "develop-along",
    authorModelTier: "plus",
    educatorModelTier: "max",
    targetStudentTier: "plus",
    guidedPracticeInteraction: "learning-delta",
    observationPolicy: "learning-delta",
    // The only elapsed-step trigger is the one-time iteration-1 bootstrap.
    observationWindow: 10,
  },
  "develop-tree-learning-delta": {
    id: "develop-tree-learning-delta",
    capabilitySourceTier: "max",
    protocol: "develop-along",
    authorModelTier: "plus",
    educatorModelTier: "max",
    targetStudentTier: "plus",
    guidedPracticeInteraction: "learning-delta",
    observationPolicy: "tree-learning-delta",
    // Elapsed tools are used only for the one-time bootstrap. Thereafter the
    // Learning-Issue Tree frontier decides whether a knowledge delta warrants
    // another Teacher turn.
    observationWindow: 10,
  },
};

export function experimentCell(mode: Mode): ExperimentCell {
  return CELLS[mode];
}

export function hasEducator(mode: Mode): boolean {
  return CELLS[mode].educatorModelTier !== null;
}

export function isDevelopAlong(mode: Mode): boolean {
  return CELLS[mode].protocol === "develop-along";
}

export function isGuidedDialogue(mode: Mode): boolean {
  return CELLS[mode].guidedPracticeInteraction === "reciprocal";
}

export function isAdaptiveHorizon(mode: Mode): boolean {
  return CELLS[mode].observationPolicy === "adaptive"
    || CELLS[mode].observationPolicy === "adaptive-horizon-only"
    || CELLS[mode].observationPolicy === "learning-frontier";
}

export function hasAdaptiveWakeConditions(mode: Mode): boolean {
  return CELLS[mode].observationPolicy === "adaptive";
}

export function isTraceTreeTriggered(mode: Mode): boolean {
  return CELLS[mode].observationPolicy === "trace-tree";
}

export function isLearningLoopTriggered(mode: Mode): boolean {
  return CELLS[mode].observationPolicy === "learning-loop";
}

export function isLearningDeltaTriggered(mode: Mode): boolean {
  return CELLS[mode].observationPolicy === "learning-delta"
    || CELLS[mode].observationPolicy === "tree-learning-delta";
}

export function isTreeLearningDelta(mode: Mode): boolean {
  return CELLS[mode].observationPolicy === "tree-learning-delta";
}

export function usesLearningStateTrace(mode: Mode): boolean {
  return isTraceTreeTriggered(mode)
    || isLearningLoopTriggered(mode)
    || isLearningDeltaTriggered(mode);
}

export function isGuidedPractice(mode: Mode): boolean {
  return CELLS[mode].guidedPracticeInteraction !== null;
}

export function isGuidedOneWay(mode: Mode): boolean {
  return CELLS[mode].guidedPracticeInteraction === "one-way";
}

export function observationWindowFor(mode: Mode): ObservationWindow {
  const cell = CELLS[mode];
  if (cell.protocol !== "develop-along" || cell.observationWindow === null) {
    throw new Error(`${mode} is not a Develop-Along observation-window cell`);
  }
  return cell.observationWindow;
}

export function modelForTier<T>(tier: ModelTier, models: { student: T; teacher: T }): T {
  return tier === "plus" ? models.student : models.teacher;
}

export function sessionTopology(
  cell: ExperimentCell,
  provider: ProviderConfig,
): Record<string, unknown> {
  const modelFor = (tier: ModelTier) =>
    tier === "plus" ? provider.studentModel : provider.teacherModel;
  return {
    author: {
      identity: cell.protocol === "compile-after" ? "direct-author" : "student-author",
      model: modelFor(cell.authorModelTier),
      continuousAcrossIterations: true,
      ownsSkillPackage: true,
    },
    educator: cell.educatorModelTier
      ? {
          identity: "educator",
          model: modelFor(cell.educatorModelTier),
          continuousAcrossIterations: true,
          readOnlySkillPackage: true,
          interventionTiming: cell.protocol === "teach-after"
            || cell.observationWindow === "trajectory-end"
            ? "after-complete-authoring-trajectory"
            : "bounded-windows-during-authoring",
          interaction: cell.guidedPracticeInteraction === "reciprocal"
            ? "natural-lesson-student-response-optional-teacher-follow-up"
            : cell.guidedPracticeInteraction === "learning-delta"
              ? "student-response-with-next-teacher-turn-only-on-new-learning-delta"
            : cell.guidedPracticeInteraction === "one-way"
              ? "one-way-lesson-without-adaptive-teacher-follow-up"
              : "single-lesson",
          observationWindow: cell.protocol === "develop-along"
            ? cell.observationWindow
            : null,
          observationPolicy: cell.observationPolicy,
          ...(cell.observationPolicy === "adaptive"
            || cell.observationPolicy === "adaptive-horizon-only"
            || cell.observationPolicy === "learning-frontier"
            ? {
                allowedObservationWindows: [5, 10, 20],
              }
            : {}),
          ...(cell.observationPolicy === "adaptive"
            ? {
                wakeConditionCatalog: [
                  "tool_error",
                  "command_nonzero_exit",
                  "command_timeout",
                  "repeated_failure(count=2|3)",
                  "skill_package_changed",
                  "tool_call(tool)",
                ],
                wakeConditionsSelectedBy: "educator",
              }
            : {}),
          ...(cell.observationPolicy === "learning-frontier"
            ? {
                learningFrontierSchedule: {
                  verification_pending: 5,
                  active_learning: 10,
                  consolidated: 20,
                },
                rawHorizonSelectedByEducator: false,
              }
            : {}),
          ...(cell.observationPolicy === "trace-tree" || cell.observationPolicy === "learning-loop"
            ? {
                traceRepresentation: cell.observationPolicy === "learning-loop"
                  ? "rule-built-task-skill-and-pedagogical-loop-tree"
                  : "rule-built-task-and-skill-state-tree",
                triggerPolicy: {
                  selectedBy: "runtime",
                  minimumToolGap: TRACE_TREE_MINIMUM_GAP,
                  maximumToolGap: TRACE_TREE_MAXIMUM_GAP,
                  signals: cell.observationPolicy === "learning-loop"
                    ? [...TRACE_SIGNAL_TYPES, ...LEARNING_LOOP_SIGNAL_TYPES]
                    : [...TRACE_SIGNAL_TYPES],
                },
                ...(cell.observationPolicy === "learning-loop"
                  ? {
                      pedagogicalLoop: "lesson-uptake-skill-revision-verification",
                      lessonLoopSelectedBy: "runtime",
                    }
                  : {}),
              }
            : {}),
          ...(cell.observationPolicy === "learning-delta"
            || cell.observationPolicy === "tree-learning-delta"
            ? {
                traceRepresentation: cell.observationPolicy === "tree-learning-delta"
                  ? "persistent-learning-issue-tree-with-rule-built-evidence-lineage"
                  : "rule-built-evidence-lineage-tree",
                triggerPolicy: {
                  selectedBy: "runtime",
                  events: [
                    "iteration-1-bootstrap",
                    cell.observationPolicy === "tree-learning-delta"
                      ? "unresolved-learning-issue-transition"
                      : "student-skill-revision-commit",
                    "prior-clean-evaluator-contradiction",
                  ],
                  periodicFallback: false,
                  ...(cell.observationPolicy === "tree-learning-delta"
                    ? {
                        groundedClosure:
                          "A changed Student package resolves the addressed issue through an evidence-backed verified, bounded, or rejected disposition",
                      }
                    : {}),
                },
              }
            : {}),
        }
      : null,
    trainSolver: {
      identity: "train-solver",
      model: provider.studentModel,
      freshPerIteration: true,
      workspacePerIteration: true,
      distinctFromAuthor: true,
      frozenSkillPackage: true,
    },
    heldoutSolver: {
      identity: "student-heldout-solver",
      model: provider.studentModel,
      freshPerVariant: true,
      frozenSkillPackage: true,
    },
  };
}
