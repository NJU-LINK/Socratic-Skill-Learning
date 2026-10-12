import assert from "node:assert/strict";
import { createHash, randomUUID } from "node:crypto";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { TaskEnvironment, TaskInfrastructureError, safeDockerName, sanitizedContextDigest } from "../src/runtime/docker.js";
import { runProcess } from "../src/runtime/process.js";

test("Docker deadlines stop commands in the container without changing normal command behavior", { timeout: 60_000 }, async (t) => {
  const docker = await runProcess("docker", ["info", "--format", "{{.ServerVersion}}"], { timeoutMs: 5_000 }).catch(() => undefined);
  const image = await runProcess("docker", ["image", "inspect", "ubuntu:24.04"], { timeoutMs: 5_000 }).catch(() => undefined);
  if (!docker || docker.exitCode !== 0 || !image || image.exitCode !== 0) {
    t.skip("Docker integration requires a running daemon and the local ubuntu:24.04 image; no images are downloaded");
    return;
  }

  const root = await mkdtemp(path.join(os.tmpdir(), "ssl-deadline-test-"));
  const family = `deadline-fixture-${randomUUID().slice(0, 8)}`;
  const variantRoot = path.join(root, family, "v01");
  const environment = new TaskEnvironment(`timeout-test-${randomUUID()}`, true);
  let builtImage: string | undefined;
  async function setScorer(runner: string): Promise<void> {
    await writeFile(path.join(variantRoot, "run-tests.sh"), runner);
    await writeFile(path.join(root, "scorer-manifest.json"), JSON.stringify({
      schemaVersion: 2,
      scorers: {
        [`${family}/v01`]: {
          strategy: "source-runner",
          testLayout: "flat",
          runnerSha256: createHash("sha256").update(runner).digest("hex"),
        },
      },
    }));
  }
  try {
    await mkdir(path.join(variantRoot, "tests"), { recursive: true });
    await writeFile(path.join(variantRoot, "tests", "fixture.txt"), "deadline fixture\n");
    await writeFile(path.join(variantRoot, "Dockerfile"), "FROM ubuntu:24.04\nRUN useradd -m agent && mkdir /app && chown agent /app\nUSER agent\nWORKDIR /app\n");
    await setScorer("#!/usr/bin/env bash\nprintf '1 passed\\n'\n");
    builtImage = safeDockerName(`sst-${family}-v01-${(await sanitizedContextDigest(variantRoot)).slice(0, 16)}`);
    await environment.reset(family, "v01", variantRoot);

    await t.test("a command that ignores TERM and its child cannot perform later writes", async () => {
      const result = await environment.shell("trap '' TERM; bash -c 'sleep 1.3; touch /app/late-write' & wait", 0.2);
      assert.equal(result.timedOut, true);
      assert.equal(result.stdout, "");
      assert.equal(result.stderr, "");
      await environment.shell("sleep 1.4; test ! -e /app/late-write", 3).then((check) => assert.equal(check.exitCode, 0));
      assert.doesNotMatch(result.command, /SSL_COMMAND_COMPLETE_|ssl-deadline-/);
    });

    await t.test("normal exits 124 and 137 retain their output and are not deadlines", async () => {
      for (const status of [0, 7, 124, 137]) {
        const result = await environment.shell(`printf 'output'; printf 'error' >&2; exit ${status}`, 2);
        assert.equal(result.exitCode, status);
        assert.equal(result.timedOut, false);
        assert.equal(result.stdout, "output");
        assert.equal(result.stderr, "error");
      }
    });

    await t.test("a successfully launched background service survives the next command", async () => {
      const started = await environment.shell("nohup bash -c 'sleep 0.5; touch /app/service-ready; sleep 20' >/dev/null 2>&1 & echo $!", 2);
      assert.equal(started.exitCode, 0);
      assert.equal(started.timedOut, false);
      const pid = Number(started.stdout.trim());
      assert.ok(Number.isInteger(pid) && pid > 0);
      const next = await environment.shell(`sleep 0.7; test -f /app/service-ready && kill -0 ${pid}`, 2);
      assert.equal(next.exitCode, 0);
      assert.equal(next.timedOut, false);
      await environment.shell(`kill ${pid}`, 2);
    });

    await t.test("scorer commands use the same container-side deadline", async () => {
      await setScorer("#!/usr/bin/env bash\ntrap '' TERM\nbash -c 'sleep 1.3; touch /app/late-scorer-write' &\nwait\nprintf '1 passed\\n'\n");
      await assert.rejects(environment.runTests(0.2), (error: unknown) => error instanceof TaskInfrastructureError && /Scorer timed out/.test(error.message));
      const check = await environment.shell("sleep 1.4; test ! -e /app/late-scorer-write", 3);
      assert.equal(check.exitCode, 0);
      await setScorer("#!/usr/bin/env bash\nprintf '1 passed\\n'\n");
      const score = await environment.runTests(2);
      assert.equal(score.score, 1);
      assert.equal(score.timedOut, false);
      assert.doesNotMatch(score.output, /SSL_COMMAND_COMPLETE_|ssl-deadline-/);
    });

    await t.test("an unavailable deadline supervisor stops and invalidates the task container", async () => {
      const sabotage = await environment.shell("mv /usr/bin/timeout /usr/bin/timeout.disabled", 2);
      // The normal agent user has no permission to change the supervisor.
      assert.notEqual(sabotage.exitCode, 0);
      const container = (environment as unknown as { containerName: string }).containerName;
      const disable = await runProcess("docker", ["exec", "-u", "0", container, "mv", "/usr/bin/timeout", "/usr/bin/timeout.disabled"], { timeoutMs: 5_000 });
      assert.equal(disable.exitCode, 0);
      await assert.rejects(environment.shell("sleep 20", 0.2), TaskInfrastructureError);
      assert.throws(() => environment.assertValid(), TaskInfrastructureError);
      const inspect = await runProcess("docker", ["inspect", "--format", "{{.State.Running}}", container], { timeoutMs: 5_000 });
      assert.equal(inspect.stdout.trim(), "false");
    });
  } finally {
    await environment.stop();
    if (builtImage) await runProcess("docker", ["image", "rm", builtImage], { timeoutMs: 15_000 });
    await rm(root, { recursive: true, force: true });
  }
});
