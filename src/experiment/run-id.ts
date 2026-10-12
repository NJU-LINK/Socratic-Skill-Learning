import { ALL_MODES, type Mode } from "./types.js";

const RUN_ID_MODES = [...ALL_MODES].sort((a, b) => b.length - a.length);

export function createRunId(mode: Mode, family: string, replicate: number): string {
  const timestamp = new Date().toISOString().replace(/\D/g, "");
  return `${timestamp}-${mode}-${family}-r${replicate}`;
}

/** Parse <timestamp>-<mode>-<family>-r<replicate>, including historical modes.
 * Family names contain hyphens, so match known modes before extracting them. */
export function parseRunId(runId: string): { mode: Mode; family: string; replicate: number } | undefined {
  const match = runId.match(/^(\d+)-(.+)-r(\d+)$/);
  if (!match) return undefined;
  const body = match[2]!;
  const replicate = Number(match[3]);
  for (const mode of RUN_ID_MODES) {
    if (body.startsWith(`${mode}-`)) {
      return { mode, family: body.slice(mode.length + 1), replicate };
    }
  }
  return undefined;
}
