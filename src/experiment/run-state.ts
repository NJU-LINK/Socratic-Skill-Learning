import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import path from "node:path";

export const RUN_PHASES = [
  "induction-running",
  "heldout-ready",
  "heldout-running",
  "complete",
  "invalid",
] as const;

export type RunPhase = (typeof RUN_PHASES)[number];

export interface RunState {
  schemaVersion: 1;
  runId: string;
  phase: RunPhase;
  updatedAt: string;
  reason?: string;
}

function statePath(runRoot: string): string {
  return path.join(runRoot, "run-state.json");
}

async function writeState(runRoot: string, state: RunState): Promise<void> {
  await mkdir(runRoot, { recursive: true });
  const destination = statePath(runRoot);
  const temporary = `${destination}.tmp-${process.pid}`;
  await writeFile(temporary, `${JSON.stringify(state, null, 2)}\n`, "utf8");
  await rename(temporary, destination);
}

export async function initializeRunState(runRoot: string, runId: string): Promise<RunState> {
  const state: RunState = {
    schemaVersion: 1,
    runId,
    phase: "induction-running",
    updatedAt: new Date().toISOString(),
  };
  await writeState(runRoot, state);
  return state;
}

export async function readRunState(runRoot: string): Promise<RunState> {
  const state = JSON.parse(await readFile(statePath(runRoot), "utf8")) as RunState;
  if (
    state.schemaVersion !== 1
    || typeof state.runId !== "string"
    || !(RUN_PHASES as readonly string[]).includes(state.phase)
  ) {
    throw new Error(`Invalid run state: ${statePath(runRoot)}`);
  }
  return state;
}

export async function transitionRunState(
  runRoot: string,
  expected: RunPhase | RunPhase[],
  next: RunPhase,
  reason?: string,
): Promise<RunState> {
  const current = await readRunState(runRoot);
  const allowed = Array.isArray(expected) ? expected : [expected];
  if (!allowed.includes(current.phase)) {
    throw new Error(
      `Illegal run-state transition for ${current.runId}: expected ${allowed.join(" or ")}, `
      + `found ${current.phase}, requested ${next}`,
    );
  }
  const state: RunState = {
    schemaVersion: 1,
    runId: current.runId,
    phase: next,
    updatedAt: new Date().toISOString(),
    ...(reason ? { reason } : {}),
  };
  await writeState(runRoot, state);
  return state;
}
