import type { Mode } from "./experiment/types.js";

/** Public method names, matching the method directories in experiments/. */
export const METHOD_NAMES = [
  "expert-authoring",
  "post-hoc-teaching",
  "fixed-window-ssl",
  "issue-guided-ssl",
  "no-skill",
  "trace2skill",
  "skill-kd",
] as const;

export type MethodName = (typeof METHOD_NAMES)[number];

export const METHOD_LABELS: Record<MethodName, string> = {
  "expert-authoring": "Expert Authoring",
  "post-hoc-teaching": "Post-hoc Teaching",
  "fixed-window-ssl": "Fixed-Window SSL",
  "issue-guided-ssl": "Issue-Guided SSL",
  "no-skill": "No Skill",
  trace2skill: "Trace2Skill",
  "skill-kd": "SKILL-KD",
};

/** Older commands and downloaded trajectory archives remain readable. */
export const LEGACY_METHOD_ALIASES = {
  "compile-after": "expert-authoring",
  "teach-after": "post-hoc-teaching",
  ist: "fixed-window-ssl",
  issueist: "issue-guided-ssl",
} as const satisfies Record<string, MethodName>;

export function canonicalMethod(name: string): MethodName {
  if ((METHOD_NAMES as readonly string[]).includes(name)) return name as MethodName;
  const alias = Object.entries(LEGACY_METHOD_ALIASES).find(([legacy]) => legacy === name);
  if (alias) return alias[1];
  throw new Error(`Unknown method ${name}; expected one of ${METHOD_NAMES.join(", ")}`);
}

/** Prefer current directory names; fall back to a pre-renaming archive. */
export function methodDirectoryNames(method: MethodName): string[] {
  return [method, ...Object.entries(LEGACY_METHOD_ALIASES)
    .filter(([, canonical]) => canonical === method).map(([legacy]) => legacy)];
}

/** Methods whose acquisition runs through RunOrchestrator.run(). */
export const ORCHESTRATED_METHODS: readonly MethodName[] = [
  "expert-authoring",
  "post-hoc-teaching",
  "fixed-window-ssl",
  "issue-guided-ssl",
];

const METHOD_TO_MODE: Record<Exclude<MethodName, "no-skill" | "trace2skill" | "skill-kd">, Mode> = {
  "expert-authoring": "max-compile-after",
  "post-hoc-teaching": "max-teach-after",
  "fixed-window-ssl": "max-guided-dialogue",
  "issue-guided-ssl": "develop-tree-learning-delta",
};

export function methodForMode(mode: string): MethodName | undefined {
  return ORCHESTRATED_METHODS.find((method) => modeForMethod(method) === mode);
}

/** Methods runnable through `ssl run|acquire|evaluate` (the default when
 *  --methods is omitted); trace2skill and skill-kd have their own pipelines. */
export const RUNNABLE_METHODS: readonly MethodName[] = [
  ...ORCHESTRATED_METHODS,
  "no-skill",
] as const;

export function parseMethods(value: string | undefined): MethodName[] {
  const names = (value?.split(",") ?? [...RUNNABLE_METHODS])
    .map((item) => item.trim()).filter(Boolean).map(canonicalMethod);
  if (names.length === 0) throw new Error("--methods cannot be empty");
  const seen = new Set<string>();
  for (const name of names) {
    if (seen.has(name)) throw new Error(`Duplicate method ${name}`);
    seen.add(name);
  }
  return names;
}

export function modeForMethod(method: MethodName): Mode {
  const mode = METHOD_TO_MODE[method as keyof typeof METHOD_TO_MODE];
  if (!mode) throw new Error(`Method ${method} is not orchestrated by RunOrchestrator`);
  return mode;
}
