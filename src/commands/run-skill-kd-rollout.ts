import { readFile } from "node:fs/promises";
import { executeSkillKdRollout, type SkillKdRolloutRequest } from "../baselines/skill-kd-rollout.js";

if (process.argv.length !== 3) throw new Error("Internal usage: run-skill-kd-rollout.ts request.json");
const request = JSON.parse(await readFile(process.argv[2]!, "utf8")) as SkillKdRolloutRequest;
await executeSkillKdRollout(request);
