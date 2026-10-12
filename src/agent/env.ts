import { readFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { config as loadDotenv } from "dotenv";

/**
 * Resolve the provider endpoint from the environment.
 *
 * Loads .env from the harness root (or its parent) when present, then reads
 * SSL_URL / SSL_KEY. SST_URL / SST_KEY and lowercase url / key remain accepted
 * for existing deployments.
 */
export async function providerEnvironment(projectRoot: string): Promise<{
  baseUrl: string;
  apiKey: string;
}> {
  const candidates = [
    path.join(projectRoot, ".env"),
    path.resolve(projectRoot, "..", ".env"),
  ];
  const envPath = await Promise.all(
    candidates.map(async (candidate) =>
      await readFile(candidate, "utf8").then(() => candidate).catch(() => undefined)
    ),
  ).then((items) =>
    items.find((item): item is string => item !== undefined) ?? candidates[0]!
  );
  loadDotenv({ path: envPath, quiet: true });
  const baseUrl = process.env.SSL_URL ?? process.env.SST_URL ?? process.env.url;
  const apiKey = process.env.SSL_KEY ?? process.env.SST_KEY ?? process.env.key;
  if (!baseUrl || !apiKey) {
    throw new Error("Set SSL_URL and SSL_KEY in the environment or .env (SST_URL/SST_KEY and lowercase url/key are also accepted)");
  }
  return { baseUrl, apiKey };
}

/** Normalize an OpenAI-compatible base URL: no trailing slash. */
export function normalizeProviderBaseUrl(url: string): string {
  return url.endsWith("/") ? url.slice(0, -1) : url;
}
