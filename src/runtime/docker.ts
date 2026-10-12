import { createHash } from "node:crypto";
import { cp, mkdir, mkdtemp, readFile, readdir, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { requireSuccess, runProcess, type ProcessResult } from "./process.js";
import { ContainerDeadlineError, runDockerExec } from "./docker-exec.js";
import {
  loadScorerPlan,
  scorerCommand,
  scorerTestRoot,
} from "./scorer.js";
import type { TestResult } from "../experiment/types.js";

export function safeDockerName(value: string): string {
  const normalized = value.toLowerCase().replace(/[^a-z0-9_.-]+/g, "-");
  if (normalized.length <= 110) return normalized;
  const suffix = createHash("sha256").update(normalized).digest("hex").slice(0, 12);
  return `${normalized.slice(0, 97)}-${suffix}`;
}

function shellQuote(value: string): string {
  return `'${value.replaceAll("'", "'\"'\"'")}'`;
}

function combined(result: ProcessResult): string {
  return [result.stdout, result.stderr].filter(Boolean).join("\n").trim();
}

const PRIVATE_BUILD_ENTRIES = new Set([
  "solution.sh",
  "tests",
  "run-tests.sh",
  "task.yaml",
  "docker-compose.yaml",
]);
const imageBuilds = new Map<string, Promise<void>>();

export interface SanitizedBuildContext {
  root: string;
  context: string;
}

export async function sanitizedContextDigest(variantRoot: string): Promise<string> {
  const sourceRoot = path.resolve(variantRoot);
  const entries: Array<{ relative: string; content: Buffer }> = [];
  async function walk(directory: string): Promise<void> {
    const children = await readdir(directory, { withFileTypes: true });
    for (const child of children.sort((a, b) => a.name.localeCompare(b.name))) {
      const full = path.join(directory, child.name);
      const relative = path.relative(sourceRoot, full);
      const topLevel = relative.split(path.sep)[0] ?? relative;
      if (PRIVATE_BUILD_ENTRIES.has(topLevel)) continue;
      if (child.isDirectory()) await walk(full);
      else if (child.isFile()) entries.push({ relative: relative.split(path.sep).join("/"), content: await readFile(full) });
    }
  }
  await walk(sourceRoot);
  const digest = createHash("sha256");
  for (const entry of entries) {
    digest.update(entry.relative);
    digest.update("\0");
    digest.update(entry.content);
    digest.update("\0");
  }
  return digest.digest("hex");
}

/**
 * Terminal-bench family assets keep private references and tests beside the
 * Dockerfile. Docker must never receive those files as build context because a
 * broad `COPY . /app` would otherwise expose them to the agent.
 */
export async function prepareSanitizedBuildContext(variantRoot: string): Promise<SanitizedBuildContext> {
  const sourceRoot = path.resolve(variantRoot);
  const root = await mkdtemp(path.join(os.tmpdir(), "sst-build-"));
  const context = path.join(root, "context");
  await cp(sourceRoot, context, {
    recursive: true,
    preserveTimestamps: true,
    filter: (source) => {
      const relative = path.relative(sourceRoot, source);
      if (!relative) return true;
      const topLevel = relative.split(path.sep)[0] ?? relative;
      return !PRIVATE_BUILD_ENTRIES.has(topLevel);
    },
  });
  return { root, context };
}

export function parseTestOutput(output: string, exitCode = 0, timedOut = false): TestResult {
  let passed = Number(output.match(/(\d+) passed/)?.[1] ?? 0);
  let failed = Number(output.match(/(\d+) failed/)?.[1] ?? 0);
  let errors = Number(output.match(/(\d+) error/)?.[1] ?? 0);
  let total = passed + failed + errors;

  if (total === 0) {
    const unittest = output.match(/Ran (\d+) test/);
    if (unittest) {
      total = Number(unittest[1]);
      failed = Number(output.match(/failures=(\d+)/)?.[1] ?? 0);
      errors = Number(output.match(/errors=(\d+)/)?.[1] ?? 0);
      passed = /^OK$/m.test(output) ? total : Math.max(0, total - failed - errors);
    }
  }
  return {
    passed,
    failed,
    errors,
    total,
    score: total > 0 ? passed / total : 0,
    output,
    exitCode,
    timedOut,
  };
}

export function isMissingContainerFailure(result: ProcessResult): boolean {
  if (result.exitCode === 0) return false;
  return /(?:no such container|container .+ is not running|cannot connect to the docker daemon|is the docker daemon running)/i.test(
    combined(result),
  );
}

export function sourceRunnerNeedsPythonInstaller(runner: string): boolean {
  return /\buv\s+pip\s+install\b/.test(runner)
    && /\bpython3?\s+-m\s+pip\s+install\b/.test(runner);
}

export class TaskInfrastructureError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "TaskInfrastructureError";
  }
}

export class TaskEnvironment {
  private containerName: string | undefined;
  private variantRoot: string | undefined;
  private immutableSnapshotRoot: string | undefined;
  private infrastructureError: TaskInfrastructureError | undefined;

  constructor(
    private readonly runId: string,
    private readonly reuseImages: boolean,
    private readonly proxy?: string,
  ) {}

  async reset(family: string, variant: string, variantRoot: string, skillDir?: string): Promise<void> {
    this.assertValid();
    await this.removeContainer();
    this.variantRoot = variantRoot;
    const contextDigest = await sanitizedContextDigest(variantRoot);
    const image = safeDockerName(`sst-${family}-${variant}-${contextDigest.slice(0, 16)}`);
    const container = safeDockerName(`se-${this.runId}-${family}-${variant}`);

    let build = imageBuilds.get(image);
    if (!build) {
      build = (async () => {
        let exists = false;
        if (this.reuseImages) {
          const inspect = await runProcess("docker", ["image", "inspect", image], { timeoutMs: 30_000 });
          exists = inspect.exitCode === 0;
        }
        if (exists) return;
        const proxyBuildArgs = this.proxy
          ? [
              "--build-arg", `HTTP_PROXY=${this.proxy}`,
              "--build-arg", `HTTPS_PROXY=${this.proxy}`,
              "--build-arg", `http_proxy=${this.proxy}`,
              "--build-arg", `https_proxy=${this.proxy}`,
            ]
          : [];
        const buildContext = await prepareSanitizedBuildContext(variantRoot);
        try {
          let result: ProcessResult | undefined;
          for (let attempt = 1; attempt <= 3; attempt += 1) {
            // --network=host: on this host the egress proxy is reachable only
            // from the host network namespace (bridge containers get 502 on
            // HTTPS CONNECT), so builds must share the host network for apt/pip
            // to reach package indexes through the configured proxy.
            result = await runProcess(
              "docker",
              ["build", "--network=host", ...proxyBuildArgs, "-t", image, buildContext.context],
              {
                timeoutMs: 30 * 60_000,
                inherit: true,
              },
            );
            if (result.exitCode === 0 && !result.timedOut) break;
            if (attempt < 3) {
              console.warn(
                `[docker] build ${family}/${variant} attempt ${attempt}/3 failed `
                + `(exit=${result.exitCode}${result.timedOut ? ", timed out" : ""}); retrying`,
              );
            }
          }
          if (!result) throw new Error(`docker build ${family}/${variant} did not start`);
          requireSuccess(result, `docker build ${family}/${variant} after 3 attempts`);
        } finally {
          await rm(buildContext.root, { recursive: true, force: true });
        }
      })();
      imageBuilds.set(image, build);
    }
    try {
      await build;
    } finally {
      if (imageBuilds.get(image) === build) imageBuilds.delete(image);
    }

    await runProcess("docker", ["rm", "-f", container], { timeoutMs: 45_000 });
    const mountArgs = skillDir
      ? ["--mount", `type=bind,src=${path.resolve(skillDir)},dst=/skill,readonly`]
      : [];
    const proxyEnvArgs = this.proxy
      ? [
          "-e", `HTTP_PROXY=${this.proxy}`,
          "-e", `HTTPS_PROXY=${this.proxy}`,
          "-e", `http_proxy=${this.proxy}`,
          "-e", `https_proxy=${this.proxy}`,
          "-e", "NO_PROXY=localhost,127.0.0.1",
          "-e", "no_proxy=localhost,127.0.0.1",
        ]
      : [];
    const start = await runProcess(
      "docker",
      ["run", "-d", "--name", container, ...proxyEnvArgs, ...mountArgs, image, "sleep", "infinity"],
      { timeoutMs: 60_000 },
    );
    requireSuccess(start, `docker run ${family}/${variant}`);
    this.containerName = container;
    await this.assertNoBenchmarkLeakage();
    await this.captureImmutableInputs();
  }

  private async assertNoBenchmarkLeakage(): Promise<void> {
    // The sanitized build context already excludes the private top-level
    // `tests/` tree. A task may legitimately create its own project tests
    // under /app, so the runtime audit checks private benchmark filenames
    // rather than treating every directory named `tests` as verifier leakage.
    const audit = await this.shell(
      `set -eu
leaks="$(
  find /app -maxdepth 6 -type f \\( -name solution.sh -o -name run-tests.sh -o -name task.yaml \\) -print
)"
if [ -n "$leaks" ]; then
  printf '%s\\n' "$leaks"
  exit 97
fi`,
      60,
    );
    if (audit.exitCode !== 0) {
      const leaked = combined(audit) || "unknown private benchmark artifact";
      throw new Error(`Benchmark leakage detected inside task image:\n${leaked}`);
    }
  }

  private async captureImmutableInputs(): Promise<void> {
    if (!this.containerName || !this.variantRoot) throw new Error("Task container is not running");
    const scorer = await loadScorerPlan(this.variantRoot);
    if (!scorer.immutableInputs?.length) return;

    const snapshotRoot = await mkdtemp(path.join(os.tmpdir(), "sst-inputs-"));
    try {
      for (const immutableInput of scorer.immutableInputs) {
        const source = `/app/${immutableInput.split(path.sep).join("/")}`;
        const destination = path.join(snapshotRoot, immutableInput);
        await mkdir(path.dirname(destination), { recursive: true });
        const snapshot = await runProcess(
          "docker",
          ["cp", `${this.containerName}:${source}`, destination],
          { timeoutMs: 120_000 },
        );
        requireSuccess(snapshot, `snapshot immutable input ${immutableInput}`);
      }
      this.immutableSnapshotRoot = snapshotRoot;
    } catch (error) {
      await rm(snapshotRoot, { recursive: true, force: true });
      throw error;
    }
  }

  async shell(command: string, timeoutSeconds?: number): Promise<ProcessResult> {
    return await this.execShell(command, timeoutSeconds);
  }

  private async shellAsRoot(command: string, timeoutSeconds?: number): Promise<ProcessResult> {
    return await this.execShell(command, timeoutSeconds, "0");
  }

  private async execShell(
    command: string,
    timeoutSeconds?: number,
    user?: string,
  ): Promise<ProcessResult> {
    this.assertValid();
    const container = this.containerName;
    if (!container) throw new Error("Task container is not running");
    const result = await this.execInContainer(container, ["bash", "-lc", command], {
      ...(timeoutSeconds === undefined ? {} : { timeoutSeconds }),
      ...(user ? { user } : {}),
    });
    if (isMissingContainerFailure(result)) {
      this.infrastructureError = new TaskInfrastructureError(
        `Task container disappeared during a measured rollout: ${combined(result) || result.command}`,
      );
      throw this.infrastructureError;
    }
    return result;
  }

  private async execInContainer(
    container: string,
    command: string[],
    options: Parameters<typeof runDockerExec>[2],
  ): Promise<ProcessResult> {
    try {
      return await runDockerExec(container, command, options);
    } catch (error) {
      if (!(error instanceof ContainerDeadlineError)) throw error;
      this.infrastructureError = new TaskInfrastructureError(error.message);
      throw this.infrastructureError;
    }
  }

  assertValid(): void {
    if (this.infrastructureError) throw this.infrastructureError;
  }

  /**
   * Install the private reference implementation only for the scorer preflight.
   * This must be called after reset() has completed its leakage audit and must
   * never be used by an agent-facing solve.
   */
  async installReferenceSolution(solutionPath: string): Promise<void> {
    if (!this.containerName) throw new Error("Task container is not running");
    const copied = await runProcess(
      "docker",
      ["cp", solutionPath, `${this.containerName}:/app/solution.sh`],
      { timeoutMs: 60_000 },
    );
    requireSuccess(copied, "install private reference solution");
    const chmod = await this.shellAsRoot("chmod 755 /app/solution.sh", 60);
    requireSuccess(chmod, "make private reference solution executable");
  }

  async runTests(timeoutSeconds = 300): Promise<TestResult> {
    this.assertValid();
    if (!this.containerName || !this.variantRoot) throw new Error("Task container is not running");
    const testsDir = path.join(this.variantRoot, "tests");
    const runTestsPath = path.join(this.variantRoot, "run-tests.sh");
    const scorer = await loadScorerPlan(this.variantRoot);
    const directSystemPytest = scorer.strategy === "system-pytest";
    const testRoot = scorerTestRoot(scorer);

    await this.shellAsRoot(`rm -rf /tests && mkdir -p ${testRoot}`, 60);
    const copyTests = await runProcess("docker", ["cp", `${testsDir}/.`, `${this.containerName}:${testRoot}/`], {
      timeoutMs: 120_000,
    });
    requireSuccess(copyTests, "copy tests into task container");
    const copyRunner = await runProcess(
      "docker",
      ["cp", runTestsPath, `${this.containerName}:/tests/run-tests.sh`],
      { timeoutMs: 60_000 },
    );
    requireSuccess(copyRunner, "copy test runner into task container");

    for (const immutableInput of scorer.immutableInputs ?? []) {
      if (!this.immutableSnapshotRoot) {
        throw new Error(`Missing immutable-input snapshot for ${scorer.key}`);
      }
      const source = path.join(this.immutableSnapshotRoot, immutableInput);
      const destination = `/app/${immutableInput.split(path.sep).join("/")}`;
      const prepareDestination = await this.shellAsRoot(
        `rm -rf ${shellQuote(destination)} && mkdir -p ${shellQuote(path.posix.dirname(destination))}`,
        60,
      );
      requireSuccess(prepareDestination, `prepare immutable input ${immutableInput}`);
      const restoreInput = await runProcess(
        "docker",
        ["cp", source, `${this.containerName}:${destination}`],
        { timeoutMs: 60_000 },
      );
      requireSuccess(restoreInput, `restore immutable input ${immutableInput}`);
    }

    await this.shellAsRoot(
      // A private source runner may need the reference under /tests during its
      // preflight, but the scorer must observe the same /app tree as a real
      // agent evaluation. Move the benchmark-owned oracle out of /app before
      // any assertions inspect agent side effects.
      "if [ -f /app/solution.sh ]; then mv -f /app/solution.sh /tests/solution.sh; chmod 755 /tests/solution.sh || true; fi",
      60,
    );
    const sourceRunner = await readFile(runTestsPath, "utf8");
    if (!directSystemPytest && sourceRunnerNeedsPythonInstaller(sourceRunner)) {
      const prepareInstaller = await this.shell(
        `set -eu
if ! command -v uv >/dev/null 2>&1 && ! python3 -m pip --version >/dev/null 2>&1; then
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends python3-pip
fi`,
        10 * 60,
      );
      requireSuccess(prepareInstaller, "restore source-runner Python package installer");
    }
    if (directSystemPytest) {
      // This path is enabled only by a reviewed, hash-bound scorer manifest
      // entry. It preserves the source runner's exact pytest version and target
      // while removing its network-dependent uv bootstrap.
      const preparePytest = await this.shellAsRoot(
        `set -eu
if ! python3 -c 'import pytest; assert pytest.__version__ == "${scorer.pytestVersion}"' >/dev/null 2>&1; then
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-pip
  python3 -m pip install --break-system-packages "pytest==${scorer.pytestVersion}"
fi`,
        10 * 60,
      );
      requireSuccess(preparePytest, "prepare private pytest scorer");
    }
    const result = await this.execInContainer(this.containerName, scorerCommand(scorer), {
      env: ["TEST_DIR=/tests", "PIP_BREAK_SYSTEM_PACKAGES=1", "PIP_ROOT_USER_ACTION=ignore"],
      timeoutSeconds,
    });
    if (isMissingContainerFailure(result)) {
      this.infrastructureError = new TaskInfrastructureError(
        `Task container disappeared during scoring: ${combined(result) || result.command}`,
      );
      throw this.infrastructureError;
    }
    if (result.timedOut) {
      throw new TaskInfrastructureError(`Scorer timed out after ${timeoutSeconds}s: ${combined(result)}`);
    }
    const output = combined(result);
    const collected = parseTestOutput(output, result.exitCode, result.timedOut);
    if (collected.total === 0) {
      throw new TaskInfrastructureError(
        `Scorer produced no parseable test summary (exit=${result.exitCode}):\n${output}`,
      );
    }
    return collected;
  }

  async exportApp(destination: string): Promise<void> {
    if (!this.containerName) throw new Error("Task container is not running");
    await rm(destination, { recursive: true, force: true });
    await mkdir(destination, { recursive: true });
    const result = await runProcess("docker", ["cp", `${this.containerName}:/app/.`, destination], {
      timeoutMs: 5 * 60_000,
    });
    requireSuccess(result, "export task artifacts");
  }

  async stop(): Promise<void> {
    await this.removeContainer();
  }

  private async removeContainer(): Promise<void> {
    if (this.containerName) {
      await runProcess("docker", ["rm", "-f", this.containerName], { timeoutMs: 45_000 });
    }
    if (this.immutableSnapshotRoot) {
      await rm(this.immutableSnapshotRoot, { recursive: true, force: true });
    }
    this.containerName = undefined;
    this.variantRoot = undefined;
    this.immutableSnapshotRoot = undefined;
  }
}
