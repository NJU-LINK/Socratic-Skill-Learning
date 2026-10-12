import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { requireSuccess, runProcess } from "../src/runtime/process.js";

test("process deadlines terminate descendants that retain the output pipes", async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), "ssl-process-timeout-"));
  const marker = path.join(directory, "late-write");
  const descendant = `setTimeout(() => require('node:fs').writeFileSync(${JSON.stringify(marker)}, 'continued'), 3000)`;
  const parent = `
    const {spawn} = require('node:child_process');
    const child = spawn(process.execPath, ['-e', ${JSON.stringify(descendant)}], {stdio: 'inherit'});
    console.log('descendant=' + child.pid);
    setInterval(() => {}, 1000);
  `;
  let descendantPid: number | undefined;
  try {
    const start = Date.now();
    const result = await runProcess(process.execPath, ["-e", parent], { timeoutMs: 1000 });
    descendantPid = Number(/descendant=(\d+)/.exec(result.stdout)?.[1]);
    assert.ok(Number.isInteger(descendantPid), "the descendant must start before the deadline");
    assert.equal(result.timedOut, true);
    assert.ok(Date.now() - start < 2500, "inherited pipes must not extend the deadline");
    await assert.rejects(readFile(marker), { code: "ENOENT" });
    assert.throws(() => requireSuccess(result, "test command"), /timed out/);
  } finally {
    if (descendantPid && Number.isInteger(descendantPid)) {
      try { process.kill(descendantPid, "SIGKILL"); } catch { /* Already terminated. */ }
    }
    await rm(directory, { recursive: true, force: true });
  }
});

test("a completed parent cannot turn a descendant timeout into success", async () => {
  const parent = `
    const {spawn} = require('node:child_process');
    const child = spawn(process.execPath, ['-e', 'setTimeout(() => {}, 3000)'], {stdio: 'inherit'});
    child.unref();
    console.log('parent finished');
  `;
  const result = await runProcess(process.execPath, ["-e", parent], { timeoutMs: 1000 });
  assert.match(result.stdout, /parent finished/);
  assert.equal(result.timedOut, true);
  assert.throws(() => requireSuccess(result, "test command"), /timed out/);
});

test("normal process output and nonzero exit codes are preserved", async () => {
  const result = await runProcess(process.execPath, ["-e", "console.log('output'); console.error('error'); process.exitCode = 7"], { timeoutMs: 5000 });
  assert.equal(result.timedOut, false);
  assert.equal(result.exitCode, 7);
  assert.equal(result.stdout, "output\n");
  assert.equal(result.stderr, "error\n");
  assert.throws(() => requireSuccess(result, "test command"), /exit 7/);
});

test("spawn errors clear the process deadline", async () => {
  await assert.rejects(
    runProcess(`ssl-command-does-not-exist-${process.pid}`, [], { timeoutMs: 30_000 }),
    { code: "ENOENT" },
  );
});
