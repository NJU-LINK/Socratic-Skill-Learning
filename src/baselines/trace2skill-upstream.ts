import { access, cp, mkdir, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { skillPackageManifest, skillPackageSha256 } from "../agent/skill-package.js";
import { validateSkill } from "../experiment/orchestrator.js";
import type { FamilyConfig } from "../experiment/types.js";
import { requireSuccess, runProcess } from "../runtime/process.js";
import { readJsonIfExists, writeJson } from "./trace2skill-io.js";
import type { Trace2SkillConfig, Trace2SkillRecord } from "./trace2skill-types.js";

function normalizedGitUrl(value: string): string {
  return value.trim().replace(/\/$/, "").replace(/\.git$/, "");
}

export async function validateTrace2SkillUpstream(config: Trace2SkillConfig): Promise<void> {
  const origin = await runProcess("git", ["remote", "get-url", "origin"], { cwd: config.upstreamCheckout });
  requireSuccess(origin, "read Trace2Skill origin");
  if (normalizedGitUrl(origin.stdout) !== normalizedGitUrl(config.upstreamRepository)) {
    throw new Error(`Trace2Skill origin is ${origin.stdout.trim()}, expected ${config.upstreamRepository}`);
  }
  const commit = await runProcess("git", ["rev-parse", "HEAD"], { cwd: config.upstreamCheckout });
  requireSuccess(commit, "read Trace2Skill upstream commit");
  if (commit.stdout.trim() !== config.upstreamCommit) {
    throw new Error(`Trace2Skill checkout is ${commit.stdout.trim()}, expected ${config.upstreamCommit}`);
  }
  const trackedDiff = await runProcess("git", ["diff", "--quiet", "HEAD", "--"], { cwd: config.upstreamCheckout });
  if (trackedDiff.exitCode !== 0) throw new Error("Trace2Skill tracked files differ from the pinned upstream commit");
  const status = await runProcess("git", ["status", "--porcelain", "--untracked-files=all"], {
    cwd: config.upstreamCheckout,
  });
  requireSuccess(status, "inspect Trace2Skill checkout status");
  const unexpected = status.stdout.split("\n").map((line) => line.trim()).filter(Boolean)
    .filter((line) => !line.endsWith("skills/skill-creator/scripts/quick_validate.py"));
  if (unexpected.length > 0) {
    throw new Error(`Trace2Skill checkout contains unexpected files:\n${unexpected.join("\n")}`);
  }
  const python = path.join(config.pythonVenv, "bin", "python");
  await access(python);
  await access(path.join(config.upstreamCheckout, "skills", "skill-creator", "scripts", "quick_validate.py"));
  const imports = await runProcess(
    python,
    ["-c", "import openai,tqdm,diskcache,requests,yaml; print('trace2skill-python-ok')"],
    { cwd: config.upstreamCheckout },
  );
  requireSuccess(imports, "validate Trace2Skill Python environment");
  const help = await runProcess(
    python,
    ["-m", "skill_evolver.run_parallel_combined_skill_evolution", "--help"],
    { cwd: config.upstreamCheckout },
  );
  requireSuccess(help, "validate official Trace2Skill CLI");
}

export async function setupTrace2SkillUpstream(config: Trace2SkillConfig): Promise<void> {
  const present = await access(path.join(config.upstreamCheckout, ".git")).then(() => true).catch(() => false);
  if (!present) {
    await mkdir(path.dirname(config.upstreamCheckout), { recursive: true });
    requireSuccess(
      await runProcess("git", ["clone", config.upstreamRepository, config.upstreamCheckout], { inherit: true }),
      "clone official Trace2Skill repository",
    );
  }
  const currentHead = await runProcess("git", ["rev-parse", "--verify", "HEAD"], { cwd: config.upstreamCheckout });
  if (currentHead.exitCode === 0) {
    const trackedClean = await runProcess("git", ["diff", "--quiet", "HEAD", "--"], { cwd: config.upstreamCheckout });
    if (trackedClean.exitCode !== 0) {
      throw new Error("Refusing to change a Trace2Skill checkout with tracked local modifications");
    }
  }
  requireSuccess(
    await runProcess("git", ["fetch", "origin", config.upstreamCommit], { cwd: config.upstreamCheckout, inherit: true }),
    "fetch pinned Trace2Skill commit",
  );
  requireSuccess(
    await runProcess("git", ["checkout", "--detach", config.upstreamCommit], { cwd: config.upstreamCheckout, inherit: true }),
    "checkout pinned Trace2Skill commit",
  );
  const python = path.join(config.pythonVenv, "bin", "python");
  if (!(await access(python).then(() => true).catch(() => false))) {
    await mkdir(path.dirname(config.pythonVenv), { recursive: true });
    requireSuccess(await runProcess("python3", ["-m", "venv", config.pythonVenv], { inherit: true }), "create venv");
  }
  requireSuccess(
    await runProcess(python, ["-m", "pip", "install", "-r", path.join(
      config.projectRoot,
      "scripts",
      "trace2skill",
      "requirements.txt",
    )], { inherit: true }),
    "install Trace2Skill Python dependencies",
  );
  const shimTarget = path.join(config.upstreamCheckout, "skills", "skill-creator", "scripts", "quick_validate.py");
  await mkdir(path.dirname(shimTarget), { recursive: true });
  await cp(path.join(config.projectRoot, "scripts", "trace2skill", "quick_validate.py"), shimTarget);
  await validateTrace2SkillUpstream(config);
}

export async function evolveTracePool(options: {
  config: Trace2SkillConfig;
  family: FamilyConfig;
  runRoot: string;
  seedPackage: string;
  errorRecords: Trace2SkillRecord[];
  successRecords: Trace2SkillRecord[];
  baseUrl: string;
  apiKey: string;
}): Promise<string> {
  const finalPackage = path.join(
    options.runRoot,
    "snapshots",
    `iteration-${options.config.tracesPerFamily}`,
    "skill",
    options.family.name,
  );
  const completion = await readJsonIfExists<{ packageSha256: string }>(
    path.join(options.runRoot, "evolution", "complete.json"),
  );
  if (completion) {
    const manifest = await skillPackageManifest(finalPackage);
    if (skillPackageSha256(manifest) !== completion.packageSha256) {
      throw new Error(`Frozen Trace2Skill package changed after evolution: ${finalPackage}`);
    }
    return finalPackage;
  }
  const evolutionRoot = path.join(options.runRoot, "evolution");
  const workPackage = path.join(evolutionRoot, "work", options.family.name);
  await rm(path.join(evolutionRoot, "work"), { recursive: true, force: true });
  await mkdir(path.dirname(workPackage), { recursive: true });
  await cp(options.seedPackage, workPackage, { recursive: true });
  const errorPath = path.join(evolutionRoot, "error-records.json");
  const successPath = path.join(evolutionRoot, "success-records.json");
  await writeJson(errorPath, options.errorRecords);
  await writeJson(successPath, options.successRecords);
  const python = path.join(options.config.pythonVenv, "bin", "python");
  const args = [
    "-m", "skill_evolver.run_parallel_combined_skill_evolution",
    "--error-json", errorPath,
    "--success-json", successPath,
    "--skill-dir", workPackage,
    "--model", options.config.experimentConfig.provider.teacherModel,
    "--llm-client", "openai",
    "--generation-config", options.config.generationConfig,
    "--batch-size", String(options.config.batchSize),
    "--merge-batch-size", String(options.config.mergeBatchSize),
    "--max-workers", String(options.config.evolverWorkers),
    "--max-skill-lines", String(options.config.maxSkillLines),
    "--temperature", String(options.config.temperature),
    "--save-intermediates",
    "--intermediates-dir", path.join(evolutionRoot, "intermediates"),
    "--parse-failure-dir", path.join(evolutionRoot, "parse-failures"),
    "--cache-path", path.join(evolutionRoot, "llm-cache"),
    "--patch-file", path.join(evolutionRoot, "cumulative.patch"),
    "--changelog", path.join(evolutionRoot, "change.log"),
    "--patch-pipeline", "json",
    "--verbose",
  ];
  const evolved = await runProcess(python, args, {
    cwd: options.config.upstreamCheckout,
    env: { ...process.env, OPENAI_BASE_URL: options.baseUrl, OPENAI_API_KEY: options.apiKey },
    inherit: true,
    timeoutMs: 60 * 60_000,
  });
  await writeFile(path.join(evolutionRoot, "stdout.log"), evolved.stdout, "utf8");
  await writeFile(path.join(evolutionRoot, "stderr.log"), evolved.stderr, "utf8");
  requireSuccess(evolved, `official Trace2Skill evolution for ${options.family.name}`);
  await validateSkill(path.join(workPackage, "SKILL.md"), options.family.name);
  await rm(finalPackage, { recursive: true, force: true });
  await mkdir(path.dirname(finalPackage), { recursive: true });
  await cp(workPackage, finalPackage, { recursive: true });
  const manifest = await skillPackageManifest(finalPackage);
  await writeJson(path.join(evolutionRoot, "complete.json"), {
    completedAt: new Date().toISOString(),
    upstreamCommit: options.config.upstreamCommit,
    errorRecords: options.errorRecords.length,
    successRecords: options.successRecords.length,
    packageSha256: skillPackageSha256(manifest),
    manifest,
  });
  return finalPackage;
}
