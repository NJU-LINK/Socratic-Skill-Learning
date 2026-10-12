import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

function packageManifest(source: NodeRequire, name: string): string {
  // Pi exposes import-only entry points. Locate its metadata through Node's
  // package search paths without requiring an unavailable CommonJS export.
  for (const directory of source.resolve.paths(name) ?? []) {
    const file = path.join(directory, name, "package.json");
    try {
      if (JSON.parse(readFileSync(file, "utf8")).name === name) return file;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
    }
  }
  throw new Error(`Cannot locate installed package ${name}`);
}

function packageVersion(entry: string, name: string): string {
  let directory = path.dirname(entry);
  while (true) {
    try {
      const metadata = JSON.parse(readFileSync(path.join(directory, "package.json"), "utf8"));
      if (metadata.name === name) return metadata.version;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
    }
    const parent = path.dirname(directory);
    if (parent === directory) throw new Error(`Cannot locate installed package ${name}`);
    directory = parent;
  }
}

test("the pinned Pi runtime actually resolves the patched dependencies", () => {
  const fromRoot = createRequire(import.meta.url);
  const piEntry = fileURLToPath(import.meta.resolve("@earendil-works/pi-coding-agent"));
  assert.equal(packageVersion(piEntry, "@earendil-works/pi-coding-agent"), "0.81.1");
  const fromPi = createRequire(piEntry);
  const aiEntry = packageManifest(fromPi, "@earendil-works/pi-ai");
  assert.equal(packageVersion(aiEntry, "@earendil-works/pi-ai"), "0.81.1");
  assert.equal(packageVersion(fromPi.resolve("undici"), "undici"), "8.10.2");

  const fromMinimatch = createRequire(fromPi.resolve("minimatch"));
  assert.equal(packageVersion(fromMinimatch.resolve("brace-expansion"), "brace-expansion"), "5.0.12");

  // Check the nested AI SDK too: an upstream shrinkwrap can leave a second,
  // vulnerable copy installed even when the root lockfile appears patched.
  for (const source of [fromRoot, fromPi]) {
    const fromAi = createRequire(packageManifest(source, "@earendil-works/pi-ai"));
    const fromGoogle = createRequire(fromAi.resolve("@google/genai"));
    assert.equal(packageVersion(fromGoogle.resolve("protobufjs"), "protobufjs"), "7.6.6");
  }
});
