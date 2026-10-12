#!/usr/bin/env node
/** Optional maintenance command for publishing records from completed raw runs. */
import path from "node:path";
import process from "node:process";
import { pathToFileURL } from "node:url";
import { parseArgs } from "node:util";
import { exportRunsRoot } from "./lib/record-export.js";

export async function main(args: string[] = process.argv.slice(2)): Promise<void> {
  const { values } = parseArgs({
    args,
    options: {
      runs: { type: "string" },
      out: { type: "string" },
      help: { type: "boolean" },
    },
  });
  if (values.help) {
    console.log("Usage: node --import tsx scripts/export-records.ts --runs <dir> --out <dir>");
    return;
  }
  if (!values.runs || !values.out) throw new Error("export requires --runs <dir> and --out <dir>");
  const outRoot = path.resolve(values.out);
  const totals = await exportRunsRoot(path.resolve(values.runs), outRoot);
  console.log(`[export] files=${totals.files} records=${totals.records} -> ${outRoot}`);
}

if (process.argv[1] && pathToFileURL(path.resolve(process.argv[1])).href === import.meta.url) {
  await main().catch((error: unknown) => {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  });
}
