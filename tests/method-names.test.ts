import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";
import { parseMethods, modeForMethod } from "../src/methods.js";
import { experimentCell } from "../src/experiment/protocol.js";
import { exportRunsRoot } from "../scripts/lib/record-export.js";
import { parseRunId } from "../src/experiment/run-id.js";
import { loadSkillKdConfig } from "../src/baselines/skill-kd-config.js";
import { candidateFrozenPackages } from "../src/runner.js";

const root = fileURLToPath(new URL("../", import.meta.url));
const current = "expert-authoring,post-hoc-teaching,fixed-window-ssl,issue-guided-ssl,no-skill";
const legacy = "compile-after,teach-after,ist,issueist,no-skill";

function offlineEnvironment(): NodeJS.ProcessEnv {
  const env = { ...process.env };
  for (const key of ["SSL_URL", "SSL_KEY", "SST_URL", "SST_KEY", "url", "key"]) delete env[key];
  return env;
}

test("paper names and legacy aliases select the same teaching protocols", () => {
  assert.deepEqual(parseMethods(legacy), parseMethods(current));
  assert.deepEqual(parseMethods(undefined), parseMethods(current));
  const fixed = experimentCell(modeForMethod("fixed-window-ssl"));
  assert.equal(fixed.observationPolicy, "fixed");
  assert.equal(fixed.guidedPracticeInteraction, "reciprocal");
  const issue = experimentCell(modeForMethod("issue-guided-ssl"));
  assert.equal(issue.observationPolicy, "tree-learning-delta");
  const expert = experimentCell(modeForMethod("expert-authoring"));
  assert.equal(expert.authorModelTier, "max");
  assert.equal(expert.educatorModelTier, null);
  const posthoc = experimentCell(modeForMethod("post-hoc-teaching"));
  assert.equal(posthoc.authorModelTier, "plus");
  assert.equal(posthoc.educatorModelTier, "max");
  assert.equal(posthoc.protocol, "teach-after");
});

test("mixing a legacy alias with its paper name cannot launch a duplicate run", () => {
  assert.throws(() => parseMethods("ist,fixed-window-ssl"), /Duplicate method/);
  assert.throws(() => parseMethods("issueist,issue-guided-ssl"), /Duplicate method/);
  assert.throws(() => parseMethods("unknown"), /Unknown method/);
  assert.throws(() => parseMethods(", ,"), /cannot be empty/);
});

test("run ids preserve family names and recognize current and historical modes", () => {
  for (const mode of ["max-guided-dialogue", "develop-adaptive-horizon-only", "develop-adaptive"]) {
    assert.deepEqual(parseRunId(`20260926000000000-${mode}-html-finance-verify-r3`), {
      mode, family: "html-finance-verify", replicate: 3,
    });
  }
  assert.equal(parseRunId("20260926000000000-unknown-html-finance-verify-r1"), undefined);
});

test("SKILL-KD defaults to the 22-family, 155-case main scope without exclusions", async () => {
  const config = await loadSkillKdConfig(path.join(root, "configs/skill-kd-baseline.yaml"));
  assert.equal(config.experimentConfig.configPath, path.join(root, "configs/scopes/main.yaml"));
  assert.equal(config.experimentConfig.families.length, 22);
  assert.equal(config.experimentConfig.families.reduce((sum, family) => sum + family.heldout.length, 0), 155);
  assert.deepEqual(config.analysisExclusions, []);
});

test("the CLI plans identical runs for old and new names without credentials", () => {
  const plan = (methods: string) => execFileSync(process.execPath, [
    "--import", "tsx", "src/cli.ts", "run", "--scope", "main", "--model", "qwen",
    "--methods", methods, "--families", "html-finance-verify", "--replicates", "1", "--dry-run",
  ], { cwd: root, env: offlineEnvironment(), encoding: "utf8" })
    .replace(/\d{14,}-/g, "TIMESTAMP-");
  const output = plan(current);
  assert.equal(plan(legacy), output);
  for (const name of current.split(",")) assert.ok(output.includes(name));
});

test("frozen evaluation finds current and legacy archives in both cohort layouts", async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), "ssl-frozen-test-"));
  try {
    for (const layout of ["qwen", "cross-model"]) {
      const cohort = path.join(dir, layout);
      const skill = (name: string) => layout === "qwen"
        ? path.join(cohort, name, "r1", "example", "skill")
        : path.join(cohort, "r1", name, "example", "skill");
      const oldPackage = skill("ist");
      await mkdir(oldPackage, { recursive: true });
      await writeFile(path.join(oldPackage, "SKILL.md"), "legacy package");
      assert.deepEqual(await candidateFrozenPackages(cohort, "fixed-window-ssl", 1, "example"), [oldPackage]);
      const latest = path.join(skill("fixed-window-ssl"), "iteration-3");
      await mkdir(latest, { recursive: true });
      await mkdir(path.join(skill("fixed-window-ssl"), "iteration-1"), { recursive: true });
      await writeFile(path.join(latest, "SKILL.md"), "current package");
      assert.equal((await candidateFrozenPackages(cohort, "fixed-window-ssl", 1, "example"))[0], latest);
    }
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test("exporting a historical run writes current paths and metadata and preserves the Skill", async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), "ssl-export-test-"));
  try {
    const runs = path.join(dir, "runs");
    const run = path.join(runs, "20260926000000000-max-guided-dialogue-example-family-r1");
    const snapshot = path.join(run, "snapshots", "iteration-3", "skill", "example-family");
    await mkdir(snapshot, { recursive: true });
    await writeFile(path.join(snapshot, "SKILL.md"), "# An unchanged learned Skill\n");
    await writeFile(path.join(run, "result.json"), JSON.stringify({ iterations: [{ iteration: 3 }] }));
    const out = path.join(dir, "exported");
    execFileSync(process.execPath, [
      "--import", "tsx", "scripts/export-records.ts", "--runs", runs, "--out", out,
    ], { cwd: root, env: offlineEnvironment(), encoding: "utf8" });
    const cell = path.join(out, "fixed-window-ssl", "r1", "example-family");
    assert.equal(JSON.parse(await readFile(path.join(cell, "meta.json"), "utf8")).method, "fixed-window-ssl");
    assert.equal(await readFile(path.join(cell, "skill", "iteration-3", "SKILL.md"), "utf8"), "# An unchanged learned Skill\n");
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test("No-Skill export reads saved scores and current sessions, including results without transcripts", async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), "ssl-export-no-skill-test-"));
  try {
    const runs = path.join(dir, "runs");
    const replicateRoot = path.join(runs, "no-skill", "replicate-1");
    const resultFamily = path.join(replicateRoot, "results", "example-family");
    await mkdir(resultFamily, { recursive: true });
    const tests = (score: number) => ({ score, passed: score * 4, failed: (1 - score) * 4, timedOut: false });
    await writeFile(path.join(resultFamily, "v02.json"), JSON.stringify({
      status: "complete", attempt: 2, tests: tests(0.75),
    }));
    await writeFile(path.join(resultFamily, "v03.json"), JSON.stringify({
      status: "task-timeout", attempt: 1, tests: { score: 0, passed: 0, failed: 0, timedOut: true },
    }));
    await writeFile(path.join(resultFamily, "v04.json"), JSON.stringify({
      status: "infrastructure-invalid", attempt: 1,
    }));
    const session = path.join(replicateRoot, "sessions", "example-family", "v02", "attempt-2", "session");
    await mkdir(session, { recursive: true });
    await writeFile(path.join(session, "trace.jsonl"), JSON.stringify({
      type: "message", message: { role: "assistant", content: [{ type: "text", text: "saved response" }] },
    }) + "\n");
    await writeFile(path.join(session, "events.jsonl"), "ignored trace events\n");
    const legacyAttempt = path.join(replicateRoot, "legacy-family", "v02", "attempt-1");
    await mkdir(legacyAttempt, { recursive: true });
    await writeFile(path.join(legacyAttempt, "result.json"), JSON.stringify({
      status: "complete", attempt: 1, tests: tests(0.5),
    }));
    const out = path.join(dir, "exported");
    const totals = await exportRunsRoot(runs, out);
    assert.equal(totals.records, 1);
    const cell = path.join(out, "no-skill", "r1", "example-family");
    const meta = JSON.parse(await readFile(path.join(cell, "meta.json"), "utf8"));
    assert.deepEqual(meta.stats.heldout.v02, { records: 1, status: "complete", ...tests(0.75) });
    assert.deepEqual(meta.stats.heldout.v03, {
      records: 0, status: "task-timeout", score: 0, passed: 0, failed: 0, timedOut: true,
    });
    assert.deepEqual(meta.stats.heldout.v04, { records: 0, status: "infrastructure-invalid" });
    assert.equal(JSON.parse(await readFile(path.join(cell, "heldout", "v02.jsonl"), "utf8")).text, "saved response");
    const legacyMeta = JSON.parse(await readFile(path.join(out, "no-skill", "r1", "legacy-family", "meta.json"), "utf8"));
    assert.equal(legacyMeta.stats.heldout.v02.score, 0.5);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test("record export is an optional script and importing its command has no side effects", () => {
  const options = { cwd: root, env: offlineEnvironment(), encoding: "utf8" as const, stdio: "pipe" as const };
  const help = execFileSync(process.execPath, ["--import", "tsx", "src/cli.ts", "--help"], options);
  assert.ok(!help.includes("ssl export"));
  assert.throws(() => execFileSync(process.execPath,
    ["--import", "tsx", "src/cli.ts", "export"], options), /Unknown command export/);
  const scriptHelp = execFileSync(process.execPath,
    ["--import", "tsx", "scripts/export-records.ts", "--help"], options);
  assert.ok(scriptHelp.includes("--runs <dir> --out <dir>"));
  const moduleUrl = pathToFileURL(path.join(root, "scripts/export-records.ts")).href;
  assert.equal(execFileSync(process.execPath, [
    "--import", "tsx", "--input-type=module", "-e", `await import(${JSON.stringify(moduleUrl)});`,
  ], options), "");
});

test("SSL credentials work from .env and previous environment names remain supported", async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), "ssl-env-test-"));
  try {
    const code = `import { providerEnvironment } from ${JSON.stringify(pathToFileURL(path.join(root, "src/agent/env.ts")).href)};
      console.log(JSON.stringify(await providerEnvironment(${JSON.stringify(dir)})));`;
    const read = (env: NodeJS.ProcessEnv) => JSON.parse(execFileSync(process.execPath,
      ["--import", "tsx", "--input-type=module", "-e", code], { cwd: root, env, encoding: "utf8" }));
    for (const prefix of ["SSL", "SST"]) {
      assert.deepEqual(read({ ...offlineEnvironment(), [`${prefix}_URL`]: "https://example.invalid/v1", [`${prefix}_KEY`]: "test-key" }),
        { baseUrl: "https://example.invalid/v1", apiKey: "test-key" });
    }
    assert.deepEqual(read({ ...offlineEnvironment(), url: "https://example.invalid/v1", key: "test-key" }),
      { baseUrl: "https://example.invalid/v1", apiKey: "test-key" });
    await writeFile(path.join(dir, ".env"), "SSL_URL=https://example.invalid/v1\nSSL_KEY=file-key\n");
    assert.equal(read(offlineEnvironment()).apiKey, "file-key");
    assert.equal(read({ ...offlineEnvironment(), SSL_KEY: "environment-key" }).apiKey, "environment-key");
    assert.equal(read({ ...offlineEnvironment(), SST_KEY: "old-key" }).apiKey, "file-key");
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});
