import { createModels, type ModelBundle } from "./model.js";
import { appendFile, mkdir } from "node:fs/promises";
import path from "node:path";
import { TaskPool } from "../runtime/task-pool.js";
import type { PilotConfig } from "../experiment/types.js";

export function providerCredentials(baseUrl: string, primaryKey: string, env = process.env) {
  const credentials = [{ label: "key-1", baseUrl, apiKey: primaryKey }];
  if (env.key2?.trim()) {
    if (env.key2.trim() === primaryKey.trim()) throw new Error("key2 duplicates key; this would not add capacity");
    credentials.push({ label: "key-2", baseUrl: env.url2?.trim() || baseUrl, apiKey: env.key2.trim() });
  }
  return credentials;
}

export async function createModelPool(config: PilotConfig, baseUrl: string, apiKey: string,
  singleKeyConcurrency = config.cellConcurrency * config.groupConcurrency) {
  const credentials = providerCredentials(baseUrl, apiKey);
  const capacity = Number(process.env.SKILL_KEY_CONCURRENCY
    ?? (credentials.length > 1 ? 2 : singleKeyConcurrency));
  if (!Number.isInteger(capacity) || capacity < 1 || capacity > 32) {
    throw new Error("SKILL_KEY_CONCURRENCY must be an integer between 1 and 32");
  }
  // Independent runtimes: never mutate an active session's API key.
  const bundles = await Promise.all(credentials.map(c => createModels(config, c.baseUrl, c.apiKey)));
  const pool = new TaskPool<ModelBundle>(bundles, capacity);
  await mkdir(config.runsRoot, { recursive: true });
  const log = async (event: string, task: string, index: number) => {
    const line = JSON.stringify({ at: new Date().toISOString(), event, task,
      credential: credentials[index]!.label, pid: process.pid });
    console.log(line);
    await appendFile(path.join(config.runsRoot, "credential-leases.jsonl"), `${line}\n`, "utf8");
  };
  console.log(JSON.stringify({ event: "credential-pool", keys: credentials.length, slotsPerKey: capacity }));
  return {
    primary: bundles[0]!,
    run: <R>(task: string, work: (models: ModelBundle) => Promise<R>) => pool.run(async (models, index) => {
      await log("credential-lease", task, index);
      try { return await work(models); }
      finally { await log("credential-release", task, index); }
    }),
  };
}
