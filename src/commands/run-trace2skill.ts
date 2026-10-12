import path from "node:path";
import process from "node:process";
import { providerEnvironment } from "../agent/env.js";
import { createModels, normalizeProviderBaseUrl } from "../agent/model.js";
import {
  Trace2SkillBaselineRunner,
  loadTrace2SkillConfig,
  setupTrace2SkillUpstream,
  summarizeTrace2SkillMatrix,
  trace2SkillRunRoot,
  validateTrace2SkillUpstream,
  writeJson,
} from "../baselines/trace2skill.js";
import { selectFamilies } from "../experiment/config.js";

type Command = "setup" | "validate" | "run";

function option(argv: string[], name: string): string | undefined {
  const index = argv.indexOf(name);
  return index >= 0 ? argv[index + 1] : undefined;
}

function commaList(value: string | undefined): string[] {
  return value?.split(",").map((item) => item.trim()).filter(Boolean) ?? [];
}

function positiveInteger(raw: string | undefined, fallback: number, label: string): number {
  const value = Number(raw ?? fallback);
  if (!Number.isInteger(value) || value < 1) throw new Error(`${label} must be a positive integer`);
  return value;
}

async function main(): Promise<void> {
  const argv = process.argv.slice(2);
  const HELP = "npm run ssl -- trace2skill setup|validate|run [--config PATH] [--family a,b] [--replicate 1,2,3] [--phase induce|evaluate|all] [--family-concurrency N] [--dry-run]";
  if (argv.includes("--help")) {
    console.log(HELP);
    return;
  }
  const command = (argv[0] ?? "validate") as Command;
  if (!["setup", "validate", "run"].includes(command)) {
    throw new Error(`Usage: ${HELP}`);
  }
  const config = await loadTrace2SkillConfig(option(argv, "--config") ?? "configs/trace2skill-baseline.yaml");

  if (command === "setup") {
    await setupTrace2SkillUpstream(config);
    console.log(JSON.stringify({
      ready: true,
      upstreamCheckout: config.upstreamCheckout,
      upstreamCommit: config.upstreamCommit,
      pythonVenv: config.pythonVenv,
    }, null, 2));
    return;
  }

  await validateTrace2SkillUpstream(config);
  const familyNames = commaList(option(argv, "--family"));
  const families = selectFamilies(config.experimentConfig, familyNames);
  const replicateOption = commaList(option(argv, "--replicate"));
  const replicates = replicateOption.length > 0
    ? replicateOption.map((value) => positiveInteger(value, 1, "--replicate"))
    : Array.from({ length: config.replicates }, (_, index) => index + 1);
  if (new Set(replicates).size !== replicates.length || replicates.some((value) => value > config.replicates)) {
    throw new Error(`--replicate must select unique values from 1..${config.replicates}`);
  }
  const phase = option(argv, "--phase") ?? "all";
  if (phase !== "induce" && phase !== "evaluate" && phase !== "all") {
    throw new Error("--phase must be induce, evaluate, or all");
  }
  const familyConcurrency = positiveInteger(
    option(argv, "--family-concurrency"),
    config.familyConcurrency,
    "--family-concurrency",
  );
  if (familyConcurrency > 8) throw new Error("--family-concurrency must not exceed 8");
  const description = {
    protocolVersion: config.protocolVersion,
    upstreamRepository: config.upstreamRepository,
    upstreamCommit: config.upstreamCommit,
    families: families.map((family) => family.name),
    replicates,
    tracesPerFamily: config.tracesPerFamily,
    phase,
    familyConcurrency,
    trajectoryConcurrency: config.trajectoryConcurrency,
    heldoutVariantConcurrency: config.heldoutVariantConcurrency,
    runs: replicates.flatMap((replicate) => families.map((family) => ({
      family: family.name,
      replicate,
      runRoot: trace2SkillRunRoot(config, family.name, replicate),
    }))),
  };
  if (command === "validate" || argv.includes("--dry-run")) {
    console.log(JSON.stringify(description, null, 2));
    return;
  }

  const environment = await providerEnvironment(config.projectRoot);
  const provider = { ...environment, baseUrl: normalizeProviderBaseUrl(environment.baseUrl) };
  const models = await createModels(config.experimentConfig, provider.baseUrl, provider.apiKey);
  const summaries = await new Trace2SkillBaselineRunner(config, models, provider).runMatrix({
    families,
    replicates,
    phase,
    familyConcurrency,
  });
  const output = path.join(config.runsRoot, `matrix-${phase}-summary.json`);
  const metrics = phase === "induce"
    ? null
    : summarizeTrace2SkillMatrix(summaries, families, replicates);
  await writeJson(output, {
    generatedAt: new Date().toISOString(),
    ...description,
    metrics,
    summaries,
  });
  console.log(JSON.stringify({ complete: true, output, runs: summaries.length, metrics }, null, 2));
}

await main();
