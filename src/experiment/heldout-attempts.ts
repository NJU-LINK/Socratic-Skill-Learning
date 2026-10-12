import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";

export type HeldoutAttemptStatus = "running" | "complete" | "invalid";

export interface HeldoutAttempt {
  variant: string;
  attempt: number;
  status: HeldoutAttemptStatus;
  startedAt: string;
  finishedAt?: string;
  attemptRoot: string;
  resultPath?: string;
  invalidErrorType?: string;
  invalidReason?: string;
}

export interface HeldoutAttemptLedger {
  schemaVersion: 1;
  runId: string;
  iteration: number;
  frozenPackageManifestSha256: string;
  attempts: HeldoutAttempt[];
}

function ledgerPath(runRoot: string, iteration: number): string {
  return path.join(runRoot, "heldout", `iteration-${iteration}`, "attempts.json");
}

export async function loadHeldoutLedger(options: {
  runRoot: string;
  runId: string;
  iteration: number;
  frozenPackageManifestSha256: string;
}): Promise<HeldoutAttemptLedger> {
  const filePath = ledgerPath(options.runRoot, options.iteration);
  const existing = await readFile(filePath, "utf8")
    .then((text) => JSON.parse(text) as HeldoutAttemptLedger)
    .catch(() => undefined);
  if (!existing) {
    return {
      schemaVersion: 1,
      runId: options.runId,
      iteration: options.iteration,
      frozenPackageManifestSha256: options.frozenPackageManifestSha256,
      attempts: [],
    };
  }
  if (
    existing.schemaVersion !== 1
    || existing.runId !== options.runId
    || existing.iteration !== options.iteration
    || existing.frozenPackageManifestSha256 !== options.frozenPackageManifestSha256
    || !Array.isArray(existing.attempts)
  ) {
    throw new Error(`Held-out attempt ledger does not match the frozen run: ${filePath}`);
  }
  for (const attempt of existing.attempts) {
    if (attempt.status === "running") {
      attempt.status = "invalid";
      attempt.finishedAt = new Date().toISOString();
      attempt.invalidErrorType = "InterruptedHeldoutController";
      attempt.invalidReason = "The held-out controller ended before this fresh solver attempt completed.";
    }
  }
  return existing;
}

export async function writeHeldoutLedger(
  runRoot: string,
  ledger: HeldoutAttemptLedger,
): Promise<void> {
  const filePath = ledgerPath(runRoot, ledger.iteration);
  await mkdir(path.dirname(filePath), { recursive: true });
  const temporary = `${filePath}.tmp-${process.pid}`;
  await writeFile(temporary, `${JSON.stringify(ledger, null, 2)}\n`, "utf8");
  await rename(temporary, filePath);
}

export function completedHeldoutAttempt(
  ledger: HeldoutAttemptLedger,
  variant: string,
): HeldoutAttempt | undefined {
  return ledger.attempts
    .filter((attempt) => attempt.variant === variant && attempt.status === "complete")
    .sort((a, b) => a.attempt - b.attempt)[0];
}

export function beginHeldoutAttempt(
  ledger: HeldoutAttemptLedger,
  runRoot: string,
  variant: string,
): HeldoutAttempt {
  const existing = completedHeldoutAttempt(ledger, variant);
  if (existing) throw new Error(`Held-out ${variant} already has canonical attempt ${existing.attempt}`);
  const attemptNumber = Math.max(
    0,
    ...ledger.attempts.filter((attempt) => attempt.variant === variant).map((attempt) => attempt.attempt),
  ) + 1;
  const attempt: HeldoutAttempt = {
    variant,
    attempt: attemptNumber,
    status: "running",
    startedAt: new Date().toISOString(),
    attemptRoot: path.join(
      runRoot,
      "heldout",
      `iteration-${ledger.iteration}`,
      variant,
      `attempt-${attemptNumber}`,
    ),
  };
  ledger.attempts.push(attempt);
  return attempt;
}

export function completeHeldoutAttempt(attempt: HeldoutAttempt, resultPath: string): void {
  if (attempt.status !== "running") throw new Error(`Cannot complete held-out attempt in state ${attempt.status}`);
  attempt.status = "complete";
  attempt.finishedAt = new Date().toISOString();
  attempt.resultPath = resultPath;
}

export function invalidateHeldoutAttempt(attempt: HeldoutAttempt, error: unknown): void {
  if (attempt.status !== "running") throw new Error(`Cannot invalidate held-out attempt in state ${attempt.status}`);
  attempt.status = "invalid";
  attempt.finishedAt = new Date().toISOString();
  attempt.invalidErrorType = error instanceof Error ? error.name : typeof error;
  attempt.invalidReason = error instanceof Error ? error.message : String(error);
}

