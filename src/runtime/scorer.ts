import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";

export type ScorerStrategy = "source-runner" | "system-pytest";
export type TestLayout = "flat" | "runner-tests-subdir";

interface SourceRunnerPolicy {
  strategy: "source-runner";
  testLayout: TestLayout;
  immutableInputs?: string[];
  testTarget?: never;
  pytestVersion?: never;
  rationale?: never;
}

interface SystemPytestPolicy {
  strategy: "system-pytest";
  testLayout: "flat";
  immutableInputs?: string[];
  testTarget: string;
  pytestVersion: string;
  rationale: string;
}

type ScorerManifestEntry = (SourceRunnerPolicy | SystemPytestPolicy) & {
  runnerSha256: string;
};

export type ScorerPlan = ScorerManifestEntry & {
  key: string;
  manifestPath: string;
};

function sha256(value: string | Buffer): string {
  return createHash("sha256").update(value).digest("hex");
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function assertSafeTarget(value: string, label: string): void {
  const pieces = value.split(/[\\/]/);
  if (!value || path.isAbsolute(value) || pieces.includes("..") || pieces.includes(".")) {
    throw new Error(`${label} must be a non-empty package-relative path`);
  }
}

function parseManifestEntry(raw: unknown, key: string): ScorerManifestEntry {
  if (!isRecord(raw)) throw new Error(`Invalid scorer entry for ${key}`);
  const strategy = raw.strategy;
  const testLayout = raw.testLayout;
  if (strategy !== "source-runner" && strategy !== "system-pytest") {
    throw new Error(`Invalid scorer strategy for ${key}`);
  }
  if (testLayout !== "flat" && testLayout !== "runner-tests-subdir") {
    throw new Error(`Invalid test layout for ${key}`);
  }
  const runnerSha256 = raw.runnerSha256;
  if (typeof runnerSha256 !== "string" || !/^[a-f0-9]{64}$/.test(runnerSha256)) {
    throw new Error(`Missing or invalid runner hash for ${key}`);
  }
  const immutableInputs = raw.immutableInputs;
  if (
    immutableInputs !== undefined
    && (
      !Array.isArray(immutableInputs)
      || immutableInputs.some((input) => typeof input !== "string")
    )
  ) {
    throw new Error(`${key}.immutableInputs must be an array of package-relative paths`);
  }
  const resolvedImmutableInputs = immutableInputs as string[] | undefined;
  if (resolvedImmutableInputs) {
    const unique = new Set<string>();
    for (const input of resolvedImmutableInputs) {
      assertSafeTarget(input, `${key}.immutableInputs`);
      if (unique.has(input)) throw new Error(`${key}.immutableInputs contains duplicate ${input}`);
      unique.add(input);
    }
  }

  if (strategy === "source-runner") {
    return {
      strategy,
      testLayout,
      ...(resolvedImmutableInputs?.length ? { immutableInputs: resolvedImmutableInputs } : {}),
      runnerSha256,
    };
  }
  if (testLayout !== "flat") {
    throw new Error(`system-pytest scorer ${key} must use the flat test layout`);
  }
  const { testTarget, pytestVersion, rationale } = raw;
  if (
    typeof testTarget !== "string"
    || typeof pytestVersion !== "string"
    || typeof rationale !== "string"
    || !rationale.trim()
  ) {
    throw new Error(`Incomplete system-pytest scorer for ${key}`);
  }
  assertSafeTarget(testTarget, `${key}.testTarget`);
  return {
    strategy,
    testLayout,
    ...(resolvedImmutableInputs?.length ? { immutableInputs: resolvedImmutableInputs } : {}),
    testTarget,
    pytestVersion,
    rationale,
    runnerSha256,
  };
}

export async function loadScorerPlan(variantRoot: string): Promise<ScorerPlan> {
  const resolvedVariant = path.resolve(variantRoot);
  const assetRoot = path.dirname(path.dirname(resolvedVariant));
  const familyDirectory = path.basename(path.dirname(resolvedVariant));
  const variant = path.basename(resolvedVariant);
  const key = `${familyDirectory}/${variant}`;
  const manifestPath = path.join(assetRoot, "scorer-manifest.json");
  const raw = JSON.parse(await readFile(manifestPath, "utf8")) as unknown;
  if (!isRecord(raw) || raw.schemaVersion !== 2 || !isRecord(raw.scorers)) {
    throw new Error(`Invalid scorer manifest: ${manifestPath}`);
  }
  // Bench directories drop the legacy "family-" prefix; accept either key form.
  const entry = raw.scorers[key] ?? raw.scorers[`family-${key}`];
  if (!entry) throw new Error(`Scorer manifest has no explicit contract for ${key}`);
  const plan = parseManifestEntry(entry, key);
  const runner = await readFile(path.join(resolvedVariant, "run-tests.sh"));
  if (sha256(runner) !== plan.runnerSha256) {
    throw new Error(`Scorer contract for ${key} is stale: run-tests.sh hash does not match`);
  }
  return { key, manifestPath, ...plan };
}

export function scorerTestRoot(plan: ScorerPlan): "/tests" | "/tests/tests" {
  return plan.testLayout === "flat" ? "/tests" : "/tests/tests";
}

export function scorerCommand(plan: ScorerPlan): string[] {
  if (plan.strategy === "source-runner") return ["bash", "/tests/run-tests.sh"];
  return ["python3", "-m", "pytest", `/tests/${plan.testTarget}`, "-rA"];
}
