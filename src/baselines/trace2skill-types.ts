import type { EvalResult, TraceEvent } from "../experiment/types.js";

export const TRACE2SKILL_REPOSITORY = "https://github.com/Qwen-Applications/Trace2Skill.git";
export const TRACE2SKILL_COMMIT = "3d0b52a140f002a512930252b613c49048f7d5ac";
export const TRACE2SKILL_PROTOCOL = "adapted-trace2skill-pool-v1";

export interface RawTrace2SkillConfig {
  schemaVersion: number;
  protocolVersion: string;
  experimentConfig: string;
  experimentModel?: string;
  runsRoot: string;
  upstreamCheckout: string;
  pythonVenv: string;
  upstreamRepository: string;
  upstreamCommit: string;
  tracesPerFamily: number;
  replicates: number;
  familyConcurrency: number;
  trajectoryConcurrency: number;
  heldoutVariantConcurrency: number;
  evolverWorkers: number;
  batchSize: number;
  mergeBatchSize: number;
  maxSkillLines: number;
  maxTokens: number;
  temperature: number;
  generationConfig: string;
}

export interface Trace2SkillConfig extends Omit<RawTrace2SkillConfig,
  "experimentConfig" | "runsRoot" | "upstreamCheckout" | "pythonVenv" | "generationConfig"
> {
  configPath: string;
  projectRoot: string;
  experimentConfig: import("../experiment/types.js").PilotConfig;
  runsRoot: string;
  upstreamCheckout: string;
  pythonVenv: string;
  generationConfig: string;
}

export interface Trace2SkillRecordItem {
  type: "failure_cause" | "failure_memory" | "success_memory";
  number: number;
  title: string;
  description: string;
  content: string;
  relation_to_skill?: string;
  skill_reflection?: string;
}

export interface Trace2SkillRecord {
  instance_id: string;
  source_file: string;
  items: Trace2SkillRecordItem[];
}

export interface Trace2SkillTrajectoryArtifact extends EvalResult {
  trajectory: TraceEvent[];
  rawSessionFile?: string | null;
  rawSessionSha256?: string | null;
}

export interface Trace2SkillRunSummary {
  schemaVersion: 1;
  protocolVersion: typeof TRACE2SKILL_PROTOCOL;
  family: string;
  replicate: number;
  runId: string;
  runRoot: string;
  traces: Array<{
    index: number;
    score: number;
    passed: number;
    total: number;
    recordSource: "error" | "success";
  }>;
  finalSkillPackage: string;
  finalSkillPackageSha256: string;
  heldout: Array<{ variant: string; score: number; passed: number; total: number }>;
}

export interface Trace2SkillMatrixMetrics {
  complete: boolean;
  runs: number;
  heldoutOutcomes: number;
  familyMacroAvg3: number | null;
  variantMacroAvg3: number | null;
  replicateFamilyMacro: Record<string, number>;
  familyAvg3: Record<string, number>;
}
