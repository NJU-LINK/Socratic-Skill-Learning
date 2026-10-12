import { access, mkdir } from "node:fs/promises";
import path from "node:path";
import { requireSuccess, runProcess } from "../runtime/process.js";
import type { SkillKdConfig } from "./skill-kd-config.js";

export function skillKdPythonEnv(config: SkillKdConfig): NodeJS.ProcessEnv {
  return { ...process.env, PYTHONPATH: path.join(config.upstreamCheckout, "src"), PYTHONUNBUFFERED: "1",
    PYTHONDONTWRITEBYTECODE: "1", PYTHONNOUSERSITE: "1" };
}

async function checkCheckout(config: SkillKdConfig, checkCommit: boolean): Promise<void> {
  const git = async (...args: string[]) => {
    const result = await runProcess("git", args, { cwd: config.upstreamCheckout });
    requireSuccess(result, `SKILL-KD git ${args[0]}`);
    return result.stdout.trim();
  };
  if ((await git("remote", "get-url", "origin")).replace(/\.git$/, "") !== config.upstreamRepository.replace(/\.git$/, "")) {
    throw new Error("SKILL-KD checkout has a different origin");
  }
  if (await git("status", "--porcelain", "--untracked-files=all")) {
    throw new Error("Refusing a modified SKILL-KD upstream checkout");
  }
  // Ignored .env and shadowing Python modules must not change the pinned code.
  if (await git("ls-files", "--others", "--ignored", "--exclude-standard")) {
    throw new Error("SKILL-KD upstream has ignored files; keep its checkout pristine (including .env/__pycache__)");
  }
  if (checkCommit && await git("rev-parse", "HEAD") !== config.upstreamCommit) {
    throw new Error(`SKILL-KD HEAD must be ${config.upstreamCommit}`);
  }
}

export async function validateSkillKdUpstream(config: SkillKdConfig): Promise<void> {
  await checkCheckout(config, true);
  requireSuccess(await runProcess(path.join(config.pythonVenv, "bin", "python"), [
    "-c", "from pact.run_experiment import evolve_on_task; from pact.llm import run_tool_loop; print('skill-kd-python-ok')",
  ], { cwd: config.projectRoot, env: skillKdPythonEnv(config) }), "validate SKILL-KD Python imports");
}

export async function setupSkillKdUpstream(config: SkillKdConfig): Promise<void> {
  const present = await access(config.upstreamCheckout).then(() => true).catch(() => false);
  if (!present) {
    await mkdir(path.dirname(config.upstreamCheckout), { recursive: true });
    requireSuccess(await runProcess("git", ["clone", "--no-checkout", config.upstreamRepository, config.upstreamCheckout],
      { inherit: true }), "clone SKILL-KD");
  } else {
    await checkCheckout(config, false);
  }
  for (const args of [["fetch", "origin", config.upstreamCommit], ["checkout", "--detach", config.upstreamCommit]]) {
    requireSuccess(await runProcess("git", args, { cwd: config.upstreamCheckout, inherit: true }), "pin SKILL-KD");
  }
  const python = path.join(config.pythonVenv, "bin", "python");
  if (!(await access(python).then(() => true).catch(() => false))) {
    await mkdir(path.dirname(config.pythonVenv), { recursive: true });
    requireSuccess(await runProcess("python3", ["-m", "venv", config.pythonVenv], { inherit: true }), "create SKILL-KD venv");
  }
  requireSuccess(await runProcess(python, ["-m", "pip", "install", "-r",
    path.join(config.projectRoot, "scripts/skill-kd/requirements.txt")], { inherit: true }), "install SKILL-KD dependencies");
  await validateSkillKdUpstream(config);
}
