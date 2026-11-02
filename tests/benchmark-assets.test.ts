import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { readFile, readdir } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { parse } from "yaml";
import { TaskEnvironment } from "../src/runtime/docker.js";
import { loadScorerPlan } from "../src/runtime/scorer.js";

const benchmark = fileURLToPath(new URL("../benchmark/", import.meta.url));

async function variantDirectories(): Promise<string[]> {
  const variants: string[] = [];
  for (const family of await readdir(benchmark, { withFileTypes: true })) {
    if (!family.isDirectory()) continue;
    for (const variant of await readdir(path.join(benchmark, family.name), { withFileTypes: true })) {
      if (variant.isDirectory() && /^v\d+$/.test(variant.name)) {
        variants.push(path.join(benchmark, family.name, variant.name));
      }
    }
  }
  return variants.sort();
}

test("every released task has a valid, current scorer contract", async () => {
  const variants = await variantDirectories();
  assert.ok(variants.length > 0);
  for (const variant of variants) await loadScorerPlan(variant);
});

test("Compose fallback images and container names remain valid after release sanitization", async () => {
  for (const variant of await variantDirectories()) {
    const filename = path.join(variant, "docker-compose.yaml");
    const source = await readFile(filename, "utf8");
    // Resolve the defaults without inheriting a maintainer's Terminal-Bench
    // environment, which would otherwise hide broken fallback names.
    const defaults = source
      .replace(/\$\{[A-Za-z_][A-Za-z0-9_]*:-([^}]+)\}/g, "$1")
      // Some upstream files require explicit names rather than defaults.
      .replace(/\$\{[A-Za-z_][A-Za-z0-9_]*\}/g, "stb-configured");
    const document = parse(defaults) as { services: Record<string, { image?: string; container_name?: string }> };
    for (const service of Object.values(document.services)) {
      if (service.image) {
        assert.doesNotMatch(service.image, /\s/, `${filename}: image`);
        const repository = service.image.split("@")[0]!.replace(/:[^/:]+$/, "");
        assert.equal(repository, repository.toLowerCase(), `${filename}: image repository must be lowercase`);
      }
      if (service.container_name) {
        assert.match(service.container_name, /^[a-zA-Z0-9][a-zA-Z0-9_.-]+$/, `${filename}: container_name`);
      }
    }
  }
});

// Opt in because the original task image and pytest may need network access:
// SSL_TEST_BENCHMARK_DOCKER=1 node --import tsx --test tests/benchmark-assets.test.ts
test("pypi-server/v15 scores real task outputs through TaskEnvironment", {
  skip: process.env.SSL_TEST_BENCHMARK_DOCKER !== "1",
  timeout: 15 * 60_000,
}, async (t) => {
  const variant = path.join(benchmark, "pypi-server", "v15");
  // A host's loopback proxy is not necessarily reachable inside Docker.
  const proxy = process.env.SSL_TEST_DOCKER_PROXY;
  const environment = new TaskEnvironment(`v15-regression-${randomUUID()}`, true, proxy);
  try {
    await environment.reset("pypi-server", "v15", variant);

    await t.test("an unsolved workspace is a scored failure, not an infrastructure error", async () => {
      const result = await environment.runTests(180);
      assert.equal(result.total, 3);
      assert.equal(result.passed, 0);
      assert.equal(result.failed, 3);
      assert.equal(result.score, 0);
      assert.equal(result.timedOut, false);
      assert.equal(result.exitCode, 1);
    });

    await t.test("the reference solution passes all three original checks", async () => {
      await environment.installReferenceSolution(path.join(variant, "solution.sh"));
      const solution = await environment.shell("cd /app && bash /app/solution.sh", 600);
      assert.equal(solution.exitCode, 0, solution.stderr);
      assert.equal(solution.timedOut, false);
      const result = await environment.runTests(180);
      assert.equal(result.total, 3);
      assert.equal(result.passed, 3);
      assert.equal(result.failed, 0);
      assert.equal(result.score, 1);
      assert.equal(result.exitCode, 0);
    });

    await t.test("an incomplete package index is rejected after a successful reference run", async () => {
      const damage = await environment.shell("rm /app/index-root/simple/vectorops/vectorops-0.1.0.tar.gz", 10);
      assert.equal(damage.exitCode, 0);
      const result = await environment.runTests(180);
      assert.equal(result.total, 3);
      assert.equal(result.passed, 1);
      assert.equal(result.failed, 2);
      assert.equal(result.score, 1 / 3);
      assert.equal(result.timedOut, false);
      assert.equal(result.exitCode, 1);
    });
  } finally {
    await environment.stop();
  }
});
