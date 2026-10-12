#!/usr/bin/env node
/**
 * ssl — Socratic Skill Learning harness CLI.
 *
 * Two decoupled stages that can run independently or together:
 *   acquire  : run skill acquisition (teaching protocols or baselines)
 *   evaluate : evaluate frozen packages on held-out variants
 *   run      : acquire then evaluate
 *
 * Scope selects the evaluation set: full | main | lite, or a custom YAML path.
 * Methods: expert-authoring, post-hoc-teaching, fixed-window-ssl, issue-guided-ssl, no-skill, trace2skill, skill-kd.
 */
import { parseArgs } from "node:util";
import path from "node:path";
import process from "node:process";
import { acquire, evaluate } from "./runner.js";
import { METHOD_LABELS, METHOD_NAMES, parseMethods } from "./methods.js";

const SCOPES = new Set(["full", "main", "lite"]);
const MODELS = new Set(["qwen", "deepseek", "kimi"]);

function option(name: string): string | undefined {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] : undefined;
}

function list(value: string | undefined): string[] {
  return value?.split(",").map((item) => item.trim()).filter(Boolean) ?? [];
}

function scopeConfigPath(scope: string | undefined): string {
  const value = scope ?? "main";
  if (SCOPES.has(value)) {
    return configAsset("scopes", `${value}.yaml`);
  }
  return path.resolve(value);
}

function modelConfigPath(model: string | undefined): string {
  const value = model ?? "qwen";
  if (MODELS.has(value)) {
    return configAsset("models", `${value}.yaml`);
  }
  return path.resolve(value);
}

function configAsset(kind: "scopes" | "models", file: string): string {
  const here = path.resolve(path.dirname(new URL(import.meta.url).pathname));
  return path.resolve(here, "..", "configs", kind, file);
}

function commonOptions() {
  const parsed = parseArgs({
    allowPositionals: true,
    options: {
      scope: { type: "string" },
      model: { type: "string" },
      bench: { type: "string" },
      methods: { type: "string" },
      families: { type: "string" },
      replicates: { type: "string" },
      frozen: { type: "string" },
      runs: { type: "string" },
      "dry-run": { type: "boolean" },
      help: { type: "boolean" },
    },
  });
  return parsed.values;
}

function replicatesOf(values: { replicates?: string }): number[] | undefined {
  const items = list(values.replicates).map(Number);
  if (values.replicates !== undefined && items.length === 0) throw new Error("--replicates cannot be empty");
  return items.length ? items : undefined;
}

const HELP = `ssl — Socratic Skill Learning harness

Usage:
  ssl run      --scope main|lite|full|<yaml> --model qwen|deepseek|kimi|<yaml>
                [--methods fixed-window-ssl,post-hoc-teaching] [--families a,b] [--replicates 1,2]
                [--bench <dir>] [--dry-run]      acquire then evaluate
  ssl acquire  [same options]                     only run acquisition
  ssl evaluate [same options] [--runs <dir>] [--frozen <cohortRoot>]
                                                 only evaluation; --frozen points at a
                                                 experiment cohort (e.g.
                                                 experiments/cross-model/deepseek)
  ssl trace2skill <command> [options]             baseline pipeline; see --help
  ssl skill-kd <command> [options]                baseline pipeline; see --help

Scopes (families/held-out cases) live in configs/scopes: main.yaml (22/155),
lite.yaml (10/77), full.yaml (35/373); copy custom.example.yaml for your own.
Models (what to run with) live in configs/models: qwen.yaml, deepseek.yaml,
kimi.yaml; copy custom.example.yaml for any OpenAI-compatible endpoint.

Methods (paper name: command / trajectory identifier):
${METHOD_NAMES.map((name) => `  ${METHOD_LABELS[name]}: ${name}`).join("\n")}
Trace2Skill and SKILL-KD use their separate commands above.
Legacy method aliases: compile-after, teach-after, ist, issueist.

Environment: SSL_URL / SSL_KEY (endpoint), optional DOCKER_PROXY, HTTPS_PROXY.
Previous SST_URL / SST_KEY settings and the npm script sst remain supported.`;

async function main(): Promise<void> {
  const positional = process.argv[2] ?? "run";
  const forwarded = process.argv.slice(3);
  if (positional === "--help" || positional === "help" || (forwarded.includes("--help") && positional !== "trace2skill" && positional !== "skill-kd")) {
    console.log(HELP);
    return;
  }
  if (positional === "trace2skill") {
    process.argv = [process.argv[0]!, "run-trace2skill", ...forwarded];
    await import("./commands/run-trace2skill.js");
    return;
  }
  if (positional === "skill-kd") {
    process.argv = [process.argv[0]!, "run-skill-kd", ...forwarded];
    await import("./commands/run-skill-kd.js");
    return;
  }
  if (!["run", "acquire", "evaluate"].includes(positional)) {
    throw new Error(`Unknown command ${positional}; see ssl --help`);
  }
  const values = commonOptions();
  const methods = parseMethods(values.methods);
  const families = list(values.families);
  if (values.families !== undefined && families.length === 0) throw new Error("--families cannot be empty");
  const replicates = replicatesOf(values);
  const shared = {
    configPath: scopeConfigPath(values.scope),
    modelPath: modelConfigPath(option("--model")),
    ...(option("--bench") ? { benchRoot: path.resolve(option("--bench")!) } : {}),
    methods,
    ...(families.length ? { families } : {}),
    ...(replicates ? { replicates } : {}),
    dryRun: values["dry-run"] ?? false,
  };
  if (positional === "acquire") {
    await acquire(shared);
    return;
  }
  if (positional === "evaluate") {
    const frozen = values.frozen ?? option("--frozen");
    if (values["dry-run"]) {
      console.log(`[evaluate] scope: ${shared.configPath}`);
      console.log(`[evaluate] model: ${shared.modelPath}`);
      console.log(`[evaluate] methods: ${methods.join(", ")}`);
      if (frozen) console.log(`[evaluate] frozen root: ${path.resolve(frozen)}`);
      return;
    }
    await evaluate({
      ...shared,
      ...(option("--runs") ? { runsRoot: path.resolve(option("--runs")!) } : {}),
      ...(frozen ? { frozenRoot: path.resolve(frozen) } : {}),
    });
    return;
  }
  if (values["dry-run"]) {
    await acquire(shared);
    return;
  }
  await acquire(shared);
  await evaluate(shared);
}

await main().catch((error: unknown) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
});
