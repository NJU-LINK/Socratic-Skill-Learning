import { createHash } from "node:crypto";
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";

export interface SkillPackageEntry {
  path: string;
  bytes: number;
  sha256: string;
}

export interface SkillPackageChange {
  path: string;
  change: "added" | "modified" | "deleted";
  beforeSha256?: string;
  afterSha256?: string;
  beforeBytes?: number;
  afterBytes?: number;
}

export async function skillPackageManifest(root: string): Promise<SkillPackageEntry[]> {
  const entries: SkillPackageEntry[] = [];
  async function walk(directory: string): Promise<void> {
    for (const entry of await readdir(directory, { withFileTypes: true })) {
      const full = path.join(directory, entry.name);
      if (entry.isDirectory()) {
        await walk(full);
      } else if (entry.isFile()) {
        const content = await readFile(full);
        entries.push({
          path: path.relative(root, full).split(path.sep).join("/"),
          bytes: content.byteLength,
          sha256: createHash("sha256").update(content).digest("hex"),
        });
      }
    }
  }
  await walk(root);
  return entries.sort((a, b) => a.path.localeCompare(b.path));
}

export function skillPackageSha256(manifest: SkillPackageEntry[]): string {
  return createHash("sha256").update(JSON.stringify(manifest)).digest("hex");
}

export function diffSkillPackages(
  before: SkillPackageEntry[],
  after: SkillPackageEntry[],
): SkillPackageChange[] {
  const prior = new Map(before.map((entry) => [entry.path, entry]));
  const current = new Map(after.map((entry) => [entry.path, entry]));
  const paths = [...new Set([...prior.keys(), ...current.keys()])].sort();
  const changes: SkillPackageChange[] = [];
  for (const filePath of paths) {
    const oldEntry = prior.get(filePath);
    const newEntry = current.get(filePath);
    if (!oldEntry && newEntry) {
      changes.push({
        path: filePath,
        change: "added",
        afterSha256: newEntry.sha256,
        afterBytes: newEntry.bytes,
      });
    } else if (oldEntry && !newEntry) {
      changes.push({
        path: filePath,
        change: "deleted",
        beforeSha256: oldEntry.sha256,
        beforeBytes: oldEntry.bytes,
      });
    } else if (oldEntry && newEntry && oldEntry.sha256 !== newEntry.sha256) {
      changes.push({
        path: filePath,
        change: "modified",
        beforeSha256: oldEntry.sha256,
        afterSha256: newEntry.sha256,
        beforeBytes: oldEntry.bytes,
        afterBytes: newEntry.bytes,
      });
    }
  }
  return changes;
}

export function skillPackageSummary(manifest: SkillPackageEntry[]): {
  sha256: string;
  files: number;
  bytes: number;
  manifest: SkillPackageEntry[];
} {
  return {
    sha256: skillPackageSha256(manifest),
    files: manifest.length,
    bytes: manifest.reduce((total, entry) => total + entry.bytes, 0),
    manifest,
  };
}
