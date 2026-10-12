import { DeadlineExceededError, runWithDeadline } from "../runtime/deadline.js";
import type { TestResult } from "./types.js";

/** A solver deadline is a measured zero, not a retryable infrastructure failure. */
export async function withSolverBudget<T>(options: {
  label: string;
  timeoutMs?: number | undefined;
  operation: () => Promise<T>;
  stop: () => Promise<void>;
}): Promise<{ completion: T; timeout?: never } | { timeout: TestResult; completion?: never }> {
  try {
    const completion = options.timeoutMs === undefined
      ? await options.operation()
      : await runWithDeadline({ ...options, timeoutMs: options.timeoutMs, onTimeout: options.stop });
    return { completion };
  } catch (error) {
    if (!(error instanceof DeadlineExceededError)) throw error;
    return { timeout: {
      passed: 0, failed: 0, errors: 0, total: 0, score: 0,
      output: `${error.message}; solver stopped, private scorer not run.`,
      exitCode: 124, timedOut: true,
    } };
  }
}
