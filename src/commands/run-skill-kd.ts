import { parseArgs } from "node:util";
import path from "node:path";
import { createModels } from "../agent/model.js";
import { selectFamilies } from "../experiment/config.js";
import { requireSuccess, runProcess } from "../runtime/process.js";
import { loadSkillKdConfig, positiveInteger, skillKdRunId } from "../baselines/skill-kd-config.js";
import { sha256, skillKdProvider } from "../baselines/skill-kd-rollout.js";
import { setupSkillKdUpstream, skillKdPythonEnv, validateSkillKdUpstream } from "../baselines/skill-kd-upstream.js";
import { mapSkillKdLimit, SkillKdRunner, summarizeSkillKd, type SkillKdRunSummary } from "../baselines/skill-kd.js";
import { readJsonIfExists, writeJson } from "../baselines/trace2skill-io.js";

async function main(): Promise<void> {
  const { values, positionals } = parseArgs({ allowPositionals: true, options: {
    config: { type: "string" }, family: { type: "string" }, replicate: { type: "string" },
    phase: { type: "string" }, "family-concurrency": { type: "string" },
    "dry-run": { type: "boolean" }, help: { type: "boolean" },
  } });
  if (values.help) {
    console.log("npm run ssl -- skill-kd setup|plan|validate|test|run|summary [--config PATH] [--family a,b] [--replicate 1,2,3] [--phase induce|evaluate|all] [--family-concurrency N] [--dry-run]");
    return;
  }
  const command = positionals[0] ?? "plan";
  if (positionals.length > 1 || !["setup", "plan", "validate", "test", "run", "summary"].includes(command)) {
    throw new Error("Expected setup|plan|validate|test|run|summary; use --help");
  }
  const config = await loadSkillKdConfig(values.config);
  const comma = (value: string | undefined) => value?.split(",").map((s) => s.trim()).filter(Boolean) ?? [];
  const names = comma(values.family);
  if (values.family !== undefined && !names.length) throw new Error("--family cannot be empty");
  if (new Set(names).size !== names.length) throw new Error("Duplicate --family selection");
  const families = selectFamilies(config.experimentConfig, names);
  const replicateValues = comma(values.replicate);
  if (values.replicate !== undefined && !replicateValues.length) throw new Error("--replicate cannot be empty");
  const replicates = replicateValues.length
    ? replicateValues.map((v) => positiveInteger(v, "--replicate", config.replicates)) : [1, 2, 3];
  if (new Set(replicates).size !== replicates.length) throw new Error("Duplicate --replicate selection");
  const phase = values.phase ?? "all";
  if (!["induce", "evaluate", "all"].includes(phase)) throw new Error("--phase must be induce|evaluate|all");
  const concurrency = positiveInteger(values["family-concurrency"] ?? config.familyConcurrency, "--family-concurrency", 8);
  const cells = replicates.flatMap((replicate) => families.map((family) => ({ family, replicate })));
  const plan = {
    protocolVersion: config.protocolVersion, upstreamCommit: config.upstreamCommit,
    families: families.map((f) => f.name), replicates, runs: cells.length, phase,
    anchorPasses: config.anchorPasses, maxAdaptiveRoundsPerPass: config.maxAdaptiveRounds,
    maxStudentRolloutsPerRun: config.anchorPasses * (1 + config.maxAdaptiveRounds),
    maxTeacherRolloutsPerRun: config.anchorPasses,
    familyConcurrency: concurrency, heldoutVariantConcurrency: config.heldoutVariantConcurrency,
    rawHeldoutOutcomes: families.reduce((sum, f) => sum + f.heldout.length, 0) * replicates.length,
    analysisExclusions: config.analysisExclusions, runsRoot: config.runsRoot,
    provider: config.experimentConfig.provider,
  };
  if (command === "plan" || values["dry-run"]) {
    console.log(JSON.stringify(plan, null, 2));
    return;
  }
  if (command === "setup") {
    await setupSkillKdUpstream(config);
    console.log("Pinned SKILL-KD checkout and Python environment are ready.");
    return;
  }
  if (command === "validate" || command === "test") {
    await validateSkillKdUpstream(config);
    if (command === "test") {
      requireSuccess(await runProcess(path.join(config.pythonVenv, "bin", "python"), [
        "-m", "unittest", "discover", "-s", "scripts/skill-kd", "-p", "test_*.py", "-v",
      ], { cwd: config.projectRoot, env: skillKdPythonEnv(config), inherit: true }), "offline SKILL-KD integration tests");
    }
    console.log(JSON.stringify({ validated: true, ...plan }, null, 2));
    return;
  }
  let summaries: SkillKdRunSummary[];
  if (command === "summary") {
    summaries = await Promise.all(cells.map(async ({ family, replicate }) => {
      const file = path.join(config.runsRoot, skillKdRunId(family.name, replicate), "run-summary.json");
      const row = await readJsonIfExists<SkillKdRunSummary>(file);
      if (!row) throw new Error(`Evaluation incomplete: ${file}`);
      if (row.protocolVersion !== config.protocolVersion) throw new Error(`Wrong protocol: ${file}`);
      return row;
    }));
  } else {
    await validateSkillKdUpstream(config);
    const provider = await skillKdProvider(config.projectRoot);
    const models = await createModels(config.experimentConfig, provider.baseUrl, provider.apiKey);
    const runner = new SkillKdRunner(config, models, provider);
    summaries = await mapSkillKdLimit(cells, concurrency,
      async ({ family, replicate }) => runner.runFamily(family, replicate, phase as "induce" | "evaluate" | "all"));
  }
  const metrics = phase === "induce" && command !== "summary" ? null
    : summarizeSkillKd(summaries, families, replicates, config.analysisExclusions);
  // All 22 names exceed common filesystem component limits when selecting only
  // one replicate. Keep the full selection in the JSON, with a bounded filename.
  const familyLabel = families.length <= 2 ? families.map((f) => f.name).join("+")
    : `${families.length}families-${sha256(JSON.stringify(families.map((f) => f.name))).slice(0, 12)}`;
  const selection = families.length === config.experimentConfig.families.length && replicates.length === config.replicates
    ? "full" : `${familyLabel}-r${replicates.join("+")}`;
  const output = path.join(config.runsRoot, `matrix-${command === "summary" ? "summary" : phase}-${selection}.json`);
  await writeJson(output, { generatedAt: new Date().toISOString(), plan, metrics, summaries });
  console.log(JSON.stringify({ complete: true, output, metrics }, null, 2));
}

await main();
