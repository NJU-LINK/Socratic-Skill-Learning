import { createHash } from "node:crypto";
import { readFile, readdir, stat } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { runProcess } from "../runtime/process.js";
import type { PilotConfig } from "./types.js";

export interface ExperimentProvenance {
  schemaVersion: 1;
  protocolVersion: string;
  git: {
    commit: string;
    dirty: boolean;
    statusSha256: string;
  };
  configSha256: string;
  packageJsonSha256: string;
  packageLockSha256: string;
  implementationSha256: string;
  implementationFiles: Record<string, string>;
  promptSourceSha256: string;
  sourceManifestSha256: string;
  specAuditSha256: string;
  scorerManifestSha256: string;
  scorerPolicySha256: string;
  familyAssets: Record<string, string>;
  sourceRevision: string | null;
  lockSha256: string;
}

function sha256(value: string | Buffer): string {
  return createHash("sha256").update(value).digest("hex");
}

async function filesUnder(root: string): Promise<string[]> {
  const files: string[] = [];
  const walk = async (directory: string): Promise<void> => {
    for (const entry of await readdir(directory, { withFileTypes: true })) {
      const absolute = path.join(directory, entry.name);
      if (entry.isDirectory()) await walk(absolute);
      else if (entry.isFile()) files.push(absolute);
    }
  };
  await walk(root);
  return files.sort();
}

async function treeSha256(root: string): Promise<string> {
  const digest = createHash("sha256");
  for (const absolute of await filesUnder(root)) {
    const relative = path.relative(root, absolute).split(path.sep).join("/");
    const metadata = await stat(absolute);
    digest.update(relative);
    digest.update("\0");
    digest.update(String(metadata.mode & 0o777));
    digest.update("\0");
    digest.update(await readFile(absolute));
    digest.update("\0");
  }
  return digest.digest("hex");
}

async function gitState(projectRoot: string): Promise<ExperimentProvenance["git"]> {
  const [commit, status] = await Promise.all([
    runProcess("git", ["rev-parse", "HEAD"], { cwd: projectRoot, timeoutMs: 30_000 }),
    runProcess("git", ["status", "--porcelain=v1", "--untracked-files=normal"], {
      cwd: projectRoot,
      timeoutMs: 30_000,
    }),
  ]);
  if (commit.exitCode !== 0 || status.exitCode !== 0) {
    throw new Error(`Cannot resolve experiment Git state:\n${commit.stderr}\n${status.stderr}`);
  }
  const statusText = status.stdout;
  return {
    commit: commit.stdout.trim(),
    dirty: statusText.trim().length > 0,
    statusSha256: sha256(statusText),
  };
}

export async function implementationProvenance(
  config: PilotConfig,
): Promise<ExperimentProvenance> {
  const srcRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
  const implementationFiles = (await filesUnder(srcRoot))
    .filter((file) => file.endsWith(".ts") && !file.endsWith(".test.ts"))
    .map((file) => path.relative(srcRoot, file).split(path.sep).join("/"))
    .sort();
  const contents = await Promise.all(implementationFiles.map(async (name) => ({
    name,
    text: await readFile(path.join(srcRoot, name), "utf8"),
  })));
  const sourceManifestText = await readFile(path.join(config.assetsRoot, "source-manifest.json"), "utf8");
  const sourceManifest = JSON.parse(sourceManifestText) as { sourceRevision?: string };
  const specAuditText = await readFile(path.join(config.assetsRoot, "spec-audit.json"), "utf8");
  const scorerManifestText = await readFile(path.join(config.assetsRoot, "scorer-manifest.json"), "utf8");
  const scorerPolicyText = await readFile(path.join(config.projectRoot, "configs", "scorer-policy.json"), "utf8");
  const implementationFileHashes = Object.fromEntries(
    contents.map((item) => [item.name, sha256(item.text)]),
  );
  const familyAssets = Object.fromEntries(await Promise.all(
    config.families.map(async (family) => [
      family.name,
      await treeSha256(path.join(config.assetsRoot, family.name)),
    ]),
  ));
  const locked = {
    schemaVersion: 1 as const,
    protocolVersion: config.protocolVersion,
    git: await gitState(config.projectRoot),
    configSha256: sha256(await readFile(config.configPath)),
    packageJsonSha256: sha256(await readFile(path.join(config.projectRoot, "package.json"))),
    packageLockSha256: sha256(await readFile(path.join(config.projectRoot, "package-lock.json"))),
    implementationSha256: sha256(contents.map((item) => `${item.name}\n${item.text}`).join("\n")),
    implementationFiles: implementationFileHashes,
    promptSourceSha256: implementationFileHashes["agent/prompts.ts"] ?? "",
    sourceManifestSha256: sha256(sourceManifestText),
    specAuditSha256: sha256(specAuditText),
    scorerManifestSha256: sha256(scorerManifestText),
    scorerPolicySha256: sha256(scorerPolicyText),
    familyAssets,
    sourceRevision: sourceManifest.sourceRevision ?? null,
  };
  return {
    ...locked,
    lockSha256: sha256(JSON.stringify(locked)),
  };
}
