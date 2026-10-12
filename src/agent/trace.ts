import { appendFile, mkdir } from "node:fs/promises";
import path from "node:path";
import type { AgentSession, AgentSessionEvent } from "@earendil-works/pi-coding-agent";
import type { TraceEvent } from "../experiment/types.js";

function compact(value: unknown, limit = 8_000): unknown {
  if (typeof value === "string") return value.length > limit ? `${value.slice(0, limit)}…[truncated]` : value;
  try {
    const encoded = JSON.stringify(value);
    if (encoded.length <= limit) return value;
    return `${encoded.slice(0, limit)}…[truncated]`;
  } catch {
    return String(value);
  }
}

function eventData(event: AgentSessionEvent): Record<string, unknown> {
  switch (event.type) {
    case "tool_execution_start":
      return { toolCallId: event.toolCallId, toolName: event.toolName, args: compact(event.args) };
    case "tool_execution_end":
      return {
        toolCallId: event.toolCallId,
        toolName: event.toolName,
        isError: event.isError,
        result: compact(event.result),
      };
    case "message_update":
      return {};
    case "message_start":
      return { role: event.message.role, message: compact(event.message, 20_000) };
    case "message_end": {
      const message = event.message;
      if (message.role !== "assistant") {
        return { role: message.role, message: compact(message, 20_000) };
      }
      return {
        role: message.role,
        model: message.model,
        responseModel: message.responseModel ?? null,
        stopReason: message.stopReason,
        usage: message.usage,
        errorMessage: message.errorMessage ?? null,
        content: compact(message.content, 20_000),
      };
    }
    case "turn_start":
      return {};
    case "turn_end":
      return { message: compact(event.message, 20_000) };
    case "compaction_start":
      return { reason: event.reason };
    case "compaction_end":
      return { reason: event.reason, aborted: event.aborted, errorMessage: event.errorMessage };
    case "auto_retry_start":
      return { attempt: event.attempt, maxAttempts: event.maxAttempts, errorMessage: event.errorMessage };
    case "auto_retry_end":
      return { success: event.success, attempt: event.attempt, finalError: event.finalError };
    default:
      return {};
  }
}

export class TraceRecorder {
  private phase = "setup";
  private toolCallCount = 0;
  private eventSequence = 0;
  private segment: TraceEvent[] = [];
  private writeChain: Promise<void> = Promise.resolve();

  constructor(
    readonly label: string,
    readonly filePath: string,
  ) {}

  async attach(session: AgentSession): Promise<() => void> {
    await mkdir(path.dirname(this.filePath), { recursive: true });
    return session.subscribe((event) => {
      if (event.type === "message_update") return;
      if (event.type === "tool_execution_end") this.toolCallCount += 1;
      const record: TraceEvent = {
        sequence: ++this.eventSequence,
        at: new Date().toISOString(),
        session: this.label,
        phase: this.phase,
        type: event.type,
        data: eventData(event),
      };
      this.segment.push(record);
      const line = `${JSON.stringify(record)}\n`;
      this.writeChain = this.writeChain.then(async () => await appendFile(this.filePath, line));
    });
  }

  setPhase(phase: string): void {
    this.phase = phase;
  }

  getPhase(): string {
    return this.phase;
  }

  getToolCallCount(): number {
    return this.toolCallCount;
  }

  takeSegment(): TraceEvent[] {
    const result = this.segment;
    this.segment = [];
    return result;
  }

  peekSegment(): TraceEvent[] {
    return [...this.segment];
  }

  async flush(): Promise<void> {
    await this.writeChain;
  }
}

function eventArgs(event: TraceEvent): Record<string, unknown> {
  const args = event.data.args;
  if (args && typeof args === "object" && !Array.isArray(args)) {
    return args as Record<string, unknown>;
  }
  if (typeof args === "string") {
    try {
      const parsed = JSON.parse(args) as unknown;
      return parsed && typeof parsed === "object" && !Array.isArray(parsed)
        ? parsed as Record<string, unknown>
        : {};
    } catch {
      return {};
    }
  }
  return {};
}

function packageRelativePath(raw: string, family: string): string | undefined {
  const normalized = raw.replaceAll("\\", "/");
  const marker = `skill/${family}/`;
  const index = normalized.indexOf(marker);
  if (index < 0) return undefined;
  const relative = normalized.slice(index + marker.length).replace(/^\/+/, "");
  if (!relative || relative.split("/").includes("..")) return undefined;
  return relative;
}

export function skillResourceReads(events: TraceEvent[], family: string): string[] {
  const resources: string[] = [];
  for (const event of events) {
    if (event.type !== "tool_execution_start") continue;
    const tool = String(event.data.toolName ?? "");
    const args = eventArgs(event);
    const relative = tool === "skill_read"
      ? typeof args.path === "string" ? args.path : undefined
      : tool === "read" && typeof args.path === "string"
        ? packageRelativePath(args.path, family)
        : undefined;
    if (relative && !relative.split(/[\\/]/).includes("..")) resources.push(relative.replaceAll("\\", "/"));
  }
  return [...new Set(resources)].sort();
}

export function skillResourceExecutions(events: TraceEvent[], family: string): string[] {
  const resources: string[] = [];
  const escapedFamily = family.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const patterns = [
    // Host workspace path used by Pi's read-only evaluator tools.
    new RegExp(`(?:^|[\\s"'=])/?skill/${escapedFamily}/([A-Za-z0-9._/-]+)`, "g"),
    // The complete family package is mounted read-only at /skill in the task
    // container, so scripts invoked through task_shell do not include family.
    /(?:^|[\s"'=])\/?skill\/([A-Za-z0-9._/-]+)/g,
  ];
  for (const event of events) {
    if (event.type !== "tool_execution_start" || event.data.toolName !== "task_shell") continue;
    const command = eventArgs(event).command;
    if (typeof command !== "string") continue;
    for (const pattern of patterns) {
      for (const match of command.matchAll(pattern)) {
        let relative = match[1]?.replace(/[),;:'"]+$/, "");
        if (relative?.startsWith(`${family}/`)) relative = relative.slice(family.length + 1);
        if (relative && !relative.split("/").includes("..")) resources.push(relative);
      }
    }
  }
  return [...new Set(resources)].sort();
}
