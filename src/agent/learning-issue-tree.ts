import type {
  EducationCheckpoint,
  LearningIssueCommit,
  LearningIssueLesson,
} from "../experiment/types.js";

export const LEARNING_ISSUE_TREE_VERSION = "learning-issue-tree-v1" as const;
export const LEARNING_ISSUE_LOCAL_VIEW_LIMIT = 2_500;

export type LearningIssueStatus =
  | "active_learning"
  | "verification_pending"
  | "consolidated"
  | "contradicted";

export type LearningIssueTransition = "opened" | "updated" | "reopened";

export interface LearningIssueRevision {
  iteration: number;
  toolOrdinal: number;
  packageSha256: string | null;
  changedPaths: string[];
  summary: string;
  evidence: string;
  explicitCommit: boolean;
  issueResolution?: "verified" | "bounded" | "rejected";
  successfulPostLessonVerification: boolean;
}

export interface LearningIssueNode {
  id: string;
  parentId: string | null;
  childIds: string[];
  status: LearningIssueStatus;
  focus: string;
  acceptanceCriterion: string | null;
  openedAt: {
    iteration: number;
    toolOrdinal: number;
    trigger: EducationCheckpoint["trigger"];
  };
  revisions: LearningIssueRevision[];
  observations: Array<{
    iteration: number;
    toolOrdinal: number;
    trigger: EducationCheckpoint["trigger"];
    note: string;
  }>;
  lessons: Array<{
    checkpoint: number;
    lessonId: string;
    focus: string;
    acceptanceCriterion: string;
  }>;
  studentResponses: Array<{
    checkpoint: number;
    iteration: number;
    toolOrdinal: number;
    text: string;
  }>;
  resolvedAt: {
    iteration: number;
    toolOrdinal: number;
    reason:
      | "teacher-silence"
      | "verified-student-assimilation"
      | "evidence-bounded-assimilation"
      | "evidence-backed-rejection";
  } | null;
  reopenCount: number;
}

export interface LearningIssueTreeSnapshot {
  version: typeof LEARNING_ISSUE_TREE_VERSION;
  semantics: "node-is-falsifiable-learning-issue";
  activeIssueId: string | null;
  rootIds: string[];
  nodes: LearningIssueNode[];
  events: Array<{
    sequence: number;
    kind:
      | "open"
      | "update"
      | "teach"
      | "silence-resolve"
      | "verified-resolve"
      | "bounded-resolve"
      | "rejected-resolve"
      | "reopen"
      | "student-response";
    nodeId: string;
    iteration: number;
    toolOrdinal: number;
    detail: string;
  }>;
}

export interface LearningIssueCheckpointInput {
  trigger: EducationCheckpoint["trigger"];
  iteration: number;
  toolOrdinal: number;
  packageSha256: string | null;
  changedPaths: string[];
  explicitCommit: boolean;
  commit?: LearningIssueCommit;
  successfulPostLessonVerification: boolean;
}

export interface LearningIssueCheckpointDecision {
  checkpointRequired: boolean;
  transition:
    | LearningIssueTransition
    | "verified-closure"
    | "bounded-closure"
    | "rejected-closure";
  node: LearningIssueNode;
}

function clipped(value: string, limit: number): string {
  const compact = value.replace(/\s+/g, " ").trim();
  return compact.length > limit ? `${compact.slice(0, limit)}…` : compact;
}

function cloneNode(node: LearningIssueNode): LearningIssueNode {
  return {
    ...node,
    childIds: [...node.childIds],
    openedAt: { ...node.openedAt },
    revisions: node.revisions.map((revision) => ({
      ...revision,
      changedPaths: [...revision.changedPaths],
    })),
    observations: node.observations.map((observation) => ({ ...observation })),
    lessons: node.lessons.map((lesson) => ({ ...lesson })),
    studentResponses: node.studentResponses.map((response) => ({ ...response })),
    resolvedAt: node.resolvedAt ? { ...node.resolvedAt } : null,
  };
}

/**
 * Persistent semantic memory for Tree-Structured Learning Delta.
 *
 * The class deliberately does not inspect model prose or choose lessons. It
 * maps explicit Student knowledge revisions and independent evaluator
 * contradictions onto a small issue tree. Only unresolved/reopened frontier
 * transitions request Teacher work. A Student-authored package revision can
 * close the active issue without redundant review only through an explicit,
 * evidence-bearing disposition: verified, bounded, or rejected.
 */
export class LearningIssueTree {
  private counter = 0;
  private eventCounter = 0;
  private activeIssueId: string | null = null;
  private readonly rootIds: string[] = [];
  private readonly nodes: LearningIssueNode[] = [];
  private readonly byId = new Map<string, LearningIssueNode>();
  private readonly packageOwner = new Map<string, string>();
  private readonly events: LearningIssueTreeSnapshot["events"] = [];

  observeCheckpoint(input: LearningIssueCheckpointInput): LearningIssueCheckpointDecision {
    const addressed = input.commit?.addressesIssueId
      ? this.byId.get(input.commit.addressesIssueId)
      : undefined;
    const active = this.activeIssue();

    const declaredResolution = input.commit?.issueResolution;
    const hasChangedPackage = input.changedPaths.length > 0;
    const verifiedClosure = declaredResolution === "verified"
      && input.successfulPostLessonVerification;
    const reasonedClosure = declaredResolution === "bounded"
      || declaredResolution === "rejected";
    if (
      input.trigger === "skill-commit"
      && active
      && addressed?.id === active.id
      && hasChangedPackage
      && (verifiedClosure || reasonedClosure)
    ) {
      const revision = this.revision(input);
      active.revisions.push(revision);
      active.status = "consolidated";
      const reason = declaredResolution === "verified"
        ? "verified-student-assimilation"
        : declaredResolution === "bounded"
          ? "evidence-bounded-assimilation"
          : "evidence-backed-rejection";
      const eventKind = declaredResolution === "verified"
        ? "verified-resolve"
        : declaredResolution === "bounded"
          ? "bounded-resolve"
          : "rejected-resolve";
      const transition = declaredResolution === "verified"
        ? "verified-closure"
        : declaredResolution === "bounded"
          ? "bounded-closure"
          : "rejected-closure";
      active.resolvedAt = {
        iteration: input.iteration,
        toolOrdinal: input.toolOrdinal,
        reason,
      };
      this.rememberPackage(input.packageSha256, active.id);
      this.record(eventKind, active, input, revision.evidence);
      this.resumeNearestUnresolvedParent(active);
      return {
        checkpointRequired: false,
        transition,
        node: cloneNode(active),
      };
    }

    if (input.trigger === "evaluator-contradiction") {
      const packageNode = input.packageSha256
        ? this.byId.get(this.packageOwner.get(input.packageSha256) ?? "")
        : undefined;
      const node = packageNode ?? active ?? this.openNode(input, null);
      const transition: LearningIssueTransition = node.status === "consolidated"
        ? "reopened"
        : "updated";
      node.status = "contradicted";
      node.resolvedAt = null;
      if (transition === "reopened") node.reopenCount += 1;
      node.observations.push({
        iteration: input.iteration,
        toolOrdinal: input.toolOrdinal,
        trigger: input.trigger,
        note: "A fresh clean-v01 evaluator contradicted the package associated with this issue.",
      });
      this.activeIssueId = node.id;
      this.record(transition === "reopened" ? "reopen" : "update", node, input, "fresh evaluator contradiction");
      return { checkpointRequired: true, transition, node: cloneNode(node) };
    }

    if (addressed && addressed.status !== "consolidated") {
      addressed.revisions.push(this.revision(input));
      addressed.status = "verification_pending";
      addressed.observations.push({
        iteration: input.iteration,
        toolOrdinal: input.toolOrdinal,
        trigger: input.trigger,
        note: input.commit?.evidence ?? "Student revised the active issue without closure evidence.",
      });
      this.activeIssueId = addressed.id;
      this.rememberPackage(input.packageSha256, addressed.id);
      this.record("update", addressed, input, input.commit?.summary ?? "package revision");
      return { checkpointRequired: true, transition: "updated", node: cloneNode(addressed) };
    }

    const parentId = active?.id ?? null;
    const node = this.openNode(input, parentId);
    return { checkpointRequired: true, transition: "opened", node: cloneNode(node) };
  }

  applyTeacherDecision(input: {
    nodeId: string;
    checkpoint: number;
    iteration: number;
    toolOrdinal: number;
    lessonId?: string;
    lesson?: LearningIssueLesson;
  }): LearningIssueNode {
    const node = this.requiredNode(input.nodeId);
    if (input.lesson && input.lessonId) {
      node.focus = clipped(input.lesson.focus, 400);
      node.acceptanceCriterion = clipped(input.lesson.acceptanceCriterion, 600);
      node.status = "verification_pending";
      node.resolvedAt = null;
      node.lessons.push({
        checkpoint: input.checkpoint,
        lessonId: input.lessonId,
        focus: node.focus,
        acceptanceCriterion: node.acceptanceCriterion,
      });
      this.activeIssueId = node.id;
      this.recordRaw("teach", node.id, input.iteration, input.toolOrdinal, node.acceptanceCriterion);
    } else {
      node.status = "consolidated";
      node.resolvedAt = {
        iteration: input.iteration,
        toolOrdinal: input.toolOrdinal,
        reason: "teacher-silence",
      };
      this.recordRaw("silence-resolve", node.id, input.iteration, input.toolOrdinal, "Teacher found no material unresolved learning delta.");
      this.resumeNearestUnresolvedParent(node);
    }
    return cloneNode(node);
  }

  noteStudentResponse(
    nodeId: string,
    checkpoint: number,
    iteration: number,
    toolOrdinal: number,
    text: string,
  ): void {
    const node = this.byId.get(nodeId);
    if (!node) return;
    node.studentResponses.push({
      checkpoint,
      iteration,
      toolOrdinal,
      text: clipped(text, 800),
    });
    this.recordRaw("student-response", node.id, iteration, toolOrdinal, text);
  }

  activeIssue(): LearningIssueNode | undefined {
    return this.activeIssueId ? this.byId.get(this.activeIssueId) : undefined;
  }

  localView(): Record<string, unknown> {
    const active = this.activeIssue();
    const path: LearningIssueNode[] = [];
    let cursor = active;
    while (cursor) {
      path.push(cursor);
      cursor = cursor.parentId ? this.byId.get(cursor.parentId) : undefined;
    }
    path.reverse();
    const recentlyResolved = this.nodes
      .filter((node) => node.status === "consolidated")
      .slice(-2)
      .map((node) => ({ id: node.id, focus: clipped(node.focus, 180), reason: node.resolvedAt?.reason }));
    const view = {
      version: LEARNING_ISSUE_TREE_VERSION,
      semantics: "node-is-falsifiable-learning-issue",
      activeIssueId: active?.id ?? null,
      activePath: path.slice(-3).map((node) => ({
        id: node.id,
        parentId: node.parentId,
        status: node.status,
        focus: clipped(node.focus, 240),
        acceptanceCriterion: node.acceptanceCriterion
          ? clipped(node.acceptanceCriterion, 300)
          : null,
        latestRevision: node.revisions.at(-1)
          ? {
              summary: clipped(node.revisions.at(-1)!.summary, 220),
              evidence: clipped(node.revisions.at(-1)!.evidence, 260),
              changedPaths: node.revisions.at(-1)!.changedPaths.slice(0, 8),
              issueResolution: node.revisions.at(-1)!.issueResolution ?? null,
              successfulPostLessonVerification:
                node.revisions.at(-1)!.successfulPostLessonVerification,
            }
          : null,
      })),
      recentlyResolved,
    };
    const rendered = JSON.stringify(view);
    if (rendered.length > LEARNING_ISSUE_LOCAL_VIEW_LIMIT) {
      return {
        version: LEARNING_ISSUE_TREE_VERSION,
        semantics: "node-is-falsifiable-learning-issue",
        activeIssueId: active?.id ?? null,
        activePath: path.slice(-2).map((node) => ({
          id: node.id,
          parentId: node.parentId,
          status: node.status,
          focus: clipped(node.focus, 180),
          acceptanceCriterion: node.acceptanceCriterion
            ? clipped(node.acceptanceCriterion, 220)
            : null,
        })),
      };
    }
    return view;
  }

  snapshot(): LearningIssueTreeSnapshot {
    return {
      version: LEARNING_ISSUE_TREE_VERSION,
      semantics: "node-is-falsifiable-learning-issue",
      activeIssueId: this.activeIssueId,
      rootIds: [...this.rootIds],
      nodes: this.nodes.map(cloneNode),
      events: this.events.map((event) => ({ ...event })),
    };
  }

  private openNode(input: LearningIssueCheckpointInput, parentId: string | null): LearningIssueNode {
    this.counter += 1;
    const revision = this.revision(input);
    const node: LearningIssueNode = {
      id: `issue-${this.counter}`,
      parentId,
      childIds: [],
      status: "active_learning",
      focus: clipped(
        input.commit?.summary
          ?? (input.trigger === "bootstrap"
            ? "Build the initial reusable family representation."
            : "Diagnose the current reusable Skill revision."),
        400,
      ),
      acceptanceCriterion: null,
      openedAt: {
        iteration: input.iteration,
        toolOrdinal: input.toolOrdinal,
        trigger: input.trigger,
      },
      revisions: input.changedPaths.length > 0 || input.commit ? [revision] : [],
      observations: [],
      lessons: [],
      studentResponses: [],
      resolvedAt: null,
      reopenCount: 0,
    };
    this.nodes.push(node);
    this.byId.set(node.id, node);
    if (parentId) this.requiredNode(parentId).childIds.push(node.id);
    else this.rootIds.push(node.id);
    this.activeIssueId = node.id;
    this.rememberPackage(input.packageSha256, node.id);
    this.record("open", node, input, revision.summary);
    return node;
  }

  private revision(input: LearningIssueCheckpointInput): LearningIssueRevision {
    return {
      iteration: input.iteration,
      toolOrdinal: input.toolOrdinal,
      packageSha256: input.packageSha256,
      changedPaths: [...input.changedPaths],
      summary: clipped(input.commit?.summary ?? "Implicit complete-package revision.", 500),
      evidence: clipped(input.commit?.evidence ?? "No explicit Student evidence declaration.", 800),
      explicitCommit: input.explicitCommit,
      ...(input.commit?.issueResolution
        ? { issueResolution: input.commit.issueResolution }
        : {}),
      successfulPostLessonVerification: input.successfulPostLessonVerification,
    };
  }

  private resumeNearestUnresolvedParent(node: LearningIssueNode): void {
    let parent = node.parentId ? this.byId.get(node.parentId) : undefined;
    while (parent?.status === "consolidated") {
      parent = parent.parentId ? this.byId.get(parent.parentId) : undefined;
    }
    this.activeIssueId = parent?.id ?? null;
  }

  private rememberPackage(packageSha256: string | null, nodeId: string): void {
    if (packageSha256) this.packageOwner.set(packageSha256, nodeId);
  }

  private requiredNode(nodeId: string): LearningIssueNode {
    const node = this.byId.get(nodeId);
    if (!node) throw new Error(`Unknown learning issue ${nodeId}`);
    return node;
  }

  private record(
    kind: LearningIssueTreeSnapshot["events"][number]["kind"],
    node: LearningIssueNode,
    input: LearningIssueCheckpointInput,
    detail: string,
  ): void {
    this.recordRaw(kind, node.id, input.iteration, input.toolOrdinal, detail);
  }

  private recordRaw(
    kind: LearningIssueTreeSnapshot["events"][number]["kind"],
    nodeId: string,
    iteration: number,
    toolOrdinal: number,
    detail: string,
  ): void {
    this.eventCounter += 1;
    this.events.push({
      sequence: this.eventCounter,
      kind,
      nodeId,
      iteration,
      toolOrdinal,
      detail: clipped(detail, 800),
    });
  }
}
