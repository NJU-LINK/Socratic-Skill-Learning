import type { Model } from "@earendil-works/pi-ai";
import { ModelRuntime } from "@earendil-works/pi-coding-agent";
import type { PilotConfig } from "../experiment/types.js";

export interface ModelBundle {
  runtime: ModelRuntime;
  student: Model<any>;
  teacher: Model<any>;
}

export function normalizeProviderBaseUrl(raw: string): string {
  return raw.trim().replace(/\/+$/, "").replace(/\/chat\/completions$/, "");
}

interface RuntimeModelProfile {
  name: string;
  thinkingLevelMap?: { xhigh: "max"; max: "max" };
  compat: {
    supportsStore: false;
    supportsDeveloperRole: false;
    supportsReasoningEffort: boolean;
    supportsStrictMode: false;
    supportsUsageInStreaming: true;
    maxTokensField: "max_completion_tokens";
    thinkingFormat: "qwen" | "openai" | "zai";
    requiresReasoningContentOnAssistantMessages?: true;
  };
}

/**
 * Keep provider quirks next to model identity rather than leaking them into
 * experiment orchestration. Both DeepSeek V4 snapshots use thinking by
 * default; OpenAI-style reasoning_effort selects the requested depth.
 */
export function runtimeModelProfile(id: string, role: "student" | "teacher"): RuntimeModelProfile {
  const common = {
    supportsStore: false as const,
    supportsDeveloperRole: false as const,
    supportsStrictMode: false as const,
    supportsUsageInStreaming: true as const,
    maxTokensField: "max_completion_tokens" as const,
  };
  if (id === "kimi-k3") {
    return {
      name: `${id} (${role})`,
      thinkingLevelMap: { xhigh: "max", max: "max" },
      compat: { ...common, supportsReasoningEffort: true, thinkingFormat: "openai",
        requiresReasoningContentOnAssistantMessages: true },
    };
  }
  if (id === "kimi-k2.5" || id === "kimi-k2.6") {
    return { name: `${id} (${role})`, compat: { ...common,
      supportsReasoningEffort: false, thinkingFormat: "zai",
      requiresReasoningContentOnAssistantMessages: true } };
  }
  if (id.startsWith("deepseek-v4-")) {
    return {
      name: `${id} (${role})`,
      thinkingLevelMap: { xhigh: "max", max: "max" },
      compat: {
        ...common,
        supportsReasoningEffort: true,
        thinkingFormat: "openai",
        requiresReasoningContentOnAssistantMessages: true,
      },
    };
  }
  return {
    name: `${id} (${role})`,
    compat: {
      ...common,
      supportsReasoningEffort: false,
      thinkingFormat: "qwen",
    },
  };
}

export async function createModels(config: PilotConfig, baseUrl: string, apiKey: string): Promise<ModelBundle> {
  if (!baseUrl.trim()) throw new Error("Missing `url` in .env");
  if (!apiKey.trim()) throw new Error("Missing `key` in .env");

  const runtime = await ModelRuntime.create({ modelsPath: null, allowModelNetwork: false });
  const modelDefinition = (id: string, role: "student" | "teacher") => {
    const profile = runtimeModelProfile(id, role);
    const limits = role === "teacher" && config.provider.teacherLimits
      ? config.provider.teacherLimits : config.provider;
    return {
      id,
      name: profile.name,
      reasoning: true,
      input: ["text"] as ("text" | "image")[],
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
      contextWindow: limits.contextWindow,
      maxTokens: limits.maxCompletionTokens,
      ...(profile.thinkingLevelMap ? { thinkingLevelMap: profile.thinkingLevelMap } : {}),
      compat: profile.compat,
    };
  };

  runtime.registerProvider(config.provider.id, {
    name: "Alibaba Model Studio (OpenAI-compatible)",
    baseUrl: normalizeProviderBaseUrl(baseUrl),
    api: "openai-completions",
    authHeader: true,
    models: [
      modelDefinition(config.provider.studentModel, "student"),
      modelDefinition(config.provider.teacherModel, "teacher"),
    ],
  });
  await runtime.setRuntimeApiKey(config.provider.id, apiKey);

  const student = runtime.getModel(config.provider.id, config.provider.studentModel);
  const teacher = runtime.getModel(config.provider.id, config.provider.teacherModel);
  if (!student || !teacher) throw new Error("Failed to register configured experiment models");
  return { runtime, student, teacher };
}
