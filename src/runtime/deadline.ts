export class DeadlineExceededError extends Error {
  constructor(
    readonly label: string,
    readonly timeoutMs: number,
    readonly timeoutAt: string,
  ) {
    super(`${label} exceeded ${timeoutMs}ms`);
    this.name = "DeadlineExceededError";
  }
}

/**
 * Run one measured operation under a hard deadline. Once the deadline fires,
 * the result is always a timeout even if aborting the underlying operation
 * makes it reject with a secondary error first.
 */
export async function runWithDeadline<T>(options: {
  label: string;
  timeoutMs: number;
  operation: () => Promise<T>;
  onTimeout: () => void | Promise<void>;
}): Promise<T> {
  let timer: NodeJS.Timeout | undefined;
  let timeoutError: DeadlineExceededError | undefined;
  let abortPromise: Promise<void> | undefined;
  let rejectDeadline: ((error: DeadlineExceededError) => void) | undefined;
  const deadline = new Promise<never>((_resolve, reject) => {
    rejectDeadline = reject;
  });

  timer = setTimeout(() => {
    timeoutError = new DeadlineExceededError(
      options.label,
      options.timeoutMs,
      new Date().toISOString(),
    );
    abortPromise = Promise.resolve(options.onTimeout()).then(() => undefined);
    void abortPromise.then(
      () => rejectDeadline?.(timeoutError!),
      () => rejectDeadline?.(timeoutError!),
    );
  }, options.timeoutMs);

  try {
    const result = await Promise.race([options.operation(), deadline]);
    if (timeoutError) {
      await abortPromise?.catch(() => undefined);
      throw timeoutError;
    }
    return result;
  } catch (error) {
    if (timeoutError) {
      await abortPromise?.catch(() => undefined);
      throw timeoutError;
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
}
