#!/usr/bin/env node
/** Summarize the released Qwen main-cohort scores without model calls or dependencies. */
import { mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";

const METHODS = [
  ["no-skill", "No Skill"],
  ["expert-authoring", "Expert Authoring"],
  ["post-hoc-teaching", "Post-hoc Teaching"],
  ["trace2skill", "Trace2Skill"],
  ["skill-kd", "SKILL-KD"],
  ["fixed-window-ssl", "Fixed-Window SSL"],
  ["issue-guided-ssl", "Issue-Guided SSL"],
];
const REPLICATES = [1, 2, 3];
const HELP = `Summarize the released Qwen main comparison (22 families, 155 held-out cases).

Usage: node scripts/summarize-main.mjs [--records PATH] [--out summary.csv]

  --records PATH  Qwen main-cohort directory (default: experiments/main/qwen)
  --out PATH      Also write a CSV with each replicate's macro utility and Avg@3

Scores are averaged within each family, then equally across families, then
across the three independent runs. This reads only meta.json; no API,
Docker, npm dependencies, or session transcripts are required.`;

function mean(values) {
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

async function directoryNames(directory) {
  return (await readdir(directory, { withFileTypes: true }))
    .filter((entry) => entry.isDirectory())
    .map((entry) => entry.name).sort();
}

function sameNames(actual, expected, description) {
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    const missing = expected.filter((name) => !actual.includes(name));
    const extra = actual.filter((name) => !expected.includes(name));
    throw new Error(`${description}: missing [${missing.join(", ")}], extra [${extra.join(", ")}]`);
  }
}

async function heldoutScores(root, method, replicate, family) {
  const file = path.join(root, method, `r${replicate}`, family, "meta.json");
  const meta = JSON.parse(await readFile(file, "utf8"));
  if (meta.method !== method || meta.round !== replicate || meta.family !== family) {
    throw new Error(`Method, round, or family does not match its directory: ${file}`);
  }
  const heldout = meta.stats?.heldout;
  if (!heldout || typeof heldout !== "object" || Array.isArray(heldout)) {
    throw new Error(`Missing stats.heldout: ${file}`);
  }
  const variants = Object.keys(heldout).sort();
  if (variants.length === 0) throw new Error(`No held-out scores: ${file}`);
  for (const variant of variants) {
    const score = heldout[variant]?.score;
    if (typeof score !== "number" || !Number.isFinite(score) || score < 0 || score > 1) {
      throw new Error(`Missing or invalid score for ${variant}: ${file}`);
    }
  }
  // Transcript availability (records/empty) does not affect the recorded score.
  return { variants, utility: mean(variants.map((variant) => heldout[variant].score)) };
}

function csvCell(value) {
  const text = String(value);
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

async function main() {
  const { values } = parseArgs({ options: {
    records: { type: "string" }, traj: { type: "string" },
    out: { type: "string" }, help: { type: "boolean" },
  } });
  if (values.help) {
    console.log(HELP);
    return;
  }
  if (values.records !== undefined && values.traj !== undefined) {
    throw new Error("Use --records or its legacy alias --traj, not both.");
  }
  const records = values.records ?? values.traj;
  const root = records !== undefined
    ? path.resolve(records)
    : fileURLToPath(new URL("../experiments/main/qwen/", import.meta.url));
  const families = await directoryNames(path.join(root, "no-skill", "r1"));
  if (families.length !== 22) {
    throw new Error(`Expected the 22-family Qwen main cohort; found ${families.length} families under ${root}`);
  }
  const expectedVariants = new Map();
  for (const family of families) {
    expectedVariants.set(family, (await heldoutScores(root, "no-skill", 1, family)).variants);
  }
  const cases = [...expectedVariants.values()].reduce((sum, variants) => sum + variants.length, 0);
  if (cases !== 155) {
    throw new Error(`Expected 155 held-out cases per replicate; found ${cases} under ${root}`);
  }

  const rows = [];
  for (const [method, label] of METHODS) {
    const utilities = [];
    for (const replicate of REPLICATES) {
      const directory = path.join(root, method, `r${replicate}`);
      sameNames(await directoryNames(directory), families, `Family coverage for ${method} r${replicate}`);
      const familyUtilities = [];
      for (const family of families) {
        const scores = await heldoutScores(root, method, replicate, family);
        sameNames(scores.variants, expectedVariants.get(family), `Case coverage for ${method} r${replicate} ${family}`);
        familyUtilities.push(scores.utility);
      }
      utilities.push(mean(familyUtilities));
    }
    rows.push({ method, label, utilities, avgAt3: mean(utilities) });
  }

  console.log(`Released Qwen main comparison: ${families.length} families, ${cases} cases per replicate, 3 replicates`);
  console.log("Utility: mean cases within family → mean families → mean replicates (Avg@3).\n");
  console.log(`${"Method".padEnd(22)} ${"r1".padStart(10)} ${"r2".padStart(10)} ${"r3".padStart(10)} ${"Avg@3".padStart(10)}`);
  for (const row of rows) {
    console.log(`${row.label.padEnd(22)} ${[...row.utilities, row.avgAt3].map((value) => value.toFixed(6).padStart(10)).join(" ")}`);
  }
  if (values.out !== undefined) {
    const output = path.resolve(values.out);
    const columns = ["method", "label", "families", "cases_per_replicate", "replicates", "r1", "r2", "r3", "avg_at_3"];
    const lines = [columns, ...rows.map((row) => [
      row.method, row.label, families.length, cases, REPLICATES.length, ...row.utilities, row.avgAt3,
    ])].map((row) => row.map(csvCell).join(","));
    await mkdir(path.dirname(output), { recursive: true });
    await writeFile(output, `${lines.join("\n")}\n`, "utf8");
    console.log(`\nCSV written to ${output}`);
  }
}

await main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
});
