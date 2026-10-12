import { spawn } from "node:child_process";

export interface ProcessResult {
  command: string;
  exitCode: number;
  stdout: string;
  stderr: string;
  timedOut: boolean;
}

export async function runProcess(
  command: string,
  args: string[],
  options: { cwd?: string; timeoutMs?: number; env?: NodeJS.ProcessEnv; inherit?: boolean } = {},
): Promise<ProcessResult> {
  return await new Promise((resolve, reject) => {
    const hasTimeout = options.timeoutMs !== undefined && options.timeoutMs > 0;
    const useProcessGroup = hasTimeout && process.platform !== "win32";
    const child = spawn(command, args, {
      cwd: options.cwd,
      env: options.env ?? process.env,
      // A separate POSIX group lets the deadline stop shells and their children
      // without signalling the harness itself.
      detached: useProcessGroup,
      stdio: options.inherit ? ["ignore", "pipe", "pipe"] : ["ignore", "pipe", "pipe"],
    });
    const stdout: Buffer[] = [];
    const stderr: Buffer[] = [];
    child.stdout.on("data", (chunk: Buffer) => {
      stdout.push(chunk);
      if (options.inherit) process.stdout.write(chunk);
    });
    child.stderr.on("data", (chunk: Buffer) => {
      stderr.push(chunk);
      if (options.inherit) process.stderr.write(chunk);
    });

    let timedOut = false;
    const timer = hasTimeout
      ? setTimeout(() => {
          timedOut = true;
          if (useProcessGroup && child.pid !== undefined) {
            try {
              process.kill(-child.pid, "SIGKILL");
            } catch {
              child.kill("SIGKILL");
            }
          } else if (process.platform === "win32" && child.pid !== undefined) {
            const killer = spawn("taskkill", ["/PID", String(child.pid), "/T", "/F"], {
              stdio: "ignore",
            });
            killer.once("error", () => child.kill("SIGKILL"));
            killer.once("close", () => child.kill("SIGKILL"));
          } else {
            child.kill("SIGKILL");
          }
          // An intentionally detached descendant can retain these pipes even
          // after the command exits. It must not keep a timed-out call waiting.
          child.stdout.destroy();
          child.stderr.destroy();
        }, options.timeoutMs)
      : undefined;

    child.on("error", (error) => {
      if (timer) clearTimeout(timer);
      reject(error);
    });
    child.on("close", (code) => {
      if (timer) clearTimeout(timer);
      resolve({
        command: [command, ...args].join(" "),
        exitCode: code ?? -1,
        stdout: Buffer.concat(stdout).toString("utf8"),
        stderr: Buffer.concat(stderr).toString("utf8"),
        timedOut,
      });
    });
  });
}

export function requireSuccess(result: ProcessResult, context: string): void {
  if (result.timedOut || result.exitCode !== 0) {
    const output = `${result.stdout}\n${result.stderr}`.trim();
    const reason = result.timedOut ? "timed out" : `exit ${result.exitCode}`;
    throw new Error(`${context} failed (${reason})\n${output}`);
  }
}
