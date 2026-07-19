import type { ConversationMessage, ToolCall } from "../../api/types";
import type { CliAgentRunTab } from "../AgentSessionTabStrip";

export const CLI_AGENT_TOOL_NAME = "cli_agent_run_tool";
export const CLI_AGENT_RUN_TAB_PREFIX = "cli-agent-run:";

export function cliAgentRunTabId(runId: string) {
  return `${CLI_AGENT_RUN_TAB_PREFIX}${runId}`;
}

export function cliAgentRunIdFromTabId(tabId: string) {
  return tabId.startsWith(CLI_AGENT_RUN_TAB_PREFIX)
    ? tabId.slice(CLI_AGENT_RUN_TAB_PREFIX.length)
    : "";
}

export function cliAgentRunCloseToken(run: Pick<CliAgentRunView, "id" | "sourceRunId">) {
  return run.id || run.sourceRunId;
}

type CliAgentRunResult = {
  status?: string;
  semanticStatus?: string;
  internalStatus?: string;
  code?: string;
  message?: string;
  runId?: string;
  cliRunId?: string;
  lockKey?: string;
  terminalSessionId?: string;
  terminalReuse?: boolean;
  agentType?: string;
  adapterId?: string;
  label?: string;
  mode?: string;
  cwd?: string;
  commandPreview?: string[];
  exitCode?: number | null;
  durationMs?: number;
  timedOut?: boolean;
  timeoutSeconds?: number;
  stdoutPreview?: string;
  stderrPreview?: string;
  resultSegments?: Array<{ index?: number; kind?: string; text?: string }>;
  logPath?: string;
  cliSessionId?: string;
  sourceSessionId?: string;
  sourceMessageId?: string;
  sourceRunId?: string;
  terminalStatus?: string;
  terminalAlive?: boolean;
};

export type CliAgentRunView = CliAgentRunTab & {
  messageId: string;
  sourceRunId: string;
  toolCall: ToolCall;
  result: CliAgentRunResult | null;
  terminalSessionId: string;
  cliSessionId: string;
  canonicalKey: string;
  task: string;
  cwd: string;
  commandLine: string;
  resultPreview: string;
  error: string;
  tracePath: string;
  durationMs?: number;
};

export type CliAgentTerminalSession = {
  terminalSessionId?: string;
  cliRunId?: string;
  lockKey?: string;
  adapterId?: string;
  label?: string;
  sourceSessionId?: string;
  sourceMessageId?: string;
  sourceRunId?: string;
  linkedSourceMessageIds?: string[];
  linkedSourceRunIds?: string[];
  cwd?: string;
  mode?: string;
  taskHash?: string;
  taskPreview?: string;
  cliSessionId?: string;
  commandPreview?: string[];
  resumed?: boolean;
  status?: string;
  semanticStatus?: string;
  interactionState?: "live" | "history" | "resumable" | "closed" | string;
  canInput?: boolean;
  canResume?: boolean;
  canStart?: boolean;
  resumeAction?: "none" | "resume_session" | "start_new" | string;
  displayMode?: "live_terminal" | "readonly_replay" | string;
  stateReason?: string;
  alive?: boolean;
  userClosed?: boolean;
  closedTerminalSessionIds?: string[];
  closeReason?: string;
  transport?: string;
  rows?: number;
  cols?: number;
  transcriptPath?: string;
  transcriptTail?: string;
  transcriptTailReplayable?: boolean;
  transcriptTailRenderReason?: string;
  screenText?: string;
  screenReplay?: string;
  screenQuality?: string;
  screenRows?: number;
  screenCols?: number;
  createdAt?: string;
  updatedAt?: string;
};

function textArg(args: Record<string, unknown> | undefined, key: string) {
  const value = args?.[key];
  if (typeof value === "string") {
    return value.trim();
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value).trim();
  }
  return "";
}

function parseCliAgentResultText(value: unknown): CliAgentRunResult | null {
  const raw = String(value ?? "").trim();
  if (!raw || !raw.startsWith("{")) {
    return null;
  }
  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as CliAgentRunResult : null;
  } catch {
    return null;
  }
}

function parseCliAgentResult(toolCall: ToolCall): CliAgentRunResult | null {
  for (const candidate of [toolCall.resultPreview, toolCall.summary]) {
    const parsed = parseCliAgentResultText(candidate);
    if (parsed) {
      return parsed;
    }
  }
  return null;
}

function cliAgentTitle(agentType: string, result: CliAgentRunResult | null) {
  const resultLabel = String(result?.label ?? "").trim();
  if (resultLabel) {
    return resultLabel;
  }
  if (agentType === "mimo_code") {
    return "MiMo Code";
  }
  if (agentType === "codex_code") {
    return "Codex Code";
  }
  if (agentType === "claude_code") {
    return "Claude Code";
  }
  return agentType || "CLI Agent";
}

function compactCliCommand(run: Pick<CliAgentRunView, "agentType" | "mode" | "cwd" | "task" | "result">) {
  const resultCommand = Array.isArray(run.result?.commandPreview) ? run.result?.commandPreview.join(" ") : "";
  if (resultCommand) {
    return resultCommand;
  }
  return [
    "cli_agent_run_tool",
    run.agentType ? `agent_type=${run.agentType}` : "",
    run.mode ? `mode=${run.mode}` : "",
    run.cwd ? `cwd=${run.cwd}` : "",
    run.task ? "task=<prompt>" : "",
  ].filter(Boolean).join(" ");
}

export function stableCliHash(value: string) {
  let hash = 0x811c9dc5;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return hash.toString(16).padStart(8, "0");
}

function cliAgentRunIdForSource({
  agentType,
  cwd,
  mode,
  sourceMessageId,
  sourceRunId,
  task,
}: {
  agentType: string;
  cwd: string;
  mode: string;
  sourceMessageId: string;
  sourceRunId: string;
  task: string;
}) {
  const normalizedCwd = cwd.trim().replace(/\\/g, "/").toLowerCase();
  const normalizedMode = (mode.trim().toLowerCase() || "readonly");
  if (!agentType.trim() || !normalizedCwd) {
    const sourceScope = sourceMessageId.trim() || sourceRunId.trim() || stableCliHash(task.trim());
    return `cli-run-${stableCliHash(["cli-run-v1", agentType.trim(), sourceScope, normalizedCwd, normalizedMode].join("\n"))}`;
  }
  return `cli-run-${stableCliHash(["cli-run-v3", agentType.trim(), normalizedCwd, normalizedMode].join("\n"))}`;
}

function cliAgentCanonicalKey(agentType: string, cwd: string, mode: string) {
  const normalizedAgentType = agentType.trim().toLowerCase().replace(/-/g, "_");
  const normalizedCwd = cwd.trim().replace(/\\/g, "/").toLowerCase();
  const normalizedMode = mode.trim().toLowerCase() || "readonly";
  return normalizedAgentType && normalizedCwd ? `${normalizedAgentType}|${normalizedCwd}|${normalizedMode}` : "";
}

function cliAgentLifecycleText(message: ConversationMessage, key: string) {
  const value = message.metadata?.[key];
  if (typeof value === "string") {
    return value.trim();
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value).trim();
  }
  return "";
}

function closedCliAgentRunIdFromMessage(message: ConversationMessage) {
  if (cliAgentLifecycleText(message, "kind") !== "cli_agent_lifecycle") {
    return "";
  }
  const event = cliAgentLifecycleText(message, "event") || cliAgentLifecycleText(message, "status");
  if (event !== "closed") {
    return "";
  }
  return cliAgentLifecycleText(message, "cliRunId") || cliAgentLifecycleText(message, "sourceRunId");
}

type CliAgentLifecyclePatch = {
  event: string;
  cliRunId: string;
  sourceRunId: string;
  linkedSourceRunIds: string[];
  terminalSessionId: string;
  cliSessionId: string;
  adapterId: string;
  label: string;
  cwd: string;
  mode: string;
  lockKey: string;
  status: string;
};

function cliAgentLifecyclePatchFromMessage(message: ConversationMessage): CliAgentLifecyclePatch | null {
  if (cliAgentLifecycleText(message, "kind") !== "cli_agent_lifecycle") {
    return null;
  }
  const event = cliAgentLifecycleText(message, "event") || cliAgentLifecycleText(message, "status");
  const linkedSourceRunIds = Array.isArray(message.metadata?.linkedSourceRunIds)
    ? message.metadata.linkedSourceRunIds.map((item) => String(item || "").trim()).filter(Boolean)
    : [];
  return {
    event,
    cliRunId: cliAgentLifecycleText(message, "cliRunId"),
    sourceRunId: cliAgentLifecycleText(message, "sourceRunId"),
    linkedSourceRunIds,
    terminalSessionId: cliAgentLifecycleText(message, "terminalSessionId"),
    cliSessionId: cliAgentLifecycleText(message, "cliSessionId"),
    adapterId: cliAgentLifecycleText(message, "adapterId"),
    label: cliAgentLifecycleText(message, "label"),
    cwd: cliAgentLifecycleText(message, "cwd"),
    mode: cliAgentLifecycleText(message, "mode") || "readonly",
    lockKey: cliAgentLifecycleText(message, "lockKey"),
    status: cliAgentLifecycleText(message, "status") || event,
  };
}

function applyCliAgentLifecyclePatch(run: CliAgentRunView, patch: CliAgentLifecyclePatch) {
  if (patch.terminalSessionId) {
    run.terminalSessionId = patch.terminalSessionId;
  }
  if (patch.cliSessionId) {
    run.cliSessionId = patch.cliSessionId;
  }
  if (patch.status) {
    run.status = patch.status;
  }
}

function applyCliAgentLifecyclePatchToRuns(
  runsById: Map<string, CliAgentRunView>,
  runIds: string[],
  patch: CliAgentLifecyclePatch,
) {
  for (const runId of runIds) {
    const directRun = runsById.get(runId);
    if (directRun) {
      applyCliAgentLifecyclePatch(directRun, patch);
    }
  }
  for (const run of runsById.values()) {
    if (runIds.includes(run.sourceRunId)) {
      applyCliAgentLifecyclePatch(run, patch);
    }
  }
}

function reopenCliAgentScope(
  closedRunIds: Set<string>,
  closedCanonicalKeys: Set<string>,
  canonicalKey: string,
  runIds: string[],
) {
  if (canonicalKey) {
    closedCanonicalKeys.delete(canonicalKey);
  }
  for (const runId of runIds) {
    closedRunIds.delete(runId);
  }
}

function buildCliAgentLifecycleRunView(
  message: ConversationMessage,
  patch: CliAgentLifecyclePatch,
  sourceSessionId: string,
): CliAgentRunView | null {
  if (!patch.terminalSessionId || !patch.adapterId || !patch.cwd) {
    return null;
  }
  const mode = patch.mode || "readonly";
  const sourceRunId = patch.sourceRunId || `${message.id}-${CLI_AGENT_TOOL_NAME}-lifecycle`;
  const cliRunId = patch.cliRunId || cliAgentRunIdForSource({
    agentType: patch.adapterId,
    cwd: patch.cwd,
    mode,
    sourceMessageId: message.id,
    sourceRunId,
    task: "",
  });
  const result: CliAgentRunResult = {
    status: patch.status || "attached",
    semanticStatus: patch.status || "attached",
    internalStatus: patch.status || "attached",
    code: "CLI_AGENT_TERMINAL_ACTIVE",
    cliRunId,
    terminalSessionId: patch.terminalSessionId,
    cliSessionId: patch.cliSessionId,
    lockKey: patch.lockKey,
    terminalReuse: true,
    agentType: patch.adapterId,
    adapterId: patch.adapterId,
    label: patch.label,
    mode,
    cwd: patch.cwd,
    sourceSessionId,
    sourceMessageId: message.id,
    sourceRunId,
  };
  const toolCall: ToolCall = {
    name: CLI_AGENT_TOOL_NAME,
    status: patch.status || "running",
    summary: patch.event,
    arguments: {
      agent_type: patch.adapterId,
      cwd: patch.cwd,
      mode,
    },
    resultPreview: JSON.stringify(result),
  };
  const title = patch.label || cliAgentTitle(patch.adapterId, result);
  const canonicalKey = cliAgentCanonicalKey(patch.adapterId, patch.cwd, mode);
  const run: CliAgentRunView = {
    id: cliRunId,
    messageId: message.id,
    sourceRunId,
    toolCall,
    result,
    terminalSessionId: patch.terminalSessionId,
    cliSessionId: patch.cliSessionId,
    title,
    summary: patch.event || patch.status,
    status: patch.status || "attached",
    agentType: patch.adapterId,
    mode,
    cwd: patch.cwd,
    canonicalKey,
    task: "",
    commandLine: "",
    resultPreview: String(toolCall.resultPreview ?? "").trim(),
    error: "",
    tracePath: "",
  };
  run.commandLine = compactCliCommand(run);
  return run;
}

export function buildCliAgentRunViews(messages: ConversationMessage[], sourceSessionId = ""): CliAgentRunView[] {
  const runsById = new Map<string, CliAgentRunView>();
  const runsByCanonicalKey = new Map<string, CliAgentRunView>();
  const lifecycleByRunId = new Map<string, CliAgentLifecyclePatch>();
  const lifecycleByCanonicalKey = new Map<string, CliAgentLifecyclePatch>();
  const closedRunIds = new Set<string>();
  const closedCanonicalKeys = new Set<string>();
  for (const message of messages) {
    const lifecyclePatch = cliAgentLifecyclePatchFromMessage(message);
    if (lifecyclePatch) {
      const lifecycleRunIds = [
        lifecyclePatch.cliRunId,
        lifecyclePatch.sourceRunId,
        ...lifecyclePatch.linkedSourceRunIds,
      ].filter(Boolean);
      const lifecycleCanonicalKey = cliAgentCanonicalKey(lifecyclePatch.adapterId, lifecyclePatch.cwd, lifecyclePatch.mode);
      if (lifecyclePatch.event === "closed") {
        if (lifecycleCanonicalKey) {
          closedCanonicalKeys.add(lifecycleCanonicalKey);
          const canonicalRun = runsByCanonicalKey.get(lifecycleCanonicalKey);
          if (canonicalRun) {
            runsById.delete(canonicalRun.id);
            runsByCanonicalKey.delete(lifecycleCanonicalKey);
          }
        }
        for (const runId of lifecycleRunIds) {
          closedRunIds.add(runId);
          runsById.delete(runId);
        }
        for (const run of runsById.values()) {
          if (lifecycleRunIds.includes(run.sourceRunId) || (lifecycleCanonicalKey && run.canonicalKey === lifecycleCanonicalKey)) {
            runsById.delete(run.id);
            if (run.canonicalKey) {
              runsByCanonicalKey.delete(run.canonicalKey);
            }
          }
        }
      } else {
        reopenCliAgentScope(closedRunIds, closedCanonicalKeys, lifecycleCanonicalKey, lifecycleRunIds);
        for (const runId of lifecycleRunIds) {
          lifecycleByRunId.set(runId, lifecyclePatch);
        }
        if (lifecycleCanonicalKey) {
          lifecycleByCanonicalKey.set(lifecycleCanonicalKey, lifecyclePatch);
        }
        applyCliAgentLifecyclePatchToRuns(runsById, lifecycleRunIds, lifecyclePatch);
        const lifecycleRun = buildCliAgentLifecycleRunView(message, lifecyclePatch, sourceSessionId);
        if (
          lifecycleRun
          && !closedRunIds.has(lifecycleRun.id)
          && !closedRunIds.has(lifecycleRun.sourceRunId)
          && !(lifecycleRun.canonicalKey && closedCanonicalKeys.has(lifecycleRun.canonicalKey))
        ) {
          const previousRun = lifecycleRun.canonicalKey ? runsByCanonicalKey.get(lifecycleRun.canonicalKey) : undefined;
          if (previousRun) {
            runsById.delete(previousRun.id);
          }
          if (lifecycleRun.canonicalKey) {
            runsByCanonicalKey.set(lifecycleRun.canonicalKey, lifecycleRun);
          }
          runsById.set(lifecycleRun.id, lifecycleRun);
        }
      }
      continue;
    }
    const closedRunId = closedCliAgentRunIdFromMessage(message);
    if (closedRunId) {
      closedRunIds.add(closedRunId);
      runsById.delete(closedRunId);
      continue;
    }
    for (const [index, toolCall] of (message.toolCalls ?? []).entries()) {
      if (toolCall.name !== CLI_AGENT_TOOL_NAME) {
        continue;
      }
      const result = parseCliAgentResult(toolCall);
      const args = toolCall.arguments;
      const agentType = textArg(args, "agent_type") || textArg(args, "agentType") || String(result?.agentType ?? "").trim();
      const mode = textArg(args, "mode") || String(result?.mode ?? "").trim() || "readonly";
      const cwd = textArg(args, "cwd") || String(result?.cwd ?? "").trim();
      const task = textArg(args, "task");
      const status = String(result?.semanticStatus || result?.status || toolCall.status || "running").trim();
      const title = cliAgentTitle(agentType, result);
      const summary = String(result?.code || toolCall.summary || task || cwd || "").trim();
      const sourceRunId = `${message.id}-${CLI_AGENT_TOOL_NAME}-${index}`;
      const cliRunId = String(result?.cliRunId || "").trim() || cliAgentRunIdForSource({
        agentType,
        cwd,
        mode,
        sourceMessageId: message.id,
        sourceRunId,
        task,
      });
      const canonicalKey = cliAgentCanonicalKey(agentType, cwd, mode);
      reopenCliAgentScope(closedRunIds, closedCanonicalKeys, canonicalKey, [cliRunId, sourceRunId]);
      if (canonicalKey && closedCanonicalKeys.has(canonicalKey)) {
        continue;
      }
      const lifecyclePatchForRun = lifecycleByRunId.get(cliRunId)
        ?? lifecycleByRunId.get(sourceRunId)
        ?? (canonicalKey ? lifecycleByCanonicalKey.get(canonicalKey) : undefined);
      if (!shouldRenderCliAgentRunTab(result, status, lifecyclePatchForRun)) {
        continue;
      }
      const run: CliAgentRunView = {
        id: cliRunId,
        messageId: message.id,
        sourceRunId,
        toolCall,
        result,
        terminalSessionId: String(result?.terminalSessionId || lifecyclePatchForRun?.terminalSessionId || ""),
        cliSessionId: String(result?.cliSessionId || lifecyclePatchForRun?.cliSessionId || ""),
        title,
        summary,
        status,
        agentType,
        mode,
        cwd,
        canonicalKey,
        task,
        commandLine: "",
        resultPreview: String(toolCall.resultPreview ?? "").trim(),
        error: String(result?.stderrPreview || toolCall.error || "").trim(),
        tracePath: String(result?.logPath || toolCall.tracePath || "").trim(),
        durationMs: result?.durationMs ?? toolCall.durationMs,
      };
      run.commandLine = compactCliCommand(run);
      if (canonicalKey) {
        const previousRun = runsByCanonicalKey.get(canonicalKey);
        if (previousRun) {
          runsById.delete(previousRun.id);
        }
        runsByCanonicalKey.set(canonicalKey, run);
      }
      runsById.set(cliRunId, run);
    }
  }
  return Array.from(runsById.values()).filter((run) =>
    !closedRunIds.has(run.id)
    && !closedRunIds.has(run.sourceRunId)
    && !(run.canonicalKey && closedCanonicalKeys.has(run.canonicalKey))
  );
}

export function shouldRenderCliAgentRunTab(result: CliAgentRunResult | null, status: string, lifecyclePatch?: CliAgentLifecyclePatch) {
  const code = String(result?.code || "").trim();
  if (
    code === "CLI_AGENT_TERMINAL_ACTIVE"
    || Boolean(result?.terminalSessionId)
    || Boolean(result?.terminalReuse)
    || Boolean(lifecyclePatch?.terminalSessionId)
  ) {
    return true;
  }
  if (!result) {
    return false;
  }
  const normalizedStatus = String(result?.status || status || "").trim().toLowerCase();
  if (["error", "failed", "failure", "timeout", "timed_out"].includes(normalizedStatus)) {
    return false;
  }
  if (code === "CLI_AGENT_EXITED_NONZERO" || code === "CLI_AGENT_LAUNCH_FAILED" || code === "CLI_AGENT_TIMEOUT") {
    return false;
  }
  return false;
}

export function canInputTerminal(session: CliAgentTerminalSession | null) {
  if (!session) {
    return false;
  }
  if (typeof session.canInput === "boolean") {
    return session.canInput;
  }
  return Boolean(session.alive);
}

export function isCliAgentRunActiveForClose(run: CliAgentRunView, session?: CliAgentTerminalSession) {
  if (canInputTerminal(session || null)) {
    return true;
  }
  const status = String(session?.status || run.result?.terminalStatus || run.status || "").trim().toLowerCase();
  if (["active", "attached", "pending", "queued", "sent", "task_sent", "running", "starting", "stopping"].includes(status)) {
    return true;
  }
  if (["closed", "stopped", "exited", "stale"].includes(status)) {
    return false;
  }
  const terminalSessionId = String(session?.terminalSessionId || run.terminalSessionId || run.result?.terminalSessionId || "").trim();
  const code = String(run.result?.code || "").trim();
  return Boolean(
    terminalSessionId
    && (run.result?.terminalReuse || code === "CLI_AGENT_TERMINAL_ACTIVE" || run.result?.terminalAlive),
  );
}
