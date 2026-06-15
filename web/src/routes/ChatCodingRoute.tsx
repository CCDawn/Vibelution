import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { FitAddon } from "@xterm/addon-fit";
import { Terminal } from "@xterm/xterm";
import {
  Apple,
  ArrowUpRight,
  BellRing,
  Check,
  ChevronRight,
  CircleDot,
  HeartHandshake,
  MessageCircleHeart,
  Plus,
  Search,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Square,
  SquareTerminal,
  Trash2,
  UsersRound,
  RotateCcw,
  X,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type DragEvent,
  type KeyboardEvent,
  type MouseEvent as ReactMouseEvent,
  type PointerEvent,
} from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { fetchJson } from "../api/client";
import { createChatWorkspaceCache } from "./chatWorkspaceCache";
import {
  isProjectAgentBusEventRevoked,
  listProjectAgentBusTimeline,
  revokeProjectAgentBusMessage,
  sendProjectAgentBusMessage,
} from "../api/projectAgentBus";
import { queryKeys } from "../api/queryKeys";
import {
  AgentInstance,
  ChatRoomDetail,
  ChatRoomMessage,
  ChatRoomParticipant,
  ChatRoomRoundAcceptedResponse,
  ChatRoomMode,
  ChatRoomPurpose,
  ConfigSummary,
  ChatRoomStreamEvent,
  FileContent,
  MentalStateSnapshot,
  PetActionResponse,
  PetSummary,
  RuntimeSummary,
  SessionChatReviewCandidateResponse,
  SessionCacheCompositionSegment,
  SessionContextCompositionSegment,
  ChatNextStateSignalSummary,
  SessionDeleteResponse,
  SessionGuidanceMode,
  ConversationSummary,
  SessionDetail,
  AgentToolGovernanceRequest,
  SessionRuntimeNotice,
  SessionSummary,
  SessionStreamEvent,
  SessionReferenceAttachment,
  SessionTurnAcceptedResponse,
  SessionTurnError,
  TeamListPayload,
  ConversationMessage,
  ConversationAttachment,
  ToolCall,
} from "../api/types";
import {
  shouldShowNextStateSignalInConversation,
  type TurnAvatarResolution,
} from "../components/conversation/ConversationView";
import { COMPOSER_SESSION_REFERENCE_MIME } from "../components/conversation/conversationConstants";
import { LazyConversationView } from "../components/conversation/LazyConversationView";
import { isAgentInboxMessage, isTurnErrorMessage } from "../components/conversation/messageSections";
import { LazyFilePreview } from "../components/preview/LazyFilePreview";
import { collectBrowserPageSnapshot, postBrowserTelemetry } from "../app/browserTelemetry";
import { getPageInstanceId } from "../app/pageInstance";
import { resolvePollingInterval, usePageVisibility, useStartupWarmup } from "../app/pollingPolicy";
import type { TranslationKey } from "../i18n/dictionary";
import { PaneCollapseHandle } from "../components/layout/PaneCollapseHandle";
import { petAvatarPresetLabel } from "../i18n/petLabels";
import { useAppI18n } from "../i18n/useAppI18n";
import { useChatWorkbenchStore } from "../store/chatWorkbenchStore";
import { useShellStore } from "../store/shellStore";
import {
  clampPercent,
  contextUsagePercent,
  formatContextUsage,
  formatRelativeTime,
} from "./chatShellFormat";
import {
  deriveSessionDetailQueryErrorState,
  deriveSessionListQueryErrorState,
  appendOptimisticUserMessage,
  markSessionDetailRunning,
  markSessionSummaryRunning,
  mergeSessionDetailIntoSummaries,
  renameSessionDetail,
  renameSessionInSummaries,
  removeDeletedSessionFromSummaries,
  removeOptimisticUserMessage,
  shouldAcceptSessionStreamEvent,
} from "./chatSessionState";
import {
  SESSION_INDEX_PAGE_SIZE,
  captureSessionIndexCacheSnapshots,
  restoreSessionIndexCacheSnapshots,
  updateSessionSummaryCaches,
  useSessionIndexQuery,
} from "./chatSessionIndexQuery";
import {
  latestUserMessageId as deriveLatestUserMessageId,
  resolveComposerDraftValue,
  resolveLatestEditTarget,
} from "./chatComposerState";
import { buildVisiblePanelRows, getPetAvatarPresetKey, getPetAvatarSymbol } from "./chatCompactPanel";
import {
  tokenSpeedSampleFromMessages,
  updateTokenSpeedTracker,
  type TokenSpeedTrackerState,
} from "./chatTokenSpeed";
import {
  clearPendingSelfEvolutionHandoff,
  loadPendingSelfEvolutionHandoff,
} from "./selfEvolutionHandoff";
import {
  agentDisplayInfo,
  participantAgentDisplayInfo,
  sessionAgentDisplayInfo,
} from "./agentDisplay";
import { AgentSessionTabStrip, type CliAgentRunTab } from "./AgentSessionTabStrip";
import { ConversationIndexTree } from "./ConversationIndexTree";
import {
  DEFAULT_COLLAPSED_CONVERSATION_GROUPS,
  conversationGroupLabel,
  hasInvalidChildSessionLink,
  isRepresentedInAgentSessionTabs,
  isVisibleDirectSession,
  rootSessionIdFor,
  sessionToConversationSummary,
  useConversationIndexModel,
  type ConversationIndexGroupKey,
} from "./conversationIndexModel";
import {
  isChildSession,
  isAgentRootSession,
} from "./DirectSessionIndexItem";
import { SessionContextMenu } from "./SessionContextMenu";
import {
  buildChatMentionTargets,
  tokenizeChatMentions,
  type ChatMentionTarget,
} from "./chatMentionTokens";
import styles from "./ChatCodingRoute.module.css";
import "@xterm/xterm/css/xterm.css";

type ActiveSkillContract = {
  status?: string;
  scope?: string;
  command?: string;
  args?: string;
  skillName?: string;
  skillPath?: string;
  skillHash?: string;
  description?: string;
  keyRules?: string[];
  activatedAt?: string;
  staleReason?: string;
};

type SessionDetailWithActiveSkill = SessionDetail & {
  activeSkillContract?: ActiveSkillContract | null;
};

const CLI_AGENT_TOOL_NAME = "cli_agent_run_tool";
const CLI_AGENT_RUN_TAB_PREFIX = "cli-agent-run:";

function cliAgentRunTabId(runId: string) {
  return `${CLI_AGENT_RUN_TAB_PREFIX}${runId}`;
}

function cliAgentRunIdFromTabId(tabId: string) {
  return tabId.startsWith(CLI_AGENT_RUN_TAB_PREFIX)
    ? tabId.slice(CLI_AGENT_RUN_TAB_PREFIX.length)
    : "";
}

function cliAgentRunCloseToken(run: Pick<CliAgentRunView, "id" | "sourceRunId">) {
  return run.id || run.sourceRunId;
}

type CliAgentRunResult = {
  status?: string;
  code?: string;
  runId?: string;
  cliRunId?: string;
  terminalSessionId?: string;
  terminalReuse?: boolean;
  agentType?: string;
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
  logPath?: string;
  cliSessionId?: string;
  terminalStatus?: string;
  terminalAlive?: boolean;
};

type CliAgentRunView = CliAgentRunTab & {
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

type CliAgentTerminalSession = {
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
  alive?: boolean;
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

type CliAgentTerminalEvent = {
  type?: string;
  chunk?: string;
  session?: CliAgentTerminalSession;
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

function stableCliHash(value: string) {
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
  sourceMessageId,
  sourceRunId,
  task,
}: {
  agentType: string;
  cwd: string;
  sourceMessageId: string;
  sourceRunId: string;
  task: string;
}) {
  const normalizedCwd = cwd.trim().replace(/\\/g, "/").toLowerCase();
  if (!agentType.trim() || !normalizedCwd) {
    const sourceScope = sourceMessageId.trim() || sourceRunId.trim() || stableCliHash(task.trim());
    return `cli-run-${stableCliHash(["cli-run-v1", agentType.trim(), sourceScope, normalizedCwd].join("\n"))}`;
  }
  return `cli-run-${stableCliHash(["cli-run-v2", agentType.trim(), normalizedCwd].join("\n"))}`;
}

function cliAgentCanonicalKey(agentType: string, cwd: string) {
  const normalizedAgentType = agentType.trim().toLowerCase().replace(/-/g, "_");
  const normalizedCwd = cwd.trim().replace(/\\/g, "/").toLowerCase();
  return normalizedAgentType && normalizedCwd ? `${normalizedAgentType}|${normalizedCwd}` : "";
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
  cwd: string;
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
    cwd: cliAgentLifecycleText(message, "cwd"),
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

function buildCliAgentRunViews(messages: ConversationMessage[], sourceSessionId = ""): CliAgentRunView[] {
  void sourceSessionId;
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
      const lifecycleCanonicalKey = cliAgentCanonicalKey(lifecyclePatch.adapterId, lifecyclePatch.cwd);
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
        for (const runId of lifecycleRunIds) {
          lifecycleByRunId.set(runId, lifecyclePatch);
        }
        if (lifecycleCanonicalKey) {
          lifecycleByCanonicalKey.set(lifecycleCanonicalKey, lifecyclePatch);
        }
        applyCliAgentLifecyclePatchToRuns(runsById, lifecycleRunIds, lifecyclePatch);
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
      const mode = textArg(args, "mode") || String(result?.mode ?? "").trim();
      const cwd = textArg(args, "cwd") || String(result?.cwd ?? "").trim();
      const task = textArg(args, "task");
      const status = String(result?.status || toolCall.status || "running").trim();
      const title = cliAgentTitle(agentType, result);
      const summary = String(result?.code || toolCall.summary || task || cwd || "").trim();
      const sourceRunId = `${message.id}-${CLI_AGENT_TOOL_NAME}-${index}`;
      const cliRunId = String(result?.cliRunId || "").trim() || cliAgentRunIdForSource({
        agentType,
        cwd,
        sourceMessageId: message.id,
        sourceRunId,
        task,
      });
      const canonicalKey = cliAgentCanonicalKey(agentType, cwd);
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

function shouldRenderCliAgentRunTab(result: CliAgentRunResult | null, status: string, lifecyclePatch?: CliAgentLifecyclePatch) {
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
  if (["error", "failed", "failure", "timeout"].includes(normalizedStatus)) {
    return false;
  }
  if (code === "CLI_AGENT_EXITED_NONZERO" || code === "CLI_AGENT_LAUNCH_FAILED" || code === "CLI_AGENT_TIMEOUT") {
    return false;
  }
  return false;
}

function terminalStatusText(session: CliAgentTerminalSession | null, connecting: boolean, lang: "zh" | "en") {
  if (connecting && !session) {
    return lang === "zh" ? "连接中" : "Connecting";
  }
  if (!session) {
    return lang === "zh" ? "未连接" : "Disconnected";
  }
  if (session.alive) {
    return session.resumed ? (lang === "zh" ? "已恢复" : "Resumed") : (lang === "zh" ? "运行中" : "Running");
  }
  const status = String(session.status || "").trim();
  if (status === "exited") {
    return lang === "zh" ? "已退出" : "Exited";
  }
  if (status === "stopping") {
    return lang === "zh" ? "停止中" : "Stopping";
  }
  return lang === "zh" ? "未运行" : "Stopped";
}

function isCliAgentRunActiveForClose(run: CliAgentRunView, session?: CliAgentTerminalSession) {
  if (session?.alive) {
    return true;
  }
  const status = String(session?.status || run.result?.terminalStatus || run.status || "").trim().toLowerCase();
  if (["active", "pending", "queued", "sent", "running", "starting", "stopping"].includes(status)) {
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

function CliAgentRunTerminalPanel({
  run,
  sourceSessionId,
  active,
  lang,
  onTerminalSessionChange,
}: {
  run: CliAgentRunView;
  sourceSessionId: string;
  active: boolean;
  lang: "zh" | "en";
  onTerminalSessionChange?: (runId: string, session: CliAgentTerminalSession) => void;
}) {
  const [terminalSession, setTerminalSession] = useState<CliAgentTerminalSession | null>(null);
  const [terminalError, setTerminalError] = useState("");
  const [connecting, setConnecting] = useState(false);
  const [terminalHasOutput, setTerminalHasOutput] = useState(false);
  const terminalElementRef = useRef<HTMLDivElement | null>(null);
  const terminalRef = useRef<Terminal | null>(null);
  const fitAddonRef = useRef<FitAddon | null>(null);
  const pendingReplayRef = useRef("");
  const terminalSessionIdRef = useRef("");
  const terminalAliveRef = useRef(false);
  const terminalHasOutputRef = useRef(false);
  const lastPostedSizeRef = useRef<{ rows: number; cols: number } | null>(null);
  const terminalSessionId = String(terminalSession?.terminalSessionId || "").trim();
  const statusText = terminalStatusText(terminalSession, connecting, lang);
  const visibleCommand = Array.isArray(terminalSession?.commandPreview) && terminalSession?.commandPreview.length
    ? terminalSession.commandPreview.join(" ")
    : run.commandLine;
  const snapshotFallbackAvailable = Boolean(String(terminalSession?.screenText || "").trim());
  const transcriptReplayBlocked = terminalSession?.transcriptTailReplayable === false && !snapshotFallbackAvailable;
  const emptyText = terminalError
    || (connecting
      ? (lang === "zh" ? "正在连接命令会话..." : "Connecting terminal session...")
      : transcriptReplayBlocked
        ? (lang === "zh"
          ? "终端已连接；历史 TUI 画面无法安全重放，等待新的可渲染输出。"
          : "Terminal connected; the historical TUI screen cannot be safely replayed. Waiting for new renderable output.")
      : (lang === "zh" ? "命令会话还没有输出。" : "No terminal output yet."));

  useEffect(() => {
    terminalSessionIdRef.current = terminalSessionId;
    terminalAliveRef.current = Boolean(terminalSession?.alive);
  }, [terminalSession?.alive, terminalSessionId]);

  const markTerminalHasOutput = useCallback(() => {
    if (terminalHasOutputRef.current) {
      return;
    }
    terminalHasOutputRef.current = true;
    setTerminalHasOutput(true);
  }, []);

  const writeTerminalChunk = useCallback((chunk: string, options?: { reset?: boolean }) => {
    const text = String(chunk || "");
    const terminal = terminalRef.current;
    if (options?.reset) {
      pendingReplayRef.current = "";
      terminalHasOutputRef.current = false;
      setTerminalHasOutput(false);
      terminal?.reset();
    }
    if (!text) {
      return;
    }
    markTerminalHasOutput();
    if (terminal) {
      terminal.write(text);
      return;
    }
    pendingReplayRef.current = `${pendingReplayRef.current}${text}`.slice(-120000);
  }, [markTerminalHasOutput]);

  const replayTerminalSnapshot = useCallback((session: CliAgentTerminalSession) => {
    if (session.transcriptTailReplayable === false) {
      const screenText = String(session.screenText || "").trim();
      const screenReplay = String(session.screenReplay || "");
      if (screenText && screenReplay.trim()) {
        writeTerminalChunk(screenReplay, { reset: true });
        return;
      }
      if (screenText) {
        writeTerminalChunk(screenText.replace(/\n/g, "\r\n"), { reset: true });
        return;
      }
      writeTerminalChunk("", { reset: true });
      return;
    }
    writeTerminalChunk(String(session.transcriptTail || ""), { reset: true });
  }, [writeTerminalChunk]);

  const sendTerminalRawInput = useCallback((data: string) => {
    const sessionId = terminalSessionIdRef.current;
    if (!sessionId || !terminalAliveRef.current || !data) {
      return;
    }
    setTerminalError("");
    fetchJson<CliAgentTerminalSession>(`/api/cli-agents/terminal-sessions/${encodeURIComponent(sessionId)}/input`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ data }),
    })
      .then((session) => setTerminalSession(session))
      .catch((error) => setTerminalError(error instanceof Error ? error.message : String(error)));
  }, []);

  const postTerminalSize = useCallback((rows: number, cols: number) => {
    const sessionId = terminalSessionIdRef.current;
    if (!sessionId || rows <= 0 || cols <= 0) {
      return;
    }
    const previous = lastPostedSizeRef.current;
    if (previous?.rows === rows && previous.cols === cols) {
      return;
    }
    lastPostedSizeRef.current = { rows, cols };
    fetchJson<CliAgentTerminalSession>(`/api/cli-agents/terminal-sessions/${encodeURIComponent(sessionId)}/resize`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rows, cols }),
    })
      .then((session) => setTerminalSession(session))
      .catch(() => undefined);
  }, []);

  const fitTerminal = useCallback(() => {
    const terminal = terminalRef.current;
    const fitAddon = fitAddonRef.current;
    if (!terminal || !fitAddon) {
      return;
    }
    try {
      fitAddon.fit();
      postTerminalSize(terminal.rows, terminal.cols);
    } catch {
      return;
    }
  }, [postTerminalSize]);

  useEffect(() => {
    const element = terminalElementRef.current;
    if (!element) {
      return;
    }
    const terminal = new Terminal({
      cursorBlink: true,
      fontFamily: '"Cascadia Mono", Consolas, "SFMono-Regular", ui-monospace, monospace',
      fontSize: 13,
      lineHeight: 1.15,
      scrollback: 5000,
      convertEol: false,
      theme: {
        background: "#06100d",
        foreground: "#d7f7e8",
        cursor: "#bdf6dc",
        selectionBackground: "#225b48",
        black: "#06100d",
        red: "#ff8a8a",
        green: "#9ee7b8",
        yellow: "#f7d774",
        blue: "#8db6ff",
        magenta: "#d6a2ff",
        cyan: "#8de9df",
        white: "#d7f7e8",
        brightBlack: "#62756f",
        brightRed: "#ffaaaa",
        brightGreen: "#bdf6dc",
        brightYellow: "#ffe59d",
        brightBlue: "#b2ccff",
        brightMagenta: "#e3bcff",
        brightCyan: "#b5fff6",
        brightWhite: "#ffffff",
      },
    });
    const fitAddon = new FitAddon();
    terminal.loadAddon(fitAddon);
    terminal.open(element);
    terminalRef.current = terminal;
    fitAddonRef.current = fitAddon;

    const pending = pendingReplayRef.current;
    if (pending) {
      pendingReplayRef.current = "";
      terminal.write(pending);
    }

    const dataDisposable = terminal.onData((data) => sendTerminalRawInput(data));
    const scheduleFit = () => {
      window.requestAnimationFrame(fitTerminal);
    };
    const resizeObserver = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(scheduleFit);
    resizeObserver?.observe(element);
    window.addEventListener("resize", scheduleFit);
    scheduleFit();

    return () => {
      resizeObserver?.disconnect();
      window.removeEventListener("resize", scheduleFit);
      dataDisposable.dispose();
      terminal.dispose();
      terminalRef.current = null;
      fitAddonRef.current = null;
    };
  }, [fitTerminal, sendTerminalRawInput]);

  useEffect(() => {
    if (!terminalSessionId) {
      return;
    }
    window.requestAnimationFrame(fitTerminal);
  }, [fitTerminal, terminalSessionId]);

  useEffect(() => {
    if (!active) {
      return;
    }
    window.requestAnimationFrame(() => {
      fitTerminal();
      terminalRef.current?.focus();
    });
  }, [active, fitTerminal, terminalSessionId]);

  useEffect(() => {
    let disposed = false;
    const controller = new AbortController();
    setConnecting(true);
    setTerminalError("");
    setTerminalSession(null);
    lastPostedSizeRef.current = null;
    writeTerminalChunk("", { reset: true });

    fetchJson<CliAgentTerminalSession>("/api/cli-agents/terminal-sessions/ensure", {
      method: "POST",
      signal: controller.signal,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        agentType: run.agentType,
        task: run.task,
        cwd: run.cwd,
        mode: run.mode || "readonly",
        sourceSessionId,
        sourceMessageId: run.messageId,
        sourceRunId: run.sourceRunId,
        cliSessionId: String(run.cliSessionId || run.result?.cliSessionId || ""),
        rows: 28,
        cols: 100,
      }),
    })
      .then((session) => {
        if (disposed) {
          return;
        }
        setTerminalSession(session);
        replayTerminalSnapshot(session);
      })
      .catch((error) => {
        if (disposed || controller.signal.aborted) {
          return;
        }
        setTerminalError(error instanceof Error ? error.message : String(error));
      })
      .finally(() => {
        if (!disposed) {
          setConnecting(false);
        }
      });

    return () => {
      disposed = true;
      controller.abort();
    };
  }, [replayTerminalSnapshot, run.agentType, run.cliSessionId, run.cwd, run.messageId, run.mode, run.sourceRunId, run.task, sourceSessionId, writeTerminalChunk]);

  useEffect(() => {
    if (terminalSession) {
      onTerminalSessionChange?.(run.id, terminalSession);
    }
  }, [onTerminalSessionChange, run.id, terminalSession]);

  useEffect(() => {
    if (!terminalSessionId || typeof EventSource === "undefined") {
      return;
    }
    const stream = new EventSource(`/api/cli-agents/terminal-sessions/${encodeURIComponent(terminalSessionId)}/events`);
    const handleEvent = (event: MessageEvent) => {
      try {
        const payload = JSON.parse(String(event.data || "{}")) as CliAgentTerminalEvent;
        if (payload.session) {
          setTerminalSession(payload.session);
          if (payload.type === "terminal_snapshot") {
            replayTerminalSnapshot(payload.session);
          }
        }
        if (payload.type === "terminal_output" && payload.chunk) {
          writeTerminalChunk(payload.chunk);
        }
      } catch {
        return;
      }
    };
    stream.addEventListener("terminal_snapshot", handleEvent as EventListener);
    stream.addEventListener("terminal_output", handleEvent as EventListener);
    stream.addEventListener("terminal_status", handleEvent as EventListener);
    stream.onerror = () => {
      setTerminalSession((current) => current ? { ...current, alive: false } : current);
    };
    return () => {
      stream.removeEventListener("terminal_snapshot", handleEvent as EventListener);
      stream.removeEventListener("terminal_output", handleEvent as EventListener);
      stream.removeEventListener("terminal_status", handleEvent as EventListener);
      stream.close();
    };
  }, [replayTerminalSnapshot, terminalSessionId, writeTerminalChunk]);

  return (
    <section
      className={active ? styles.cliAgentRunPanel : `${styles.cliAgentRunPanel} ${styles.cliAgentRunPanelHidden}`}
      aria-hidden={!active}
      aria-label={`${run.title} ${lang === "zh" ? "终端" : "terminal"}`}
      data-active={active ? "true" : "false"}
      data-cli-agent-run-id={run.id}
    >
      <div className={styles.cliAgentTerminalFrame}>
        <div className={styles.cliAgentTerminalCommand} title={visibleCommand}>
          <span className={styles.cliAgentTerminalStatus}>
            <SquareTerminal size={13} aria-hidden="true" />
            <span>{statusText}</span>
          </span>
          <code>{visibleCommand}</code>
        </div>
        <div className={styles.cliAgentTerminalOutputShell}>
          <div ref={terminalElementRef} className={styles.cliAgentTerminalOutput} />
          {terminalError || !terminalHasOutput ? (
            <div className={styles.cliAgentTerminalOverlay} data-tone={terminalError ? "error" : "muted"}>
              {emptyText}
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}

function encodeUtf8Base64(value: string): string {
  const bytes = new TextEncoder().encode(value);
  let binary = "";
  bytes.forEach((byte) => {
    binary += String.fromCharCode(byte);
  });
  return btoa(binary);
}

function clearSessionImageAttachments(
  current: Record<string, ComposerImageAttachment[]>,
  sessionId: string,
) {
  const attachments = current[sessionId] ?? [];
  attachments.forEach((attachment) => URL.revokeObjectURL(attachment.previewUrl));
  const { [sessionId]: _removed, ...remaining } = current;
  return remaining;
}

function clearSessionReferenceAttachments(
  current: Record<string, SessionReferenceAttachment[]>,
  sessionId: string,
) {
  const { [sessionId]: _removed, ...remaining } = current;
  return remaining;
}

function sessionReferenceId(reference: SessionReferenceAttachment) {
  return String(reference.referenceId || reference.sessionId || "").trim();
}

function buildSessionReferencePayload(
  session: SessionSummary,
  displayName: string,
  summary: string,
): SessionReferenceAttachment {
  const sessionId = String(session.id || "").trim();
  return {
    referenceId: `session:${sessionId}`,
    kind: "session",
    sessionId,
    title: String(session.taskTitle || session.resultCard?.title || session.title || sessionId).trim(),
    agentId: String(session.agentId || "").trim(),
    agentCode: String(session.agentCode || "").trim(),
    agentDisplayName: String(displayName || session.agentDisplayName || "").trim(),
    summary: String(summary || session.taskSummary || "").trim(),
    createdAt: new Date().toISOString(),
  };
}

function startSessionReferenceDrag(
  event: DragEvent<HTMLElement>,
  reference: SessionReferenceAttachment,
) {
  const payload = JSON.stringify(reference);
  event.dataTransfer.setData(COMPOSER_SESSION_REFERENCE_MIME, payload);
  event.dataTransfer.setData("text/plain", `[Session Reference] ${reference.title || reference.sessionId}`);
  event.dataTransfer.effectAllowed = "copy";
}

function clearSessionDraftForSubmittedTurn(
  current: Record<string, string>,
  sessionId: string,
) {
  if ((current[sessionId] ?? "") === "") {
    return current;
  }
  return {
    ...current,
    [sessionId]: "",
  };
}

function restoreSubmittedDraftIfComposerStillEmpty(
  current: Record<string, string>,
  sessionId: string,
  content: string,
) {
  if (!content || (current[sessionId] ?? "") !== "") {
    return current;
  }
  return {
    ...current,
    [sessionId]: content,
  };
}

function chatRoomModeLabel(mode: ChatRoomMode, lang: "zh" | "en") {
  if (mode.id === "round_robin") {
    return lang === "zh" ? "轮询讨论" : "Round robin";
  }
  if (mode.id === "opportunistic") {
    return lang === "zh" ? "抢占式讨论" : "Opportunistic";
  }
  if (mode.id === "medical_consultation_panel") {
    return lang === "zh" ? "协同问诊会诊" : "Medical consultation";
  }
  return mode.label || mode.id;
}

function chatRoomPurposeLabel(purpose: ChatRoomPurpose, lang: "zh" | "en") {
  if (purpose.id === "chat") {
    return lang === "zh" ? "聊天" : "Chat";
  }
  if (purpose.id === "discussion") {
    return lang === "zh" ? "讨论" : "Discussion";
  }
  if (purpose.id === "meeting") {
    return lang === "zh" ? "会议" : "Meeting";
  }
  if (purpose.id === "medical_triage") {
    return lang === "zh" ? "医疗分诊建议" : "Medical triage";
  }
  return purpose.label || purpose.id;
}

function contextCompositionSegmentClass(key: string) {
  switch (key) {
    case "current_user":
      return styles.contextCompositionSegmentUser;
    case "history":
      return styles.contextCompositionSegmentHistory;
    case "active_task":
      return styles.contextCompositionSegmentTask;
    case "agent_context":
      return styles.contextCompositionSegmentAgent;
    case "guidance":
      return styles.contextCompositionSegmentGuidance;
    case "skill":
    case "active_skill":
      return styles.contextCompositionSegmentSkill;
    case "attachments":
      return styles.contextCompositionSegmentAttachments;
    default:
      return styles.contextCompositionSegmentOther;
  }
}

function cacheDonutSegmentClass(keyOrStatus: string) {
  switch (keyOrStatus) {
    case "cached":
    case "hit":
    case "computed_hit":
      return styles.cacheDonutSegmentCached;
    case "cache_write":
    case "write":
    case "computed_write":
      return styles.cacheDonutSegmentCacheWrite;
    case "uncached":
    case "miss":
    case "computed_miss":
      return styles.cacheDonutSegmentUncached;
    case "missing":
    case "computed_unknown":
      return styles.cacheDonutSegmentMissing;
    default:
      return styles.cacheDonutSegmentOther;
  }
}

function promptSegmentCategory(segment: Pick<SessionCacheCompositionSegment, "key" | "promptCategory">) {
  const category = (segment.promptCategory || "").trim();
  if (category) {
    return category;
  }
  switch ((segment.key || "").trim()) {
    case "system_prompt":
    case "system_prompt_overhead":
      return "system_prompt";
    case "agent_protocol":
    case "agent_runtime":
    case "prompt_template":
      return "agent_spec";
    case "project_rules":
      return "developer_instructions";
    case "tool_descriptions":
      return "tool_descriptions";
    case "tool_schema":
      return "tool_schema";
    case "provider_unmapped":
      return "provider_unmapped";
    case "current_user":
      return "current_user";
    case "history":
      return "history";
    case "active_task":
      return "task_state";
    case "guidance":
      return "operator_guidance";
    case "skill":
    case "active_skill":
      return "skill_context";
    case "attachments":
      return "attachments";
    default:
      return segment.key || "context";
  }
}

function cachePromptSegmentClass(segment: Pick<SessionCacheCompositionSegment, "key" | "promptCategory">) {
  switch (promptSegmentCategory(segment)) {
    case "system_prompt":
      return styles.cacheDonutSegmentSystem;
    case "agent_spec":
    case "agent_context":
      return styles.cacheDonutSegmentAgent;
    case "developer_instructions":
    case "project_context":
      return styles.cacheDonutSegmentProjectRules;
    case "tool_descriptions":
      return styles.cacheDonutSegmentToolDescriptions;
    case "tool_schema":
      return styles.cacheDonutSegmentToolSchema;
    case "provider_unmapped":
      return styles.cacheDonutSegmentProviderUnmapped;
    case "current_user":
      return styles.cacheDonutSegmentUser;
    case "history":
      return styles.cacheDonutSegmentHistory;
    case "task_state":
      return styles.cacheDonutSegmentTask;
    case "operator_guidance":
      return styles.cacheDonutSegmentGuidance;
    case "skill_context":
      return styles.cacheDonutSegmentSkill;
    case "attachments":
      return styles.cacheDonutSegmentAttachments;
    default:
      return styles.cacheDonutSegmentOther;
  }
}

function cachePromptLegendSegmentClass(segment: Pick<SessionCacheCompositionSegment, "key" | "promptCategory">) {
  switch (promptSegmentCategory(segment)) {
    case "system_prompt":
      return styles.contextCompositionSegmentSystem;
    case "agent_spec":
    case "agent_context":
      return styles.contextCompositionSegmentAgent;
    case "developer_instructions":
    case "project_context":
      return styles.contextCompositionSegmentProjectRules;
    case "tool_descriptions":
      return styles.contextCompositionSegmentToolDescriptions;
    case "tool_schema":
      return styles.contextCompositionSegmentToolSchema;
    case "provider_unmapped":
      return styles.contextCompositionSegmentProviderUnmapped;
    case "current_user":
      return styles.contextCompositionSegmentUser;
    case "history":
      return styles.contextCompositionSegmentHistory;
    case "task_state":
      return styles.contextCompositionSegmentTask;
    case "operator_guidance":
      return styles.contextCompositionSegmentGuidance;
    case "skill_context":
      return styles.contextCompositionSegmentSkill;
    case "attachments":
      return styles.contextCompositionSegmentAttachments;
    default:
      return styles.contextCompositionSegmentOther;
  }
}

function contextCompositionSegmentLabel(key: string, fallback: string, t: (key: TranslationKey) => string) {
  const dictionaryKey = `contextSegment_${key}` as TranslationKey;
  const translated = t(dictionaryKey);
  return translated === dictionaryKey ? (fallback || key) : translated;
}

function cacheCompositionSegmentLabel(key: string, fallback: string, t: (key: TranslationKey) => string) {
  const dictionaryKey = `cacheSegment_${key}` as TranslationKey;
  const translated = t(dictionaryKey);
  return translated === dictionaryKey ? (fallback || key) : translated;
}

function promptSegmentDisplayLabel(
  segment: Pick<SessionCacheCompositionSegment, "key" | "label" | "promptCategory">,
  lang: "zh" | "en",
  t: (key: TranslationKey) => string,
) {
  const key = (segment.key || "").trim();
  switch (key) {
    case "system_prompt":
    case "system_prompt_overhead":
      return lang === "zh" ? "系统提示词" : "system prompt";
    case "agent_protocol":
      return lang === "zh" ? "Agent 规范" : "agent protocol";
    case "tool_descriptions":
      return lang === "zh" ? "工具描述" : "tool descriptions";
    case "tool_schema":
      return lang === "zh" ? "工具 schema" : "tool schema";
    case "provider_unmapped":
      return lang === "zh" ? "Provider 未映射" : "provider unmapped";
    case "agent_runtime":
      return lang === "zh" ? "Agent 运行规范" : "agent runtime rules";
    case "prompt_template":
      return lang === "zh" ? "Agent 提示模板" : "agent prompt template";
    case "project_rules":
      return lang === "zh" ? "项目规范" : "project rules";
    case "research_organization":
      return lang === "zh" ? "研究组织上下文" : "research organization context";
    case "project_agent_registry":
      return lang === "zh" ? "Agent registry" : "agent registry";
    case "agent_messages":
      return lang === "zh" ? "Agent 消息" : "agent messages";
    case "provider_extra_hit":
      return lang === "zh" ? "厂商额外命中" : "provider extra";
    default:
      return contextCompositionSegmentLabel(key, segment.label || key, t);
  }
}

function promptSegmentCategoryLabel(segment: Pick<SessionCacheCompositionSegment, "key" | "promptCategory">, lang: "zh" | "en") {
  switch (promptSegmentCategory(segment)) {
    case "system_prompt":
      return lang === "zh" ? "系统" : "system";
    case "agent_spec":
    case "agent_context":
      return lang === "zh" ? "Agent 规范" : "agent spec";
    case "developer_instructions":
      return lang === "zh" ? "项目/开发规范" : "developer rules";
    case "project_context":
      return lang === "zh" ? "项目上下文" : "project context";
    case "tool_descriptions":
      return lang === "zh" ? "工具描述" : "tool descriptions";
    case "tool_schema":
      return lang === "zh" ? "工具 schema" : "tool schema";
    case "provider_unmapped":
      return lang === "zh" ? "未映射" : "unmapped";
    case "history":
      return lang === "zh" ? "历史" : "history";
    case "current_user":
      return lang === "zh" ? "本轮输入" : "current input";
    case "operator_guidance":
      return lang === "zh" ? "操作指导" : "guidance";
    case "skill_context":
      return lang === "zh" ? "技能上下文" : "skill context";
    case "attachments":
      return lang === "zh" ? "附件" : "attachments";
    default:
      return lang === "zh" ? "上下文" : "context";
  }
}

function promptSegmentAccuracyLabel(segment: Pick<SessionCacheCompositionSegment, "accuracy" | "estimated">, lang: "zh" | "en") {
  if (segment.estimated || segment.accuracy === "estimated") {
    return lang === "zh" ? "估算" : "estimated";
  }
  if (segment.accuracy === "manifest") {
    return lang === "zh" ? "manifest" : "manifest";
  }
  return "";
}

function cacheObservedStatusLabel(status: string | undefined, lang: "zh" | "en") {
  switch ((status || "").trim()) {
    case "observed_hit":
      return lang === "zh" ? "厂商命中" : "provider hit";
    case "observed_partial":
      return lang === "zh" ? "部分命中" : "partial hit";
    case "observed_miss":
      return lang === "zh" ? "厂商未命中" : "provider miss";
    case "computed_write":
      return lang === "zh" ? "计算写入" : "computed write";
    case "computed_miss":
      return lang === "zh" ? "计算未命中" : "computed miss";
    case "not_observed":
      return lang === "zh" ? "未观测" : "not observed";
    default:
      return lang === "zh" ? "未标记" : "unmarked";
  }
}

function cacheComputedStatusLabel(status: string | undefined, lang: "zh" | "en") {
  switch ((status || "").trim()) {
    case "computed_hit":
      return lang === "zh" ? "计算命中" : "computed hit";
    case "computed_write":
      return lang === "zh" ? "计算写入" : "computed write";
    case "computed_miss":
      return lang === "zh" ? "计算未命中" : "computed miss";
    case "computed_unknown":
      return lang === "zh" ? "计算未知" : "computed unknown";
    case "provider_extra_hit":
      return lang === "zh" ? "厂商额外命中" : "provider extra hit";
    default:
      return status || (lang === "zh" ? "未知" : "unknown");
  }
}

function cacheCalibrationSummaryLabel(
  status: string,
  reason: string,
  overestimatedTokens: number,
  extraCachedTokens: number,
  numberFormatter: Intl.NumberFormat,
  lang: "zh" | "en",
) {
  const normalizedStatus = (status || "").trim();
  const normalizedReason = (reason || "").trim();
  const providerName = /xiaomi|mimo/i.test(normalizedReason)
    ? "Xiaomi/MiMo"
    : /qwen/i.test(normalizedReason)
      ? "Qwen"
      : /openai|gpt/i.test(normalizedReason)
        ? "OpenAI"
        : lang === "zh" ? "厂商" : "provider";
  if (normalizedStatus === "aligned") {
    return lang === "zh" ? `${providerName} 真实命中与计算预测一致` : `${providerName} observed hits match computed estimate`;
  }
  if (normalizedStatus === "not_available") {
    return lang === "zh" ? "厂商没有返回真实缓存字段，本面板仅展示计算预测" : "Provider cache fields were not returned; showing computed estimate only";
  }
  if (overestimatedTokens > 0) {
    return lang === "zh"
      ? `${providerName} 真实命中低于计算预测，预测未兑现 ${numberFormatter.format(overestimatedTokens)} tokens`
      : `${providerName} observed hits are below computed estimate by ${numberFormatter.format(overestimatedTokens)} tokens`;
  }
  if (extraCachedTokens > 0) {
    return lang === "zh"
      ? `${providerName} 返回了计算分段外的额外命中 ${numberFormatter.format(extraCachedTokens)} tokens`
      : `${providerName} reported ${numberFormatter.format(extraCachedTokens)} extra cached tokens outside mapped segments`;
  }
  return lang === "zh" ? "已按厂商返回的真实缓存字段校准" : "Calibrated with provider-reported cache fields";
}

function contextWindowSegmentWidth(value: number, total: number) {
  if (total <= 0 || value <= 0) {
    return "0%";
  }
  return `${Math.round((Math.max(0, value) / total) * 1000) / 10}%`;
}

const MIN_CACHE_DONUT_SEGMENT_PERCENT = 3;

type CacheDonutSegment = SessionCacheCompositionSegment & {
  actualPercent: number;
  visualPercent: number;
  startPercent: number;
  visuallyAmplified: boolean;
};

function buildCacheDonutSegments(
  segments: SessionCacheCompositionSegment[],
  total: number,
  minPercent = MIN_CACHE_DONUT_SEGMENT_PERCENT,
): CacheDonutSegment[] {
  const totalTokens = Math.max(0, total);
  const positiveSegments = segments
    .map((segment) => ({
      ...segment,
      tokens: Math.max(0, segment.tokens ?? 0),
    }))
    .filter((segment) => segment.tokens > 0);
  if (!positiveSegments.length || totalTokens <= 0) {
    return [];
  }
  const rawSegments = positiveSegments.map((segment) => ({
    ...segment,
    actualPercent: (segment.tokens / totalTokens) * 100,
  }));
  const minVisualPercent = Math.max(0, minPercent);
  const minSegmentTotal = rawSegments.reduce(
    (sum, segment) => sum + (segment.actualPercent > 0 && segment.actualPercent < minVisualPercent ? minVisualPercent : 0),
    0,
  );
  const largeRawTotal = rawSegments.reduce(
    (sum, segment) => sum + (segment.actualPercent >= minVisualPercent ? segment.actualPercent : 0),
    0,
  );
  let cursor = 0;
  if (minSegmentTotal >= 100) {
    const sharedPercent = 100 / rawSegments.length;
    return rawSegments.map((segment, index) => {
      const startPercent = cursor;
      const visualPercent = index === rawSegments.length - 1 ? Math.max(0, 100 - cursor) : sharedPercent;
      cursor += visualPercent;
      return {
        ...segment,
        visualPercent,
        startPercent,
        visuallyAmplified: visualPercent > segment.actualPercent,
      };
    });
  }
  const largeScale = largeRawTotal > 0 ? (100 - minSegmentTotal) / largeRawTotal : 1;
  return rawSegments.map((segment, index) => {
    const startPercent = cursor;
    const isSmall = segment.actualPercent > 0 && segment.actualPercent < minVisualPercent;
    const rawVisualPercent = isSmall ? minVisualPercent : segment.actualPercent * largeScale;
    const visualPercent = index === rawSegments.length - 1 ? Math.max(0, 100 - cursor) : rawVisualPercent;
    cursor += visualPercent;
    return {
      ...segment,
      visualPercent,
      startPercent,
      visuallyAmplified: visualPercent > segment.actualPercent + 0.01,
    };
  });
}

function cacheDonutSegmentTitle(
  segment: CacheDonutSegment,
  totalTokens: number,
  numberFormatter: Intl.NumberFormat,
  lang: "zh" | "en",
) {
  const percent = Math.round(segment.actualPercent);
  const parts = [
    `${segment.label || segment.key}: ${numberFormatter.format(segment.tokens)} / ${numberFormatter.format(totalTokens)} · ${percent}%`,
    segment.observedStatus ? `${lang === "zh" ? "真实状态" : "observed"} ${cacheObservedStatusLabel(segment.observedStatus, lang)}` : "",
    segment.observedCachedInputTokens ? `${lang === "zh" ? "真实命中" : "observed hit"} ${numberFormatter.format(segment.observedCachedInputTokens)}` : "",
    segment.observedMissedInputTokens ? `${lang === "zh" ? "真实未命中" : "observed miss"} ${numberFormatter.format(segment.observedMissedInputTokens)}` : "",
    segment.computedOverestimatedInputTokens ? `${lang === "zh" ? "预测未兑现" : "predicted not observed"} ${numberFormatter.format(segment.computedOverestimatedInputTokens)}` : "",
    segment.cachePolicy ? `${lang === "zh" ? "缓存策略" : "cache policy"} ${segment.cachePolicy}` : "",
    segment.source ? `${lang === "zh" ? "来源" : "source"} ${segment.source}` : "",
    segment.contentPreview ? `${lang === "zh" ? "内容" : "content"} ${segment.contentPreview}` : "",
    segment.calibrationReason || "",
    segment.description || "",
    segment.visuallyAmplified ? (lang === "zh" ? "视觉段已放大，便于鼠标锁定。" : "Visual arc is amplified for hover targeting.") : "",
  ];
  return parts.filter(Boolean).join(" · ");
}

function cacheDonutSegmentStyle(segment: CacheDonutSegment, gapPercent = 0): CSSProperties {
  const gap = Math.max(0, Math.min(1, gapPercent));
  const visiblePercent = segment.visualPercent > gap
    ? Math.max(0.45, segment.visualPercent - gap)
    : segment.visualPercent;
  const offset = -(segment.startPercent + (segment.visualPercent > gap ? gap / 2 : 0));
  return {
    strokeDasharray: `${visiblePercent} ${Math.max(0, 100 - visiblePercent)}`,
    strokeDashoffset: offset,
  };
}

function removeSessionImageAttachment(
  current: Record<string, ComposerImageAttachment[]>,
  sessionId: string,
  attachmentId: string,
) {
  const attachments = current[sessionId] ?? [];
  const removed = attachments.find((attachment) => attachment.id === attachmentId);
  if (removed) {
    URL.revokeObjectURL(removed.previewUrl);
  }
  return {
    ...current,
    [sessionId]: attachments.filter((attachment) => attachment.id !== attachmentId),
  };
}

async function uploadSessionImageAttachment(sessionId: string, attachment: ComposerImageAttachment) {
  return fetchJson<ConversationAttachment>(`/api/sessions/${sessionId}/attachments`, {
    method: "POST",
    headers: {
      "Content-Type": attachment.contentType || "application/octet-stream",
      "X-Vibelution-Filename": encodeURIComponent(attachment.filename),
    },
    body: attachment.file,
  });
}

const RESIZE_HANDLE_WIDTH = 10;
const MIN_LEFT_PANEL_WIDTH = 192;
const MAX_LEFT_PANEL_WIDTH = 520;
const MIN_RIGHT_PANEL_WIDTH = 244;
const MAX_RIGHT_PANEL_WIDTH = 560;
const TARGET_CENTER_PANE_WIDTH = 520;
const KEYBOARD_RESIZE_STEP = 24;
const MENTAL_MODEL_TOGGLE_STORAGE_KEY = "vibelution.chat.mentalModelEnabled";
const MAX_COMPOSER_IMAGE_ATTACHMENTS = 4;
const MAX_COMPOSER_IMAGE_BYTES = 8 * 1024 * 1024;
const ACTIVE_INDEX_POLL_MS = 3_000;
const ACTIVE_BACKGROUND_SYNC_POLL_MS = 5_000;
const SESSION_STREAM_MIN_APPLY_INTERVAL_MS = 350;
const SESSION_STREAM_ROUTE_SWITCH_GRACE_MS = 4_000;
const CHAT_CENTER_FIRST_MEDIA_QUERY = "(max-width: 980px)";

type ResizableSide = "left" | "right";
type PetInteractionAction = "feed" | "talk" | "care";
type FeaturePresetKey = "planningMode" | "goalMode" | "toolBoost";
type RightIndexPanel = "conversations" | "members";
type ComposerImageAttachment = {
  id: string;
  file: File;
  filename: string;
  previewUrl: string;
  sizeBytes: number;
  contentType: string;
};

type DragState = {
  side: ResizableSide;
  startX: number;
  startLeftWidth: number;
  startRightWidth: number;
};

type SessionContextMenuState = {
  sessionId: string;
  session: SessionSummary;
  x: number;
  y: number;
};

const CHAT_FEATURE_PRESETS: Array<{
  key: FeaturePresetKey;
  labelKey: TranslationKey;
  hintKey: TranslationKey;
}> = [
  {
    key: "planningMode",
    labelKey: "chatFeaturePlanningMode",
    hintKey: "chatFeaturePlanningModeHint",
  },
  {
    key: "goalMode",
    labelKey: "chatFeatureGoalMode",
    hintKey: "chatFeatureGoalModeHint",
  },
  {
    key: "toolBoost",
    labelKey: "chatFeatureToolBoost",
    hintKey: "chatFeatureToolBoostHint",
  },
];

const DEFAULT_CHAT_FEATURE_PRESETS: Record<FeaturePresetKey, boolean> = {
  planningMode: false,
  goalMode: false,
  toolBoost: false,
};

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

function getDesiredCenterWidth(layoutWidth: number) {
  const usableWidth = Math.max(0, layoutWidth - RESIZE_HANDLE_WIDTH * 2);
  return Math.min(
    TARGET_CENTER_PANE_WIDTH,
    Math.max(0, usableWidth - MIN_LEFT_PANEL_WIDTH - MIN_RIGHT_PANEL_WIDTH),
  );
}

function normalizePanelWidths(layoutWidth: number, leftWidth: number, rightWidth: number) {
  const usableWidth = Math.max(0, layoutWidth - RESIZE_HANDLE_WIDTH * 2);
  const availableForPanels = Math.max(
    MIN_LEFT_PANEL_WIDTH + MIN_RIGHT_PANEL_WIDTH,
    usableWidth - getDesiredCenterWidth(layoutWidth),
  );

  let nextLeft = clamp(leftWidth, MIN_LEFT_PANEL_WIDTH, MAX_LEFT_PANEL_WIDTH);
  let nextRight = clamp(rightWidth, MIN_RIGHT_PANEL_WIDTH, MAX_RIGHT_PANEL_WIDTH);
  let overflow = nextLeft + nextRight - availableForPanels;

  if (overflow > 0) {
    const rightSlack = nextRight - MIN_RIGHT_PANEL_WIDTH;
    const leftSlack = nextLeft - MIN_LEFT_PANEL_WIDTH;

    if (rightSlack >= leftSlack) {
      const reduceRight = Math.min(overflow, rightSlack);
      nextRight -= reduceRight;
      overflow -= reduceRight;

      const reduceLeft = Math.min(overflow, nextLeft - MIN_LEFT_PANEL_WIDTH);
      nextLeft -= reduceLeft;
    } else {
      const reduceLeft = Math.min(overflow, leftSlack);
      nextLeft -= reduceLeft;
      overflow -= reduceLeft;

      const reduceRight = Math.min(overflow, nextRight - MIN_RIGHT_PANEL_WIDTH);
      nextRight -= reduceRight;
    }
  }

  return {
    leftPanelWidth: Math.round(nextLeft),
    rightPanelWidth: Math.round(nextRight),
  };
}

function getResizeBounds(side: ResizableSide, layoutWidth: number, siblingWidth: number) {
  const usableWidth = Math.max(0, layoutWidth - RESIZE_HANDLE_WIDTH * 2);
  const maxWidth = usableWidth - getDesiredCenterWidth(layoutWidth) - siblingWidth;

  if (side === "left") {
    return {
      min: MIN_LEFT_PANEL_WIDTH,
      max: Math.max(MIN_LEFT_PANEL_WIDTH, Math.min(MAX_LEFT_PANEL_WIDTH, maxWidth)),
    };
  }

  return {
    min: MIN_RIGHT_PANEL_WIDTH,
    max: Math.max(MIN_RIGHT_PANEL_WIDTH, Math.min(MAX_RIGHT_PANEL_WIDTH, maxWidth)),
  };
}

function describeError(error: unknown, fallback: string) {
  if (error instanceof Error && error.message) {
    return `${fallback}: ${error.message}`;
  }
  return fallback;
}

const TOOL_APPROVAL_LABELS: Record<string, string> = {
  agent_message_tool: "助手消息",
  agent_tool_permission_request_tool: "权限申请",
  apply_diff_edit_tool: "差异编辑",
  apply_patch_tool: "补丁编辑",
  clean_workspace_debris_tool: "清理工作区",
  cli_tool: "命令行",
  code_symbol_tool: "代码结构",
  compress_context_tool: "压缩上下文",
  conversation_log_inspect_tool: "会话日志",
  create_child_session_tool: "创建子会话",
  get_core_context_tool: "核心记忆",
  get_current_goal_tool: "当前目标",
  get_entity_history_tool: "实体历史",
  get_git_status_summary_tool: "仓库状态",
  get_recent_changes_tool: "近期变更",
  glob_tool: "列文件",
  grep_search_tool: "搜索代码",
  image2_generate_tool: "生成图片",
  knowledge_proposal_tool: "知识提案",
  knowledge_query_tool: "知识查询",
  list_child_sessions_tool: "子会话列表",
  plan_update_tool: "更新计划",
  python_lint_tool: "代码检查",
  read_file_tool: "读文件",
  record_learning_tool: "记录学习",
  run_test_for_tool: "运行测试",
  search_error_archive_tool: "错误档案",
  search_memory_tool: "搜索记忆",
  session_reference_query_tool: "引用会话",
  task_create_tool: "创建任务",
  task_list_tool: "任务列表",
  task_start_tool: "开始任务",
  task_stop_tool: "停止任务",
  task_update_tool: "更新任务",
  trigger_self_restart_tool: "重启应用",
  web_fetch_tool: "读取网页",
  web_search_tool: "网页搜索",
  write_file_tool: "写文件",
};

function toolApprovalLabels(request: AgentToolGovernanceRequest | null | undefined) {
  const delta = request?.policyDelta;
  const tools = [
    ...(delta?.grantTools ?? []),
    ...(delta?.unblockTools ?? []),
    ...(delta?.revokeTools ?? []),
    ...(delta?.blockTools ?? []),
  ]
    .map((tool) => String(tool ?? "").trim())
    .filter(Boolean);
  const seen = new Set<string>();
  const unique = tools.filter((tool) => {
    if (seen.has(tool)) {
      return false;
    }
    seen.add(tool);
    return true;
  });
  return unique.map((tool) => ({
    id: tool,
    label: TOOL_APPROVAL_LABELS[tool] ?? "工具能力",
  }));
}

function toolApprovalScopeLabel(scope: string | undefined, lang: "zh" | "en") {
  const normalized = String(scope ?? "persistent").trim().toLowerCase();
  if (normalized === "session") {
    return lang === "zh" ? "本会话" : "This session";
  }
  if (normalized === "turn") {
    return lang === "zh" ? "本轮" : "This turn";
  }
  return lang === "zh" ? "长期策略" : "Persistent";
}

function toolApprovalRiskLabel(level: string | undefined, lang: "zh" | "en") {
  const normalized = String(level ?? "low").trim().toLowerCase();
  if (normalized === "high") {
    return lang === "zh" ? "高风险" : "High risk";
  }
  if (normalized === "medium") {
    return lang === "zh" ? "中风险" : "Medium risk";
  }
  return lang === "zh" ? "低风险" : "Low risk";
}

function submitTelemetryFields(
  sessionId: string,
  options: {
    content?: string;
    attachmentCount?: number;
    referenceCount?: number;
    mentalModelEnabled?: boolean;
    editTargetId?: string;
    composerDisabled?: boolean;
    sessionBusy?: boolean;
    activePhase?: string;
    guardReason?: string;
    uploadedAttachmentCount?: number;
    error?: unknown;
  } = {},
) {
  const fields: Record<string, unknown> = {
    sessionId,
  };
  if (options.content !== undefined) {
    fields.contentLength = options.content.length;
    fields.hasContent = options.content.trim().length > 0;
  }
  if (options.attachmentCount !== undefined) {
    fields.attachmentCount = options.attachmentCount;
  }
  if (options.referenceCount !== undefined) {
    fields.referenceCount = options.referenceCount;
  }
  if (options.uploadedAttachmentCount !== undefined) {
    fields.uploadedAttachmentCount = options.uploadedAttachmentCount;
  }
  if (options.mentalModelEnabled !== undefined) {
    fields.mentalModelEnabled = options.mentalModelEnabled;
  }
  if (options.editTargetId !== undefined) {
    fields.editTargetId = options.editTargetId;
  }
  if (options.composerDisabled !== undefined) {
    fields.composerDisabled = options.composerDisabled;
  }
  if (options.sessionBusy !== undefined) {
    fields.sessionBusy = options.sessionBusy;
  }
  if (options.activePhase !== undefined) {
    fields.activePhase = options.activePhase;
  }
  if (options.guardReason !== undefined) {
    fields.guardReason = options.guardReason;
  }
  if (options.error instanceof Error) {
    fields.errorName = options.error.name;
    fields.errorMessage = options.error.message;
  } else if (options.error !== undefined) {
    fields.errorMessage = String(options.error);
  }
  return fields;
}

function postSubmitTelemetry(
  eventCode: string,
  message: string,
  sessionId: string,
  options?: Parameters<typeof submitTelemetryFields>[1],
  level: "info" | "warning" | "error" = "info",
) {
  postBrowserTelemetry({
    phase: "chat_submit",
    eventCode,
    message,
    level,
    fields: submitTelemetryFields(sessionId, options),
  });
}

function comparableErrorText(value: unknown) {
  return String(value ?? "").replace(/\s+/g, " ").trim().toLowerCase();
}

function latestVisibleTurnErrorMessage(messages: ConversationMessage[] | undefined) {
  const latestMessage = messages?.[messages.length - 1];
  return latestMessage && isTurnErrorMessage(latestMessage) ? String(latestMessage.content ?? "") : "";
}

function shouldSuppressComposerErrorForTurnError(
  composerError: string,
  latestTurnErrorMessage: string,
  turnError: SessionTurnError | null | undefined,
) {
  const composer = comparableErrorText(composerError);
  const latestMessage = comparableErrorText(latestTurnErrorMessage);
  const turnErrorMessage = comparableErrorText(turnError?.message);
  const turnErrorType = comparableErrorText(turnError?.errorType);
  if (!composer || !latestMessage) {
    return false;
  }
  return (
    (turnErrorMessage && (composer.includes(turnErrorMessage) || turnErrorMessage.includes(composer)))
    || composer.includes(latestMessage)
    || latestMessage.includes(composer)
    || (turnErrorType && composer.includes(turnErrorType))
  );
}

function isRunningPhase(value: string | null | undefined) {
  const phase = String(value ?? "").trim().toLowerCase();
  return ["queued", "running", "thinking", "tooling", "answering", "planning", "reading", "editing", "verifying"].includes(phase);
}

function isStoppingPhase(value: string | null | undefined) {
  const phase = String(value ?? "").trim().toLowerCase();
  return phase === "stopping";
}

function isBusyPhase(value: string | null | undefined) {
  const phase = String(value ?? "").trim().toLowerCase();
  return isRunningPhase(phase) || phase === "stopping";
}

function readStoredMentalModelToggle(): boolean | null {
  if (typeof window === "undefined") {
    return null;
  }
  const raw = window.localStorage.getItem(MENTAL_MODEL_TOGGLE_STORAGE_KEY);
  if (raw === "true") {
    return true;
  }
  if (raw === "false") {
    return false;
  }
  return null;
}

function writeStoredMentalModelToggle(enabled: boolean) {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(MENTAL_MODEL_TOGGLE_STORAGE_KEY, enabled ? "true" : "false");
}

function formatAgentIdentityWithRole(name: string, role: string, fallback = "Agent") {
  const cleanName = String(name || fallback || "Agent").trim() || "Agent";
  const cleanRole = String(role || "").trim();
  return cleanRole ? `${cleanName} · ${cleanRole}` : cleanName;
}

function compactAgentRoleLabel(role: string, fallback = "") {
  const cleanRole = String(role || "").trim();
  if (!cleanRole) {
    return String(fallback || "").trim();
  }
  const beforeSlash = cleanRole.split("/")[0]?.trim() || cleanRole;
  const beforePunctuation = beforeSlash.split(/[，,。；;：:]/)[0]?.trim() || beforeSlash;
  return beforePunctuation.length > 14 ? `${beforePunctuation.slice(0, 14)}...` : beforePunctuation;
}

function shouldCollapseGroupMessage(content: string) {
  const text = String(content || "").trim();
  return text.length > 260 || text.split(/\r?\n/).length > 8;
}

function shouldDefaultCollapseGroupMessage(message: ChatRoomMessage) {
  return message.audience === "internal" || message.visibility === "collapsed_by_default";
}

function agentRoleClass(tone: string) {
  return `agentRoleTag_${tone}`;
}

function avatarInitials(agentCode?: string, name?: string, fallback = "AI") {
  const code = String(agentCode ?? "").trim();
  const numericTail = code.match(/\d{2,}$/)?.[0];
  if (numericTail) {
    return numericTail.slice(-2);
  }
  const compactCode = code.replace(/[^A-Za-z0-9]/g, "");
  if (compactCode && compactCode.length <= 3) {
    return compactCode.slice(0, 2).toUpperCase();
  }
  const title = String(name ?? "").trim();
  return title.slice(0, 2) || fallback;
}

function avatarImageUrlFrom(...sources: unknown[]) {
  for (const source of sources) {
    if (!source || typeof source !== "object") {
      continue;
    }
    const record = source as { avatarImageUrl?: unknown; agentAvatarImageUrl?: unknown };
    const url = String(record.avatarImageUrl ?? record.agentAvatarImageUrl ?? "").trim();
    if (url) {
      return url;
    }
  }
  return "";
}

function conversationMetadataText(metadata: Record<string, unknown> | undefined, key: string) {
  const value = metadata?.[key];
  return typeof value === "string" ? value.trim() : "";
}

function renderAgentAvatar(className: string, imageUrl: string | undefined, fallback: string) {
  return (
    <span className={className} aria-hidden="true">
      {imageUrl ? <img src={imageUrl} alt="" className={styles.agentAvatarImage} /> : fallback}
    </span>
  );
}

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function stripGroupSpeakerPrefix(message: ChatRoomMessage, identityName = "") {
  let content = String(message.content || message.summary || "").trim();
  if (!content) {
    return "";
  }
  const code = String(message.speakerCode ?? "").trim();
  const labels = [
    message.speakerTitle,
    identityName,
    code,
  ]
    .map((item) => String(item ?? "").trim())
    .filter(Boolean);
  labels.forEach((label) => {
    content = content.replace(new RegExp(`^\\s*${escapeRegExp(label)}\\s*[:：]\\s*`), "").trim();
  });
  if (code) {
    content = content.replace(
      new RegExp(`^\\s*${escapeRegExp(code)}\\s*[·\\-]\\s*[^\\n:：]{1,40}\\s*[:：]\\s*`),
      "",
    ).trim();
  }
  return content;
}

function isAvailableGroupParticipant(participant: ChatRoomParticipant) {
  return !participant.agentMissing && participant.enabled !== false;
}

function removeDeletedSessionFromConversations(
  conversations: ConversationSummary[] | undefined,
  deletedSessionId: string,
): ConversationSummary[] | undefined {
  if (!conversations) {
    return conversations;
  }
  return conversations.filter((conversation) => {
    if (conversation.type !== "direct_agent") {
      return true;
    }
    return conversation.directSessionId !== deletedSessionId && conversation.conversationId !== deletedSessionId;
  });
}

function mergeSessionDetailIntoConversations(
  conversations: ConversationSummary[] | undefined,
  detail: SessionDetail,
): ConversationSummary[] | undefined {
  if (!conversations) {
    return conversations;
  }
  const nextConversation = sessionToConversationSummary(detail);
  const existingIndex = conversations.findIndex(
    (conversation) =>
      conversation.type === "direct_agent"
      && (conversation.directSessionId === detail.id || conversation.conversationId === detail.id),
  );
  if (existingIndex < 0) {
    return [nextConversation, ...conversations];
  }
  return conversations.map((conversation, index) =>
    index === existingIndex
      ? {
          ...conversation,
          ...nextConversation,
        }
      : conversation,
  );
}

function renameSessionInConversations(
  conversations: ConversationSummary[] | undefined,
  sessionId: string,
  title: string,
  updatedAt: string,
  session?: SessionSummary | SessionDetail,
): ConversationSummary[] | undefined {
  if (!conversations || !sessionId) {
    return conversations;
  }

  return conversations.map((conversation) => {
    const directSessionId = String(conversation.directSessionId || conversation.conversationId || "").trim();
    if (conversation.type !== "direct_agent" || directSessionId !== sessionId) {
      return conversation;
    }
    if (session && isAgentRootSession(session)) {
      return {
        ...conversation,
        title,
        agentDisplayName: title,
        updatedAt,
      };
    }
    return {
      ...conversation,
      title,
      updatedAt,
    };
  });
}

function latestSessionMessageId(detail: SessionDetail): string {
  const messages = detail.messages ?? [];
  return messages[messages.length - 1]?.id ?? "";
}

function latestSessionMessageSignal(detail: SessionDetail): string {
  const messages = detail.messages ?? [];
  const message = messages[messages.length - 1];
  if (!message) {
    return "";
  }
  return [
    message.id ?? "",
    message.streaming ? "streaming" : "settled",
    message.content?.length ?? 0,
    message.toolCalls?.length ?? 0,
    message.feedbackEvents?.length ?? 0,
  ].join(":");
}

function sessionDetailSnapshotKey(detail: SessionDetail): string {
  return [
    detail.id,
    detail.status ?? "",
    detail.currentPhase ?? "",
    detail.updatedAt ?? "",
    detail.messages?.length ?? 0,
    latestSessionMessageId(detail),
    latestSessionMessageSignal(detail),
  ].join("|");
}

function mergeAssistantDeltaIntoSessionDetail(
  detail: SessionDetail | undefined,
  payload: Extract<SessionStreamEvent, { type: "assistant_delta" }>,
): SessionDetail | undefined {
  if (!detail || detail.id !== payload.sessionId) {
    return detail;
  }
  const liveMessageId = `${payload.sessionId}-message-live`;
  const now = payload.updatedAt || new Date().toISOString();
  const messages = detail.messages ?? [];
  const liveIndex = messages.findIndex((message) => message.id === liveMessageId);
  const previous = liveIndex >= 0 ? messages[liveIndex] : undefined;
  const contentDelta = payload.contentDelta ?? payload.content ?? "";
  const thoughtDelta = payload.thoughtDelta ?? payload.thought ?? "";
  const nextContent = payload.replaceContent
    ? contentDelta
    : `${previous?.content ?? ""}${contentDelta}`;
  const nextThought = payload.replaceThought
    ? thoughtDelta
    : `${previous?.thought ?? ""}${thoughtDelta}`;
  if (!nextContent && !nextThought && !payload.stage && !(payload.feedbackEvents?.length)) {
    return {
      ...detail,
      updatedAt: now,
      messages: messages.filter((message) => message.id !== liveMessageId),
    };
  }
  const nextLiveMessage: ConversationMessage = {
    id: liveMessageId,
    role: "assistant",
    content: nextContent,
    timestamp: now,
    streaming: !payload.done,
    streamStage: payload.stage || undefined,
    thought: nextThought || undefined,
    feedbackEvents: payload.feedbackEvents ?? [],
  };
  if (liveIndex >= 0) {
    const previousLiveMessage = messages[liveIndex];
    const merged: ConversationMessage = {
      ...previousLiveMessage,
      ...nextLiveMessage,
      mentalSnapshot: previousLiveMessage.mentalSnapshot,
      toolCalls: previousLiveMessage.toolCalls,
    };
    return {
      ...detail,
      updatedAt: now,
      messages: [
        ...messages.slice(0, liveIndex),
        merged,
        ...messages.slice(liveIndex + 1),
      ],
    };
  }
  return {
    ...detail,
    updatedAt: now,
    messages: [...messages, nextLiveMessage],
  };
}

function latestMentalSnapshot(messages: ConversationMessage[] | undefined): MentalStateSnapshot | undefined {
  return [...(messages ?? [])].reverse().find((message) => message.role === "assistant" && message.mentalSnapshot)?.mentalSnapshot;
}

function latestChatRoomRound(room: ChatRoomDetail | null | undefined) {
  const rounds = room?.rounds ?? [];
  return rounds.length ? rounds[rounds.length - 1] : null;
}

export function ChatCodingRoute() {
  const { lang, t, statusLabel } = useAppI18n();
  const queryClient = useQueryClient();
  const chatWorkspaceCache = useMemo(() => createChatWorkspaceCache(queryClient), [queryClient]);
  const navigate = useNavigate();
  const location = useLocation();
  const chatPanelWidths = useShellStore((state) => state.chatPanelWidths);
  const setChatPanelWidths = useShellStore((state) => state.setChatPanelWidths);
  const activeSessionId = useChatWorkbenchStore((state) => state.activeSessionId);
  const sessionWorkspaces = useChatWorkbenchStore((state) => state.sessionWorkspaces);
  const setActiveSession = useChatWorkbenchStore((state) => state.setActiveSession);
  const hydrateSession = useChatWorkbenchStore((state) => state.hydrateSession);
  const removeSessionWorkspace = useChatWorkbenchStore((state) => state.removeSession);
  const closePreviewTab = useChatWorkbenchStore((state) => state.closePreviewTab);
  const setActiveTab = useChatWorkbenchStore((state) => state.setActiveTab);
  const [sessionFilter, setSessionFilter] = useState("");
  const [dragState, setDragState] = useState<DragState | null>(null);
  const [leftRailCollapsed, setLeftRailCollapsed] = useState(false);
  const [rightPaneCollapsed, setRightPaneCollapsed] = useState(false);
  const [centerFirstLayout, setCenterFirstLayout] = useState(false);
  const [cacheDetailOpen, setCacheDetailOpen] = useState(false);
  const centerFirstAutoCollapseRef = useRef(false);
  const imageUploadInFlightRef = useRef<Record<string, boolean>>({});
  const [sessionDrafts, setSessionDrafts] = useState<Record<string, string>>({});
  const [sessionComposerErrors, setSessionComposerErrors] = useState<Record<string, string>>({});
  const [sessionImageAttachments, setSessionImageAttachments] = useState<Record<string, ComposerImageAttachment[]>>({});
  const [sessionReferenceAttachments, setSessionReferenceAttachments] = useState<Record<string, SessionReferenceAttachment[]>>({});
  const [sessionImageUploadPending, setSessionImageUploadPending] = useState<Record<string, boolean>>({});
  const [sessionEditTargets, setSessionEditTargets] = useState<Record<string, { messageId: string; original: string }>>({});
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
  const [editingSessionTitle, setEditingSessionTitle] = useState("");
  const [sessionContextMenu, setSessionContextMenu] = useState<SessionContextMenuState | null>(null);
  const [sessionStreamConnected, setSessionStreamConnected] = useState(false);
  const [groupStreamConnected, setGroupStreamConnected] = useState(false);
  const [tokenSpeedTracker, setTokenSpeedTracker] = useState<TokenSpeedTrackerState | null>(null);
  const [petActionFeedback, setPetActionFeedback] = useState("");
  const [mentalModelEnabledForNextTurn, setMentalModelEnabledForNextTurn] = useState<boolean>(
    () => readStoredMentalModelToggle() ?? false,
  );
  const [featurePresetState, setFeaturePresetState] = useState<Record<FeaturePresetKey, boolean>>(
    DEFAULT_CHAT_FEATURE_PRESETS,
  );
  const [groupComposerOpen, setGroupComposerOpen] = useState(false);
  const [groupTitleDraft, setGroupTitleDraft] = useState("");
  const [groupModeDraft, setGroupModeDraft] = useState("round_robin");
  const [groupPurposeDraft, setGroupPurposeDraft] = useState("discussion");
  const [groupSelectedAgentIds, setGroupSelectedAgentIds] = useState<string[]>([]);
  const [collapsedConversationGroups, setCollapsedConversationGroups] = useState<Record<ConversationIndexGroupKey, boolean>>(
    DEFAULT_COLLAPSED_CONVERSATION_GROUPS,
  );
  const [rightIndexPanel, setRightIndexPanel] = useState<RightIndexPanel>("conversations");
  const [activeGroupRoomId, setActiveGroupRoomId] = useState("");
  const [expandedGroupAgentSessionIds, setExpandedGroupAgentSessionIds] = useState<string[]>([]);
  const [expandedGroupMessageIds, setExpandedGroupMessageIds] = useState<string[]>([]);
  const [groupTopicDraft, setGroupTopicDraft] = useState("");
  const [projectBusDraft, setProjectBusDraft] = useState("");
  const [projectBusInterruptTargets, setProjectBusInterruptTargets] = useState(false);
  const [groupRoomActionError, setGroupRoomActionError] = useState("");
  const [groupManageTitleDraft, setGroupManageTitleDraft] = useState("");
  const [groupManageSessionIds, setGroupManageSessionIds] = useState<string[]>([]);
  const [groupManageModeDraft, setGroupManageModeDraft] = useState("round_robin");
  const [groupManagePurposeDraft, setGroupManagePurposeDraft] = useState("discussion");
  const [closedCliAgentRunTokensBySession, setClosedCliAgentRunTokensBySession] = useState<Record<string, string[]>>({});
  const [cliAgentTerminalSessions, setCliAgentTerminalSessions] = useState<Record<string, CliAgentTerminalSession>>({});
  const [mountedCliAgentRunIdsBySession, setMountedCliAgentRunIdsBySession] = useState<Record<string, string[]>>({});
  const layoutRef = useRef<HTMLDivElement | null>(null);
  const sessionStreamErrorLoggedRef = useRef<Record<string, boolean>>({});
  const sessionStreamPayloadErrorLoggedRef = useRef<Record<string, boolean>>({});
  const sessionStreamApplyStatsRef = useRef<Record<string, { received: number; applied: number; dropped: number }>>({});
  const sessionStreamDecisionSnapshotRef = useRef({
    sessionId: "",
    shouldConnect: false,
    pageVisible: false,
    chatStartupWarmupActive: false,
    chatPollingVisible: false,
    directSessionBackgroundSyncActive: false,
    routeTargetMatches: false,
    routeSettling: false,
    routeSwitchGraceActive: false,
    routeSwitchGraceMsRemaining: 0,
  });
  const groupStreamErrorLoggedRef = useRef<Record<string, boolean>>({});
  const groupStreamPayloadErrorLoggedRef = useRef<Record<string, boolean>>({});
  const requestedSessionId = useMemo(() => {
    return new URLSearchParams(location.search).get("session") ?? "";
  }, [location.search]);
  const requestedRoomId = useMemo(() => {
    return new URLSearchParams(location.search).get("room") ?? "";
  }, [location.search]);
  const pageVisible = usePageVisibility();
  const [chatStartupDataReady, setChatStartupDataReady] = useState(false);
  const chatStartupWarmupActive = useStartupWarmup(chatStartupDataReady);
  const chatPollingVisible = pageVisible || chatStartupWarmupActive;
  const projectBusActive = activeGroupRoomId === "__project_agent_bus__";
  const groupPanelActive = Boolean(activeGroupRoomId);
  const legacyGroupRoomActive = groupPanelActive && !projectBusActive;
  const directSessionPanelActive = Boolean(activeSessionId) && !groupPanelActive;
  const sessionQueryText = sessionFilter.trim();
  const [directSessionBackgroundSyncActive, setDirectSessionBackgroundSyncActive] = useState(false);
  const [groupBackgroundSyncActive, setGroupBackgroundSyncActive] = useState(false);
  const sessionStreamRouteTargetMatches = Boolean(
    activeSessionId
    && !groupPanelActive
    && (!requestedSessionId || requestedSessionId === activeSessionId),
  );

  useEffect(() => {
    if (!sessionContextMenu) {
      return;
    }
    function closeSessionContextMenu() {
      setSessionContextMenu(null);
    }
    function handleKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape") {
        closeSessionContextMenu();
      }
    }
    window.addEventListener("pointerdown", closeSessionContextMenu);
    window.addEventListener("scroll", closeSessionContextMenu, true);
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("pointerdown", closeSessionContextMenu);
      window.removeEventListener("scroll", closeSessionContextMenu, true);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [sessionContextMenu]);
  const sessionStreamRouteSettling = Boolean(
    activeSessionId
    && !groupPanelActive
    && requestedSessionId
    && requestedSessionId !== activeSessionId,
  );
  const sessionStreamGraceSessionRef = useRef("");
  const sessionStreamGraceUntilRef = useRef(0);
  if (activeSessionId && sessionStreamGraceSessionRef.current !== activeSessionId) {
    sessionStreamGraceSessionRef.current = activeSessionId;
    sessionStreamGraceUntilRef.current = Date.now() + SESSION_STREAM_ROUTE_SWITCH_GRACE_MS;
  }
  const sessionStreamRouteSwitchGraceActive = Boolean(
    activeSessionId
    && sessionStreamRouteTargetMatches
    && sessionStreamGraceSessionRef.current === activeSessionId
    && Date.now() < sessionStreamGraceUntilRef.current,
  );
  const sessionStreamShouldConnect = Boolean(
    activeSessionId
    && sessionStreamRouteTargetMatches
    && (chatPollingVisible || sessionStreamRouteSwitchGraceActive),
  );
  sessionStreamDecisionSnapshotRef.current = {
    sessionId: activeSessionId || "",
    shouldConnect: sessionStreamShouldConnect,
    pageVisible,
    chatStartupWarmupActive,
    chatPollingVisible,
    directSessionBackgroundSyncActive,
    routeTargetMatches: sessionStreamRouteTargetMatches,
    routeSettling: sessionStreamRouteSettling,
    routeSwitchGraceActive: sessionStreamRouteSwitchGraceActive,
    routeSwitchGraceMsRemaining: Math.max(0, sessionStreamGraceUntilRef.current - Date.now()),
  };
  const groupStreamShouldConnect = Boolean(
    legacyGroupRoomActive
    && activeGroupRoomId
    && (chatPollingVisible || groupBackgroundSyncActive),
  );
  useEffect(() => {
    if (!legacyGroupRoomActive && rightIndexPanel === "members") {
      setRightIndexPanel("conversations");
    }
  }, [legacyGroupRoomActive, rightIndexPanel]);

  const runtimeQuery = useQuery({
    queryKey: queryKeys.runtimeSummary(),
    queryFn: () => fetchJson<RuntimeSummary>("/api/runtime/summary"),
    refetchInterval: resolvePollingInterval(chatPollingVisible, 5_000),
    refetchIntervalInBackground: chatStartupWarmupActive,
  });
  const petQuery = useQuery({
    queryKey: queryKeys.petSummary(),
    queryFn: () => fetchJson<PetSummary>("/api/pet/summary"),
    refetchInterval: resolvePollingInterval(chatPollingVisible, 10_000),
    refetchIntervalInBackground: chatStartupWarmupActive,
  });
  const configSummaryQuery = useQuery({
    queryKey: queryKeys.configPublic(),
    queryFn: () => fetchJson<ConfigSummary>("/api/config/public"),
    staleTime: 30_000,
  });
  const modelLabelsById = useMemo(
    () => new Map(Object.entries(configSummaryQuery.data?.modelLabels ?? {})),
    [configSummaryQuery.data?.modelLabels],
  );
  const resolveModelLabel = useCallback(
    (modelId: string) => modelLabelsById.get(modelId),
    [modelLabelsById],
  );
  const rawSessionsQuery = useSessionIndexQuery({
    queryClient,
    queryText: sessionQueryText,
    refetchInterval: resolvePollingInterval(
      chatPollingVisible,
      sessionStreamConnected && directSessionPanelActive ? false : ACTIVE_INDEX_POLL_MS,
      { backgroundMs: directSessionBackgroundSyncActive && !sessionStreamConnected ? ACTIVE_BACKGROUND_SYNC_POLL_MS : false },
    ),
    refetchIntervalInBackground: chatStartupWarmupActive || directSessionBackgroundSyncActive,
  });
  const visibleSessionsData = useMemo(
    () => rawSessionsQuery.data?.filter(isVisibleDirectSession),
    [rawSessionsQuery.data],
  );
  const sessionsQuery = {
    ...rawSessionsQuery,
    data: visibleSessionsData,
  };
  const conversationsQuery = useQuery({
    queryKey: queryKeys.conversations(),
    queryFn: () => fetchJson<ConversationSummary[]>("/api/conversations"),
    refetchInterval: resolvePollingInterval(
      chatPollingVisible,
      (sessionStreamConnected && directSessionPanelActive) || (groupStreamConnected && legacyGroupRoomActive)
        ? false
        : ACTIVE_INDEX_POLL_MS,
      {
        backgroundMs:
          (directSessionBackgroundSyncActive && !sessionStreamConnected)
          || (groupBackgroundSyncActive && !groupStreamConnected)
            ? ACTIVE_BACKGROUND_SYNC_POLL_MS
            : false,
      },
    ),
    refetchIntervalInBackground: chatStartupWarmupActive || directSessionBackgroundSyncActive || groupBackgroundSyncActive,
  });
  const teamsQuery = useQuery({
    queryKey: queryKeys.teams(),
    queryFn: () => fetchJson<TeamListPayload>("/api/teams"),
    refetchInterval: resolvePollingInterval(chatPollingVisible, directSessionPanelActive ? false : ACTIVE_INDEX_POLL_MS),
    refetchIntervalInBackground: chatStartupWarmupActive,
  });
  const agentsQuery = useQuery({
    queryKey: queryKeys.agents(),
    queryFn: () => fetchJson<AgentInstance[]>("/api/agents?detail=summary"),
    enabled: groupComposerOpen || Boolean(activeSessionId),
  });
  const chatRoomModesQuery = useQuery({
    queryKey: queryKeys.chatRoomModes(),
    queryFn: () => fetchJson<ChatRoomMode[]>("/api/chat-rooms/modes"),
    enabled: groupComposerOpen || legacyGroupRoomActive,
  });
  const chatRoomPurposesQuery = useQuery({
    queryKey: queryKeys.chatRoomPurposes(),
    queryFn: () => fetchJson<ChatRoomPurpose[]>("/api/chat-rooms/purposes"),
    enabled: groupComposerOpen || legacyGroupRoomActive,
  });
  const activeGroupRoomQuery = useQuery({
    queryKey: queryKeys.chatRoom(activeGroupRoomId || "none"),
    queryFn: () => fetchJson<ChatRoomDetail>(`/api/chat-rooms/${activeGroupRoomId}`),
    enabled: legacyGroupRoomActive,
    refetchInterval: legacyGroupRoomActive
      ? resolvePollingInterval(
          chatPollingVisible,
          groupStreamConnected ? false : 3_000,
          { backgroundMs: groupBackgroundSyncActive && !groupStreamConnected ? ACTIVE_BACKGROUND_SYNC_POLL_MS : false },
        )
      : false,
    refetchIntervalInBackground: chatStartupWarmupActive || groupBackgroundSyncActive,
  });
  const projectAgentBusQuery = useQuery({
    queryKey: queryKeys.projectAgentBus(),
    queryFn: () => listProjectAgentBusTimeline(),
    enabled: projectBusActive,
    refetchInterval: projectBusActive ? resolvePollingInterval(chatPollingVisible, 3_000) : false,
    refetchIntervalInBackground: chatStartupWarmupActive,
  });
  const expandedGroupAgentDetailQueries = useQueries({
    queries: expandedGroupAgentSessionIds.map((sessionId) => ({
      queryKey: queryKeys.session(sessionId || "none"),
      queryFn: () => fetchJson<SessionDetail>(`/api/sessions/${sessionId}`),
      enabled: legacyGroupRoomActive && Boolean(sessionId),
      refetchInterval: legacyGroupRoomActive && sessionId
        ? resolvePollingInterval(
            chatPollingVisible,
            3_000,
            { backgroundMs: groupBackgroundSyncActive && !groupStreamConnected ? ACTIVE_BACKGROUND_SYNC_POLL_MS : false },
          )
        : false,
      refetchIntervalInBackground: chatStartupWarmupActive || groupBackgroundSyncActive,
    })),
  });
  const syncSessionDetail = useCallback(
    (detail: SessionDetail) => {
      let shouldSyncSummaries = true;
      queryClient.setQueryData<SessionDetail>(queryKeys.session(detail.id), (previous) => {
        if (previous && sessionDetailSnapshotKey(previous) === sessionDetailSnapshotKey(detail)) {
          shouldSyncSummaries = false;
          return previous;
        }
        return detail;
      });
      if (!shouldSyncSummaries) {
        return;
      }
      updateSessionSummaryCaches(queryClient, (sessions) =>
        mergeSessionDetailIntoSummaries(sessions, detail),
      );
      queryClient.setQueryData<ConversationSummary[]>(queryKeys.conversations(), (conversations) =>
        mergeSessionDetailIntoConversations(conversations, detail),
      );
    },
    [queryClient],
  );
  const syncChatRoomDetail = useCallback(
    (room: ChatRoomDetail) => {
      queryClient.setQueryData(queryKeys.chatRoom(room.roomId), room);
      if (String(room.status ?? "").trim().toLowerCase() !== "running") {
        void chatWorkspaceCache.afterChatRoomChanged(room.roomId);
      }
    },
    [chatWorkspaceCache, queryClient],
  );
  const directSessionActiveSummary = useMemo(
    () => (activeSessionId ? sessionsQuery.data?.find((session) => session.id === activeSessionId) : undefined),
    [activeSessionId, sessionsQuery.data],
  );
  useEffect(() => {
    setGroupBackgroundSyncActive(Boolean(
      legacyGroupRoomActive
      && isBusyPhase(activeGroupRoomQuery.data?.status),
    ));
  }, [activeGroupRoomQuery.data?.status, legacyGroupRoomActive]);
  useEffect(() => {
    if (requestedRoomId && activeGroupRoomId !== requestedRoomId) {
      setActiveGroupRoomId(requestedRoomId);
      setRightIndexPanel("members");
      setRightPaneCollapsed(false);
      setGroupRoomActionError("");
      return;
    }
    if (
      requestedSessionId
      && !requestedRoomId
      && sessionsQuery.data?.some((session) => session.id === requestedSessionId)
      && activeSessionId !== requestedSessionId
    ) {
      setActiveGroupRoomId("");
      setActiveSession(requestedSessionId);
      return;
    }
    if (!activeSessionId && sessionsQuery.data && sessionsQuery.data.length > 0) {
      setActiveSession(sessionsQuery.data[0].id);
      return;
    }
    if (
      activeSessionId
      && !requestedRoomId
      && sessionsQuery.data
      && sessionsQuery.data.length > 0
      && !sessionsQuery.data.some((session) => session.id === activeSessionId)
    ) {
      setActiveSession(sessionsQuery.data[0].id);
    }
  }, [activeGroupRoomId, activeSessionId, requestedRoomId, requestedSessionId, sessionsQuery.data, setActiveSession]);

  useEffect(() => {
    const pendingHandoff = loadPendingSelfEvolutionHandoff();
    if (!pendingHandoff || !sessionsQuery.data || sessionsQuery.data.length === 0) {
      return;
    }
    const matchedSession = sessionsQuery.data.find((item) => item.id === pendingHandoff.sessionId);
    const targetSessionId = matchedSession?.id || activeSessionId || sessionsQuery.data[0]?.id || "";
    if (!targetSessionId) {
      return;
    }
    if (activeSessionId !== targetSessionId) {
      setActiveSession(targetSessionId);
    }
    setSessionDrafts((current) => ({
      ...current,
      [targetSessionId]: pendingHandoff.content,
    }));
    setSessionComposerErrors((current) => ({
      ...current,
      [targetSessionId]: "",
    }));
    clearPendingSelfEvolutionHandoff();
  }, [activeSessionId, sessionsQuery.data, setActiveSession]);

  const sessionDetailQuery = useQuery({
    queryKey: queryKeys.session(activeSessionId ?? "none"),
    enabled: Boolean(activeSessionId),
    queryFn: () => fetchJson<SessionDetail>(`/api/sessions/${activeSessionId}`),
    refetchInterval: activeSessionId
      ? resolvePollingInterval(
          chatPollingVisible,
          sessionStreamConnected ? false : 3_000,
          { backgroundMs: directSessionBackgroundSyncActive && !sessionStreamConnected ? ACTIVE_BACKGROUND_SYNC_POLL_MS : false },
        )
      : false,
    refetchIntervalInBackground: chatStartupWarmupActive || directSessionBackgroundSyncActive,
  });
  useEffect(() => {
    const directReady = Boolean(activeSessionId ? sessionDetailQuery.data : sessionsQuery.data);
    const groupReady = !legacyGroupRoomActive || Boolean(activeGroupRoomQuery.data);
    if (runtimeQuery.data && sessionsQuery.data && conversationsQuery.data && teamsQuery.data && directReady && groupReady) {
      setChatStartupDataReady(true);
    }
  }, [
    activeGroupRoomQuery.data,
    activeSessionId,
    conversationsQuery.data,
    legacyGroupRoomActive,
    runtimeQuery.data,
    sessionDetailQuery.data,
    sessionsQuery.data,
    teamsQuery.data,
  ]);
  useEffect(() => {
    setDirectSessionBackgroundSyncActive(Boolean(
      activeSessionId
      && directSessionPanelActive
      && isBusyPhase(sessionDetailQuery.data?.currentPhase || directSessionActiveSummary?.currentPhase || directSessionActiveSummary?.status),
    ));
  }, [
    activeSessionId,
    directSessionActiveSummary?.currentPhase,
    directSessionActiveSummary?.status,
    directSessionPanelActive,
    sessionDetailQuery.data?.currentPhase,
  ]);

  const submitTurnMutation = useMutation({
    mutationFn: async (
      {
        sessionId,
        content,
        mentalModelEnabled,
        attachmentIds,
        references,
      }: {
        sessionId: string;
        content: string;
        mentalModelEnabled: boolean;
        attachmentIds?: string[];
        references?: SessionReferenceAttachment[];
      },
    ) => {
      postSubmitTelemetry(
        "browser.chat_submit.request_started",
        "Direct chat submit request started.",
        sessionId,
        {
          content,
          attachmentCount: attachmentIds?.length ?? 0,
          referenceCount: references?.length ?? 0,
          mentalModelEnabled,
        },
      );
      return fetchJson<SessionTurnAcceptedResponse>(`/api/sessions/${sessionId}/messages`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Prefer": "respond-async",
        },
        body: JSON.stringify({
          content,
          contentUtf8Base64: encodeUtf8Base64(content),
          attachmentIds: attachmentIds ?? [],
          references: references ?? [],
          mentalModelEnabled,
        }),
      });
    },
    onMutate: async (variables) => {
      postSubmitTelemetry(
        "browser.chat_submit.mutate_called",
        "Direct chat submit mutation started.",
        variables.sessionId,
        {
          content: variables.content,
          attachmentCount: variables.attachmentIds?.length ?? 0,
          referenceCount: variables.references?.length ?? 0,
          mentalModelEnabled: variables.mentalModelEnabled,
        },
      );
      queryClient.setQueryData<SessionDetail>(queryKeys.session(variables.sessionId), (detail) =>
        markSessionDetailRunning(appendOptimisticUserMessage(detail, variables)),
      );
      updateSessionSummaryCaches(queryClient, (sessions) =>
        markSessionSummaryRunning(sessions, variables.sessionId),
      );
    },
    onSuccess: (acceptedTurn, variables) => {
      postSubmitTelemetry(
        "browser.chat_submit.accepted",
        "Direct chat submit was accepted by the backend.",
        variables.sessionId,
        {
          content: variables.content,
          attachmentCount: variables.attachmentIds?.length ?? 0,
          referenceCount: variables.references?.length ?? 0,
          mentalModelEnabled: variables.mentalModelEnabled,
        },
      );
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: "",
      }));
      setSessionImageAttachments((current) => clearSessionImageAttachments(current, variables.sessionId));
      setSessionReferenceAttachments((current) => clearSessionReferenceAttachments(current, variables.sessionId));
      queryClient.setQueryData<SessionDetail>(queryKeys.session(variables.sessionId), markSessionDetailRunning);
      void chatWorkspaceCache.afterDirectTurnAccepted(acceptedTurn.sessionId || variables.sessionId);
    },
    onError: (error, variables) => {
      postSubmitTelemetry(
        "browser.chat_submit.request_failed",
        "Direct chat submit request failed before the backend accepted the turn.",
        variables.sessionId,
        {
          content: variables.content,
          attachmentCount: variables.attachmentIds?.length ?? 0,
          referenceCount: variables.references?.length ?? 0,
          mentalModelEnabled: variables.mentalModelEnabled,
          error,
        },
        "error",
      );
      queryClient.setQueryData<SessionDetail>(queryKeys.session(variables.sessionId), (detail) =>
        removeOptimisticUserMessage(detail, variables),
      );
      setSessionDrafts((current) => restoreSubmittedDraftIfComposerStillEmpty(current, variables.sessionId, variables.content));
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: describeError(error, t("submitFailed")),
      }));
      void chatWorkspaceCache.afterDirectTurnFailed(variables.sessionId);
    },
  });

  const editResubmitMutation = useMutation({
    mutationFn: async (
      {
        sessionId,
        messageId,
        content,
        mentalModelEnabled,
        attachmentIds: _attachmentIds,
      }: {
        sessionId: string;
        messageId: string;
        content: string;
        mentalModelEnabled: boolean;
        attachmentIds?: string[];
      },
    ) =>
      fetchJson<SessionDetail>(`/api/sessions/${sessionId}/messages/edit-resubmit`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ messageId, content, contentUtf8Base64: encodeUtf8Base64(content), mentalModelEnabled }),
      }),
    onMutate: async (variables) => {
      queryClient.setQueryData<SessionDetail>(queryKeys.session(variables.sessionId), markSessionDetailRunning);
      updateSessionSummaryCaches(queryClient, (sessions) =>
        markSessionSummaryRunning(sessions, variables.sessionId),
      );
    },
    onSuccess: (nextDetail, variables) => {
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: "",
      }));
      setSessionDrafts((current) => ({
        ...current,
        [variables.sessionId]: "",
      }));
      setSessionEditTargets((current) => {
        const { [variables.sessionId]: _removed, ...remaining } = current;
        return remaining;
      });
      syncSessionDetail(nextDetail);
      void chatWorkspaceCache.afterSessionChanged();
    },
    onError: (error, variables) => {
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: describeError(error, t("editResubmitFailed")),
      }));
      void chatWorkspaceCache.afterDirectTurnFailed(variables.sessionId);
    },
  });

  const stopTurnMutation = useMutation({
    mutationFn: async ({ sessionId }: { sessionId: string }) =>
      fetchJson<SessionDetail>(`/api/sessions/${sessionId}/stop`, {
        method: "POST",
      }),
    onSuccess: (nextDetail, variables) => {
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: "",
      }));
      syncSessionDetail(nextDetail);
      void chatWorkspaceCache.afterSessionChanged();
    },
    onError: (error, variables) => {
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: describeError(error, t("stopFailed")),
      }));
      void chatWorkspaceCache.afterDirectTurnFailed(variables.sessionId);
    },
  });

  const sessionGuidanceMutation = useMutation({
    mutationFn: async (
      {
        sessionId,
        content,
        mode,
      }: {
        sessionId: string;
        content: string;
        mode: SessionGuidanceMode;
      },
    ) =>
      fetchJson<SessionDetail>(`/api/sessions/${sessionId}/guidance`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ content, mode }),
      }),
    onSuccess: (nextDetail, variables) => {
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: "",
      }));
      setSessionDrafts((current) => ({
        ...current,
        [variables.sessionId]: "",
      }));
      syncSessionDetail(nextDetail);
      void chatWorkspaceCache.afterSessionChanged({ sessionId: variables.sessionId });
    },
    onError: (error, variables) => {
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: describeError(error, t("guidanceFailed")),
      }));
      void chatWorkspaceCache.refreshSessionRuntime(variables.sessionId);
    },
  });

  const createSessionMutation = useMutation({
    mutationFn: async () =>
      fetchJson<SessionDetail>("/api/sessions", {
        method: "POST",
      }),
    onSuccess: (nextDetail) => {
      setActiveGroupRoomId("");
      setRightIndexPanel("conversations");
      setActiveSession(nextDetail.id);
      setSessionFilter("");
      setSessionComposerErrors((current) => ({
        ...current,
        [nextDetail.id]: "",
      }));
      syncSessionDetail(nextDetail);
      void chatWorkspaceCache.afterSessionChanged();
    },
    onError: (error) => {
      setSessionComposerErrors((current) => ({
        ...current,
        __sessions__: describeError(error, t("createSessionFailed")),
      }));
      void chatWorkspaceCache.refreshConversationIndex();
    },
  });

  const createGroupRoomMutation = useMutation({
    mutationFn: async (
      { title, agentIds, mode, purpose }: { title: string; agentIds: string[]; mode: string; purpose: string },
    ) =>
      fetchJson<ChatRoomDetail>("/api/chat-rooms", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ title, agentIds, mode, purpose }),
      }),
    onSuccess: (room) => {
      setGroupComposerOpen(false);
      setGroupTitleDraft("");
      setGroupModeDraft("round_robin");
      setGroupPurposeDraft("discussion");
      setGroupSelectedAgentIds([]);
      setSessionFilter("");
      setSessionComposerErrors((current) => ({
        ...current,
        __sessions__: "",
      }));
      setActiveGroupRoomId(room.roomId);
      setRightIndexPanel("members");
      queryClient.setQueryData(queryKeys.chatRoom(room.roomId), room);
      void chatWorkspaceCache.afterChatRoomChanged(room.roomId);
    },
    onError: (error) => {
      setSessionComposerErrors((current) => ({
        ...current,
        __sessions__: describeError(
          error,
          lang === "zh" ? "创建群聊失败" : "Create group chat failed",
        ),
      }));
    },
  });

  const startGroupRoundMutation = useMutation({
    mutationFn: async (
      { roomId, topic, mode, purpose }: { roomId: string; topic: string; mode: string; purpose: string },
    ) =>
      fetchJson<ChatRoomRoundAcceptedResponse>(`/api/chat-rooms/${roomId}/rounds`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Prefer": "respond-async",
        },
        body: JSON.stringify({ topic, mode, purpose }),
      }),
    onSuccess: (accepted) => {
      setActiveGroupRoomId(accepted.roomId);
      setRightIndexPanel("members");
      setGroupTopicDraft("");
      setGroupRoomActionError("");
      void chatWorkspaceCache.afterGroupRoundStarted(accepted.roomId);
    },
    onError: (error) => {
      setGroupRoomActionError(describeError(error, lang === "zh" ? "启动群聊讨论失败" : "Run group discussion failed"));
      if (activeGroupRoomId) {
        void chatWorkspaceCache.afterChatRoomChanged(activeGroupRoomId);
      }
    },
  });

  const stopGroupRoundMutation = useMutation({
    mutationFn: async ({ roomId }: { roomId: string }) =>
      fetchJson<ChatRoomDetail>(`/api/chat-rooms/${roomId}/stop`, {
        method: "POST",
      }),
    onSuccess: (room) => {
      setActiveGroupRoomId(room.roomId);
      setRightIndexPanel("members");
      setGroupRoomActionError("");
      syncChatRoomDetail(room);
      void chatWorkspaceCache.afterGroupRoundStopped(room.roomId);
    },
    onError: (error, variables) => {
      setGroupRoomActionError(describeError(error, lang === "zh" ? "停止群聊讨论失败" : "Stop group discussion failed"));
      void chatWorkspaceCache.afterGroupRoundStopped(variables.roomId);
    },
  });

  const sendProjectBusMessageMutation = useMutation({
    mutationFn: async (
      {
        content,
        interruptTargets,
      }: {
        content: string;
        interruptTargets: boolean;
      },
    ) =>
      sendProjectAgentBusMessage({ content, interruptTargets }),
    onSuccess: () => {
      setProjectBusDraft("");
      setGroupRoomActionError("");
      void chatWorkspaceCache.afterProjectBusChanged();
    },
    onError: (error) => {
      setGroupRoomActionError(describeError(error, lang === "zh" ? "发送总群引导失败" : "Send project bus guidance failed"));
      void chatWorkspaceCache.afterProjectBusFailed();
    },
  });

  const revokeProjectBusMessageMutation = useMutation({
    mutationFn: async ({ eventId }: { eventId: string }) =>
      revokeProjectAgentBusMessage({
        eventId,
        reason: "user_recalled_project_bus_message",
      }),
    onSuccess: () => {
      setGroupRoomActionError("");
      void chatWorkspaceCache.afterProjectBusChanged();
    },
    onError: (error) => {
      setGroupRoomActionError(describeError(error, lang === "zh" ? "撤回总群消息失败" : "Recall project bus message failed"));
      void chatWorkspaceCache.afterProjectBusFailed();
    },
  });

  const updateGroupRoomMutation = useMutation({
    mutationFn: async (
      { roomId, title, sessionIds, mode, purpose }: {
        roomId: string;
        title: string;
        sessionIds: string[];
        mode: string;
        purpose: string;
      },
    ) =>
      fetchJson<ChatRoomDetail>(`/api/chat-rooms/${roomId}`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          title,
          participantSessionIds: sessionIds,
          mode,
          purpose,
        }),
      }),
    onSuccess: (room) => {
      setActiveGroupRoomId(room.roomId);
      setRightIndexPanel("members");
      setGroupManageTitleDraft(room.title || "");
      setGroupManageSessionIds(room.participants.map((participant) => participant.sessionId));
      setGroupManageModeDraft(room.mode || "round_robin");
      setGroupManagePurposeDraft(room.purpose || "discussion");
      setGroupRoomActionError("");
      queryClient.setQueryData(queryKeys.chatRoom(room.roomId), room);
      void chatWorkspaceCache.afterChatRoomChanged(room.roomId);
    },
    onError: (error) => {
      setGroupRoomActionError(describeError(error, lang === "zh" ? "更新群聊失败" : "Update group failed"));
      if (activeGroupRoomId) {
        void chatWorkspaceCache.afterChatRoomChanged(activeGroupRoomId);
      }
    },
  });

  const deleteGroupRoomMutation = useMutation({
    mutationFn: async ({ roomId }: { roomId: string }) =>
      fetchJson<{ deleted: boolean; roomId: string }>(`/api/chat-rooms/${roomId}`, {
        method: "DELETE",
      }),
    onSuccess: (_payload, variables) => {
      setActiveGroupRoomId("");
      setRightIndexPanel("conversations");
      setGroupTopicDraft("");
      setGroupRoomActionError("");
      setGroupManageTitleDraft("");
      setGroupManageSessionIds([]);
      setGroupManageModeDraft("round_robin");
      queryClient.removeQueries({ queryKey: queryKeys.chatRoom(variables.roomId), exact: true });
      void chatWorkspaceCache.afterChatRoomChanged(variables.roomId);
    },
    onError: (error) => {
      setGroupRoomActionError(describeError(error, lang === "zh" ? "删除群聊失败" : "Delete group failed"));
    },
  });

  const resetGroupRoomMutation = useMutation({
    mutationFn: async ({ roomId }: { roomId: string }) =>
      fetchJson<ChatRoomDetail>(`/api/chat-rooms/${roomId}/reset`, {
        method: "POST",
      }),
    onSuccess: (room) => {
      setActiveGroupRoomId(room.roomId);
      setRightIndexPanel("members");
      setGroupRoomActionError("");
      syncChatRoomDetail(room);
      void chatWorkspaceCache.afterChatRoomChanged(room.roomId);
    },
    onError: (error) => {
      setGroupRoomActionError(describeError(error, lang === "zh" ? "重置群聊失败" : "Reset group failed"));
      if (activeGroupRoomId) {
        void chatWorkspaceCache.afterChatRoomChanged(activeGroupRoomId);
      }
    },
  });

  const deleteSessionMutation = useMutation({
    mutationFn: async ({ sessionId }: { sessionId: string }) =>
      fetchJson<SessionDeleteResponse>(`/api/sessions/${sessionId}`, {
        method: "DELETE",
        headers: {
          "Prefer": "respond-async",
        },
      }),
    onSuccess: (deleteResult, variables) => {
      const nextActiveSessionId = deleteResult.nextActiveSessionId || "";
      removeSessionWorkspace(variables.sessionId, nextActiveSessionId);
      setActiveSession(nextActiveSessionId);
      setSessionDrafts((current) => {
        const { [variables.sessionId]: _removed, ...remaining } = current;
        return remaining;
      });
      setSessionImageAttachments((current) => clearSessionImageAttachments(current, variables.sessionId));
      delete imageUploadInFlightRef.current[variables.sessionId];
      setSessionImageUploadPending((current) => {
        const { [variables.sessionId]: _removed, ...remaining } = current;
        return remaining;
      });
      setSessionComposerErrors((current) => {
        const { [variables.sessionId]: _removed, ...remaining } = current;
        return nextActiveSessionId
          ? {
              ...remaining,
              [nextActiveSessionId]: "",
            }
          : remaining;
      });
      queryClient.removeQueries({ queryKey: queryKeys.session(variables.sessionId), exact: true });
      updateSessionSummaryCaches(queryClient, (sessions) =>
        sessions?.filter((session) => session.id !== variables.sessionId),
      );
      queryClient.setQueryData<ConversationSummary[]>(queryKeys.conversations(), (conversations) =>
        removeDeletedSessionFromConversations(conversations, variables.sessionId),
      );
      setGroupManageSessionIds((current) => current.filter((sessionId) => sessionId !== variables.sessionId));
      void chatWorkspaceCache.afterChatRoomsChanged();
      if (nextActiveSessionId) {
        void chatWorkspaceCache.refreshSessionRuntime(nextActiveSessionId);
      }
      if (activeGroupRoomId) {
        void chatWorkspaceCache.afterChatRoomChanged(activeGroupRoomId);
      }
      void chatWorkspaceCache.afterSessionChanged();
    },
    onError: (error, variables) => {
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: describeError(error, t("deleteSessionFailed")),
      }));
      void chatWorkspaceCache.refreshSessionRuntime(variables.sessionId);
    },
  });

  const renameSessionMutation = useMutation({
    mutationFn: async ({ sessionId, title }: { sessionId: string; title: string }) =>
      fetchJson<SessionDetail>(`/api/sessions/${sessionId}`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ title }),
      }),
    onMutate: (variables) => {
      const updatedAt = new Date().toISOString();
      const previousSessions = queryClient.getQueryData<SessionSummary[]>(queryKeys.sessions());
      const previousSessionIndexCaches = captureSessionIndexCacheSnapshots(queryClient);
      const previousConversations = queryClient.getQueryData<ConversationSummary[]>(queryKeys.conversations());
      const previousDetail = queryClient.getQueryData<SessionDetail>(queryKeys.session(variables.sessionId));
      const targetSession = previousDetail ?? previousSessions?.find((session) => session.id === variables.sessionId);
      setEditingSessionId(null);
      setEditingSessionTitle("");
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: "",
      }));
      updateSessionSummaryCaches(queryClient, (sessions) =>
        renameSessionInSummaries(sessions, variables.sessionId, variables.title, updatedAt),
      );
      queryClient.setQueryData<ConversationSummary[]>(queryKeys.conversations(), (conversations) =>
        renameSessionInConversations(conversations, variables.sessionId, variables.title, updatedAt, targetSession),
      );
      queryClient.setQueryData<SessionDetail>(queryKeys.session(variables.sessionId), (detail) =>
        renameSessionDetail(detail, variables.sessionId, variables.title, updatedAt),
      );
      return { previousSessions, previousSessionIndexCaches, previousConversations, previousDetail };
    },
    onSuccess: (nextDetail, variables) => {
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: "",
      }));
      const confirmedTitle = String(nextDetail.title || variables.title).trim() || variables.title;
      const confirmedUpdatedAt = String(nextDetail.updatedAt || new Date().toISOString()).trim();
      updateSessionSummaryCaches(queryClient, (sessions) =>
        renameSessionInSummaries(sessions, variables.sessionId, confirmedTitle, confirmedUpdatedAt),
      );
      queryClient.setQueryData<ConversationSummary[]>(queryKeys.conversations(), (conversations) =>
        renameSessionInConversations(conversations, variables.sessionId, confirmedTitle, confirmedUpdatedAt, nextDetail),
      );
      queryClient.setQueryData<SessionDetail>(queryKeys.session(variables.sessionId), (detail) =>
        renameSessionDetail(detail, variables.sessionId, confirmedTitle, confirmedUpdatedAt),
      );
      queryClient.setQueryData<SessionDetail>(queryKeys.session(variables.sessionId), (detail) => ({
        ...(detail ?? nextDetail),
        ...nextDetail,
      }));
    },
    onError: (error, variables, context) => {
      if (context?.previousSessions) {
        queryClient.setQueryData(queryKeys.sessions(), context.previousSessions);
      }
      restoreSessionIndexCacheSnapshots(queryClient, context?.previousSessionIndexCaches);
      if (context?.previousConversations) {
        queryClient.setQueryData(queryKeys.conversations(), context.previousConversations);
      }
      if (context?.previousDetail) {
        queryClient.setQueryData(queryKeys.session(variables.sessionId), context.previousDetail);
      }
      setEditingSessionId(variables.sessionId);
      setEditingSessionTitle(variables.title);
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: describeError(error, t("renameSessionFailed")),
      }));
    },
  });

  const addSessionToReviewMutation = useMutation({
    mutationFn: async ({ sessionId }: { sessionId: string }) =>
      fetchJson<SessionChatReviewCandidateResponse>(
        `/api/sessions/${sessionId}/chat-review-candidate`,
        {
          method: "POST",
        },
      ),
    onSuccess: (payload, variables) => {
      const detail = payload.summary
        ? `${t("addSessionToReviewSucceeded")} ${payload.summary}`
        : t("addSessionToReviewSucceeded");
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: detail,
        __sessions__: "",
      }));
      void queryClient.invalidateQueries({ queryKey: queryKeys.evolutionChatReview() });
    },
    onError: (error, variables) => {
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: describeError(error, t("addSessionToReviewFailed")),
      }));
      void queryClient.invalidateQueries({ queryKey: queryKeys.evolutionChatReview() });
    },
  });

  const resolveToolApprovalMutation = useMutation({
    mutationFn: async (
      { request, decision }: {
        request: AgentToolGovernanceRequest;
        decision: "approve" | "reject";
      },
    ) =>
      fetchJson<AgentToolGovernanceRequest>(
        `/api/agents/${encodeURIComponent(request.targetAgentId)}/tool-governance-requests/${encodeURIComponent(request.requestId)}`,
        {
          method: "PATCH",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            decision,
            resolvedBy: "user",
            resolutionNote: decision === "approve" ? "会话内批准" : "会话内拒绝",
          }),
        },
      ),
    onSuccess: (_payload, variables) => {
      const sessionId = activeSessionId || variables.request.sourceSessionId || "";
      setSessionComposerErrors((current) => (sessionId ? { ...current, [sessionId]: "" } : current));
      if (sessionId) {
        void queryClient.invalidateQueries({ queryKey: queryKeys.session(sessionId) });
        void chatWorkspaceCache.refreshSessionRuntime(sessionId);
      }
      void queryClient.invalidateQueries({ queryKey: queryKeys.agents() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.agentConfigWorkspace() });
      void chatWorkspaceCache.afterSessionChanged({ sessionId });
    },
    onError: (error, variables) => {
      const sessionId = activeSessionId || variables.request.sourceSessionId || "__sessions__";
      setSessionComposerErrors((current) => ({
        ...current,
        [sessionId]: describeError(error, lang === "zh" ? "处理工具审批失败" : "Resolve tool approval failed"),
      }));
    },
  });

  const petActionMutation = useMutation({
    mutationFn: async ({ action }: { action: PetInteractionAction }) =>
      fetchJson<PetActionResponse>("/api/pet/actions", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ action }),
      }),
    onSuccess: (payload) => {
      setPetActionFeedback(payload.message);
      queryClient.setQueryData(queryKeys.petSummary(), payload.summary);
      void queryClient.invalidateQueries({ queryKey: queryKeys.petSummary() });
    },
    onError: (error) => {
      setPetActionFeedback(describeError(error, lang === "zh" ? "宠物互动失败" : "Pet interaction failed"));
      void queryClient.invalidateQueries({ queryKey: queryKeys.petSummary() });
    },
  });

  const activeGroupRoom = activeGroupRoomQuery.data;
  const teams = teamsQuery.data?.teams ?? [];
  const linkedTeamRoomIds = useMemo(() => {
    return new Set(teams.map((team) => String(team.linkedChatRoomId ?? "").trim()).filter(Boolean));
  }, [teams]);
  const activeGroupTeam = useMemo(() => {
    const roomId = String(activeGroupRoom?.roomId || activeGroupRoomId || "").trim();
    const configTeamId = String((activeGroupRoom?.config ?? {}).teamId ?? "").trim();
    return teams.find((team) => {
      const teamId = String(team.teamId ?? "").trim();
      const linkedRoomId = String(team.linkedChatRoomId ?? team.linkedChatRoom?.roomId ?? "").trim();
      return (configTeamId && teamId === configTeamId) || (roomId && linkedRoomId === roomId);
    }) ?? null;
  }, [activeGroupRoom?.config, activeGroupRoom?.roomId, activeGroupRoomId, teams]);
  const activeGroupTeamOwned = Boolean(activeGroupTeam);
  const availableGroupParticipants = useMemo(
    () => (activeGroupRoom?.participants ?? []).filter(isAvailableGroupParticipant),
    [activeGroupRoom?.participants],
  );
  const availableGroupParticipantCount = availableGroupParticipants.length;

  useEffect(() => {
    if (activeSessionId && sessionDetailQuery.data) {
      hydrateSession(activeSessionId, [], "agent");
    }
  }, [activeSessionId, hydrateSession, sessionDetailQuery.data]);

  useEffect(() => {
    if (!activeGroupRoom) {
      return;
    }
    const existingSessionIds = new Set((sessionsQuery.data ?? []).map((session) => session.id));
    setGroupManageSessionIds(
      activeGroupRoom.participants
        .map((participant) => participant.sessionId)
        .filter((sessionId) => existingSessionIds.has(sessionId)),
    );
    setGroupManageTitleDraft(activeGroupRoom.title || "");
    setGroupManageModeDraft(activeGroupRoom.mode || "round_robin");
    setGroupManagePurposeDraft(activeGroupRoom.purpose || "discussion");
  }, [activeGroupRoom, sessionsQuery.data]);

  useEffect(() => {
    if (!sessionStreamShouldConnect || typeof EventSource === "undefined") {
      const decisionSnapshot = sessionStreamDecisionSnapshotRef.current;
      setSessionStreamConnected(false);
      postBrowserTelemetry({
        phase: "session_stream",
        eventCode: "browser.session_stream.skipped",
        message: "Session detail stream connection was skipped.",
        level: "info",
        fields: {
          sessionId: decisionSnapshot.sessionId,
          shouldConnect: decisionSnapshot.shouldConnect,
          pageVisible: decisionSnapshot.pageVisible,
          chatStartupWarmupActive: decisionSnapshot.chatStartupWarmupActive,
          chatPollingVisible: decisionSnapshot.chatPollingVisible,
          directSessionBackgroundSyncActive: decisionSnapshot.directSessionBackgroundSyncActive,
          routeTargetMatches: decisionSnapshot.routeTargetMatches,
          routeSettling: decisionSnapshot.routeSettling,
          routeSwitchGraceActive: decisionSnapshot.routeSwitchGraceActive,
          visibilityState: typeof document === "undefined" ? "unknown" : document.visibilityState,
          eventSourceAvailable: typeof EventSource !== "undefined",
          pageInstanceId: getPageInstanceId(),
          ...collectBrowserPageSnapshot(),
        },
      });
      return;
    }

    let disposed = false;
    let pendingDetail: SessionDetail | null = null;
    let applyTimer: ReturnType<typeof window.setTimeout> | null = null;
    let lastAppliedAt = 0;
    const streamSessionId = String(activeSessionId || "");
    if (!streamSessionId) {
      setSessionStreamConnected(false);
      return;
    }
    const decisionSnapshot = sessionStreamDecisionSnapshotRef.current;
    postBrowserTelemetry({
      phase: "session_stream",
      eventCode: "browser.session_stream.effect_started",
      message: "Session detail stream effect started.",
      level: "info",
      fields: {
        sessionId: streamSessionId,
        shouldConnect: decisionSnapshot.shouldConnect,
        pageVisible: decisionSnapshot.pageVisible,
        chatStartupWarmupActive: decisionSnapshot.chatStartupWarmupActive,
        chatPollingVisible: decisionSnapshot.chatPollingVisible,
        directSessionBackgroundSyncActive: decisionSnapshot.directSessionBackgroundSyncActive,
        routeTargetMatches: decisionSnapshot.routeTargetMatches,
        routeSettling: decisionSnapshot.routeSettling,
        routeSwitchGraceActive: decisionSnapshot.routeSwitchGraceActive,
        routeSwitchGraceMsRemaining: decisionSnapshot.routeSwitchGraceMsRemaining,
        visibilityState: typeof document === "undefined" ? "unknown" : document.visibilityState,
        pageInstanceId: getPageInstanceId(),
        ...collectBrowserPageSnapshot(),
      },
    });
    const stream = new EventSource(`/api/sessions/${streamSessionId}/events`);

    function applyPendingDetail(reason: "timer" | "close" | "final") {
      if (!pendingDetail || disposed) {
        return;
      }
      const detail = pendingDetail;
      pendingDetail = null;
      if (applyTimer) {
        window.clearTimeout(applyTimer);
        applyTimer = null;
      }
      lastAppliedAt = Date.now();
      const stats = sessionStreamApplyStatsRef.current[streamSessionId] ?? { received: 0, applied: 0, dropped: 0 };
      stats.applied += 1;
      sessionStreamApplyStatsRef.current[streamSessionId] = stats;
      if (stats.applied === 1 || (stats.dropped > 0 && stats.applied % 20 === 0)) {
        postBrowserTelemetry({
          phase: "session_stream",
          eventCode: "browser.session_stream.snapshot_applied",
          message: "Session detail stream snapshot was applied to the UI cache.",
          level: "info",
          fields: {
            sessionId: streamSessionId,
            reason,
            receivedCount: stats.received,
            appliedCount: stats.applied,
            droppedCount: stats.dropped,
            messageCount: detail.messages?.length ?? 0,
            currentPhase: detail.currentPhase || detail.status || "",
          },
        });
      }
      syncSessionDetail(detail);
    }

    function queueSessionDetail(detail: SessionDetail, payloadLength: number) {
      const stats = sessionStreamApplyStatsRef.current[streamSessionId] ?? { received: 0, applied: 0, dropped: 0 };
      stats.received += 1;
      if (pendingDetail) {
        stats.dropped += 1;
      }
      sessionStreamApplyStatsRef.current[streamSessionId] = stats;
      pendingDetail = detail;
      const phase = String(detail.currentPhase || detail.status || "").trim().toLowerCase();
      if (phase && !isBusyPhase(phase)) {
        applyPendingDetail("final");
        return;
      }
      const elapsed = Date.now() - lastAppliedAt;
      const delayMs = Math.max(0, SESSION_STREAM_MIN_APPLY_INTERVAL_MS - elapsed);
      if (!applyTimer) {
        applyTimer = window.setTimeout(() => {
          applyTimer = null;
          applyPendingDetail("timer");
        }, delayMs);
      }
      if (stats.received === 1 || stats.received % 20 === 0) {
        postBrowserTelemetry({
          phase: "session_stream",
          eventCode: "browser.session_stream.snapshot_queued",
          message: "Session detail stream snapshot was queued before UI cache apply.",
          level: "info",
          fields: {
            sessionId: streamSessionId,
            receivedCount: stats.received,
            appliedCount: stats.applied,
            droppedCount: stats.dropped,
            payloadLength,
            messageCount: detail.messages?.length ?? 0,
            currentPhase: detail.currentPhase || detail.status || "",
            minApplyIntervalMs: SESSION_STREAM_MIN_APPLY_INTERVAL_MS,
          },
        });
      }
    }

    stream.onopen = () => {
      if (!disposed) {
        setSessionStreamConnected(true);
        sessionStreamErrorLoggedRef.current[streamSessionId] = false;
        postBrowserTelemetry({
          phase: "session_stream",
          eventCode: "browser.session_stream.opened",
          message: "Session detail stream opened.",
          level: "info",
          fields: {
            sessionId: streamSessionId,
          },
        });
      }
    };

    stream.onerror = () => {
      if (!disposed) {
        setSessionStreamConnected(false);
        if (!sessionStreamErrorLoggedRef.current[streamSessionId]) {
          sessionStreamErrorLoggedRef.current[streamSessionId] = true;
          postBrowserTelemetry({
            phase: "session_stream",
            eventCode: "browser.session_stream.error",
            message: "Session detail stream reported an error.",
            level: "warning",
            fields: {
              sessionId: streamSessionId,
              readyState: stream.readyState,
            },
          });
        }
      }
    };

    function handleSessionDetail(event: MessageEvent<string>) {
      let payload: SessionStreamEvent;
      try {
        payload = JSON.parse(event.data) as SessionStreamEvent;
      } catch {
        if (!sessionStreamPayloadErrorLoggedRef.current[streamSessionId]) {
          sessionStreamPayloadErrorLoggedRef.current[streamSessionId] = true;
          postBrowserTelemetry({
            phase: "session_stream",
            eventCode: "browser.session_stream.bad_payload",
            message: "Session detail stream payload could not be parsed.",
            level: "warning",
            fields: {
              sessionId: streamSessionId,
              payloadLength: event.data.length,
            },
          });
        }
        return;
      }
      if (!shouldAcceptSessionStreamEvent(payload, streamSessionId) || payload.type !== "session_detail") {
        return;
      }
      setSessionStreamConnected(true);
      queueSessionDetail(payload.detail, event.data.length);
    }

    function handleAssistantDelta(event: MessageEvent<string>) {
      let payload: SessionStreamEvent;
      try {
        payload = JSON.parse(event.data) as SessionStreamEvent;
      } catch {
        if (!sessionStreamPayloadErrorLoggedRef.current[streamSessionId]) {
          sessionStreamPayloadErrorLoggedRef.current[streamSessionId] = true;
          postBrowserTelemetry({
            phase: "session_stream",
            eventCode: "browser.session_stream.bad_payload",
            message: "Session assistant delta stream payload could not be parsed.",
            level: "warning",
            fields: {
              sessionId: streamSessionId,
              payloadLength: event.data.length,
            },
          });
        }
        return;
      }
      if (!shouldAcceptSessionStreamEvent(payload, streamSessionId) || payload.type !== "assistant_delta") {
        return;
      }
      setSessionStreamConnected(true);
      queryClient.setQueryData<SessionDetail>(queryKeys.session(streamSessionId), (detail) =>
        mergeAssistantDeltaIntoSessionDetail(detail, payload),
      );
      const stats = sessionStreamApplyStatsRef.current[streamSessionId] ?? { received: 0, applied: 0, dropped: 0 };
      stats.received += 1;
      stats.applied += 1;
      sessionStreamApplyStatsRef.current[streamSessionId] = stats;
      if (stats.applied === 1 || stats.applied % 50 === 0) {
        postBrowserTelemetry({
          phase: "session_stream",
          eventCode: "browser.session_stream.assistant_delta_applied",
          message: "Session assistant delta stream was applied to the UI cache.",
          level: "info",
          fields: {
            sessionId: streamSessionId,
            turnId: payload.turnId,
            stage: payload.stage,
            appliedCount: stats.applied,
            payloadLength: event.data.length,
            contentDeltaLength: (payload.contentDelta ?? payload.content ?? "").length,
            thoughtDeltaLength: (payload.thoughtDelta ?? payload.thought ?? "").length,
            done: payload.done,
          },
        });
      }
    }

    stream.addEventListener("session_detail", handleSessionDetail as EventListener);
    stream.addEventListener("assistant_delta", handleAssistantDelta as EventListener);

    return () => {
      const readyStateBeforeClose = stream.readyState;
      applyPendingDetail("close");
      disposed = true;
      setSessionStreamConnected(false);
      if (applyTimer) {
        window.clearTimeout(applyTimer);
        applyTimer = null;
      }
      stream.removeEventListener("session_detail", handleSessionDetail as EventListener);
      stream.removeEventListener("assistant_delta", handleAssistantDelta as EventListener);
      stream.close();
      postBrowserTelemetry({
        phase: "session_stream",
        eventCode: "browser.session_stream.closed",
        message: "Session detail stream closed.",
        fields: {
          sessionId: streamSessionId,
          readyState: readyStateBeforeClose,
        },
      });
    };
  }, [
    activeSessionId,
    sessionStreamShouldConnect,
    syncSessionDetail,
  ]);

  useEffect(() => {
    if (!groupStreamShouldConnect || typeof EventSource === "undefined") {
      setGroupStreamConnected(false);
      return;
    }

    let disposed = false;
    const streamRoomId = String(activeGroupRoomId || "");
    if (!streamRoomId) {
      setGroupStreamConnected(false);
      return;
    }
    const stream = new EventSource(`/api/chat-rooms/${streamRoomId}/events`);

    stream.onopen = () => {
      if (!disposed) {
        setGroupStreamConnected(true);
        groupStreamErrorLoggedRef.current[streamRoomId] = false;
        postBrowserTelemetry({
          phase: "chat_room_stream",
          eventCode: "browser.chat_room_stream.opened",
          message: "Chat room detail stream opened.",
          level: "info",
          fields: {
            roomId: streamRoomId,
          },
        });
      }
    };

    stream.onerror = () => {
      if (!disposed) {
        setGroupStreamConnected(false);
        if (!groupStreamErrorLoggedRef.current[streamRoomId]) {
          groupStreamErrorLoggedRef.current[streamRoomId] = true;
          postBrowserTelemetry({
            phase: "chat_room_stream",
            eventCode: "browser.chat_room_stream.error",
            message: "Chat room detail stream reported an error.",
            level: "warning",
            fields: {
              roomId: streamRoomId,
              readyState: stream.readyState,
            },
          });
        }
      }
    };

    function handleChatRoomDetail(event: MessageEvent<string>) {
      let payload: ChatRoomStreamEvent;
      try {
        payload = JSON.parse(event.data) as ChatRoomStreamEvent;
      } catch {
        if (!groupStreamPayloadErrorLoggedRef.current[streamRoomId]) {
          groupStreamPayloadErrorLoggedRef.current[streamRoomId] = true;
          postBrowserTelemetry({
            phase: "chat_room_stream",
            eventCode: "browser.chat_room_stream.bad_payload",
            message: "Chat room detail stream payload could not be parsed.",
            level: "warning",
            fields: {
              roomId: streamRoomId,
              payloadLength: event.data.length,
            },
          });
        }
        return;
      }
      if (payload.roomId !== streamRoomId || payload.detail?.roomId !== streamRoomId) {
        return;
      }
      setGroupStreamConnected(true);
      syncChatRoomDetail(payload.detail);
    }

    stream.addEventListener("chat_room_detail", handleChatRoomDetail as EventListener);

    return () => {
      const readyStateBeforeClose = stream.readyState;
      disposed = true;
      setGroupStreamConnected(false);
      stream.removeEventListener("chat_room_detail", handleChatRoomDetail as EventListener);
      stream.close();
      postBrowserTelemetry({
        phase: "chat_room_stream",
        eventCode: "browser.chat_room_stream.closed",
        message: "Chat room detail stream closed.",
        fields: {
          roomId: streamRoomId,
          readyState: readyStateBeforeClose,
        },
      });
    };
  }, [activeGroupRoomId, groupStreamShouldConnect, syncChatRoomDetail]);

  const workspace = activeSessionId
    ? sessionWorkspaces[activeSessionId] ?? {
        openTabs: [],
        activeTab: "agent",
      }
    : { openTabs: [], activeTab: "agent" };

  const activeCliAgentRunId = cliAgentRunIdFromTabId(workspace.activeTab);
  const activeFilePath = workspace.activeTab !== "agent" && !activeCliAgentRunId ? workspace.activeTab : null;
  const fileContentQuery = useQuery({
    queryKey: queryKeys.fileContent(activeFilePath ?? ""),
    enabled: Boolean(activeFilePath),
    queryFn: () =>
      fetchJson<FileContent>(`/api/files/content?path=${encodeURIComponent(activeFilePath ?? "")}`),
  });

  const changedFiles = new Set(sessionDetailQuery.data?.changedFiles ?? []);
  const leftPanelWidth = chatPanelWidths.leftPanelWidth;
  const rightPanelWidth = chatPanelWidths.rightPanelWidth;

  const syncPanelWidthsToLayout = useCallback(() => {
    const layoutWidth = layoutRef.current?.getBoundingClientRect().width ?? 0;
    if (!layoutWidth) {
      return;
    }
    const normalized = normalizePanelWidths(layoutWidth, leftPanelWidth, rightPanelWidth);
    if (
      normalized.leftPanelWidth !== leftPanelWidth ||
      normalized.rightPanelWidth !== rightPanelWidth
    ) {
      setChatPanelWidths(normalized);
    }
  }, [leftPanelWidth, rightPanelWidth, setChatPanelWidths]);

  useEffect(() => {
    syncPanelWidthsToLayout();
    const layoutElement = layoutRef.current;
    if (!layoutElement) {
      return;
    }

    const observer = new ResizeObserver(() => {
      syncPanelWidthsToLayout();
    });
    observer.observe(layoutElement);

    return () => observer.disconnect();
  }, [syncPanelWidthsToLayout]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const mediaQuery = window.matchMedia(CHAT_CENTER_FIRST_MEDIA_QUERY);
    function applyCenterFirstState(matches: boolean) {
      setCenterFirstLayout(matches);
      if (matches && !centerFirstAutoCollapseRef.current) {
        centerFirstAutoCollapseRef.current = true;
        setLeftRailCollapsed(true);
        setRightPaneCollapsed(true);
      }
      if (!matches) {
        centerFirstAutoCollapseRef.current = false;
      }
    }
    applyCenterFirstState(mediaQuery.matches);
    const handleChange = (event: MediaQueryListEvent) => {
      applyCenterFirstState(event.matches);
    };
    mediaQuery.addEventListener("change", handleChange);
    return () => mediaQuery.removeEventListener("change", handleChange);
  }, []);

  useEffect(() => {
    if (!dragState) {
      return;
    }
    const activeDrag = dragState;

    const previousCursor = document.body.style.cursor;
    const previousUserSelect = document.body.style.userSelect;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";

    function stopDragging() {
      setDragState(null);
    }

    function handlePointerMove(event: globalThis.PointerEvent) {
      const layoutWidth = layoutRef.current?.getBoundingClientRect().width ?? 0;
      if (!layoutWidth) {
        return;
      }

      const delta = event.clientX - activeDrag.startX;

      if (activeDrag.side === "left") {
        if (leftRailCollapsed) {
          return;
        }
        const bounds = getResizeBounds("left", layoutWidth, rightPaneCollapsed ? 0 : activeDrag.startRightWidth);
        const nextLeftWidth = clamp(activeDrag.startLeftWidth + delta, bounds.min, bounds.max);
        setChatPanelWidths({ leftPanelWidth: Math.round(nextLeftWidth) });
        return;
      }

      if (rightPaneCollapsed) {
        return;
      }
      const bounds = getResizeBounds("right", layoutWidth, leftRailCollapsed ? 0 : activeDrag.startLeftWidth);
      const nextRightWidth = clamp(activeDrag.startRightWidth - delta, bounds.min, bounds.max);
      setChatPanelWidths({ rightPanelWidth: Math.round(nextRightWidth) });
    }

    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", stopDragging);
    window.addEventListener("pointercancel", stopDragging);

    return () => {
      document.body.style.cursor = previousCursor;
      document.body.style.userSelect = previousUserSelect;
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", stopDragging);
      window.removeEventListener("pointercancel", stopDragging);
    };
  }, [dragState, leftRailCollapsed, rightPaneCollapsed, setChatPanelWidths]);

  const locale = lang === "zh" ? "zh-CN" : "en-US";

  const timeFormatter = useMemo(
    () =>
      new Intl.DateTimeFormat(locale, {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
      }),
    [locale],
  );
  const numberFormatter = useMemo(() => new Intl.NumberFormat(locale), [locale]);

  const runtime = runtimeQuery.data;
  const pet = petQuery.data;
  const rawSessionDetail = sessionDetailQuery.data;
  const selectedSessionDetail =
    rawSessionDetail && rawSessionDetail.id === activeSessionId ? rawSessionDetail : undefined;
  const detail = selectedSessionDetail;
  const closedCliAgentRunTokens = activeSessionId ? (closedCliAgentRunTokensBySession[activeSessionId] ?? []) : [];
  const closedCliAgentRunTokenSet = useMemo(() => new Set(closedCliAgentRunTokens), [closedCliAgentRunTokens]);
  const cliAgentRunTabs = useMemo(
    () => buildCliAgentRunViews(detail?.messages ?? [], activeSessionId ?? "").filter((run) => !closedCliAgentRunTokenSet.has(cliAgentRunCloseToken(run))),
    [activeSessionId, closedCliAgentRunTokenSet, detail?.messages],
  );
  const activeCliAgentRun = useMemo(
    () => activeCliAgentRunId ? cliAgentRunTabs.find((run) => run.id === activeCliAgentRunId) : undefined,
    [activeCliAgentRunId, cliAgentRunTabs],
  );
  const mountedCliAgentRunIds = activeSessionId ? (mountedCliAgentRunIdsBySession[activeSessionId] ?? []) : [];
  const mountedCliAgentRunIdSet = useMemo(() => {
    const ids = new Set(mountedCliAgentRunIds);
    if (activeCliAgentRun && !groupPanelActive) {
      ids.add(activeCliAgentRun.id);
    }
    return ids;
  }, [activeCliAgentRun, groupPanelActive, mountedCliAgentRunIds]);
  const mountedCliAgentRuns = useMemo(
    () => cliAgentRunTabs.filter((run) => mountedCliAgentRunIdSet.has(run.id)),
    [cliAgentRunTabs, mountedCliAgentRunIdSet],
  );
  useEffect(() => {
    if (!activeSessionId || !activeCliAgentRun || groupPanelActive) {
      return;
    }
    setMountedCliAgentRunIdsBySession((current) => {
      const existing = current[activeSessionId] ?? [];
      if (existing.includes(activeCliAgentRun.id)) {
        return current;
      }
      return {
        ...current,
        [activeSessionId]: [...existing, activeCliAgentRun.id],
      };
    });
  }, [activeCliAgentRun, activeSessionId, groupPanelActive]);
  useEffect(() => {
    if (!activeSessionId) {
      return;
    }
    const availableRunIds = new Set(cliAgentRunTabs.map((run) => run.id));
    setMountedCliAgentRunIdsBySession((current) => {
      const existing = current[activeSessionId] ?? [];
      const next = existing.filter((runId) => availableRunIds.has(runId));
      if (next.length === existing.length) {
        return current;
      }
      if (next.length === 0) {
        const { [activeSessionId]: _removed, ...remaining } = current;
        return remaining;
      }
      return {
        ...current,
        [activeSessionId]: next,
      };
    });
  }, [activeSessionId, cliAgentRunTabs]);
  useEffect(() => {
    if (!activeSessionId || !activeCliAgentRunId) {
      return;
    }
    if (!cliAgentRunTabs.some((run) => run.id === activeCliAgentRunId)) {
      setActiveTab(activeSessionId, "agent");
    }
  }, [activeCliAgentRunId, activeSessionId, cliAgentRunTabs, setActiveTab]);
  const handleCliAgentTerminalSessionChange = useCallback((runId: string, session: CliAgentTerminalSession) => {
    setCliAgentTerminalSessions((current) => {
      const previous = current[runId];
      if (
        previous?.terminalSessionId === session.terminalSessionId
        && previous?.status === session.status
        && previous?.alive === session.alive
        && previous?.cliSessionId === session.cliSessionId
      ) {
        return current;
      }
      return {
        ...current,
        [runId]: session,
      };
    });
  }, []);
  const closeCliAgentRun = useCallback(async (run: CliAgentRunView) => {
    if (!activeSessionId) {
      return;
    }
    const terminalSession = cliAgentTerminalSessions[run.id];
    const terminalSessionId = String(terminalSession?.terminalSessionId || run.terminalSessionId || run.result?.terminalSessionId || "").trim();
    const shouldStopTerminal = isCliAgentRunActiveForClose(run, terminalSession);
    if (shouldStopTerminal && typeof window !== "undefined") {
      const confirmed = window.confirm(
        lang === "zh"
          ? `关闭后将结束当前 ${run.title} 终端会话，是否关闭？`
          : `Closing will end the current ${run.title} terminal session. Close it?`,
      );
      if (!confirmed) {
        return;
      }
    }
    if (shouldStopTerminal && terminalSessionId) {
      try {
        await fetchJson<CliAgentTerminalSession>(
          `/api/cli-agents/terminal-sessions/${encodeURIComponent(terminalSessionId)}/stop`,
          { method: "POST" },
        );
        void sessionDetailQuery.refetch();
      } catch (error) {
        if (typeof window !== "undefined") {
          window.alert(
            lang === "zh"
              ? `关闭 ${run.title} 终端失败：${describeError(error, "请求失败")}`
              : `Failed to close ${run.title}: ${describeError(error, "Request failed")}`,
          );
        }
        return;
      }
    }
    setClosedCliAgentRunTokensBySession((current) => {
      const existing = current[activeSessionId] ?? [];
      const closeToken = cliAgentRunCloseToken(run);
      if (existing.includes(closeToken)) {
        return current;
      }
      return {
        ...current,
        [activeSessionId]: [...existing, closeToken],
      };
    });
    setCliAgentTerminalSessions((current) => {
      const { [run.id]: _removed, ...remaining } = current;
      return remaining;
    });
    setMountedCliAgentRunIdsBySession((current) => {
      const existing = current[activeSessionId] ?? [];
      if (!existing.includes(run.id)) {
        return current;
      }
      const next = existing.filter((runId) => runId !== run.id);
      if (next.length === 0) {
        const { [activeSessionId]: _removed, ...remaining } = current;
        return remaining;
      }
      return {
        ...current,
        [activeSessionId]: next,
      };
    });
    if (activeCliAgentRunId === run.id) {
      setActiveTab(activeSessionId, "agent");
    }
  }, [activeCliAgentRunId, activeSessionId, cliAgentTerminalSessions, lang, sessionDetailQuery, setActiveTab]);
  const sessionDetailLoadingForActiveSession = Boolean(
    activeSessionId
    && (!rawSessionDetail || rawSessionDetail.id !== activeSessionId)
    && sessionDetailQuery.isFetching,
  );
  const runtimeActiveChatTurnSessionIds = new Set(
    [
      ...(runtime?.workRuns?.activeItems?.chat_turn ?? []),
      runtime?.workRuns?.active?.chat_turn,
    ]
      .map((run) => String(run?.sessionId ?? "").trim())
      .filter(Boolean),
  );
  const runtimeMatchesSelectedSession = Boolean(
    activeSessionId && runtimeActiveChatTurnSessionIds.has(activeSessionId),
  );
  const runtimeActiveChatTurnSessionId = runtimeActiveChatTurnSessionIds.values().next().value ?? "";
  const runtimeActiveSessionLabel = runtimeActiveChatTurnSessionId
    ? sessionsQuery.data?.find((session) => session.id === runtimeActiveChatTurnSessionId)?.title
      || runtime?.sessionTitle
      || runtimeActiveChatTurnSessionId
    : "";
  const runtimeMismatchLine = runtimeActiveChatTurnSessionId && !runtimeMatchesSelectedSession
    ? (lang === "zh"
      ? `运行器正在处理：${runtimeActiveSessionLabel}`
      : `Runtime is processing: ${runtimeActiveSessionLabel}`)
    : "";
  const lastContextComposition = detail?.lastContextComposition ?? null;
  const lastCacheComposition = detail?.lastCacheComposition ?? null;
  const activeSkillContract = (detail as SessionDetailWithActiveSkill | undefined)?.activeSkillContract ?? null;
  const activeSkillCommand = String(activeSkillContract?.command ?? "").trim();
  const activeSkillName = String(activeSkillContract?.skillName ?? activeSkillCommand).trim();
  const activeSkillStatusValue = String(activeSkillContract?.status ?? "active").trim().toLowerCase();
  const activeSkillStatus = ["active", "stale", "missing"].includes(activeSkillStatusValue)
    ? activeSkillStatusValue
    : "active";
  const activeSkillStatusLabel = activeSkillStatus === "stale"
    ? (lang === "zh" ? "已变更" : "stale")
    : activeSkillStatus === "missing"
      ? (lang === "zh" ? "缺失" : "missing")
      : (lang === "zh" ? "生效中" : "active");
  const activeSkillStatusClass = activeSkillStatus === "stale"
    ? styles.activeSkillStatus_stale
    : activeSkillStatus === "missing"
      ? styles.activeSkillStatus_missing
      : styles.activeSkillStatus_active;
  const activeSkillHash = String(activeSkillContract?.skillHash ?? "").trim();
  const activeSkillShortHash = activeSkillHash ? activeSkillHash.slice(0, 8) : "";
  const activeSkillRuleCount = Array.isArray(activeSkillContract?.keyRules)
    ? activeSkillContract.keyRules.length
    : 0;
  const activeSkillSummary = activeSkillContract && (activeSkillName || activeSkillCommand)
    ? [
      activeSkillCommand ? `/${activeSkillCommand}` : "",
      activeSkillName,
      activeSkillStatusLabel,
      activeSkillShortHash ? `#${activeSkillShortHash}` : "",
    ].filter(Boolean).join(" · ")
    : "";
  const projectBusTimeline = projectAgentBusQuery.data;
  const projectBusEvents = projectBusTimeline?.events ?? [];
  const activeGroupRound = latestChatRoomRound(activeGroupRoom);
  const activeGroupRoomStatus = String(activeGroupRoom?.status ?? "").trim().toLowerCase();
  const groupRoundRunning = activeGroupRoomStatus === "running";
  const groupRoundStopping = activeGroupRoomStatus === "stopping";
  const groupRoundActive = groupRoundRunning || groupRoundStopping;
  const activeGroupParticipantById = useMemo(() => {
    const entries = (activeGroupRoom?.participants ?? []).map((participant) => [participant.participantId, participant] as const);
    return new Map(entries);
  }, [activeGroupRoom?.participants]);
  const groupManageSessionSet = useMemo(() => new Set(groupManageSessionIds), [groupManageSessionIds]);
  const activeGroupParticipantSessionSet = useMemo(
    () => new Set(availableGroupParticipants.map((participant) => participant.sessionId)),
    [availableGroupParticipants],
  );
  const expandedGroupAgentDetailsBySessionId = useMemo(() => {
    const entries = expandedGroupAgentSessionIds.map((sessionId, index) => {
      const query = expandedGroupAgentDetailQueries[index];
      return [sessionId, query] as const;
    });
    return new Map(entries);
  }, [expandedGroupAgentDetailQueries, expandedGroupAgentSessionIds]);
  useEffect(() => {
    if (!groupPanelActive) {
      if (expandedGroupAgentSessionIds.length) {
        setExpandedGroupAgentSessionIds([]);
      }
      return;
    }
    const nextExpanded = expandedGroupAgentSessionIds.filter((sessionId) => activeGroupParticipantSessionSet.has(sessionId));
    if (nextExpanded.length !== expandedGroupAgentSessionIds.length) {
      setExpandedGroupAgentSessionIds(nextExpanded);
    }
  }, [activeGroupParticipantSessionSet, expandedGroupAgentSessionIds, groupPanelActive]);
  const groupManageChanged = Boolean(
    legacyGroupRoomActive
    &&
    activeGroupRoom
    && (
      groupManageTitleDraft.trim() !== (activeGroupRoom.title || "").trim()
      || groupManageModeDraft !== (activeGroupRoom.mode || "round_robin")
      || groupManagePurposeDraft !== (activeGroupRoom.purpose || "discussion")
      || groupManageSessionIds.length !== activeGroupParticipantSessionSet.size
      || groupManageSessionIds.some((sessionId) => !activeGroupParticipantSessionSet.has(sessionId))
    ),
  );
  const groupManageDisabled =
    !legacyGroupRoomActive
    ||
    !activeGroupRoom
    || activeGroupTeamOwned
    || groupRoundActive
    || updateGroupRoomMutation.isPending
    || !groupManageTitleDraft.trim()
    || groupManageSessionIds.length < 2
    || !groupManageModeDraft
    || !groupManagePurposeDraft;
  const groupDeleteDisabled =
    !legacyGroupRoomActive
    ||
    !activeGroupRoom
    || activeGroupTeamOwned
    || groupRoundActive
    || deleteGroupRoomMutation.isPending;
  const groupResetDisabled =
    !legacyGroupRoomActive
    ||
    !activeGroupRoom
    || groupRoundActive
    || resetGroupRoomMutation.isPending
    || (activeGroupRoom?.rounds ?? []).length < 1;
  const groupStopDisabled =
    !legacyGroupRoomActive
    || !activeGroupRoom
    || !groupRoundRunning
    || stopGroupRoundMutation.isPending;
  const activeSurfaceTitle = groupPanelActive
    ? (
      projectBusActive
        ? (lang === "zh" ? "助手通知流" : "Agent notice stream")
        : activeGroupRoom?.title ?? (lang === "zh" ? "群聊加载中" : "Loading group")
    )
    : detail?.agentDisplayName ?? detail?.title ?? directSessionActiveSummary?.agentDisplayName ?? directSessionActiveSummary?.title ?? t("loadingSession");
  const activeSurfaceStatus = groupPanelActive
    ? (
      projectBusActive
        ? (lang === "zh" ? "全局广播" : "global broadcast")
        : statusLabel(activeGroupRoom?.status ?? "ready")
    )
    : statusLabel(detail?.status || detail?.currentPhase || "idle");
  const activeSurfaceLine = groupPanelActive
    ? (
      projectBusActive
        ? `${projectBusTimeline?.activeAgentCount ?? 0} ${lang === "zh" ? "位 active Agent · 全局广播/私信投递记录" : "active agents · broadcast/private delivery log"}`
        : (
          activeGroupRound?.summary
          || (lang === "zh"
            ? `${availableGroupParticipantCount} 位可用助手`
            : `${availableGroupParticipantCount} available agents · ${activeGroupRoom?.mode ?? "round_robin"} · ${activeGroupRoom?.purpose ?? "discussion"}`)
        )
    )
    : "";
  const sessionDetailErrorState = deriveSessionDetailQueryErrorState(detail, sessionDetailQuery.isError, {
    dataUpdatedAt: sessionDetailQuery.dataUpdatedAt,
    errorUpdatedAt: sessionDetailQuery.errorUpdatedAt,
    streamConnected: sessionStreamConnected,
  });
  const sessionsErrorState = deriveSessionListQueryErrorState(sessionsQuery.data, sessionsQuery.isError);
  const sessionDetailErrorMessage = sessionDetailQuery.isError
    ? describeError(sessionDetailQuery.error, t("loadFailed"))
    : "";
  const invalidChildSessionLinkMessage = hasInvalidChildSessionLink(directSessionActiveSummary)
    ? (
      lang === "zh"
        ? "child_session_link_invalid: 子对话缺少 parentSessionId/rootSessionId，无法挂载到顶部 Agent 会话轨道。本轮已停止展示，请修复会话索引数据。"
        : "child_session_link_invalid: child session is missing parentSessionId/rootSessionId and cannot be mounted in the top Agent session strip. Fix the session index data."
    )
    : "";
  const sessionsErrorMessage = sessionsQuery.isError
    ? describeError(sessionsQuery.error, t("loadFailed"))
    : "";
  const contextCompositionSegments = useMemo(() => {
    const segments = lastContextComposition?.segments ?? [];
    return segments.filter((segment: SessionContextCompositionSegment) => (segment.tokens ?? 0) > 0 || (segment.chars ?? 0) > 0 || (segment.itemCount ?? 0) > 0);
  }, [lastContextComposition]);
  const contextCompositionTotalTokens = Math.max(
    lastContextComposition?.totalTokens ?? 0,
    contextCompositionSegments.reduce((total, segment) => total + Math.max(0, segment.tokens ?? 0), 0),
  );
  const contextCompositionLimitTokens = Math.max(
    lastContextComposition?.limitTokens ?? 0,
    contextCompositionTotalTokens,
  );
  const contextCompositionUsedPercent = contextCompositionLimitTokens > 0
    ? Math.round(Math.min(1, contextCompositionTotalTokens / contextCompositionLimitTokens) * 100)
    : 0;
  const contextCompositionRemainingTokens = Math.max(0, contextCompositionLimitTokens - contextCompositionTotalTokens);
  const contextCompositionSummary = lastContextComposition
    ? `${numberFormatter.format(contextCompositionTotalTokens)} / ${numberFormatter.format(contextCompositionLimitTokens)} · ${contextCompositionUsedPercent}%`
    : t("noPreviousContextComposition");
  const contextCompositionTitle = lastContextComposition
    ? [
      `${t("previousContextComposition")} ${numberFormatter.format(contextCompositionTotalTokens)} / ${numberFormatter.format(contextCompositionLimitTokens)} tokens`,
      `${contextCompositionUsedPercent}%`,
      `${numberFormatter.format(lastContextComposition.totalChars ?? 0)} chars`,
      lastContextComposition.recordedAt ? formatTime(lastContextComposition.recordedAt) : "",
      lastContextComposition.source || "",
    ].filter(Boolean).join(" · ")
    : t("noPreviousContextComposition");
  const activeSkillTitle = activeSkillContract && (activeSkillName || activeSkillCommand)
    ? [
      lang === "zh" ? "当前 Skill Contract" : "Active Skill Contract",
      activeSkillCommand ? `/${activeSkillCommand}` : "",
      activeSkillName,
      activeSkillStatusLabel,
      activeSkillHash ? `hash ${activeSkillHash}` : "",
      activeSkillContract.scope ? `scope ${activeSkillContract.scope}` : "",
      activeSkillContract.activatedAt ? `${lang === "zh" ? "激活于" : "activated"} ${formatTime(activeSkillContract.activatedAt)}` : "",
      activeSkillRuleCount ? `${numberFormatter.format(activeSkillRuleCount)} ${lang === "zh" ? "条规则" : "rules"}` : "",
      activeSkillContract.staleReason ? `reason ${activeSkillContract.staleReason}` : "",
      activeSkillContract.skillPath || "",
    ].filter(Boolean).join(" · ")
    : "";
  const providerCacheInputTokens = Math.max(0, lastCacheComposition?.inputTokens ?? lastCacheComposition?.calibratedInputTokens ?? 0);
  const providerCachedInputTokens = Math.max(
    0,
    Math.min(
      lastCacheComposition?.calibratedCachedInputTokens ?? lastCacheComposition?.cachedInputTokens ?? 0,
      providerCacheInputTokens,
    ),
  );
  const providerUncachedInputTokens = Math.max(
    0,
    lastCacheComposition?.uncachedInputTokens ?? (providerCacheInputTokens - providerCachedInputTokens),
  );
  const cacheCalibrationStatus = lastCacheComposition?.calibrationStatus || "";
  const cacheCalibrationReason = lastCacheComposition?.calibrationReason || "";
  const cacheComputedOverestimatedInputTokens = Math.max(0, lastCacheComposition?.computedOverestimatedInputTokens ?? 0);
  const cacheProviderExtraCachedInputTokens = Math.max(0, lastCacheComposition?.providerExtraCachedInputTokens ?? 0);
  const cacheCalibrationSummaryText = cacheCalibrationSummaryLabel(
    cacheCalibrationStatus,
    cacheCalibrationReason,
    cacheComputedOverestimatedInputTokens,
    cacheProviderExtraCachedInputTokens,
    numberFormatter,
    lang,
  );
  const trueCacheDonutSegments = useMemo(
    () => buildCacheDonutSegments(
      [
        {
          key: "cached",
          label: t("cacheSegment_cached"),
          tokens: providerCachedInputTokens,
          status: "hit",
          source: "provider_usage",
          description: lang === "zh" ? "上游返回的真实缓存命中输入 token。" : "Provider-reported cached input tokens.",
        },
        {
          key: "uncached",
          label: t("cacheSegment_uncached"),
          tokens: Math.max(0, providerCacheInputTokens - providerCachedInputTokens),
          status: "miss",
          source: "provider_usage",
          description: lang === "zh" ? "上游返回的非缓存命中输入 token。" : "Provider-reported input tokens that were not cache hits.",
        },
      ],
      providerCacheInputTokens,
    ),
    [lang, providerCachedInputTokens, providerCacheInputTokens, t],
  );
  const computedCacheCompositionSegments = useMemo(() => {
    const segments = lastCacheComposition?.computedSegments ?? [];
    return segments
      .filter((segment: SessionCacheCompositionSegment) => (segment.tokens ?? 0) > 0 || segment.key === "computed_missing")
      .map((segment) => {
        return {
          ...segment,
          label: promptSegmentDisplayLabel(segment, lang, t),
        };
      });
  }, [lang, lastCacheComposition, t]);
  const computedCacheCompositionTotalTokens = Math.max(
    lastCacheComposition?.computedInputTokens ?? 0,
    computedCacheCompositionSegments.reduce((total, segment) => total + Math.max(0, segment.tokens ?? 0), 0),
  );
  const cachePromptCompositionSegments = useMemo(() => {
    const segments = (lastCacheComposition?.calibratedSegments?.length
      ? (lastCacheComposition.calibratedSegments ?? [])
      : computedCacheCompositionSegments
    );
    return segments
      .filter((segment: SessionCacheCompositionSegment) => (segment.tokens ?? 0) > 0 || segment.key === "computed_missing")
      .map((segment) => {
        return {
          ...segment,
          label: promptSegmentDisplayLabel(segment, lang, t),
        };
      });
  }, [computedCacheCompositionSegments, lang, lastCacheComposition, t]);
  const cachePromptCompositionTotalTokens = Math.max(
    computedCacheCompositionTotalTokens,
    cachePromptCompositionSegments.reduce((total, segment) => total + Math.max(0, segment.tokens ?? 0), 0),
  );
  const cachePromptDonutSegments = useMemo(
    () => buildCacheDonutSegments(cachePromptCompositionSegments, cachePromptCompositionTotalTokens),
    [cachePromptCompositionSegments, cachePromptCompositionTotalTokens],
  );
  const cacheCompositionPercent = Math.round(Math.max(0, Math.min(1, lastCacheComposition?.cacheHitRate ?? 0)) * 100);
  const computedCacheCompositionPercent = Math.round(Math.max(0, Math.min(1, lastCacheComposition?.computedCacheHitRate ?? 0)) * 100);
  const averageCacheObservedTurnCount = Math.max(
    0,
    lastCacheComposition?.averageObservedTurnCount || detail?.cacheUsage?.totalObservedTurnCount || 0,
  );
  const averageCacheInputTokens = Math.max(
    0,
    lastCacheComposition?.averageInputTokens || detail?.cacheUsage?.totalInputTokens || 0,
  );
  const averageCachedInputTokens = Math.max(
    0,
    lastCacheComposition?.averageCachedInputTokens || detail?.cacheUsage?.totalCachedInputTokens || 0,
  );
  const averageCacheHitRate = averageCacheInputTokens > 0
    ? averageCachedInputTokens / averageCacheInputTokens
    : (detail?.cacheUsage?.totalCacheHitRate ?? lastCacheComposition?.averageCacheHitRate ?? 0);
  const averageCacheCompositionPercent = Math.round(Math.max(0, Math.min(1, averageCacheHitRate)) * 100);
  const cacheCompositionTrueLabel = lang === "zh" ? "真" : "true";
  const cacheCompositionComputedLabel = lang === "zh" ? "计" : "calc";
  const cacheCompositionAverageLabel = lang === "zh" ? "均" : "avg";
  const cacheCompositionAverageValue = averageCacheObservedTurnCount > 0 ? `${averageCacheCompositionPercent}%` : "--";
  const cacheDetailAvailable = Boolean(lastCacheComposition);
  const cacheDetailDialogTitle = lang === "zh" ? "缓存命中详情" : "Cache hit details";
  const cacheDetailOpenLabel = lang === "zh" ? "查看上一轮缓存命中详情" : "View previous cache hit details";
  const cacheCompositionSummary = lastCacheComposition
    ? lastCacheComposition.source === "provider_usage"
      ? `${cacheCompositionTrueLabel} ${cacheCompositionPercent}% · ${cacheCompositionComputedLabel} ${computedCacheCompositionPercent}% · ${cacheCompositionAverageLabel} ${cacheCompositionAverageValue}`
      : lastCacheComposition.source === "not_called"
        ? t("cacheHitNotCalled")
      : t("cacheHitMissing")
    : t("cacheObservationPending");
  const cacheCompositionTitle = lastCacheComposition
    ? lastCacheComposition.source === "provider_usage"
      ? [
        `${cacheCompositionTrueLabel} ${numberFormatter.format(providerCachedInputTokens)} / ${numberFormatter.format(providerCacheInputTokens)} · ${cacheCompositionPercent}%`,
        `${cacheCompositionComputedLabel} ${numberFormatter.format(lastCacheComposition.computedCachedInputTokens ?? 0)} / ${numberFormatter.format(computedCacheCompositionTotalTokens)} · ${computedCacheCompositionPercent}%`,
        `${cacheCompositionAverageLabel} ${numberFormatter.format(averageCachedInputTokens)} / ${numberFormatter.format(averageCacheInputTokens)} · ${cacheCompositionAverageValue}`,
        `${lang === "zh" ? "观测轮次" : "observed turns"} ${numberFormatter.format(averageCacheObservedTurnCount)}`,
        cacheComputedOverestimatedInputTokens > 0 ? `${lang === "zh" ? "预测未兑现" : "predicted not observed"} ${numberFormatter.format(cacheComputedOverestimatedInputTokens)}` : "",
        cacheProviderExtraCachedInputTokens > 0 ? `${lang === "zh" ? "厂商额外命中" : "provider extra hit"} ${numberFormatter.format(cacheProviderExtraCachedInputTokens)}` : "",
        cacheCalibrationStatus ? `${lang === "zh" ? "校准" : "calibration"} ${cacheCalibrationStatus}` : "",
        `write ${numberFormatter.format(lastCacheComposition.cacheCreationInputTokens ?? 0)}`,
        `uncached ${numberFormatter.format(providerUncachedInputTokens)}`,
        cacheCalibrationReason,
      ].filter(Boolean).join(" · ")
      : lastCacheComposition.source === "not_called"
        ? t("cacheHitNotCalled")
      : t("cacheHitMissing")
    : t("cacheObservationPending");
  const closeCacheDetail = useCallback(() => setCacheDetailOpen(false), []);
  const openCacheDetail = useCallback(() => {
    if (cacheDetailAvailable) {
      setCacheDetailOpen(true);
    }
  }, [cacheDetailAvailable]);
  useEffect(() => {
    if (!cacheDetailOpen) {
      return undefined;
    }
    function handleCacheDetailKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape") {
        closeCacheDetail();
      }
    }
    window.addEventListener("keydown", handleCacheDetailKeyDown);
    return () => window.removeEventListener("keydown", handleCacheDetailKeyDown);
  }, [cacheDetailOpen, closeCacheDetail]);
  useEffect(() => {
    setCacheDetailOpen(false);
  }, [activeSessionId]);
  const pendingToolApproval = useMemo(
    () => (detail?.pendingToolGovernanceRequests ?? []).find((request) => request.status === "pending_review") ?? null,
    [detail?.pendingToolGovernanceRequests],
  );
  const pendingToolApprovalLabels = useMemo(
    () => toolApprovalLabels(pendingToolApproval),
    [pendingToolApproval],
  );
  const pendingToolApprovalRawTitle = pendingToolApprovalLabels.map((item) => item.id).join("、");
  const pendingToolApprovalScope = toolApprovalScopeLabel(pendingToolApproval?.grantScope, lang);
  const pendingToolApprovalRisk = toolApprovalRiskLabel(pendingToolApproval?.riskLevel, lang);
  const pendingToolApprovalPending = Boolean(
    pendingToolApproval
    && resolveToolApprovalMutation.isPending
    && resolveToolApprovalMutation.variables?.request.requestId === pendingToolApproval.requestId,
  );
  const activeDraft = activeSessionId ? sessionDrafts[activeSessionId] ?? "" : "";
  const activeComposerRawError = activeSessionId ? sessionComposerErrors[activeSessionId] ?? "" : "";
  const activeLatestTurnErrorMessage = useMemo(
    () => latestVisibleTurnErrorMessage(detail?.messages),
    [detail?.messages],
  );
  const activeComposerError = shouldSuppressComposerErrorForTurnError(
    activeComposerRawError,
    activeLatestTurnErrorMessage,
    detail?.lastTurnError,
  )
    ? ""
    : activeComposerRawError;
  const activeEditTarget = activeSessionId ? sessionEditTargets[activeSessionId] ?? null : null;
  const activeImageAttachments = activeSessionId ? sessionImageAttachments[activeSessionId] ?? [] : [];
  const activeReferenceAttachments = activeSessionId ? sessionReferenceAttachments[activeSessionId] ?? [] : [];
  const activeImageUploadPending = activeSessionId ? Boolean(sessionImageUploadPending[activeSessionId]) : false;
  const activeAgentId = detail?.agentId || "";
  const activeSessionAgent = activeAgentId ? (agentsQuery.data ?? []).find((agent) => agent.agentId === activeAgentId) : undefined;
  const activeAgentDisplay = detail
    ? sessionAgentDisplayInfo(detail, activeSessionAgent, lang, resolveModelLabel)
    : { name: pet?.name || "Agent", functionLabel: "", tone: "chat" as const, meta: "" };
  const activeAgentDisplayName = activeAgentDisplay.name;
  const activeAgentAvatarImageUrl = avatarImageUrlFrom(activeSessionAgent, detail);
  const activeAgentAvatarFallback = avatarInitials(detail?.agentCode, activeAgentDisplayName);
  const activeAgentStatusMessage = detail?.agentMissing
    ? detail.agentStatusMessage || (lang === "zh" ? "缺少有效 Agent，部分内容无法继续运行。" : "Missing valid Agent. Some content cannot keep running.")
    : "";
  const activeRuntimeNotices = useMemo<SessionRuntimeNotice[]>(() => {
    return (detail?.runtimeNotices ?? [])
      .filter((notice) => String(notice.message ?? "").trim())
      .slice(-1);
  }, [detail?.runtimeNotices]);
  const activeControlSignals = useMemo<ChatNextStateSignalSummary[]>(() => {
    const phase = detail?.currentPhase || directSessionActiveSummary?.currentPhase || directSessionActiveSummary?.status || "";
    return (detail?.nextStateSignals ?? [])
      .filter((signal) => shouldShowNextStateSignalInConversation(signal, phase))
      .slice(-3)
      .reverse();
  }, [detail?.currentPhase, detail?.nextStateSignals, directSessionActiveSummary?.currentPhase, directSessionActiveSummary?.status]);
  const latestControlSignal = activeControlSignals[0] ?? null;
  const latestControlSignalLine = latestControlSignal
    ? [
      activeControlSignals.length > 1 ? numberFormatter.format(activeControlSignals.length) : "",
      latestControlSignal.summary,
    ].filter(Boolean).join(" · ")
    : "";
  const latestControlSignalTitle = latestControlSignal
    ? [
      t("nextStateSignalsLabel"),
      latestControlSignal.kind,
      latestControlSignal.source,
      latestControlSignal.relatedEventCode,
      latestControlSignal.turnId,
      latestControlSignal.createdAt ? formatTime(latestControlSignal.createdAt) : "",
      latestControlSignal.summary,
    ].filter(Boolean).join(" · ")
    : "";
  const latestUserMessageId = useMemo(() => deriveLatestUserMessageId(detail?.messages), [detail?.messages]);
  const resolvedEditTarget = resolveLatestEditTarget(activeEditTarget, latestUserMessageId);
  const activeDraftEffective = resolveComposerDraftValue(activeDraft, activeEditTarget, resolvedEditTarget);
  const submitMutationMatchesActiveSession =
    submitTurnMutation.variables?.sessionId === activeSessionId;
  const editResubmitMutationMatchesActiveSession =
    editResubmitMutation.variables?.sessionId === activeSessionId;
  const stopMutationMatchesActiveSession =
    stopTurnMutation.variables?.sessionId === activeSessionId;
  const guidanceMutationMatchesActiveSession =
    sessionGuidanceMutation.variables?.sessionId === activeSessionId;
  const submitPending =
    (submitTurnMutation.isPending && submitMutationMatchesActiveSession)
    || (editResubmitMutation.isPending && editResubmitMutationMatchesActiveSession)
    || activeImageUploadPending;
  const sessionRunning = isRunningPhase(detail?.currentPhase);
  const sessionStopping = isStoppingPhase(detail?.currentPhase) || Boolean(detail?.stopRequested);
  const sessionBusy = isBusyPhase(detail?.currentPhase);
  const composerStopMode = sessionBusy;
  const composerGuidance = sessionBusy && !sessionStopping ? t("sessionBusyComposerGuidance") : "";
  const composerPending =
    composerStopMode ? (stopTurnMutation.isPending && stopMutationMatchesActiveSession) || sessionStopping : submitPending;
  const composerSafeGuidancePending =
    sessionGuidanceMutation.isPending
    && guidanceMutationMatchesActiveSession
    && sessionGuidanceMutation.variables?.mode === "safe";
  const composerInterruptGuidancePending =
    sessionGuidanceMutation.isPending
    && guidanceMutationMatchesActiveSession
    && sessionGuidanceMutation.variables?.mode === "interrupt";
  const composerDisabled = !activeSessionId || submitPending;
  const composerActionDisabled = !activeSessionId || (
    composerStopMode
      ? composerPending
      : submitPending || (!activeDraftEffective.trim() && !activeImageAttachments.length && !activeReferenceAttachments.length)
  );
  const composerPlaceholder =
    !activeSessionId
      ? t("loadingSession")
      : sessionStopping
        ? t("sessionStoppingPlaceholder")
        : sessionBusy
          ? t("sessionBusyPlaceholder")
          : resolvedEditTarget
            ? t("editMessagePlaceholder")
          : t("messageInputPlaceholder");
  const sessionContextUsage = detail?.contextUsage;
  const panelContextUsed = lastContextComposition?.totalTokens ?? sessionContextUsage?.used ?? 0;
  const panelContextLimit = lastContextComposition?.limitTokens ?? sessionContextUsage?.limit ?? 0;
  const contextPercent = contextUsagePercent(panelContextUsed, panelContextLimit);
  const contextUsageLabel = formatContextUsage(panelContextUsed, panelContextLimit, locale);
  const contextSourceLine = lastContextComposition
    ? t("previousContextComposition")
    : sessionContextUsage
      ? t("sessionContextEstimate")
      : sessionDetailLoadingForActiveSession
        ? t("loadingContext")
        : t("sessionContextEstimate");
  const petVitals = useMemo(
    () => [
      { key: "hunger", label: t("hunger"), value: clampPercent(pet?.hunger ?? 0) },
      { key: "energy", label: t("energy"), value: clampPercent(pet?.energy ?? 0) },
      { key: "health", label: t("health"), value: clampPercent(pet?.health ?? 0) },
      { key: "love", label: t("love"), value: clampPercent(pet?.love ?? 0) },
    ],
    [pet?.energy, pet?.health, pet?.hunger, pet?.love, t],
  );
  const petCompanionLine = petQuery.isError
    ? describeError(petQuery.error, t("loadFailed"))
    : pet?.inDream
      ? t("petCompanionDreaming")
      : (pet?.health ?? 0) < 35
        ? t("petCompanionLowHealth")
        : (pet?.hunger ?? 0) < 30
          ? t("petCompanionLowFuel")
          : (pet?.energy ?? 0) < 35
            ? t("petCompanionLowEnergy")
            : t("petCompanionStable");
  const petPresetLabel = petAvatarPresetLabel(t, pet?.avatarPreset);
  const petAvatarPresetKey = getPetAvatarPresetKey(pet?.avatarPreset);
  const petAvatarSkinClass = styles[`petShowcaseAvatar_${petAvatarPresetKey}`] ?? styles.petShowcaseAvatar_default;
  const petAvatarSymbol = getPetAvatarSymbol(pet?.avatarPreset, pet?.name);
  const petInteractionLabels = {
    group: lang === "zh" ? "宠物互动" : "Pet interactions",
    pending: petActionMutation.isPending
      ? lang === "zh" ? "处理中" : "Working"
      : lang === "zh" ? "即时生效" : "Live",
    feed: lang === "zh" ? "喂食" : "Feed",
    talk: lang === "zh" ? "沟通" : "Talk",
    care: lang === "zh" ? "照看" : "Care",
    feedTitle: lang === "zh" ? "喂食并刷新宠物状态" : "Feed and refresh pet state",
    talkTitle: lang === "zh" ? "和宠物沟通并刷新状态" : "Talk and refresh pet state",
    careTitle: lang === "zh" ? "照看宠物并刷新状态" : "Care and refresh pet state",
  };
  const contextStatusLine = sessionDetailErrorState.blockingError
    ? sessionDetailErrorMessage
    : detail
      ? contextUsageLabel
      : t("loadingContext");
  const contextUsageMetaLine = sessionContextUsage
    ? `${numberFormatter.format(sessionContextUsage.messageCount)} ${lang === "zh" ? "条消息" : "messages"} · ${numberFormatter.format(sessionContextUsage.userMessageCount)} ${lang === "zh" ? "用户" : "user"} / ${numberFormatter.format(sessionContextUsage.assistantMessageCount)} Agent`
    : lastContextComposition
      ? `${numberFormatter.format(lastContextComposition.totalChars ?? 0)} chars · ${lastContextComposition.source || "session_detail"}`
      : t("loadingContext");
  const sessionCacheUsage = detail?.cacheUsage;
  const sessionLlmUsage = detail?.llmUsage ?? null;
  const hasProviderLlmUsage = sessionLlmUsage?.source === "provider_usage";
  const hasProviderCacheUsage = sessionCacheUsage?.source === "provider_usage";
  const llmUsageNotCalled = sessionLlmUsage?.source === "not_called" || sessionCacheUsage?.source === "not_called";
  const cacheHitRatePercent = Math.round(Math.max(0, Math.min(1, sessionCacheUsage?.turnCacheHitRate ?? 0)) * 100);
  const cacheHitLine = hasProviderCacheUsage && sessionCacheUsage
    ? `${numberFormatter.format(sessionCacheUsage.turnCachedInputTokens)} / ${numberFormatter.format(sessionCacheUsage.turnInputTokens)} · ${cacheHitRatePercent}%`
    : llmUsageNotCalled
      ? t("cacheHitNotCalled")
    : t("cacheHitMissing");
  const llmUsageLine = hasProviderLlmUsage
    ? `${numberFormatter.format(sessionLlmUsage.inputTokens)} tokens · ${numberFormatter.format(sessionLlmUsage.cachedInputTokens)} cached`
    : llmUsageNotCalled
      ? t("llmUsageNotCalled")
    : t("llmUsageMissing");
  const llmUsageTitle = hasProviderLlmUsage
    ? [
      `${numberFormatter.format(sessionLlmUsage.inputTokens)} in`,
      `${numberFormatter.format(sessionLlmUsage.outputTokens)} out`,
      `${numberFormatter.format(sessionLlmUsage.cachedInputTokens)} cached`,
      `${numberFormatter.format(sessionLlmUsage.cacheCreationInputTokens ?? 0)} write`,
      `${numberFormatter.format(sessionLlmUsage.uncachedInputTokens ?? 0)} uncached`,
    ].join(" · ")
    : llmUsageNotCalled
      ? t("llmUsageNotCalled")
    : t("llmUsageMissing");
  const compression = runtimeMatchesSelectedSession ? runtime?.contextCompression : undefined;
  const compressionCurrentPercent = compression
    ? Math.round(Math.max(0, Math.min(1, compression.usageRatio || 0)) * 100)
    : contextPercent;
  const compressionLevelLabel = compression?.enabled === false
    ? t("compressionDisabled")
    : compression?.currentLevel
      ? compression.currentLevel === "normal"
        ? (lang === "zh" ? "未到阈值" : "below threshold")
        : (lang === "zh" ? `${compression.currentLevel} 档` : `${compression.currentLevel} level`)
      : "--";
  const compressionCurrentLine = compression
    ? (lang === "zh"
      ? `当前 ${compressionCurrentPercent}% · ${compressionLevelLabel}`
      : `Current ${compressionCurrentPercent}% · ${compressionLevelLabel}`)
    : `-- · ${compressionLevelLabel}`;
  const compressionMainLine = compression
    ? `${numberFormatter.format(compression.currentTokens)} / ${numberFormatter.format(compression.effectiveTokenLimit)} · ${compressionCurrentPercent}%`
    : t("loadingContext");
  const compressionScopeLine = compression
    ? `${t("compressionScopeRuntime")} · ${t("compressionLimitBasisEffective")}`
    : t("loadingContext");
  const compressionModelWindowLine = compression
    ? numberFormatter.format(compression.contextWindowLimit)
    : "--";
  const compressionTitleLine = compression
    ? `${compressionMainLine} · ${compressionScopeLine} · window ${numberFormatter.format(compression.contextWindowLimit)} · source ${compression.source || "runtime_state"}`
    : t("loadingContext");
  const lastCompression = compression?.lastCompression ?? null;
  const lastCompressionSourceText = (() => {
    if (!lastCompression) {
      return "";
    }
    switch (lastCompression.triggerSource) {
      case "manual":
        return lang === "zh" ? "Agent 主动请求" : "Agent requested";
      case "provider_limit":
        return lang === "zh" ? "上下文上限触发" : "Context limit triggered";
      case "auto":
        return lang === "zh" ? "阈值自动触发" : "Threshold triggered";
      default:
        return String(lastCompression.triggerSource || "").trim() || (lang === "zh" ? "未知来源" : "Unknown source");
    }
  })();
  const lastCompressionLine = lastCompression
    ? (lang === "zh"
      ? `${lastCompressionSourceText}，${lastCompression.level || "--"} 档：${numberFormatter.format(lastCompression.beforeTokens)} -> ${numberFormatter.format(lastCompression.afterTokens)}，节省 ${numberFormatter.format(lastCompression.savedTokens)} token`
      : `${lastCompressionSourceText}, ${lastCompression.level || "--"} level: ${numberFormatter.format(lastCompression.beforeTokens)} -> ${numberFormatter.format(lastCompression.afterTokens)}, saved ${numberFormatter.format(lastCompression.savedTokens)} tokens`)
    : t("compressionNoRecord");
  const compressionUpdatedLine = lastCompression?.timestamp
    ? formatRelativeTime(lastCompression.timestamp, Date.now(), locale) || formatTime(lastCompression.timestamp)
    : compression?.updatedAt
      ? formatRelativeTime(compression.updatedAt, Date.now(), locale) || formatTime(compression.updatedAt)
      : "";
  const sessionStateLabel = (() => {
    if (groupPanelActive) {
      return activeSurfaceStatus;
    }
    const runtimeSessionState = runtimeMatchesSelectedSession ? runtime?.sessionState : "";
    switch (runtimeSessionState) {
      case "thinking":
        return t("sessionStateThinking");
      case "tooling":
        return t("sessionStateTooling");
      case "answering":
        return t("sessionStateAnswering");
      default:
        return statusLabel(runtimeSessionState || detail?.currentPhase || directSessionActiveSummary?.currentPhase || directSessionActiveSummary?.status || "idle");
    }
  })();
  const sessionStateLine = groupPanelActive
    ? activeSurfaceLine
    : runtimeMatchesSelectedSession && runtime?.sessionStateLine
      ? runtime.sessionStateLine
      : runtimeMismatchLine || (sessionDetailErrorState.blockingError
        ? sessionDetailErrorMessage
        : activeAgentStatusMessage || detail?.taskSummary || directSessionActiveSummary?.taskSummary || (sessionDetailLoadingForActiveSession ? t("loadingSession") : t("preparingShell")));
  const activeTask = detail?.activeTask ?? null;
  const agentDirectSessionMismatch = Boolean(detail?.agentDirectSessionMismatch);
  const agentPrimaryDirectSessionId = String(detail?.agentPrimaryDirectSessionId ?? "").trim();
  const sessionBindingMismatchLine = agentDirectSessionMismatch ? t("sessionBindingMismatchLine") : "";
  const sessionStateValue = String(groupPanelActive ? (projectBusActive ? "ready" : activeGroupRoom?.status ?? "ready") : (runtimeMatchesSelectedSession ? runtime?.sessionState : "") || detail?.currentPhase || directSessionActiveSummary?.currentPhase || directSessionActiveSummary?.status || "idle")
    .trim()
    .toLowerCase();
  useEffect(() => {
    const sample = groupPanelActive
      ? null
      : tokenSpeedSampleFromMessages(
        detail?.id ?? activeSessionId,
        detail?.messages,
        sessionStateValue,
        Date.now(),
      );
    setTokenSpeedTracker((previous) => updateTokenSpeedTracker(previous, sample));
  }, [activeSessionId, detail?.id, detail?.messages, groupPanelActive, sessionStateValue]);
  const activeTaskSummary = agentDirectSessionMismatch
    ? ""
    : activeTask?.goal
      || activeTask?.title
      || activeTask?.nextAction
      || activeTask?.latestSummary
      || "";
  const currentTaskSummary =
    activeTaskSummary
    || detail?.taskSummary
    || directSessionActiveSummary?.taskSummary
    || (runtimeMatchesSelectedSession ? runtime?.taskSummary : "")
    || t("preparingShell");
  const fileContextValue = detail?.defaultFileContext ?? (runtimeMatchesSelectedSession ? runtime?.defaultRoute : undefined) ?? "workspace";
  const tokenSpeedValue = tokenSpeedTracker
    ? tokenSpeedTracker.tokensPerSecond === null
      ? t("tokenSpeedSampling")
      : `${tokenSpeedTracker.tokensPerSecond >= 10 ? Math.round(tokenSpeedTracker.tokensPerSecond) : tokenSpeedTracker.tokensPerSecond.toFixed(1)} tok/s`
    : "";
  const tokenSpeedTitle = tokenSpeedTracker
    ? `${t("tokenSpeedEstimated")} · ${numberFormatter.format(tokenSpeedTracker.tokenCount)} tokens`
    : "";
  const sessionCompactRows = buildVisiblePanelRows(
    [
      ...(tokenSpeedTracker ? [{
        label: t("tokenSpeed"),
        value: tokenSpeedValue,
        title: tokenSpeedTitle,
      }] : []),
      {
        label: t("llmInputTokens"),
        value: llmUsageLine,
        title: llmUsageTitle,
      },
      {
        label: t("fileContext"),
        value: fileContextValue,
        title: fileContextValue,
      },
      ...(agentDirectSessionMismatch ? [{
        label: t("sessionBinding"),
        value: t("sessionBindingHistorical"),
        title: `${sessionBindingMismatchLine} ${agentPrimaryDirectSessionId}`,
      }] : []),
      ...(latestControlSignal ? [{
        label: t("nextStateSignalsLabel"),
        value: latestControlSignalLine,
        title: latestControlSignalTitle,
      }] : []),
      {
        label: t("currentTask"),
        value: currentTaskSummary,
        title: currentTaskSummary,
      },
      {
        label: t("promptCache"),
        value: cacheHitLine,
        title: sessionCacheUsage
          ? `${t("promptCacheLast")} ${numberFormatter.format(sessionCacheUsage.lastCachedInputTokens)} / ${numberFormatter.format(sessionCacheUsage.lastInputTokens)} · ${t("promptCacheTotal")} ${numberFormatter.format(sessionCacheUsage.totalCachedInputTokens)} / ${numberFormatter.format(sessionCacheUsage.totalInputTokens)}`
          : t("cacheObservationPending"),
      },
    ],
    [t("preparingShell"), t("loadingSession"), t("loadingContext")],
  );
  const mental = runtime?.mentalState;
  const mentalCognitiveStateValue = String(mental?.cognitiveState ?? "unknown").trim().toLowerCase() || "unknown";
  const mentalSourceValue = String(mental?.source ?? "unavailable").trim().toLowerCase() || "unavailable";
  const mentalCognitiveStateLabel = (() => {
    switch (mentalCognitiveStateValue) {
      case "normal":
        return t("mentalCognitiveState_normal");
      case "productive":
        return t("mentalCognitiveState_productive");
      case "looping":
        return t("mentalCognitiveState_looping");
      case "thrashing":
        return t("mentalCognitiveState_thrashing");
      case "tunnel_vision":
        return t("mentalCognitiveState_tunnel_vision");
      case "disoriented":
        return t("mentalCognitiveState_disoriented");
      default:
        return t("mentalCognitiveState_unknown");
    }
  })();
  const mentalSourceLabel = (() => {
    switch (mentalSourceValue) {
      case "state":
        return t("mentalSourceState");
      case "diagnosis":
        return t("mentalSourceDiagnosis");
      default:
        return t("mentalSourceUnavailable");
    }
  })();
  const mentalStateLabel = mental?.mood?.trim() || mentalCognitiveStateLabel;
  const mentalSummary = mental?.feeling?.trim() || mental?.summary || t("mentalStatePending");
  const mentalWhisper = mental?.whisper?.trim() || t("mentalStatePending");
  const mentalConfidence =
    Number.isFinite(mental?.confidence)
      ? `${Math.round((mental?.confidence ?? 0) * 100)}%`
      : "--";
  const mentalRelativeTime = formatRelativeTime(mental?.updatedAt ?? "", Date.now(), locale) || "--";
  const mentalCompactLine = [
    mentalSourceLabel,
    mentalConfidence !== "--" ? `${t("mentalConfidence")} ${mentalConfidence}` : "",
    mentalRelativeTime !== "--" ? mentalRelativeTime : "",
  ]
    .filter(Boolean)
    .join(" · ");
  const petCompactLine = [
    petCompanionLine,
    pet?.heartActive ? t("heartActive") : t("heartIdle"),
    pet?.inDream ? t("dreamSleeping") : t("dreamAwake"),
    `${t("tokens")} ${numberFormatter.format(pet?.totalTokens ?? 0)}`,
  ]
    .filter(Boolean)
    .join(" · ");

  const agentsById = useMemo(() => {
    return new Map((agentsQuery.data ?? []).map((agent) => [agent.agentId, agent]));
  }, [agentsQuery.data]);

  const agentsByCode = useMemo(() => {
    const map = new Map<string, AgentInstance>();
    for (const agent of agentsQuery.data ?? []) {
      const code = String(agent.agentCode ?? "").trim();
      if (code) {
        map.set(code, agent);
      }
    }
    return map;
  }, [agentsQuery.data]);

  const resolveConversationTurnAvatar = useCallback((message: ConversationMessage): TurnAvatarResolution | undefined => {
    if (!isAgentInboxMessage(message)) {
      return undefined;
    }
    const metadata = message.metadata;
    const sourceAgentId = conversationMetadataText(metadata, "sourceAgentId");
    const sourceAgentCode = conversationMetadataText(metadata, "sourceAgentCode");
    const sourceAgentName = conversationMetadataText(metadata, "sourceAgentName");
    const agent =
      (sourceAgentId ? agentsById.get(sourceAgentId) : undefined)
      ?? (sourceAgentCode ? agentsByCode.get(sourceAgentCode) : undefined);
    return {
      imageUrl: avatarImageUrlFrom(agent),
      fallback: avatarInitials(sourceAgentCode, sourceAgentName),
    };
  }, [agentsByCode, agentsById]);

  const chatMentionTargets = useMemo(() => {
    return buildChatMentionTargets(agentsQuery.data ?? []);
  }, [agentsQuery.data]);

  const allVisibleSessions = useMemo(() => {
    return (sessionsQuery.data ?? []).filter(isVisibleDirectSession);
  }, [sessionsQuery.data]);

  const sessionsById = useMemo(() => {
    return new Map(allVisibleSessions.map((session) => [session.id, session]));
  }, [allVisibleSessions]);

  const contextMenuSession = useMemo(() => {
    if (!sessionContextMenu) {
      return undefined;
    }
    return sessionsById.get(sessionContextMenu.sessionId) ?? sessionContextMenu.session;
  }, [sessionContextMenu, sessionsById]);

  const rightIndexSessions = useMemo(() => {
    return allVisibleSessions.filter((session) => !isRepresentedInAgentSessionTabs(session));
  }, [allVisibleSessions]);

  const activeRootSessionId = rootSessionIdFor(directSessionActiveSummary);
  const agentSessionTabs = useMemo(() => {
    if (!activeRootSessionId) {
      return [];
    }
    const rootSession = sessionsById.get(activeRootSessionId);
    const childSessions = allVisibleSessions
      .filter((session) => isChildSession(session) && rootSessionIdFor(session) === activeRootSessionId)
      .sort((left, right) =>
        String(left.updatedAt || left.lastActive || "").localeCompare(String(right.updatedAt || right.lastActive || "")),
      );
    return [rootSession, ...childSessions]
      .filter((session): session is SessionSummary => Boolean(session))
      .filter((session, index, sessions) => sessions.findIndex((item) => item.id === session.id) === index);
  }, [activeRootSessionId, allVisibleSessions, sessionsById]);

  const groupCandidateAgents = useMemo(() => {
    return (agentsQuery.data ?? []).filter((agent) => {
      return (
        String(agent.kind ?? "").trim() === "persistent"
        && String(agent.status ?? "").trim() !== "archived"
        && String(agent.directSessionId ?? "").trim()
      );
    });
  }, [agentsQuery.data]);

  const readyChatRoomModes = useMemo(() => {
    const modes = (chatRoomModesQuery.data ?? []).filter((mode) => String(mode.status ?? "").trim() === "ready");
    return modes.length ? modes : [{ id: "round_robin", label: "Round robin", status: "ready" }];
  }, [chatRoomModesQuery.data]);
  const availableChatRoomPurposes = useMemo(() => {
    const purposes = chatRoomPurposesQuery.data ?? [];
    return purposes.length
      ? purposes
      : [
          { id: "chat", label: "Chat", description: "" },
          { id: "discussion", label: "Discussion", description: "" },
          { id: "meeting", label: "Meeting", description: "" },
          { id: "medical_triage", label: "Medical triage", description: "" },
        ];
  }, [chatRoomPurposesQuery.data]);

  const activeGroupTeamMemberByAgentId = useMemo(() => {
    return new Map(
      (activeGroupTeam?.members ?? [])
        .map((member) => [String(member.agentId ?? "").trim(), member] as const)
        .filter(([agentId]) => Boolean(agentId)),
    );
  }, [activeGroupTeam?.members]);
  const groupParticipantIdentity = useCallback(
    (
      participant: ChatRoomParticipant | undefined,
      fallback: { agentId?: string; agentCode?: string; title?: string; participantId?: string; agentAvatarImageUrl?: string } = {},
    ) => {
      const agentId = String(participant?.agentId || fallback.agentId || "").trim();
      const participantLike = participant ?? {
        participantId: String(fallback.participantId || agentId || "agent").trim(),
        kind: "session_agent",
        agentId,
        agentCode: String(fallback.agentCode || "").trim(),
        agentAvatarImageUrl: String(fallback.agentAvatarImageUrl || "").trim(),
        sessionId: "",
        title: String(fallback.title || fallback.participantId || agentId || "Agent").trim(),
        enabled: true,
        status: "",
      };
      const participantAgent = agentId ? agentsById.get(agentId) : undefined;
      const display = participantAgentDisplayInfo(participantLike, participantAgent, lang, resolveModelLabel);
      const member = agentId ? activeGroupTeamMemberByAgentId.get(agentId) : undefined;
      const participantTeamRole = String(participant?.teamMemberPurpose || participant?.teamRole || "").trim();
      const role = String(participantTeamRole || member?.purpose || member?.role || display.functionLabel || "").trim();
      const name = String(display.name || fallback.title || fallback.participantId || "Agent").trim();
      const compactRole = compactAgentRoleLabel(role || display.functionLabel);
      return {
        ...display,
        name,
        functionLabel: role || display.functionLabel,
        compactRole,
        avatarImageUrl: avatarImageUrlFrom(participantAgent, participantLike, fallback),
        identityLabel: formatAgentIdentityWithRole(name, compactRole, fallback.participantId || "Agent"),
        fullIdentityLabel: [
          formatAgentIdentityWithRole(name, role || display.functionLabel, fallback.participantId || "Agent"),
          display.modelLabel,
        ].filter(Boolean).join(" · "),
      };
    },
    [activeGroupTeamMemberByAgentId, agentsById, lang, resolveModelLabel],
  );
  const {
    filteredConversations,
    filteredStandaloneGroupConversations,
    filteredTeams,
    groupedConversations,
    searchHasTerm,
  } = useConversationIndexModel({
    conversations: conversationsQuery.data,
    lang,
    linkedTeamRoomIds,
    rawSessions: rawSessionsQuery.data,
    rightIndexSessions,
    sessionFilter,
    sessionsById,
    teams,
  });
  const sessionIndexLoadedCount = rawSessionsQuery.loadedCount;
  const sessionIndexTotalEstimate = rawSessionsQuery.totalEstimate;
  const sessionIndexHasMore = rawSessionsQuery.hasMore;
  const sessionIndexLoadMoreLabel = rawSessionsQuery.isLoadingMore
    ? (lang === "zh" ? "加载中" : "Loading")
    : (lang === "zh" ? "加载更多会话" : "Load more chats");
  const sessionIndexFullyLoadedLabel = lang === "zh" ? "已加载全部会话" : "All chats loaded";
  const sessionIndexProgressLabel =
    sessionIndexTotalEstimate > sessionIndexLoadedCount
      ? `${numberFormatter.format(sessionIndexLoadedCount)} / ${numberFormatter.format(sessionIndexTotalEstimate)}`
      : numberFormatter.format(sessionIndexLoadedCount);
  const sessionIndexProgressVisible = sessionIndexHasMore || sessionIndexTotalEstimate > SESSION_INDEX_PAGE_SIZE;

  function formatTime(value: string) {
    if (!value) {
      return "";
    }
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) {
      return value;
    }
    return timeFormatter.format(parsed);
  }

  function toggleConversationGroup(groupKey: ConversationIndexGroupKey) {
    setCollapsedConversationGroups((current) => ({
      ...current,
      [groupKey]: !current[groupKey],
    }));
  }

  function handleComposerChange(value: string) {
    if (!activeSessionId) {
      return;
    }
    setSessionDrafts((current) => ({
      ...current,
      [activeSessionId]: value,
    }));
    setSessionComposerErrors((current) => ({
      ...current,
      [activeSessionId]: "",
    }));
  }

  function handleMentalModelEnabledChange(enabled: boolean) {
    setMentalModelEnabledForNextTurn(enabled);
    writeStoredMentalModelToggle(enabled);
  }

  function handleAddComposerAttachments(files: FileList | File[]) {
    if (!activeSessionId) {
      return;
    }
    const incoming = Array.from(files || []).filter((file) => file.type.startsWith("image/"));
    if (!incoming.length) {
      return;
    }
    const accepted: ComposerImageAttachment[] = [];
    const rejected: string[] = [];
    for (const file of incoming) {
      if (!["image/png", "image/jpeg", "image/webp"].includes(file.type)) {
        rejected.push(file.name);
        continue;
      }
      if (file.size > MAX_COMPOSER_IMAGE_BYTES) {
        rejected.push(file.name);
        continue;
      }
      accepted.push({
        id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
        file,
        filename: file.name || "image",
        previewUrl: URL.createObjectURL(file),
        sizeBytes: file.size,
        contentType: file.type,
      });
    }
    setSessionImageAttachments((current) => {
      const existing = current[activeSessionId] ?? [];
      const merged = [...existing, ...accepted].slice(0, MAX_COMPOSER_IMAGE_ATTACHMENTS);
      return {
        ...current,
        [activeSessionId]: merged,
      };
    });
    setSessionComposerErrors((current) => ({
      ...current,
      [activeSessionId]: rejected.length
        ? (lang === "zh" ? "部分图片格式或大小不支持。" : "Some images were rejected by type or size.")
        : "",
    }));
  }

  function handleRemoveComposerAttachment(attachmentId: string) {
    if (!activeSessionId) {
      return;
    }
    setSessionImageAttachments((current) => removeSessionImageAttachment(current, activeSessionId, attachmentId));
  }

  function handleAddComposerReference(reference: SessionReferenceAttachment) {
    if (!activeSessionId) {
      return;
    }
    const referenceId = sessionReferenceId(reference);
    if (!referenceId) {
      setSessionComposerErrors((current) => ({
        ...current,
        [activeSessionId]: lang === "zh" ? "会话引用缺少有效 id。" : "Session reference is missing a valid id.",
      }));
      return;
    }
    setSessionReferenceAttachments((current) => {
      const existing = current[activeSessionId] ?? [];
      if (existing.some((item) => sessionReferenceId(item) === referenceId)) {
        return current;
      }
      return {
        ...current,
        [activeSessionId]: [...existing, reference].slice(-6),
      };
    });
    setSessionComposerErrors((current) => ({
      ...current,
      [activeSessionId]: "",
    }));
  }

  function handleRemoveComposerReference(referenceId: string) {
    if (!activeSessionId) {
      return;
    }
    setSessionReferenceAttachments((current) => {
      const existing = current[activeSessionId] ?? [];
      const next = existing.filter((reference) => sessionReferenceId(reference) !== referenceId);
      if (next.length === existing.length) {
        return current;
      }
      if (!next.length) {
        return clearSessionReferenceAttachments(current, activeSessionId);
      }
      return {
        ...current,
        [activeSessionId]: next,
      };
    });
  }

  async function submitTurnWithAttachments(
    sessionId: string,
    content: string,
    attachments: ComposerImageAttachment[],
    references: SessionReferenceAttachment[],
    mentalModelEnabled: boolean,
  ) {
    if (imageUploadInFlightRef.current[sessionId]) {
      postSubmitTelemetry(
        "browser.chat_submit.blocked",
        "Direct chat submit was blocked while image upload was already in flight.",
        sessionId,
        {
          content,
          attachmentCount: attachments.length,
          referenceCount: references.length,
          mentalModelEnabled,
          guardReason: "image_upload_in_flight",
        },
        "warning",
      );
      return;
    }
    imageUploadInFlightRef.current[sessionId] = true;
    setSessionImageUploadPending((current) => ({
      ...current,
      [sessionId]: true,
    }));
    setSessionDrafts((current) => clearSessionDraftForSubmittedTurn(current, sessionId));
    setSessionComposerErrors((current) => ({
      ...current,
      [sessionId]: "",
    }));
    if (content || references.length) {
      queryClient.setQueryData<SessionDetail>(queryKeys.session(sessionId), (detail) =>
        markSessionDetailRunning(appendOptimisticUserMessage(detail, { sessionId, content, references })),
      );
    }
    try {
      if (attachments.length) {
        postSubmitTelemetry(
          "browser.chat_submit.upload_started",
          "Direct chat submit image upload started.",
          sessionId,
          {
            content,
            attachmentCount: attachments.length,
            referenceCount: references.length,
            mentalModelEnabled,
          },
        );
      }
      const uploaded = await Promise.all(attachments.map((attachment) => uploadSessionImageAttachment(sessionId, attachment)));
      if (attachments.length) {
        postSubmitTelemetry(
          "browser.chat_submit.upload_succeeded",
          "Direct chat submit image upload succeeded.",
          sessionId,
          {
            content,
            attachmentCount: attachments.length,
            uploadedAttachmentCount: uploaded.length,
            referenceCount: references.length,
            mentalModelEnabled,
          },
        );
      }
      postSubmitTelemetry(
        "browser.chat_submit.submit_mutate_requested",
        "Direct chat submit mutation was requested.",
        sessionId,
        {
          content,
          attachmentCount: attachments.length,
          uploadedAttachmentCount: uploaded.length,
          referenceCount: references.length,
          mentalModelEnabled,
        },
      );
      submitTurnMutation.mutate({
        sessionId,
        content,
        mentalModelEnabled,
        attachmentIds: uploaded.map((attachment) => attachment.artifactId).filter(Boolean),
        references,
      });
    } catch (error) {
      postSubmitTelemetry(
        "browser.chat_submit.upload_failed",
        "Direct chat submit image upload failed before message POST.",
        sessionId,
        {
          content,
          attachmentCount: attachments.length,
          referenceCount: references.length,
          mentalModelEnabled,
          error,
        },
        "error",
      );
      setSessionComposerErrors((current) => ({
        ...current,
        [sessionId]: describeError(error, lang === "zh" ? "图片上传失败" : "Image upload failed"),
      }));
      if (content || references.length) {
        queryClient.setQueryData<SessionDetail>(queryKeys.session(sessionId), (detail) =>
          removeOptimisticUserMessage(detail, { sessionId, content, references }),
        );
        setSessionDrafts((current) => restoreSubmittedDraftIfComposerStillEmpty(current, sessionId, content));
      }
    } finally {
      imageUploadInFlightRef.current[sessionId] = false;
      setSessionImageUploadPending((current) => ({
        ...current,
        [sessionId]: false,
      }));
    }
  }

  function handleSubmitTurn() {
    if (!activeSessionId) {
      return;
    }
    const content = activeDraftEffective.trim();
    postSubmitTelemetry(
      "browser.chat_submit.requested",
      "Direct chat submit was requested from the composer.",
      activeSessionId,
      {
        content,
        attachmentCount: activeImageAttachments.length,
        referenceCount: activeReferenceAttachments.length,
        mentalModelEnabled: mentalModelEnabledForNextTurn,
        editTargetId: resolvedEditTarget?.messageId,
        composerDisabled,
        sessionBusy,
        activePhase: detail?.currentPhase,
      },
    );
    const guardReason = composerDisabled
      ? "composer_disabled"
      : !content && !activeImageAttachments.length && !activeReferenceAttachments.length
        ? "empty_content"
        : "";
    if (guardReason) {
      postSubmitTelemetry(
        "browser.chat_submit.blocked",
        "Direct chat submit was blocked by the composer guard.",
        activeSessionId,
        {
          content,
          attachmentCount: activeImageAttachments.length,
          referenceCount: activeReferenceAttachments.length,
          mentalModelEnabled: mentalModelEnabledForNextTurn,
          editTargetId: resolvedEditTarget?.messageId,
          composerDisabled,
          sessionBusy,
          activePhase: detail?.currentPhase,
          guardReason,
        },
        "warning",
      );
      return;
    }
    if (resolvedEditTarget) {
      postSubmitTelemetry(
        "browser.chat_submit.edit_resubmit_requested",
        "Edit-resubmit mutation was requested from the composer.",
        activeSessionId,
        {
          content,
          attachmentCount: activeImageAttachments.length,
          referenceCount: activeReferenceAttachments.length,
          mentalModelEnabled: mentalModelEnabledForNextTurn,
          editTargetId: resolvedEditTarget.messageId,
          composerDisabled,
          sessionBusy,
          activePhase: detail?.currentPhase,
        },
      );
      editResubmitMutation.mutate({
        sessionId: activeSessionId,
        messageId: resolvedEditTarget.messageId,
        content,
        mentalModelEnabled: mentalModelEnabledForNextTurn,
      });
      return;
    }
    void submitTurnWithAttachments(
      activeSessionId,
      content,
      activeImageAttachments,
      activeReferenceAttachments,
      mentalModelEnabledForNextTurn,
    );
  }

  function handleEditUserMessage(message: ConversationMessage) {
    if (!activeSessionId || sessionBusy) {
      return;
    }
    if (message.id !== latestUserMessageId) {
      return;
    }
    setSessionEditTargets((current) => ({
      ...current,
      [activeSessionId]: {
        messageId: message.id,
        original: message.content,
      },
    }));
    setSessionImageAttachments((current) => clearSessionImageAttachments(current, activeSessionId));
    setSessionReferenceAttachments((current) => clearSessionReferenceAttachments(current, activeSessionId));
    setSessionDrafts((current) => ({
      ...current,
      [activeSessionId]: message.content,
    }));
    setSessionComposerErrors((current) => ({
      ...current,
      [activeSessionId]: "",
    }));
  }

  useEffect(() => {
    if (!activeSessionId || !detail || !activeEditTarget || activeEditTarget.messageId === latestUserMessageId) {
      return;
    }
    setSessionEditTargets((current) => {
      const { [activeSessionId]: _removed, ...remaining } = current;
      return remaining;
    });
    setSessionDrafts((current) => ({
      ...current,
      [activeSessionId]: "",
    }));
  }, [activeEditTarget, activeSessionId, latestUserMessageId, setSessionDrafts, setSessionEditTargets]);

  function handleCancelEditMessage() {
    if (!activeSessionId) {
      return;
    }
    setSessionEditTargets((current) => {
      const { [activeSessionId]: _removed, ...remaining } = current;
      return remaining;
    });
    setSessionDrafts((current) => ({
      ...current,
      [activeSessionId]: "",
    }));
    setSessionImageAttachments((current) => clearSessionImageAttachments(current, activeSessionId));
    setSessionReferenceAttachments((current) => clearSessionReferenceAttachments(current, activeSessionId));
  }

  function handleStopTurn() {
    if (!activeSessionId || !sessionBusy || sessionStopping) {
      return;
    }
    stopTurnMutation.mutate({
      sessionId: activeSessionId,
    });
  }

  function handleSubmitGuidance(mode: SessionGuidanceMode) {
    if (!activeSessionId || !sessionBusy || sessionStopping) {
      return;
    }
    const content = activeDraftEffective.trim();
    if (!content) {
      return;
    }
    sessionGuidanceMutation.mutate({
      sessionId: activeSessionId,
      content,
      mode,
    });
  }

  function handlePetInteraction(action: PetInteractionAction) {
    setPetActionFeedback("");
    petActionMutation.mutate({ action });
  }

  function handleCreateSession() {
    setActiveGroupRoomId("");
    setRightIndexPanel("conversations");
    setSessionComposerErrors((current) => ({
      ...current,
      __sessions__: "",
    }));
    createSessionMutation.mutate();
  }

  function handleOpenProjectAgentBus() {
    setSessionContextMenu(null);
    navigate("/chat", { replace: false });
    setActiveGroupRoomId("__project_agent_bus__");
    setRightIndexPanel("conversations");
    setRightPaneCollapsed(false);
    setGroupRoomActionError("");
    void chatWorkspaceCache.afterProjectBusFailed();
  }

  function handleOpenDirectSession(sessionId: string) {
    if (!sessionId) {
      return;
    }
    setSessionContextMenu(null);
    setActiveSession(sessionId);
    setActiveGroupRoomId("");
    setRightIndexPanel("conversations");
    setGroupRoomActionError("");
    navigate(`/chat?session=${encodeURIComponent(sessionId)}`, { replace: false });
  }

  function handleOpenMentionTarget(target: ChatMentionTarget) {
    setRightPaneCollapsed(false);
    setGroupRoomActionError("");
    if (target.kind === "all") {
      setActiveGroupRoomId("__project_agent_bus__");
      setRightIndexPanel("conversations");
      setSessionFilter("");
      void chatWorkspaceCache.afterProjectBusFailed();
      return;
    }
    if (target.directSessionId) {
      setSessionFilter("");
      handleOpenDirectSession(target.directSessionId);
      return;
    }
    const fallbackFilter = target.agentCode || target.displayName || target.agentId || "";
    if (fallbackFilter) {
      setActiveGroupRoomId("");
      setRightIndexPanel("conversations");
      setSessionFilter(fallbackFilter);
    }
  }

  function renderMentionedText(content: string, fallback = "") {
    const text = content || fallback;
    return tokenizeChatMentions(text, chatMentionTargets).map((segment, index) => {
      if (segment.type === "text") {
        return <span key={`text-${index}`}>{segment.text}</span>;
      }
      const mentionLabel = segment.target.kind === "all"
        ? (lang === "zh" ? "全体成员" : "All agents")
        : [segment.target.displayName, segment.target.agentCode].filter(Boolean).join(" · ");
      return (
        <button
          key={`mention-${index}-${segment.text}`}
          type="button"
          className={styles.agentMention}
          onClick={() => handleOpenMentionTarget(segment.target)}
          aria-label={lang === "zh" ? `打开 ${mentionLabel} 的索引` : `Open ${mentionLabel} index`}
          title={lang === "zh" ? "打开对应 Agent 索引" : "Open the matching agent index"}
        >
          {segment.text}
        </button>
      );
    });
  }

  function renderGroupMessageBody(message: ChatRoomMessage, identityName: string) {
    const content = stripGroupSpeakerPrefix(message, identityName);
    const expanded = expandedGroupMessageIds.includes(message.messageId);
    const defaultCollapsed = shouldDefaultCollapseGroupMessage(message);
    const collapsible = defaultCollapsed || shouldCollapseGroupMessage(content);
    const collapsed = collapsible && !expanded;
    const collapseLabel = defaultCollapsed
      ? (lang === "zh" ? "展开讨论" : "Show discussion")
      : (lang === "zh" ? "展开全文" : "Show full");
    return (
      <>
        <p className={collapsed ? `${styles.groupBubbleBody} ${styles.groupBubbleBodyCollapsed}` : styles.groupBubbleBody}>
          {renderMentionedText(content, lang === "zh" ? "暂无内容" : "No content yet")}
        </p>
        {collapsible ? (
          <button
            type="button"
            className={styles.groupBubbleToggle}
            onClick={() =>
              setExpandedGroupMessageIds((current) =>
                current.includes(message.messageId)
                  ? current.filter((messageId) => messageId !== message.messageId)
                  : [...current, message.messageId],
              )}
          >
            {expanded ? (lang === "zh" ? "收起" : "Collapse") : collapseLabel}
          </button>
        ) : null}
      </>
    );
  }

  function handleOpenGroupRoom(roomId: string) {
    if (!roomId) {
      return;
    }
    navigate(`/chat?room=${encodeURIComponent(roomId)}`, { replace: false });
    setActiveGroupRoomId(roomId);
    setRightIndexPanel("members");
    setRightPaneCollapsed(false);
    setGroupRoomActionError("");
    void chatWorkspaceCache.afterChatRoomChanged(roomId);
  }

  function handleToggleGroupManageSession(sessionId: string) {
    if (!sessionId || activeGroupTeamOwned || groupRoundActive || updateGroupRoomMutation.isPending) {
      return;
    }
    setGroupRoomActionError("");
    setGroupManageSessionIds((current) =>
      current.includes(sessionId)
        ? current.filter((item) => item !== sessionId)
        : [...current, sessionId],
    );
  }

  function handleToggleGroupComposer() {
    setSessionComposerErrors((current) => ({
      ...current,
      __sessions__: "",
    }));
    setGroupComposerOpen((open) => {
      const nextOpen = !open;
      if (nextOpen && !groupTitleDraft.trim()) {
        setGroupTitleDraft(lang === "zh" ? "Agent 群聊" : "Agent group");
      }
      return nextOpen;
    });
  }

  function handleToggleGroupAgent(agentId: string) {
    setSessionComposerErrors((current) => ({
      ...current,
      __sessions__: "",
    }));
    setGroupSelectedAgentIds((current) =>
      current.includes(agentId) ? current.filter((item) => item !== agentId) : [...current, agentId],
    );
  }

  function handleCreateGroupRoom() {
    const title = groupTitleDraft.trim();
    const agentIds = groupSelectedAgentIds.filter(Boolean);
    if (!title || agentIds.length < 2 || createGroupRoomMutation.isPending) {
      setSessionComposerErrors((current) => ({
        ...current,
        __sessions__: lang === "zh" ? "请输入群聊名称，并至少选择两个 Agent。" : "Enter a group name and choose at least two agents.",
      }));
      return;
    }
    createGroupRoomMutation.mutate({
      title,
      agentIds,
      mode: groupModeDraft || "round_robin",
      purpose: groupPurposeDraft || "discussion",
    });
  }

  function handleStartGroupRound() {
    const topic = groupTopicDraft.trim();
    if (!legacyGroupRoomActive || !activeGroupRoomId || !topic || startGroupRoundMutation.isPending || groupRoundActive) {
      return;
    }
    startGroupRoundMutation.mutate({
      roomId: activeGroupRoomId,
      topic,
      mode: activeGroupRoom?.mode || "round_robin",
      purpose: activeGroupRoom?.purpose || "discussion",
    });
  }

  function handleStopGroupRound() {
    if (!legacyGroupRoomActive || !activeGroupRoomId || !groupRoundRunning || stopGroupRoundMutation.isPending) {
      return;
    }
    stopGroupRoundMutation.mutate({
      roomId: activeGroupRoomId,
    });
  }

  function handleSendProjectBusMessage() {
    const content = projectBusDraft.trim();
    if (!content || sendProjectBusMessageMutation.isPending) {
      return;
    }
    sendProjectBusMessageMutation.mutate({
      content,
      interruptTargets: projectBusInterruptTargets,
    });
  }

  function handleRevokeProjectBusMessage(eventId: string) {
    if (!eventId || revokeProjectBusMessageMutation.isPending) {
      return;
    }
    revokeProjectBusMessageMutation.mutate({ eventId });
  }

  function handleApplyGroupRoomManagement() {
    if (!legacyGroupRoomActive || activeGroupTeamOwned || !activeGroupRoomId || groupManageDisabled) {
      return;
    }
    updateGroupRoomMutation.mutate({
      roomId: activeGroupRoomId,
      title: groupManageTitleDraft.trim(),
      sessionIds: groupManageSessionIds,
      mode: groupManageModeDraft || "round_robin",
      purpose: groupManagePurposeDraft || "discussion",
    });
  }

  function handleDeleteActiveGroupRoom() {
    if (!legacyGroupRoomActive || activeGroupTeamOwned || !activeGroupRoomId || groupDeleteDisabled) {
      return;
    }
    const roomTitle = (activeGroupRoom?.title || activeGroupRoomId).trim();
    const groupConfirmMessage = t("deleteGroupConfirm").replace("{title}", roomTitle || activeGroupRoomId);
    if (!window.confirm(groupConfirmMessage)) {
      return;
    }
    deleteGroupRoomMutation.mutate({ roomId: activeGroupRoomId });
  }

  function handleResetActiveGroupRoom() {
    if (!legacyGroupRoomActive || !activeGroupRoomId || groupResetDisabled) {
      return;
    }
    const roomTitle = (activeGroupRoom?.title || activeGroupRoomId).trim();
    const groupConfirmMessage = t("resetGroupConfirm").replace("{title}", roomTitle || activeGroupRoomId);
    if (!window.confirm(groupConfirmMessage)) {
      return;
    }
    resetGroupRoomMutation.mutate({ roomId: activeGroupRoomId });
  }

  function handleDeleteSession(session: SessionSummary) {
    setSessionContextMenu(null);
    if (isBusyPhase(session.currentPhase || session.status)) {
      setSessionComposerErrors((current) => ({
        ...current,
        [session.id]: t("deleteSessionBusy"),
        __sessions__: "",
      }));
      return;
    }
    const sessionTitle = (session.agentDisplayName || session.title || session.id).trim();
    const sessionConfirmMessage = t("deleteSessionConfirm").replace("{title}", sessionTitle || session.id);
    if (!window.confirm(sessionConfirmMessage)) {
      return;
    }
    setSessionComposerErrors((current) => ({
      ...current,
      [session.id]: "",
      __sessions__: "",
    }));
    deleteSessionMutation.mutate({ sessionId: session.id });
  }

  function handleAddSessionToReview(session: SessionSummary) {
    setSessionContextMenu(null);
    if (isBusyPhase(session.currentPhase || session.status)) {
      setSessionComposerErrors((current) => ({
        ...current,
        [session.id]: t("addSessionToReviewBusy"),
        __sessions__: "",
      }));
      return;
    }
    setSessionComposerErrors((current) => ({
      ...current,
      [session.id]: "",
      __sessions__: "",
    }));
    addSessionToReviewMutation.mutate({ sessionId: session.id });
  }

  function beginRenameSession(session: SessionSummary) {
    setSessionContextMenu(null);
    setEditingSessionId(session.id);
    setEditingSessionTitle(
      isAgentRootSession(session)
        ? (session.agentDisplayName || session.title)
        : isChildSession(session)
          ? (session.taskTitle || session.resultCard?.title || session.title)
          : session.title,
    );
    setSessionComposerErrors((current) => ({
      ...current,
      [session.id]: "",
      __sessions__: "",
    }));
  }

  function cancelRenameSession() {
    setSessionContextMenu(null);
    setEditingSessionId(null);
    setEditingSessionTitle("");
  }

  function openSessionContextMenu(event: ReactMouseEvent<HTMLElement>, session: SessionSummary) {
    event.preventDefault();
    event.stopPropagation();
    setSessionContextMenu({
      sessionId: session.id,
      session,
      x: event.clientX,
      y: event.clientY,
    });
  }

  function submitRenameSession(session: SessionSummary) {
    const title = editingSessionTitle.trim();
    if (!title) {
      setSessionComposerErrors((current) => ({
        ...current,
        [session.id]: t(isAgentRootSession(session) ? "renameAgentEmpty" : isChildSession(session) ? "renameTaskEmpty" : "renameSessionEmpty"),
      }));
      return;
    }
    const currentTitle = isAgentRootSession(session)
      ? (session.agentDisplayName || session.title)
      : isChildSession(session)
        ? (session.taskTitle || session.resultCard?.title || session.title)
        : session.title;
    if (title === currentTitle) {
      cancelRenameSession();
      return;
    }
    renameSessionMutation.mutate({ sessionId: session.id, title });
  }

  function handleResizeStart(side: ResizableSide, event: PointerEvent<HTMLDivElement>) {
    if (event.button !== 0) {
      return;
    }
    if ((side === "left" && leftRailCollapsed) || (side === "right" && rightPaneCollapsed)) {
      return;
    }
    event.preventDefault();
    setDragState({
      side,
      startX: event.clientX,
      startLeftWidth: leftPanelWidth,
      startRightWidth: rightPanelWidth,
    });
  }

  function handleResizeKeyDown(side: ResizableSide, event: KeyboardEvent<HTMLDivElement>) {
    if (!layoutRef.current) {
      return;
    }
    if ((side === "left" && leftRailCollapsed) || (side === "right" && rightPaneCollapsed)) {
      return;
    }

    const { key } = event;
    const direction =
      key === "ArrowLeft" ? -1 : key === "ArrowRight" ? 1 : key === "Home" ? "min" : key === "End" ? "max" : null;
    if (direction === null) {
      return;
    }

    event.preventDefault();
    const layoutWidth = layoutRef.current.getBoundingClientRect().width;

    if (side === "left") {
      const bounds = getResizeBounds("left", layoutWidth, rightPaneCollapsed ? 0 : rightPanelWidth);
      const nextLeftWidth =
        direction === "min"
          ? bounds.min
          : direction === "max"
            ? bounds.max
            : clamp(leftPanelWidth + Number(direction) * KEYBOARD_RESIZE_STEP, bounds.min, bounds.max);
      setChatPanelWidths({ leftPanelWidth: Math.round(nextLeftWidth) });
      return;
    }

    const bounds = getResizeBounds("right", layoutWidth, leftRailCollapsed ? 0 : leftPanelWidth);
    const delta =
      direction === "min"
        ? bounds.min
        : direction === "max"
          ? bounds.max
          : clamp(rightPanelWidth - Number(direction) * KEYBOARD_RESIZE_STEP, bounds.min, bounds.max);
    setChatPanelWidths({ rightPanelWidth: Math.round(delta) });
  }

  const toggleFeaturePreset = useCallback((key: FeaturePresetKey) => {
    setFeaturePresetState((current) => ({
      ...current,
      [key]: !current[key],
    }));
  }, []);

  const layoutStyle = useMemo(
    () =>
      ({
        "--chat-left-pane-width": leftRailCollapsed ? "0px" : `${leftPanelWidth}px`,
        "--chat-right-pane-width": rightPaneCollapsed ? "0px" : `${rightPanelWidth}px`,
      }) as CSSProperties,
    [leftPanelWidth, leftRailCollapsed, rightPanelWidth, rightPaneCollapsed],
  );

  const contextMenuSessionIsBusy = contextMenuSession
    ? isBusyPhase(contextMenuSession.currentPhase || contextMenuSession.status)
    : false;
  const contextMenuDeletePending = Boolean(
    contextMenuSession
    && deleteSessionMutation.isPending
    && deleteSessionMutation.variables?.sessionId === contextMenuSession.id,
  );
  const contextMenuAddToReviewPending = Boolean(
    contextMenuSession
    && addSessionToReviewMutation.isPending
    && addSessionToReviewMutation.variables?.sessionId === contextMenuSession.id,
  );
  const contextMenuDeleteDisabled = contextMenuDeletePending || contextMenuSessionIsBusy;
  const contextMenuAddToReviewDisabled = contextMenuAddToReviewPending || contextMenuSessionIsBusy;

  return (
    <div
      ref={layoutRef}
      className={centerFirstLayout ? `${styles.layout} ${styles.layoutCenterFirst}` : styles.layout}
      style={layoutStyle}
    >
      <aside className={leftRailCollapsed ? `${styles.leftRail} ${styles.paneCollapsed}` : styles.leftRail} aria-hidden={leftRailCollapsed}>
        {legacyGroupRoomActive ? (
          <section className={`${styles.leftBlock} ${styles.groupProfileBlock}`}>
            <div className={styles.sectionHeader}>
              <div className={styles.sectionIdentity}>
                <p className={styles.blockEyebrow}>{lang === "zh" ? "群资料与设置" : "Group profile"}</p>
                <h3 className={styles.sectionTitle}>{activeGroupRoom?.title ?? (lang === "zh" ? "群聊加载中" : "Loading group")}</h3>
              </div>
              <span className={`${styles.sessionStatePill} ${styles[`sessionStatePill_${String(activeGroupRoom?.status ?? "ready").trim().toLowerCase()}`]}`}>
                {statusLabel(activeGroupRoom?.status ?? "ready")}
              </span>
            </div>
            <p className={styles.contextLineCompact}>
              {activeGroupTeamOwned
                ? (lang === "zh"
                  ? "这是团队关联群聊；成员、角色和同步关系由团队页维护，这里只负责讨论运行与成员状态观察。"
                  : "This room is owned by a Team. Membership, roles, and sync stay in Teams; Chat only runs discussion and shows member status.")
                : (lang === "zh"
                  ? "这里管理当前普通群聊的资料、成员和调度；成员状态索引放在右侧独立分栏。"
                  : "Manage this standalone group's info, members, and scheduling here. Member status lives in the right index.")}
            </p>
            <div className={styles.resourceSplit}>
              <div className={styles.resourceMetric}>
                <span>{lang === "zh" ? "可用成员" : "Available"}</span>
                <strong>{numberFormatter.format(availableGroupParticipantCount)}</strong>
              </div>
              <div className={styles.resourceMetric}>
                <span>{lang === "zh" ? "调度" : "Mode"}</span>
                <strong>{activeGroupRoom?.mode ?? "round_robin"}</strong>
              </div>
              <div className={styles.resourceMetric}>
                <span>{lang === "zh" ? "目的" : "Purpose"}</span>
                <strong>{activeGroupRoom?.purpose ?? "discussion"}</strong>
              </div>
            </div>
            <section className={styles.groupManagementPanel} aria-label={lang === "zh" ? "群聊管理" : "Group management"}>
              <div className={styles.groupManagementHeader}>
                <div>
                  <strong>{activeGroupTeamOwned ? (lang === "zh" ? "团队群聊引用" : "Team room reference") : (lang === "zh" ? "群设置" : "Group settings")}</strong>
                  <span title={activeGroupRoom?.title ?? ""}>
                    {activeGroupRoom?.title ?? (lang === "zh" ? "群聊加载中" : "Loading group")}
                  </span>
                </div>
                <div className={styles.groupManagementActions}>
                  {activeGroupTeamOwned && activeGroupTeam ? (
                    <button
                      type="button"
                      className={styles.groupSecondaryButton}
                      onClick={() => navigate(`/teams?team=${encodeURIComponent(activeGroupTeam.teamId)}`)}
                    >
                      <ArrowUpRight size={14} />
                      <span>{lang === "zh" ? "打开团队" : "Open team"}</span>
                    </button>
                  ) : null}
                  <button
                    type="button"
                    className={groupManageChanged ? styles.groupApplyButton : styles.groupSecondaryButton}
                    disabled={groupManageDisabled || !groupManageChanged}
                    onClick={handleApplyGroupRoomManagement}
                  >
                    <Check size={14} />
                    <span>
                      {updateGroupRoomMutation.isPending
                        ? (lang === "zh" ? "应用中" : "Applying")
                        : (lang === "zh" ? "应用变更" : "Apply")}
                    </span>
                  </button>
                  <button
                    type="button"
                    className={styles.groupDeleteButton}
                    disabled={groupDeleteDisabled}
                    onClick={handleDeleteActiveGroupRoom}
                  >
                    <Trash2 size={14} />
                    <span>
                      {deleteGroupRoomMutation.isPending
                        ? (lang === "zh" ? "删除中" : "Deleting")
                        : (lang === "zh" ? "删除" : "Delete")}
                    </span>
                  </button>
                  <button
                    type="button"
                    className={styles.groupSecondaryButton}
                    disabled={groupResetDisabled}
                    onClick={handleResetActiveGroupRoom}
                  >
                    <RotateCcw size={14} />
                    <span>
                      {resetGroupRoomMutation.isPending
                        ? (lang === "zh" ? "重置中" : "Resetting")
                        : (lang === "zh" ? "重置消息" : "Reset messages")}
                    </span>
                  </button>
                </div>
              </div>
              {groupRoomActionError ? (
                <div className={styles.panelNotice}>{groupRoomActionError}</div>
              ) : null}
              <div className={styles.groupManagementControls}>
                <label className={styles.groupTitleField}>
                  <span>{lang === "zh" ? "群名" : "Name"}</span>
                  <input
                    value={groupManageTitleDraft}
                    maxLength={80}
                    disabled={activeGroupTeamOwned || groupRoundActive || updateGroupRoomMutation.isPending}
                    onChange={(event) => {
                      setGroupRoomActionError("");
                      setGroupManageTitleDraft(event.target.value);
                    }}
                  />
                </label>
                <label className={styles.groupModeSelect}>
                  <span>{lang === "zh" ? "调度模式" : "Mode"}</span>
                  <select
                    value={groupManageModeDraft}
                    disabled={activeGroupTeamOwned || groupRoundActive || updateGroupRoomMutation.isPending}
                    onChange={(event) => {
                      setGroupRoomActionError("");
                      setGroupManageModeDraft(event.target.value);
                    }}
                  >
                    {readyChatRoomModes.map((mode) => (
                      <option key={mode.id} value={mode.id}>
                        {chatRoomModeLabel(mode, lang)}
                      </option>
                    ))}
                  </select>
                </label>
                <label className={styles.groupModeSelect}>
                  <span>{lang === "zh" ? "对话目的" : "Purpose"}</span>
                  <select
                    value={groupManagePurposeDraft}
                    disabled={activeGroupTeamOwned || groupRoundRunning || updateGroupRoomMutation.isPending}
                    onChange={(event) => {
                      setGroupRoomActionError("");
                      setGroupManagePurposeDraft(event.target.value);
                    }}
                  >
                    {availableChatRoomPurposes.map((purpose) => (
                      <option key={purpose.id} value={purpose.id}>
                        {chatRoomPurposeLabel(purpose, lang)}
                      </option>
                    ))}
                  </select>
                </label>
                <div className={styles.groupManagementCount}>
                  <span>{lang === "zh" ? "已选" : "Selected"}</span>
                  <strong>
                    {groupManageSessionIds.length}/{sessionsQuery.data?.length ?? 0}
                  </strong>
                </div>
                <div className={styles.groupMemberPicker}>
                  {(sessionsQuery.data ?? []).map((session) => {
                    const selected = groupManageSessionSet.has(session.id);
                    const sessionAgent = session.agentId ? agentsById.get(session.agentId) : undefined;
                    const display = sessionAgentDisplayInfo(session, sessionAgent, lang, resolveModelLabel);
                    const sessionAvatarImageUrl = avatarImageUrlFrom(sessionAgent, session);
                    const missingMessage = session.agentMissing
                      ? session.agentStatusMessage || (lang === "zh" ? "缺少有效 Agent" : "Missing valid Agent")
                      : "";
                    return (
                      <label
                        key={session.id}
                        className={
                          selected
                            ? `${styles.groupMemberChip} ${styles.groupMemberChipSelected}`
                            : styles.groupMemberChip
                        }
                      >
                        <input
                          type="checkbox"
                          checked={selected}
                          disabled={activeGroupTeamOwned || groupRoundActive || updateGroupRoomMutation.isPending}
                          onChange={() => handleToggleGroupManageSession(session.id)}
                        />
                        {renderAgentAvatar(
                          styles.agentOptionAvatar,
                          sessionAvatarImageUrl,
                          avatarInitials(session.agentCode, display.name),
                        )}
                        <span className={styles.groupMemberCopy}>
                          <strong>{display.name}</strong>
                          <small className={`${styles.agentRoleTag} ${styles[agentRoleClass(display.tone)]}`}>
                            {display.functionLabel}
                          </small>
                        </span>
                        {missingMessage ? (
                          <span className={styles.agentMissingInline} title={missingMessage}>
                            {lang === "zh" ? "缺少有效 Agent" : "Missing Agent"}
                          </span>
                        ) : null}
                      </label>
                    );
                  })}
                </div>
              </div>
              {activeGroupTeamOwned ? (
                <p className={styles.groupManagementHint}>
                  {lang === "zh"
                    ? "团队关联群聊的成员来自团队组织画布；如需调整成员、角色或同步关系，请打开团队页。"
                    : "Team-owned room members come from the Team canvas. Open Teams to change members, roles, or sync."}
                </p>
              ) : groupRoundActive ? (
                <p className={styles.groupManagementHint}>
                  {lang === "zh" ? "群聊运行中，成员和模式会在本轮结束后允许修改。" : "The group is running. Members and mode can be changed after this round finishes."}
                </p>
              ) : groupManageSessionIds.length < 2 ? (
                <p className={styles.groupManagementHint}>
                  {lang === "zh" ? "群聊至少需要保留 2 位 Agent。" : "A group needs at least 2 agents."}
                </p>
              ) : null}
            </section>
          </section>
        ) : (
          <>
        <section className={styles.leftBlock}>
          <div className={styles.sectionHeader}>
            <div className={styles.sectionIdentity}>
              <p className={styles.blockEyebrow}>{t("currentSession")}</p>
              <h3 className={styles.sectionTitle}>{activeSurfaceTitle}</h3>
            </div>
            <span className={`${styles.sessionStatePill} ${styles[`sessionStatePill_${sessionStateValue}`]}`}>
              {sessionStateLabel}
            </span>
          </div>
          <p className={styles.contextLineCompact}>{sessionStateLine}</p>
          {agentDirectSessionMismatch && agentPrimaryDirectSessionId ? (
            <div className={styles.sessionBindingNotice} role="status">
              <span>{sessionBindingMismatchLine}</span>
              <button
                type="button"
                onClick={() => handleOpenDirectSession(agentPrimaryDirectSessionId)}
                title={`${t("openCurrentDirectSession")} · ${agentPrimaryDirectSessionId}`}
              >
                <ArrowUpRight size={13} />
                <span>{t("openCurrentDirectSession")}</span>
              </button>
            </div>
          ) : null}
          {sessionCompactRows.length > 0 ? (
            <div className={styles.inlineMetaList}>
              {sessionCompactRows.map((row) => (
                <span key={row.label} className={styles.inlineMetaPill} title={row.title ?? row.value}>
                  <span>{row.label}</span>
                  <strong>{row.value}</strong>
                </span>
              ))}
            </div>
          ) : null}
          <details className={styles.sessionDiagnosticsDetails}>
            <summary className={styles.sessionDiagnosticsSummary}>
              <span className={styles.sessionDiagnosticsSummaryText}>
                <ChevronRight size={14} />
                <span>{t("contextDiagnostics")}</span>
              </span>
              <span className={styles.sessionDiagnosticsSnapshot}>
                {contextPercent}% · {cacheHitLine}
              </span>
            </summary>
            <div className={styles.sessionDiagnosticsBody}>
              {activeSkillSummary ? (
                <section
                  className={`${styles.activeSkillStatus} ${activeSkillStatusClass}`}
                  title={activeSkillTitle}
                  aria-label={lang === "zh" ? "当前 active skill 状态" : "Current active skill status"}
                >
                  <div className={styles.activeSkillIdentity}>
                    <span className={styles.activeSkillEyebrow}>
                      {lang === "zh" ? "当前 Skill" : "Active skill"}
                    </span>
                    <strong>{activeSkillName || activeSkillCommand}</strong>
                  </div>
                  <div className={styles.activeSkillMeta}>
                    {activeSkillCommand ? <span>/{activeSkillCommand}</span> : null}
                    <span className={styles.activeSkillState}>{activeSkillStatusLabel}</span>
                    {activeSkillShortHash ? <span>#{activeSkillShortHash}</span> : null}
                  </div>
                </section>
              ) : null}
              <section className={styles.contextCompositionPanel} aria-label={lang === "zh" ? "状态栏上一轮上下文与缓存事实" : "Status bar previous turn context and cache facts"}>
                <div className={styles.contextCompositionItem} title={contextCompositionTitle}>
                  <div className={styles.contextCompositionHeader}>
                    <span>{t("previousContextComposition")}</span>
                    <strong>{contextCompositionSummary}</strong>
                  </div>
                  <div className={styles.contextCompositionBar} aria-hidden="true">
                    {contextCompositionSegments.length ? (
                      contextCompositionSegments.map((segment) => (
                        <span
                          key={`${segment.key}-${segment.source}`}
                          className={`${styles.contextCompositionSegment} ${styles.contextCompositionSegmentExact} ${contextCompositionSegmentClass(segment.key)}`}
                          style={{ width: contextWindowSegmentWidth(segment.tokens ?? 0, contextCompositionLimitTokens) }}
                        />
                      ))
                    ) : (
                      <span className={`${styles.contextCompositionSegment} ${styles.contextCompositionSegmentMissing}`} />
                    )}
                    {contextCompositionRemainingTokens > 0 ? (
                      <span
                        className={`${styles.contextCompositionSegment} ${styles.contextCompositionSegmentExact} ${styles.contextCompositionSegmentUnused}`}
                        style={{ width: contextWindowSegmentWidth(contextCompositionRemainingTokens, contextCompositionLimitTokens) }}
                      />
                    ) : null}
                  </div>
                  {contextCompositionSegments.length ? (
                    <div className={styles.contextCompositionLegend}>
                      {contextCompositionSegments.map((segment) => (
                        <span key={`${segment.key}-${segment.source}-legend`} title={segment.description || segment.source}>
                          <i className={contextCompositionSegmentClass(segment.key)} />
                          {contextCompositionSegmentLabel(segment.key, segment.label, t)}
                          {" "}
                          {numberFormatter.format(segment.tokens ?? 0)}
                        </span>
                      ))}
                    </div>
                  ) : null}
                </div>

                <div className={styles.contextCompositionItem}>
                  <div className={styles.contextCompositionHeader}>
                    <span>{t("previousCacheHit")}</span>
                    <strong>{cacheCompositionSummary}</strong>
                  </div>
                  <div className={styles.cacheDonutPanel}>
                    <button
                      type="button"
                      className={styles.cacheDonutTrigger}
                      onClick={openCacheDetail}
                      disabled={!cacheDetailAvailable}
                      aria-label={cacheDetailOpenLabel}
                      aria-expanded={cacheDetailOpen}
                      aria-controls={cacheDetailOpen ? "cache-detail-dialog" : undefined}
                      title={cacheDetailOpenLabel}
                    >
                    <span className={styles.cacheDonutShell}>
                      <svg
                        className={styles.cacheDonutSvg}
                        viewBox="0 0 100 100"
                        role="img"
                        aria-label={cacheCompositionTitle}
                      >
                        <circle className={`${styles.cacheDonutTrack} ${styles.cacheDonutOuterTrack}`} cx="50" cy="50" r="42" pathLength={100} />
                        {cachePromptDonutSegments.map((segment, index) => (
                          <circle
                            key={`computed-${segment.key}-${segment.status}-${index}`}
                            className={`${styles.cacheDonutSegment} ${styles.cacheDonutOuterSegment} ${cachePromptSegmentClass(segment)}`}
                            cx="50"
                            cy="50"
                            r="42"
                            pathLength={100}
                            style={cacheDonutSegmentStyle(segment, cachePromptDonutSegments.length > 1 ? 0.55 : 0)}
                          />
                        ))}
                        <circle className={`${styles.cacheDonutTrack} ${styles.cacheDonutInnerTrack}`} cx="50" cy="50" r="31" pathLength={100} />
                        {trueCacheDonutSegments.map((segment, index) => (
                          <circle
                            key={`true-${segment.key}-${segment.status}-${index}`}
                            className={`${styles.cacheDonutSegment} ${styles.cacheDonutInnerSegment} ${cacheDonutSegmentClass(segment.status || segment.key)}`}
                            cx="50"
                            cy="50"
                            r="31"
                            pathLength={100}
                            style={cacheDonutSegmentStyle(segment, trueCacheDonutSegments.length > 1 ? 0.4 : 0)}
                          />
                        ))}
                      </svg>
                      <div className={styles.cacheDonutCenter} title={cacheDetailOpenLabel}>
                        <strong>{cacheCompositionPercent}%</strong>
                        <span>{cacheCompositionComputedLabel} {computedCacheCompositionPercent}%</span>
                        <small>{cacheCompositionAverageLabel} {cacheCompositionAverageValue}</small>
                      </div>
                    </span>
                    </button>
                    <div className={styles.cacheDonutStats}>
                      <span title={cacheDetailOpenLabel}>
                        <b>{lang === "zh" ? "真实" : "true"}</b>
                        {numberFormatter.format(providerCachedInputTokens)} / {numberFormatter.format(providerCacheInputTokens)}
                      </span>
                      <span title={cacheDetailOpenLabel}>
                        <b>{lang === "zh" ? "计算" : "calc"}</b>
                        {numberFormatter.format(lastCacheComposition?.computedCachedInputTokens ?? 0)} / {numberFormatter.format(computedCacheCompositionTotalTokens)}
                      </span>
                      <span title={cacheDetailOpenLabel}>
                        <b>{lang === "zh" ? "总均" : "avg"}</b>
                        {cacheCompositionAverageValue}
                        {averageCacheObservedTurnCount > 0 ? ` · ${numberFormatter.format(averageCacheObservedTurnCount)}` : ""}
                      </span>
                    </div>
                  </div>
                  {cachePromptDonutSegments.length ? (
                    <div className={styles.contextCompositionLegend}>
                      {cachePromptDonutSegments.map((segment, index) => (
                        <span
                          key={`${segment.key}-${segment.status}-${index}-legend`}
                          title={cacheDonutSegmentTitle(segment, cachePromptCompositionTotalTokens, numberFormatter, lang)}
                        >
                          <i className={cachePromptLegendSegmentClass(segment)} />
                          {segment.key === "computed_missing" ? cacheCompositionSegmentLabel("missing", segment.label, t) : segment.label}
                          {" "}
                          {segment.key === "computed_missing" ? "" : numberFormatter.format(segment.tokens ?? 0)}
                          {segment.contentPreview ? (
                            <em className={styles.cacheDonutLegendPreview}>
                              {segment.contentPreview}
                            </em>
                          ) : null}
                        </span>
                      ))}
                    </div>
                  ) : null}
                </div>
              </section>

              <section className={`${styles.resourceBlock} ${styles.sessionResourceDiagnostics}`}>
                <div className={styles.sectionHeader}>
                  <p className={styles.blockEyebrow}>{t("sessionContextEstimate")}</p>
                  <span className={styles.metricValue}>{contextPercent}%</span>
                </div>
                <div className={styles.resourceSplit}>
                  <div className={styles.resourceMetric}>
                    <span>{contextSourceLine}</span>
                    <strong title={contextStatusLine}>{contextStatusLine}</strong>
                  </div>
                  <div className={styles.resourceMetric}>
                    <span>{t("contextCompression")}</span>
                    <strong title={compressionTitleLine}>{compressionCurrentLine}</strong>
                  </div>
                </div>
                <div className={styles.compressionFactGrid} title={compressionTitleLine}>
                  <div className={styles.compressionFact}>
                    <span>{t("runtimeContextEstimate")}</span>
                    <strong>{compressionMainLine}</strong>
                  </div>
                  <div className={styles.compressionFact}>
                    <span>{t("compressionModelWindow")}</span>
                    <strong>{compressionModelWindowLine}</strong>
                  </div>
                  <div className={`${styles.compressionFact} ${styles.compressionFactWide}`}>
                    <span>{t("compressionThresholdBasis")}</span>
                    <strong>{compressionScopeLine}</strong>
                  </div>
                </div>
                <p className={styles.oneLineValue} title={lastCompression?.reason || lastCompressionLine}>
                  <span>{t("compressionLastRun")}</span>
                  {lastCompressionLine}
                </p>
                <details className={styles.compactDetails}>
                  <summary>
                    <ChevronRight size={14} />
                    <span className={styles.compactDetailsClosedLabel}>{t("compressionStrategy")}</span>
                    <span className={styles.compactDetailsOpenLabel}>{t("collapseSection")}</span>
                  </summary>
                  <div className={styles.compressionStrategyList}>
                    {(compression?.strategy.levels ?? []).map((level) => (
                      <div key={level.level} className={styles.compressionStrategyRow}>
                        <strong>{level.level}</strong>
                        <span>{t("compressionThreshold")} {Math.round(level.thresholdRatio * 100)}% / {numberFormatter.format(level.thresholdTokens)}</span>
                        <span>{t("compressionKeepAi")} {level.keepAiMessages}</span>
                        <span>{t("compressionSummary")} {numberFormatter.format(level.summaryMaxChars)}</span>
                      </div>
                    ))}
                  </div>
                  <p className={styles.detailNote}>
                    <span>{t("compressionErrorProtection")}</span>
                    {(compression?.strategy.errorProtectionKeywords ?? []).join(" / ") || "--"}
                  </p>
                </details>
              </section>
            </div>
          </details>
        </section>

        <section className={`${styles.leftBlock} ${styles.featurePresetBlock}`}>
          <div className={styles.sectionHeader}>
            <div className={styles.sectionIdentity}>
              <p className={styles.blockEyebrow}>{t("chatFeaturePanel")}</p>
              <h3 className={styles.sectionTitle}>{t("chatFeaturePanelTitle")}</h3>
            </div>
            <span className={styles.featurePresetScope}>{t("chatFeaturePanelScope")}</span>
          </div>
          <div className={styles.featurePrimarySlot}>
            <button
              type="button"
              className={
                mentalModelEnabledForNextTurn
                  ? `${styles.featureToggle} ${styles.featureToggleActive} ${styles.featureTogglePrimary}`
                  : `${styles.featureToggle} ${styles.featureTogglePrimary}`
              }
              aria-pressed={mentalModelEnabledForNextTurn}
              disabled={!activeSessionId}
              onClick={() => handleMentalModelEnabledChange(!mentalModelEnabledForNextTurn)}
            >
              <span className={styles.featureToggleText}>
                <strong>{t("chatFeatureMentalModel")}</strong>
                <span>{t("mentalModelForNextTurn")}</span>
              </span>
              <span className={styles.featureToggleState}>
                {mentalModelEnabledForNextTurn ? t("mentalModelNextTurnOn") : t("mentalModelNextTurnOff")}
              </span>
            </button>
          </div>
          <div className={styles.featureChipRow}>
            {CHAT_FEATURE_PRESETS.map((item) => {
              const enabled = featurePresetState[item.key];
              return (
                <button
                  key={item.key}
                  type="button"
                  className={enabled ? `${styles.featureChip} ${styles.featureChipActive}` : styles.featureChip}
                  aria-pressed={enabled}
                  onClick={() => toggleFeaturePreset(item.key)}
                  title={t(item.hintKey)}
                >
                  <strong>{t(item.labelKey)}</strong>
                  <span aria-hidden="true" />
                </button>
              );
            })}
          </div>
          <p className={styles.featurePresetNote}>{t("chatFeaturePanelHint")}</p>
        </section>

        <section className={`${styles.leftBlock} ${styles.companionBlock}`}>
          <div className={styles.sectionHeader}>
            <div className={styles.sectionIdentity}>
              <p className={styles.blockEyebrow}>{t("mentalState")} / {t("petSpace")}</p>
              <p className={styles.sectionMetaLine}>{mentalCompactLine || mentalSourceLabel}</p>
            </div>
            <span className={`${styles.mentalStateBadge} ${styles[`mentalStateBadge_${mentalCognitiveStateValue}`]}`}>
              {mentalStateLabel}
            </span>
          </div>
          <p className={styles.contextLineCompact}>{mentalSummary}</p>
          <div className={styles.companionCompact}>
            <div className={styles.petMiniAvatar} aria-hidden="true">
              <div className={`${styles.petShowcaseAvatar} ${petAvatarSkinClass}`}>
                <span className={styles.petShowcaseEarLeft} />
                <span className={styles.petShowcaseEarRight} />
                <span className={styles.petShowcaseFace}>
                  <span className={styles.petShowcaseEye} />
                  <span className={styles.petShowcaseMuzzle} />
                  <span className={styles.petShowcaseEye} />
                </span>
                <span className={styles.petShowcaseSymbol}>{petAvatarSymbol}</span>
                <span className={styles.petShowcaseFootLeft} />
                <span className={styles.petShowcaseFootRight} />
              </div>
            </div>
            <div className={styles.companionCopy}>
              <div className={styles.companionTopLine}>
                <strong>{pet?.name ?? t("loadingPetState")}</strong>
                <span>{t("level")} {pet?.level ?? 0} · {petPresetLabel}</span>
              </div>
              <p title={petCompactLine}>{petCompactLine}</p>
            </div>
          </div>
          <details className={styles.compactDetails}>
            <summary>
              <ChevronRight size={14} />
              <span className={styles.compactDetailsClosedLabel}>{t("expandSection")}</span>
              <span className={styles.compactDetailsOpenLabel}>{t("collapseSection")}</span>
            </summary>
            <p className={styles.oneLineValue} title={mentalWhisper}>
              <span>{t("mentalWhisper")}</span>
              {mentalWhisper}
            </p>
            <div className={styles.inlineStatGrid}>
              <div className={styles.inlineStat}>
                <span>{t("state")}</span>
                <strong>{mentalCognitiveStateLabel}</strong>
              </div>
              <div className={styles.inlineStat}>
                <span>{t("mentalConfidence")}</span>
                <strong>{mentalConfidence}</strong>
              </div>
              <div className={styles.inlineStat}>
                <span>{t("mentalSource")}</span>
                <strong>{mentalSourceLabel}</strong>
              </div>
              <div className={styles.inlineStat}>
                <span>{t("mentalLastUpdated")}</span>
                <strong title={formatTime(mental?.updatedAt ?? "")}>{mentalRelativeTime}</strong>
              </div>
            </div>
            <div className={styles.inlineMetaList}>
              <span className={styles.inlineMetaPill}>
                <span>{t("dailyTokens")}</span>
                <strong>{numberFormatter.format(pet?.dailyTokens ?? 0)}</strong>
              </span>
              {petVitals.map((vital) => (
                <span key={vital.key} className={styles.inlineMetaPill}>
                  <span>{vital.label}</span>
                  <strong>{vital.value}</strong>
                </span>
              ))}
            </div>
            <div className={styles.petShowcaseActions} aria-label={petInteractionLabels.group}>
              <button
                type="button"
                className={styles.petShowcaseAction}
                onClick={() => handlePetInteraction("feed")}
                disabled={petActionMutation.isPending}
                title={petInteractionLabels.feedTitle}
              >
                <Apple size={14} />
                <span>{petInteractionLabels.feed}</span>
              </button>
              <button
                type="button"
                className={styles.petShowcaseAction}
                onClick={() => handlePetInteraction("talk")}
                disabled={petActionMutation.isPending}
                title={petInteractionLabels.talkTitle}
              >
                <MessageCircleHeart size={14} />
                <span>{petInteractionLabels.talk}</span>
              </button>
              <button
                type="button"
                className={styles.petShowcaseAction}
                onClick={() => handlePetInteraction("care")}
                disabled={petActionMutation.isPending}
                title={petInteractionLabels.careTitle}
              >
                <HeartHandshake size={14} />
                <span>{petInteractionLabels.care}</span>
              </button>
              <span className={styles.petShowcaseActionHint}>
                <Sparkles size={13} />
                <span>{petInteractionLabels.pending}</span>
              </span>
            </div>
            {petActionFeedback ? <p className={styles.petShowcaseFeedback}>{petActionFeedback}</p> : null}
          </details>
        </section>
          </>
        )}
      </aside>

      <PaneCollapseHandle
        side="left"
        collapsed={leftRailCollapsed}
        separatorLabel={t("resizeLeftPanel")}
        collapseLabel={lang === "zh" ? "收起左栏" : "Collapse left pane"}
        expandLabel={lang === "zh" ? "展开左栏" : "Expand left pane"}
        className={styles.resizeHandle}
        active={dragState?.side === "left"}
        activeClassName={styles.resizeHandleActive}
        onToggle={() => setLeftRailCollapsed((current) => !current)}
        onPointerDown={(event) => handleResizeStart("left", event)}
        onKeyDown={(event) => handleResizeKeyDown("left", event)}
      />

      <section className={styles.centerPane}>
        <div className={styles.tabStrip}>
          {groupPanelActive ? (
            <button
              type="button"
              className={`${styles.tab} ${styles.tabActive}`}
              onClick={() => undefined}
            >
              {projectBusActive ? (lang === "zh" ? "通知流" : "Notice stream") : (lang === "zh" ? "群聊" : "Group")}
            </button>
          ) : agentSessionTabs.length > 0 || cliAgentRunTabs.length > 0 ? (
            <AgentSessionTabStrip
              activeSessionId={activeSessionId}
              activeCliAgentRunId={activeCliAgentRunId}
              agentsById={agentsById}
              buildSessionReferencePayload={buildSessionReferencePayload}
              cliAgentRuns={cliAgentRunTabs}
              editingSessionId={editingSessionId}
              editingSessionTitle={editingSessionTitle}
              lang={lang}
              renamePending={renameSessionMutation.isPending}
              renameSessionId={renameSessionMutation.variables?.sessionId ?? ""}
              resolveModelLabel={resolveModelLabel}
              sessions={agentSessionTabs}
              statusLabel={statusLabel}
              t={t}
              workspaceActiveTab={workspace.activeTab}
              onCancelRename={cancelRenameSession}
              onContextMenu={openSessionContextMenu}
              onDragReference={startSessionReferenceDrag}
              onOpenCliAgentRun={(runId) => {
                if (activeSessionId) {
                  setActiveTab(activeSessionId, cliAgentRunTabId(runId));
                }
              }}
              onCloseCliAgentRun={(runId) => {
                const run = cliAgentRunTabs.find((item) => item.id === runId);
                if (run) {
                  void closeCliAgentRun(run);
                }
              }}
              onOpenDirectSession={handleOpenDirectSession}
              onRenameTitleChange={setEditingSessionTitle}
              onSetActiveTab={setActiveTab}
              onSubmitRename={submitRenameSession}
            />
          ) : (
            <button
              type="button"
              className={workspace.activeTab === "agent" ? `${styles.tab} ${styles.tabActive}` : styles.tab}
              onClick={() => {
                activeSessionId && setActiveTab(activeSessionId, "agent");
              }}
            >
              {t("agentSession")}
            </button>
          )}
          {!groupPanelActive && workspace.openTabs.map((tabPath) => (
            <div
              key={tabPath}
              className={
                workspace.activeTab === tabPath
                  ? `${styles.fileTab} ${styles.fileTabActive}`
                  : styles.fileTab
              }
            >
              <button
                type="button"
                className={styles.fileTabButton}
                onClick={() => {
                  activeSessionId && setActiveTab(activeSessionId, tabPath);
                }}
              >
                {tabPath.split("/").at(-1)}
              </button>
              <button
                type="button"
                className={styles.fileTabClose}
                onClick={() => activeSessionId && closePreviewTab(activeSessionId, tabPath)}
                title={t("closePreviewTab")}
                aria-label={`${t("closePreviewTab")} ${tabPath.split("/").at(-1)}`}
              >
                <X size={14} />
              </button>
            </div>
          ))}
        </div>

        <div className={styles.centerSurface}>
          {mountedCliAgentRuns.map((run) => (
            <CliAgentRunTerminalPanel
              key={run.id}
              run={run}
              sourceSessionId={activeSessionId || ""}
              active={!groupPanelActive && activeCliAgentRunId === run.id}
              lang={lang}
              onTerminalSessionChange={handleCliAgentTerminalSessionChange}
            />
          ))}
          {projectBusActive ? (
            <div className={styles.groupConversationFrame}>
              <header className={styles.groupConversationHeader}>
                <div>
                  <p>
                    {activeGroupRoom?.mode ?? "round_robin"}
                    {" · "}
                    {activeGroupRoom?.purpose ?? "discussion"}
                  </p>
                  <h2>{lang === "zh" ? "助手通知流" : "Agent notice stream"}</h2>
                  <span>
                    {projectBusTimeline?.activeAgentCount ?? availableGroupParticipantCount} {lang === "zh" ? "位 active Agent" : "active agents"}
                    {" · "}
                    {lang === "zh" ? "全局广播与投递观察" : "broadcasts and delivery observation"}
                  </span>
                </div>
                <button
                  type="button"
                  className={styles.groupRefreshButton}
                  onClick={() => void projectAgentBusQuery.refetch()}
                  disabled={projectAgentBusQuery.isFetching}
                >
                  {lang === "zh" ? "刷新" : "Refresh"}
                </button>
              </header>
              {projectAgentBusQuery.isError ? (
                <div className={styles.inlineNotice}>
                  {describeError(projectAgentBusQuery.error, t("loadFailed"))}
                </div>
              ) : null}
              {groupRoomActionError ? (
                <div className={styles.inlineNotice}>{groupRoomActionError}</div>
              ) : null}
              <div className={styles.groupMessageTimeline} aria-live={sendProjectBusMessageMutation.isPending ? "polite" : undefined}>
                {projectBusEvents.length ? (
                  projectBusEvents.map((event) => {
                    const revoked = isProjectAgentBusEventRevoked(event);
                    const targetLabel = event.targetScope === "all"
                      ? (lang === "zh" ? "全体成员" : "All agents")
                      : event.targetAgentNames.length
                        ? event.targetAgentNames.join(", ")
                        : (lang === "zh" ? "仅观察" : "Observe only");
                    const deliveryLabel = event.deliveries.length
                      ? `${event.deliveries.length} ${lang === "zh" ? "次投递" : "deliveries"}`
                      : (lang === "zh" ? "未投递" : "no delivery");
                    const interruptionLabel = event.interruptions.length
                      ? `${event.interruptions.filter((item) => item.status === "interrupted").length}/${event.interruptions.length} ${lang === "zh" ? "已打断" : "interrupted"}`
                      : "";
                    return (
                      <article key={event.eventId} className={revoked ? `${styles.projectBusEvent} ${styles.projectBusEventRevoked}` : styles.projectBusEvent}>
                        <header className={styles.projectBusEventHeader}>
                          <div>
                            <strong>{event.createdBy === "user" ? runtime?.userName || (lang === "zh" ? "我" : "Me") : event.createdBy}</strong>
                            <span>{targetLabel}</span>
                          </div>
                          <div className={styles.projectBusEventActions}>
                            <time>{formatTime(event.createdAt)}</time>
                            {event.createdBy === "user" && !revoked ? (
                              <button
                                type="button"
                                onClick={() => handleRevokeProjectBusMessage(event.eventId)}
                                disabled={revokeProjectBusMessageMutation.isPending}
                              >
                                {lang === "zh" ? "撤回" : "Recall"}
                              </button>
                            ) : null}
                          </div>
                        </header>
                        <p className={styles.projectBusEventBody}>
                          {revoked
                            ? (lang === "zh" ? "这条消息已撤回，相关 Agent 已请求停止。" : "This message was recalled. Target agents were asked to stop.")
                            : renderMentionedText(event.content)}
                        </p>
                        <div className={styles.projectBusEventMeta}>
                          <span>{revoked ? (lang === "zh" ? "已撤回" : "revoked") : event.messageType}</span>
                          <span>{deliveryLabel}</span>
                          {interruptionLabel ? <span>{interruptionLabel}</span> : null}
                          {event.unresolvedMentions.length ? (
                            <span>{lang === "zh" ? "未识别" : "unresolved"} @{event.unresolvedMentions.join(", @")}</span>
                          ) : null}
                        </div>
                      </article>
                    );
                  })
                ) : (activeGroupRoom?.rounds ?? []).length ? (
                  (activeGroupRoom?.rounds ?? []).map((round, roundIndex) => {
                    const roundRunning = String(round.status ?? "").trim().toLowerCase() === "running";
                    const deliveredParticipantIds = new Set(
                      (round.messages ?? []).map((message) => String(message.participantId ?? "").trim()),
                    );
                    const nextSpeakerId = (round.speakerOrder ?? []).find(
                      (participantId) => !deliveredParticipantIds.has(String(participantId ?? "").trim()),
                    );
                    const nextParticipant = nextSpeakerId ? activeGroupParticipantById.get(nextSpeakerId) : undefined;
                    return (
                    <section key={round.roundId} className={styles.groupRoundBlock}>
                      <div className={styles.groupRoundDivider}>
                        <span>
                          {lang === "zh" ? `第 ${roundIndex + 1} 轮` : `Round ${roundIndex + 1}`}
                          {" · "}
                          {round.mode}
                          {" · "}
                          {round.purpose ?? activeGroupRoom?.purpose ?? "discussion"}
                          {" · "}
                          {statusLabel(round.status)}
                        </span>
                        <time>{formatTime(round.updatedAt || round.startedAt)}</time>
                      </div>
                      <article className={styles.groupTopicMessage}>
                        <div className={styles.groupTopicBubble}>
                          <span>{runtime?.userName || (lang === "zh" ? "我" : "Me")}</span>
                          <p>{renderMentionedText(round.topic)}</p>
                        </div>
                      </article>
                      <div className={styles.groupMessageList}>
                        {(round.messages ?? []).map((message: ChatRoomMessage) => {
                          const speakerParticipant = activeGroupParticipantById.get(String(message.participantId ?? "").trim());
                          const speakerIdentity = groupParticipantIdentity(speakerParticipant, {
                            agentId: message.agentId,
                            agentCode: message.speakerCode,
                            title: message.speakerTitle,
                            participantId: message.participantId,
                          });
                          return (
                          <article
                            key={message.messageId}
                            className={
                              message.status === "failed"
                                ? `${styles.groupBubbleRow} ${styles.groupBubbleRowFailed}`
                                : styles.groupBubbleRow
                            }
                          >
                            {renderAgentAvatar(
                              styles.groupBubbleAvatar,
                              speakerIdentity.avatarImageUrl,
                              avatarInitials(message.speakerCode, speakerIdentity.name, "AI"),
                            )}
                            <div className={styles.groupBubble}>
                              <header className={styles.groupBubbleHeader}>
                                <strong title={speakerIdentity.fullIdentityLabel}>{speakerIdentity.identityLabel}</strong>
                                {message.status !== "completed" ? <span>{statusLabel(message.status)}</span> : null}
                              </header>
                              {renderGroupMessageBody(message, speakerIdentity.name)}
                              <time className={styles.groupBubbleMeta}>{formatTime(message.timestamp || round.updatedAt)}</time>
                            </div>
                          </article>
                          );
                        })}
                        {roundRunning && nextParticipant ? (
                          <article className={`${styles.groupBubbleRow} ${styles.groupBubbleRowPending}`}>
                            {(() => {
                              const nextIdentity = groupParticipantIdentity(nextParticipant);
                              return (
                              <>
                            {renderAgentAvatar(
                              styles.groupBubbleAvatar,
                              nextIdentity.avatarImageUrl,
                              avatarInitials(nextParticipant.agentCode, nextIdentity.name, "AI"),
                            )}
                            <div className={styles.groupBubble}>
                              <header className={styles.groupBubbleHeader}>
                                <strong title={nextIdentity.fullIdentityLabel}>{nextIdentity.identityLabel}</strong>
                                <span>{lang === "zh" ? "正在输入" : "typing"}</span>
                              </header>
                              <div className={styles.groupTypingDots} aria-label={lang === "zh" ? "正在输入" : "Typing"}>
                                <span />
                                <span />
                                <span />
                              </div>
                            </div>
                              </>
                              );
                            })()}
                          </article>
                        ) : null}
                      </div>
                      {round.summary && !roundRunning ? <p className={styles.groupRoundSummary}>{round.summary}</p> : null}
                    </section>
                    );
                  })
                ) : (
                  <div className={styles.groupEmptyState}>
                    <BellRing size={28} />
                    <p>{lang === "zh" ? "助手通知流会显示用户引导、助手私信和广播投递结果；它不是团队群聊。" : "The Agent notice stream shows guidance, private messages, broadcasts, and delivery results. It is not a team room."}</p>
                  </div>
                )}
              </div>
              <div className={styles.groupComposerBar}>
                <input
                  value={projectBusDraft}
                  onChange={(event) => setProjectBusDraft(event.target.value)}
                  disabled={sendProjectBusMessageMutation.isPending}
                  placeholder={lang === "zh" ? "输入广播；不带 @ 默认投递全体，可用 @AgentCode 指定" : "Write a broadcast; no @ sends to all, @AgentCode targets one"}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && !event.shiftKey) {
                      event.preventDefault();
                      handleSendProjectBusMessage();
                    }
                  }}
                />
                <label className={styles.projectBusInterruptToggle}>
                  <input
                    type="checkbox"
                    checked={projectBusInterruptTargets}
                    onChange={(event) => setProjectBusInterruptTargets(event.target.checked)}
                  />
                  <span>{lang === "zh" ? "打断目标助手" : "Interrupt targets"}</span>
                </label>
                <button
                  type="button"
                  onClick={handleSendProjectBusMessage}
                  disabled={
                    !projectBusDraft.trim()
                    || sendProjectBusMessageMutation.isPending
                  }
                >
                  <UsersRound size={15} />
                  <span>
                    {sendProjectBusMessageMutation.isPending
                      ? (lang === "zh" ? "发送中" : "Sending")
                      : (lang === "zh" ? "发送广播" : "Send")}
                  </span>
                </button>
              </div>
            </div>
          ) : legacyGroupRoomActive ? (
            <div className={styles.groupConversationFrame}>
              <header className={styles.groupConversationHeader}>
                <div>
                  <p>
                    {activeGroupRoom?.mode ?? "round_robin"}
                    {" · "}
                    {activeGroupRoom?.purpose ?? "discussion"}
                  </p>
                  <h2>{activeGroupRoom?.title ?? (lang === "zh" ? "群聊加载中" : "Loading group")}</h2>
                  <span>
                    {availableGroupParticipantCount} {lang === "zh" ? "位可用助手" : "available agents"}
                    {" · "}
                    {statusLabel(activeGroupRoom?.status ?? "ready")}
                  </span>
                </div>
                <button
                  type="button"
                  className={styles.groupRefreshButton}
                  onClick={() => activeGroupRoomId && void activeGroupRoomQuery.refetch()}
                  disabled={activeGroupRoomQuery.isFetching}
                >
                  {lang === "zh" ? "刷新" : "Refresh"}
                </button>
              </header>
              {activeGroupRoomQuery.isError ? (
                <div className={styles.inlineNotice}>
                  {describeError(activeGroupRoomQuery.error, t("loadFailed"))}
                </div>
              ) : null}
              <div className={styles.groupMessageTimeline} aria-live={groupRoundActive ? "polite" : undefined}>
                {(activeGroupRoom?.rounds ?? []).length ? (
                  (activeGroupRoom?.rounds ?? []).map((round, roundIndex) => {
                    const roundRunning = String(round.status ?? "").trim().toLowerCase() === "running";
                    const deliveredParticipantIds = new Set(
                      (round.messages ?? []).map((message) => String(message.participantId ?? "").trim()),
                    );
                    const nextSpeakerId = (round.speakerOrder ?? []).find(
                      (participantId) => !deliveredParticipantIds.has(String(participantId ?? "").trim()),
                    );
                    const nextParticipant = nextSpeakerId ? activeGroupParticipantById.get(nextSpeakerId) : undefined;
                    return (
                    <section key={round.roundId} className={styles.groupRoundBlock}>
                      <div className={styles.groupRoundDivider}>
                        <span>
                          {lang === "zh" ? `第 ${roundIndex + 1} 轮` : `Round ${roundIndex + 1}`}
                          {" · "}
                          {round.mode}
                          {" · "}
                          {round.purpose ?? activeGroupRoom?.purpose ?? "discussion"}
                          {" · "}
                          {statusLabel(round.status)}
                        </span>
                        <time>{formatTime(round.updatedAt || round.startedAt)}</time>
                      </div>
                      <article className={styles.groupTopicMessage}>
                        <div className={styles.groupTopicBubble}>
                          <span>{runtime?.userName || (lang === "zh" ? "我" : "Me")}</span>
                          <p>{renderMentionedText(round.topic)}</p>
                        </div>
                      </article>
                      <div className={styles.groupMessageList}>
                        {(round.messages ?? []).map((message: ChatRoomMessage) => {
                          const speakerParticipant = activeGroupParticipantById.get(String(message.participantId ?? "").trim());
                          const speakerIdentity = groupParticipantIdentity(speakerParticipant, {
                            agentId: message.agentId,
                            agentCode: message.speakerCode,
                            title: message.speakerTitle,
                            participantId: message.participantId,
                          });
                          return (
                          <article
                            key={message.messageId}
                            className={
                              message.status === "failed"
                                ? `${styles.groupBubbleRow} ${styles.groupBubbleRowFailed}`
                                : styles.groupBubbleRow
                            }
                          >
                            {renderAgentAvatar(
                              styles.groupBubbleAvatar,
                              speakerIdentity.avatarImageUrl,
                              avatarInitials(message.speakerCode, speakerIdentity.name, "AI"),
                            )}
                            <div className={styles.groupBubble}>
                              <header className={styles.groupBubbleHeader}>
                                <strong title={speakerIdentity.fullIdentityLabel}>{speakerIdentity.identityLabel}</strong>
                                {message.status !== "completed" ? <span>{statusLabel(message.status)}</span> : null}
                              </header>
                              {renderGroupMessageBody(message, speakerIdentity.name)}
                              <time className={styles.groupBubbleMeta}>{formatTime(message.timestamp || round.updatedAt)}</time>
                            </div>
                          </article>
                          );
                        })}
                        {roundRunning && nextParticipant ? (
                          <article className={`${styles.groupBubbleRow} ${styles.groupBubbleRowPending}`}>
                            {(() => {
                              const nextIdentity = groupParticipantIdentity(nextParticipant);
                              return (
                              <>
                            {renderAgentAvatar(
                              styles.groupBubbleAvatar,
                              nextIdentity.avatarImageUrl,
                              avatarInitials(nextParticipant.agentCode, nextIdentity.name, "AI"),
                            )}
                            <div className={styles.groupBubble}>
                              <header className={styles.groupBubbleHeader}>
                                <strong title={nextIdentity.fullIdentityLabel}>{nextIdentity.identityLabel}</strong>
                                <span>{lang === "zh" ? "正在输入" : "typing"}</span>
                              </header>
                              <div className={styles.groupTypingDots} aria-label={lang === "zh" ? "正在输入" : "Typing"}>
                                <span />
                                <span />
                                <span />
                              </div>
                            </div>
                              </>
                              );
                            })()}
                          </article>
                        ) : null}
                      </div>
                      {round.summary && !roundRunning ? <p className={styles.groupRoundSummary}>{round.summary}</p> : null}
                    </section>
                    );
                  })
                ) : (
                  <div className={styles.groupEmptyState}>
                    <UsersRound size={28} />
                    <p>{lang === "zh" ? "群聊已创建，输入议题后开始第一轮讨论。" : "The group is ready. Enter a topic to start the first round."}</p>
                  </div>
                )}
              </div>
              <div className={styles.groupComposerBar}>
                <input
                  value={groupTopicDraft}
                  onChange={(event) => setGroupTopicDraft(event.target.value)}
                  disabled={startGroupRoundMutation.isPending}
                  placeholder={lang === "zh" ? "输入下一轮群聊议题" : "Topic for the next group round"}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && !event.shiftKey) {
                      event.preventDefault();
                      handleStartGroupRound();
                    }
                  }}
                />
                <button
                  type="button"
                  onClick={handleStartGroupRound}
                  disabled={
                    !groupTopicDraft.trim()
                    || startGroupRoundMutation.isPending
                    || groupRoundActive
                    || !activeGroupRoom
                  }
                >
                  <UsersRound size={15} />
                  <span>
                    {startGroupRoundMutation.isPending || groupRoundActive
                      ? (groupRoundStopping ? (lang === "zh" ? "停止中" : "Stopping") : (lang === "zh" ? "讨论中" : "Running"))
                      : (lang === "zh" ? "启动一轮" : "Run round")}
                  </span>
                </button>
                {groupRoundActive ? (
                  <button
                    type="button"
                    className={styles.groupStopButton}
                    onClick={handleStopGroupRound}
                    disabled={groupStopDisabled}
                    title={lang === "zh" ? "停止当前群聊轮次" : "Stop current group round"}
                  >
                    <Square size={15} />
                    <span>
                      {stopGroupRoundMutation.isPending
                        ? (lang === "zh" ? "停止中" : "Stopping")
                        : (lang === "zh" ? "停止" : "Stop")}
                    </span>
                  </button>
                ) : null}
              </div>
            </div>
          ) : !activeSessionId && !sessionsQuery.isPending ? (
            <div className={styles.emptySurface}>{t("noSessionsYet")}</div>
          ) : sessionDetailErrorState.blockingError ? (
            <div className={styles.emptySurface}>
              {sessionDetailErrorMessage}
            </div>
          ) : invalidChildSessionLinkMessage ? (
            <div className={styles.emptySurface}>
              {invalidChildSessionLinkMessage}
            </div>
          ) : workspace.activeTab === "agent" ? (
            detail ? (
              <div className={styles.conversationFrame}>
                {sessionDetailErrorState.transientError ? (
                  <div className={styles.inlineNotice} role="status">
                    {sessionDetailErrorMessage}
                  </div>
                ) : null}
                {activeRuntimeNotices.length > 0 ? (
                  <div className={styles.runtimeNoticeStack} role="status" aria-live="polite">
                    {activeRuntimeNotices.map((notice) => (
                      <div
                        key={notice.id || `${notice.kind}-${notice.timestamp}-${notice.message}`}
                        className={[
                          styles.runtimeNotice,
                          styles[`runtimeNotice_${notice.level || "info"}`],
                        ].filter(Boolean).join(" ")}
                      >
                        <CircleDot size={13} />
                        <div className={styles.runtimeNoticeBody}>
                          <span className={styles.runtimeNoticeLabel}>
                            {lang === "zh" ? "运行状态" : "Runtime"}
                            {notice.source ? ` · ${notice.source}` : ""}
                          </span>
                          <span className={styles.runtimeNoticeMessage}>{notice.message}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : null}
                {pendingToolApproval ? (
                  <div className={styles.toolApprovalOverlay} role="presentation">
                    <section
                      className={styles.toolApprovalDialog}
                      role="dialog"
                      aria-modal="true"
                      aria-label={lang === "zh" ? "工具权限审批" : "Tool permission approval"}
                    >
                      <div className={styles.toolApprovalIcon}>
                        <ShieldAlert size={18} />
                      </div>
                      <div className={styles.toolApprovalBody}>
                        <div className={styles.toolApprovalHeader}>
                          <strong>{lang === "zh" ? "工具权限审批" : "Tool permission approval"}</strong>
                          <span>{pendingToolApprovalRisk}</span>
                        </div>
                        <p>
                          {lang === "zh"
                            ? `当前助手请求启用${pendingToolApprovalLabels.length > 1 ? "这些能力" : "此能力"}，批准后仅在${pendingToolApprovalScope}生效。`
                            : `The current agent requests tool access. Approval applies to ${pendingToolApprovalScope}.`}
                        </p>
                        <div className={styles.toolApprovalToolList} title={pendingToolApprovalRawTitle}>
                          {pendingToolApprovalLabels.length
                            ? pendingToolApprovalLabels.slice(0, 4).map((item) => (
                              <span key={item.id}>{item.label}</span>
                            ))
                            : <span>{lang === "zh" ? "工具策略变更" : "Tool policy change"}</span>}
                          {pendingToolApprovalLabels.length > 4 ? (
                            <span>{lang === "zh" ? `另 ${pendingToolApprovalLabels.length - 4} 项` : `+${pendingToolApprovalLabels.length - 4}`}</span>
                          ) : null}
                        </div>
                      </div>
                      <div className={styles.toolApprovalActions}>
                        <button
                          type="button"
                          onClick={() => resolveToolApprovalMutation.mutate({ request: pendingToolApproval, decision: "reject" })}
                          disabled={pendingToolApprovalPending}
                        >
                          <X size={15} />
                          <span>{lang === "zh" ? "拒绝" : "Reject"}</span>
                        </button>
                        <button
                          type="button"
                          className={styles.toolApprovalAllow}
                          onClick={() => resolveToolApprovalMutation.mutate({ request: pendingToolApproval, decision: "approve" })}
                          disabled={pendingToolApprovalPending}
                        >
                          <ShieldCheck size={15} />
                          <span>{pendingToolApprovalPending ? (lang === "zh" ? "处理中" : "Resolving") : (lang === "zh" ? "允许" : "Allow")}</span>
                        </button>
                      </div>
                    </section>
                  </div>
                ) : null}
                <LazyConversationView
                  sessionId={activeSessionId ?? detail.id}
                  title={detail.title}
                  phase={detail.currentPhase}
                  messages={detail.messages}
                  assistantDisplayName={activeAgentDisplayName}
                  assistantAvatarImageUrl={activeAgentAvatarImageUrl}
                  assistantAvatarFallback={activeAgentAvatarFallback}
                  resolveTurnAvatar={resolveConversationTurnAvatar}
                  userDisplayName={runtime?.userName}
                  userAvatarPreset={runtime?.userProfile?.avatarPreset}
                  userAvatarImageUrl={runtime?.userProfile?.avatarImageUrl}
                  taskSummary={currentTaskSummary}
                  defaultFileContext={detail.defaultFileContext}
                  showHeader={false}
                  showSessionOverview={false}
                  showMentalSnapshots={mentalModelEnabledForNextTurn}
                  composerValue={activeDraftEffective}
                  composerPlaceholder={composerPlaceholder}
                  composerDisabled={composerDisabled}
                  composerActionDisabled={composerActionDisabled}
                  composerActionMode={composerStopMode ? "stop" : "send"}
                  composerPending={composerPending}
                  composerSafeGuidancePending={composerSafeGuidancePending}
                  composerInterruptGuidancePending={composerInterruptGuidancePending}
                  composerError={activeComposerError}
                  composerGuidance={composerGuidance}
                  composerAttachments={activeImageAttachments.map((attachment) => ({
                    id: attachment.id,
                    filename: attachment.filename,
                    previewUrl: attachment.previewUrl,
                    sizeBytes: attachment.sizeBytes,
                    contentType: attachment.contentType,
                  }))}
                  composerReferences={activeReferenceAttachments}
                  composerAttachmentInputDisabled={composerDisabled || Boolean(resolvedEditTarget)}
                  composerModeNotice={resolvedEditTarget ? t("editMessageModeNotice") : ""}
                  cancelComposerModeLabel={t("cancelEditMessage")}
                  turnError={detail.lastTurnError}
                  stopLabel={t("stop")}
                  stopPendingLabel={t("stopPending")}
                  safeGuidanceLabel={t("safeGuidance")}
                  safeGuidancePendingLabel={t("safeGuidancePending")}
                  interruptGuidanceLabel={t("interruptGuidance")}
                  interruptGuidancePendingLabel={t("interruptGuidancePending")}
                  editingMessageId={resolvedEditTarget?.messageId}
                  editUserMessageLabel={t("editAndResendMessage")}
                  editUserMessageDisabled={submitPending}
                  onComposerChange={handleComposerChange}
                  onAddComposerAttachments={handleAddComposerAttachments}
                  onRemoveComposerAttachment={handleRemoveComposerAttachment}
                  onAddComposerReference={handleAddComposerReference}
                  onRemoveComposerReference={handleRemoveComposerReference}
                  onEditUserMessage={handleEditUserMessage}
                  onCancelComposerMode={resolvedEditTarget ? handleCancelEditMessage : undefined}
                  onSubmit={handleSubmitTurn}
                  onStop={handleStopTurn}
                  onSafeGuidance={() => handleSubmitGuidance("safe")}
                  onInterruptGuidance={() => handleSubmitGuidance("interrupt")}
                  fallback={<div className={styles.emptySurface}>{t("loadingSession")}</div>}
                />
              </div>
            ) : (
              <div className={styles.emptySurface}>{t("loadingSession")}</div>
            )
          ) : activeCliAgentRunId ? (
            activeCliAgentRun ? null : (
              <div className={styles.emptySurface}>
                {lang === "zh" ? "这个 CLI 工具页还没有可显示的运行记录。" : "This CLI tool page has no run to display."}
              </div>
            )
          ) : fileContentQuery.isError ? (
            <div className={styles.emptySurface}>
              {describeError(fileContentQuery.error, t("loadFailed"))}
            </div>
          ) : fileContentQuery.data ? (
            <LazyFilePreview
              file={fileContentQuery.data}
              changed={changedFiles.has(fileContentQuery.data.path)}
              sourceLabel={detail?.title ?? t("currentSession")}
              fallback={<div className={styles.emptySurface}>{t("loadingFilePreview")}</div>}
            />
          ) : (
            <div className={styles.emptySurface}>{t("loadingFilePreview")}</div>
          )}
        </div>
      </section>

      <PaneCollapseHandle
        side="right"
        collapsed={rightPaneCollapsed}
        separatorLabel={t("resizeRightPanel")}
        collapseLabel={lang === "zh" ? "收起右栏" : "Collapse right pane"}
        expandLabel={lang === "zh" ? "展开右栏" : "Expand right pane"}
        className={styles.resizeHandle}
        active={dragState?.side === "right"}
        activeClassName={styles.resizeHandleActive}
        onToggle={() => setRightPaneCollapsed((current) => !current)}
        onPointerDown={(event) => handleResizeStart("right", event)}
        onKeyDown={(event) => handleResizeKeyDown("right", event)}
      />

      <aside className={rightPaneCollapsed ? `${styles.rightPane} ${styles.paneCollapsed}` : styles.rightPane} aria-hidden={rightPaneCollapsed}>
        {legacyGroupRoomActive ? (
          <div
            className={styles.rightIndexTabs}
            role="tablist"
            aria-label={lang === "zh" ? "右侧索引" : "Right index"}
          >
            <button
              type="button"
              role="tab"
              aria-selected={rightIndexPanel === "conversations"}
              className={rightIndexPanel === "conversations" ? `${styles.rightIndexTab} ${styles.rightIndexTabActive}` : styles.rightIndexTab}
              onClick={() => setRightIndexPanel("conversations")}
            >
              <MessageCircleHeart size={14} />
              <span>{lang === "zh" ? "会话" : "Chats"}</span>
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={rightIndexPanel === "members"}
              className={rightIndexPanel === "members" ? `${styles.rightIndexTab} ${styles.rightIndexTabActive}` : styles.rightIndexTab}
              onClick={() => setRightIndexPanel("members")}
            >
              <UsersRound size={14} />
              <span>{lang === "zh" ? "成员" : "Members"}</span>
            </button>
          </div>
        ) : null}

        {rightIndexPanel === "members" && legacyGroupRoomActive ? (
          <div className={styles.memberIndexSummary}>
            <UsersRound size={15} />
            <span>
              {availableGroupParticipantCount} {lang === "zh" ? "位可用助手" : "available agents"}
            </span>
            <strong>{statusLabel(activeGroupRoom?.status ?? "ready")}</strong>
          </div>
        ) : (
          <div className={styles.panelSearch}>
            <Search size={15} />
            <input
              className={styles.panelSearchInput}
              type="text"
              value={sessionFilter}
              onChange={(event) => setSessionFilter(event.target.value)}
              placeholder={t("searchSessionsPlaceholder")}
            />
          </div>
        )}

        <div className={styles.panelBody}>
          {rightIndexPanel === "members" && legacyGroupRoomActive ? (
            <section className={styles.agentIndexRoster} aria-label={lang === "zh" ? "群成员状态索引" : "Group member status index"}>
              <div className={styles.sectionHeader}>
                <div className={styles.sectionIdentity}>
                  <p className={styles.blockEyebrow}>{lang === "zh" ? "成员状态" : "Member status"}</p>
                  <h3 className={styles.sectionTitle}>{activeGroupRoom?.title ?? (lang === "zh" ? "群聊加载中" : "Loading group")}</h3>
                </div>
              </div>
              <p className={styles.contextLineCompact}>
                {lang === "zh"
                  ? "只展示可用成员；已归档或断链的历史成员保留在日志里，不在这里打扰。"
                  : "Only available members are shown here; archived or broken historical members stay in diagnostics."}
              </p>
              {availableGroupParticipants.length ? (
                <div className={styles.agentIndexList}>
                  {availableGroupParticipants.map((participant: ChatRoomParticipant) => {
                  const expanded = expandedGroupAgentSessionIds.includes(participant.sessionId);
                  const participantSession = sessionsById.get(participant.sessionId);
                  const expandedDetailQuery = expandedGroupAgentDetailsBySessionId.get(participant.sessionId);
                  const memberDetail = expanded ? expandedDetailQuery?.data : undefined;
                  const memberContext = memberDetail?.contextUsage;
                  const memberContextUsed = memberContext?.used ?? 0;
                  const memberContextLimit = memberContext?.limit ?? 0;
                  const memberContextPercent = contextUsagePercent(memberContextUsed, memberContextLimit);
                  const memberMental = mentalModelEnabledForNextTurn ? latestMentalSnapshot(memberDetail?.messages) : undefined;
                  const memberMentalState = memberMental?.mood?.trim()
                    || memberMental?.cognitiveState?.trim()
                    || (lang === "zh" ? "未记录" : "No snapshot");
                  const memberMentalSummary = memberMental?.feeling?.trim()
                    || memberMental?.summary?.trim()
                    || (lang === "zh" ? "该助手尚未形成可展示的心智快照。" : "This agent has no visible mental snapshot yet.");
                  const participantDisplay = groupParticipantIdentity(participant);
                  const participantAgent = participant.agentId ? agentsById.get(participant.agentId) : undefined;
                  const participantAvatarImageUrl = avatarImageUrlFrom(participantAgent, participant);
                  const memberUpdated = formatRelativeTime(
                    memberMental?.updatedAt || memberDetail?.updatedAt || participantSession?.updatedAt || "",
                    Date.now(),
                    locale,
                  );
                  return (
                    <article key={participant.participantId || participant.sessionId} className={styles.agentIndexCard}>
                      <div className={styles.agentIndexHeader}>
                        <button
                          type="button"
                          className={styles.agentIndexExpandButton}
                          aria-expanded={expanded}
                          aria-label={expanded
                            ? (lang === "zh" ? `收起 ${participantDisplay.name} 状态` : `Collapse ${participantDisplay.name} status`)
                            : (lang === "zh" ? `展开 ${participantDisplay.name} 状态` : `Expand ${participantDisplay.name} status`)}
                          onClick={() =>
                            setExpandedGroupAgentSessionIds((current) =>
                              current.includes(participant.sessionId)
                                ? current.filter((sessionId) => sessionId !== participant.sessionId)
                                : [...current, participant.sessionId],
                            )}
                        >
                          <ChevronRight size={14} aria-hidden="true" />
                        </button>
                        <button
                          type="button"
                          className={styles.agentIndexOpenButton}
                          onClick={() => handleOpenDirectSession(participant.sessionId)}
                          aria-label={lang === "zh" ? `打开 ${participantDisplay.name} 单聊` : `Open direct chat with ${participantDisplay.name}`}
                          title={lang === "zh" ? "打开该助手的单聊" : "Open this Agent direct chat"}
                        >
                          {renderAgentAvatar(
                            styles.agentIndexAvatar,
                            participantAvatarImageUrl,
                            avatarInitials(participant.agentCode, participant.title),
                          )}
                          <span className={styles.agentIndexCopy}>
                            <strong className={styles.agentIndexNameLine}>
                              <span>{participantDisplay.name}</span>
                              <em className={`${styles.agentRoleTag} ${styles[agentRoleClass(participantDisplay.tone)]}`}>
                                {participantDisplay.functionLabel}
                              </em>
                            </strong>
                            {participantDisplay.modelLabel ? (
                              <span className={styles.agentModelLine} title={participantDisplay.modelLabel}>
                                {participantDisplay.modelLabel}
                              </span>
                            ) : null}
                          </span>
                        </button>
                        <span className={styles.agentIndexStatus}>
                          {statusLabel(participant.status || participantSession?.status || "ready")}
                        </span>
                      </div>
                      {expanded ? (
                        <div className={styles.agentIndexDetails}>
                          {expandedDetailQuery?.isPending ? (
                            <p className={styles.contextLineCompact}>{t("loadingSession")}</p>
                          ) : expandedDetailQuery?.isError ? (
                            <p className={styles.panelNotice}>{describeError(expandedDetailQuery.error, t("loadFailed"))}</p>
                          ) : (
                            <>
                              <div className={styles.resourceSplit}>
                                <div className={styles.resourceMetric}>
                                  <span>{t("contextInUse")}</span>
                                  <strong>{formatContextUsage(memberContextUsed, memberContextLimit, locale)}</strong>
                                </div>
                                <div className={styles.resourceMetric}>
                                  <span>{lang === "zh" ? "上下文占比" : "Context ratio"}</span>
                                  <strong>{memberContextPercent}%</strong>
                                </div>
                              </div>
                              <p className={styles.oneLineValue}>
                                <span>{lang === "zh" ? "消息" : "Messages"}</span>
                                {memberContext
                                  ? `${numberFormatter.format(memberContext.messageCount)} ${lang === "zh" ? "条" : "messages"} · ${numberFormatter.format(memberContext.assistantMessageCount)} Agent`
                                  : (lang === "zh" ? "暂无上下文统计" : "No context stats yet")}
                              </p>
                              <div className={styles.agentIndexMentalBlock}>
                                <div className={styles.sectionHeader}>
                                  <div className={styles.sectionIdentity}>
                                    <p className={styles.blockEyebrow}>{t("mentalState")}</p>
                                    <p className={styles.sectionMetaLine}>
                                      {memberUpdated || (lang === "zh" ? "尚未更新" : "Not updated yet")}
                                    </p>
                                  </div>
                                  <span className={styles.mentalStateBadge}>{memberMentalState}</span>
                                </div>
                                <p className={styles.contextLineCompact}>{memberMentalSummary}</p>
                              </div>
                              <p className={styles.featurePresetNote}>
                                {lang === "zh"
                                  ? "群聊成员由群聊调度驱动；需要单独调整下一轮功能时，请打开该助手的单聊。"
                                  : "Group members are driven by group scheduling. Open the direct chat to tune next-turn features."}
                              </p>
                            </>
                          )}
                        </div>
                      ) : null}
                    </article>
                  );
                  })}
                </div>
              ) : (
                <div className={styles.agentIndexEmptyState}>
                  <UsersRound size={24} />
                  <p>
                    {lang === "zh"
                      ? "暂无可用群成员。请在左侧群设置中选择成员并应用变更。"
                      : "No available group members. Choose members in the left group settings and apply the change."}
                  </p>
                </div>
              )}
            </section>
          ) : (
            <>
            <div className={styles.sessionActionRow}>
              <button
                type="button"
                className={styles.newSessionButton}
                onClick={handleCreateSession}
                disabled={createSessionMutation.isPending}
              >
                <Plus size={15} />
                <span>{createSessionMutation.isPending ? t("creatingSession") : t("newSession")}</span>
              </button>
              <button
                type="button"
                className={styles.newGroupButton}
                onClick={handleToggleGroupComposer}
                aria-expanded={groupComposerOpen}
                disabled={createGroupRoomMutation.isPending}
              >
                <UsersRound size={15} />
                <span>{groupComposerOpen ? (lang === "zh" ? "收起" : "Close") : (lang === "zh" ? "新建群聊" : "New group")}</span>
              </button>
            </div>
            <section className={styles.systemEntryGroup} aria-label={lang === "zh" ? "系统入口" : "System entries"}>
              <div className={styles.conversationTreeRootHeader}>
                <span>{lang === "zh" ? "系统入口" : "System"}</span>
                <strong>1</strong>
              </div>
              <button
                type="button"
                aria-current={projectBusActive ? "true" : undefined}
                className={
                  projectBusActive
                    ? `${styles.systemEntryButton} ${styles.systemEntryButtonActive}`
                    : styles.systemEntryButton
                }
                onClick={handleOpenProjectAgentBus}
              >
                <span className={styles.systemEntryIcon} aria-hidden="true">
                  <BellRing size={16} />
                </span>
                <span className={styles.systemEntryCopy}>
                  <span className={styles.systemEntryTitleRow}>
                    <span className={styles.systemEntryTitle}>{lang === "zh" ? "助手通知流" : "Agent notice stream"}</span>
                    {projectBusActive ? <span className={styles.sessionCurrentBadge}>{t("currentSession")}</span> : null}
                  </span>
                  <span className={styles.systemEntryMeta}>
                    {lang === "zh" ? "全局广播 · 私信投递记录" : "Global broadcast · private delivery log"}
                  </span>
                </span>
              </button>
            </section>
            {groupComposerOpen ? (
              <section className={styles.groupComposerPanel} aria-label={lang === "zh" ? "新建群聊" : "New group chat"}>
                <label className={styles.groupComposerField}>
                  <span>{lang === "zh" ? "群名" : "Name"}</span>
                  <input
                    className={styles.groupComposerInput}
                    value={groupTitleDraft}
                    maxLength={80}
                    onChange={(event) => setGroupTitleDraft(event.target.value)}
                  />
                </label>
                <label className={styles.groupComposerField}>
                  <span>{lang === "zh" ? "调度模式" : "Mode"}</span>
                  <select
                    className={styles.groupComposerInput}
                    value={groupModeDraft}
                    onChange={(event) => setGroupModeDraft(event.target.value)}
                    disabled={chatRoomModesQuery.isPending || createGroupRoomMutation.isPending}
                  >
                    {readyChatRoomModes.map((mode) => (
                      <option key={mode.id} value={mode.id}>
                        {chatRoomModeLabel(mode, lang)}
                      </option>
                    ))}
                  </select>
                </label>
                <label className={styles.groupComposerField}>
                  <span>{lang === "zh" ? "对话目的" : "Purpose"}</span>
                  <select
                    className={styles.groupComposerInput}
                    value={groupPurposeDraft}
                    onChange={(event) => setGroupPurposeDraft(event.target.value)}
                    disabled={chatRoomPurposesQuery.isPending || createGroupRoomMutation.isPending}
                  >
                    {availableChatRoomPurposes.map((purpose) => (
                      <option key={purpose.id} value={purpose.id}>
                        {chatRoomPurposeLabel(purpose, lang)}
                      </option>
                    ))}
                  </select>
                </label>
                <div className={styles.groupAgentPicker} aria-label={lang === "zh" ? "选择参与助手" : "Choose agents"}>
                  {agentsQuery.isPending ? (
                    <p className={styles.groupComposerEmpty}>{lang === "zh" ? "正在读取助手..." : "Loading agents..."}</p>
                  ) : groupCandidateAgents.length ? (
                    groupCandidateAgents.map((agent) => {
                      const selected = groupSelectedAgentIds.includes(agent.agentId);
                      const display = agentDisplayInfo(agent, lang, { resolveModelLabel });
                      return (
                        <label key={agent.agentId} className={selected ? `${styles.groupAgentOption} ${styles.groupAgentOptionSelected}` : styles.groupAgentOption}>
                          <input
                            type="checkbox"
                            checked={selected}
                            disabled={createGroupRoomMutation.isPending}
                            onChange={() => handleToggleGroupAgent(agent.agentId)}
                          />
                          {renderAgentAvatar(
                            styles.agentOptionAvatar,
                            agent.avatarImageUrl,
                            avatarInitials(agent.agentCode, display.name),
                          )}
                          <span>
                            <strong>{display.name}</strong>
                            <span className={styles.agentOptionMeta}>
                              <small className={`${styles.agentRoleTag} ${styles[agentRoleClass(display.tone)]}`}>
                                {display.functionLabel}
                              </small>
                              {display.modelLabel ? (
                                <small className={styles.agentModelTag} title={display.modelLabel}>
                                  {display.modelLabel}
                                </small>
                              ) : null}
                            </span>
                          </span>
                        </label>
                      );
                    })
                  ) : (
                    <p className={styles.groupComposerEmpty}>{lang === "zh" ? "暂无可加入群聊的持久助手。" : "No persistent agents are available."}</p>
                  )}
                </div>
                <button
                  type="button"
                  className={styles.createGroupButton}
                  onClick={handleCreateGroupRoom}
                  disabled={createGroupRoomMutation.isPending || groupSelectedAgentIds.length < 2 || !groupTitleDraft.trim()}
                >
                  <UsersRound size={15} />
                  <span>{createGroupRoomMutation.isPending ? (lang === "zh" ? "创建中" : "Creating") : (lang === "zh" ? "创建群聊" : "Create group")}</span>
                </button>
              </section>
            ) : null}
            {sessionComposerErrors.__sessions__ ? (
              <div className={styles.panelState}>{sessionComposerErrors.__sessions__}</div>
            ) : null}
            {sessionsErrorState.transientError ? (
              <div className={styles.panelNotice} role="status">{sessionsErrorMessage}</div>
            ) : null}
            {sessionsErrorState.blockingError ? (
              <div className={styles.panelState}>{sessionsErrorMessage}</div>
            ) : conversationsQuery.isPending && !conversationsQuery.data && sessionsQuery.isPending && !sessionsQuery.data ? (
              <div className={styles.panelState}>{t("loadingSession")}</div>
            ) : filteredConversations.length === 0 && filteredTeams.length === 0 && filteredStandaloneGroupConversations.length === 0 ? (
              <div className={styles.panelState}>
                {sessionFilter.trim() ? t("noSessionMatches") : t("noSessionsYet")}
              </div>
            ) : (
              <>
              <ConversationIndexTree
                activeGroupRoomId={activeGroupRoomId}
                activeSessionId={activeSessionId}
                addToReviewSucceededLabel={t("addSessionToReviewSucceeded")}
                agentsById={agentsById}
                avatarImageUrlFrom={avatarImageUrlFrom}
                avatarInitials={avatarInitials}
                buildSessionReferencePayload={buildSessionReferencePayload}
                collapsedConversationGroups={collapsedConversationGroups}
                conversationGroupLabel={conversationGroupLabel}
                deleteBusyLabel={t("deleteSessionBusy")}
                editingSessionId={editingSessionId}
                editingSessionTitle={editingSessionTitle}
                filteredConversationsCount={filteredConversations.length}
                filteredStandaloneGroupConversations={filteredStandaloneGroupConversations}
                filteredTeams={filteredTeams}
                formatTime={formatTime}
                groupPanelActive={groupPanelActive}
                groupedConversations={groupedConversations}
                isBusyPhase={isBusyPhase}
                lang={lang}
                renamePending={renameSessionMutation.isPending}
                renameSessionId={renameSessionMutation.variables?.sessionId ?? ""}
                resolveModelLabel={resolveModelLabel}
                searchHasTerm={searchHasTerm}
                sessionComposerErrors={sessionComposerErrors}
                sessionsById={sessionsById}
                statusLabel={statusLabel}
                t={t}
                onCancelRename={cancelRenameSession}
                onContextMenu={openSessionContextMenu}
                onDragReference={startSessionReferenceDrag}
                onOpenDirectSession={handleOpenDirectSession}
                onOpenGroupRoom={handleOpenGroupRoom}
                onRenameTitleChange={setEditingSessionTitle}
                onSubmitRename={submitRenameSession}
                onToggleConversationGroup={toggleConversationGroup}
              />
              {sessionIndexHasMore ? (
                <button
                  type="button"
                  className={styles.sessionLoadMoreButton}
                  onClick={() => rawSessionsQuery.loadMore()}
                  disabled={rawSessionsQuery.isLoadingMore}
                  aria-label={sessionIndexLoadMoreLabel}
                >
                  <span>{sessionIndexLoadMoreLabel}</span>
                  <strong>{sessionIndexProgressLabel}</strong>
                </button>
              ) : sessionIndexProgressVisible ? (
                <div className={styles.sessionLoadMoreStatus} role="status">
                  <span>{sessionIndexFullyLoadedLabel}</span>
                  <strong>{sessionIndexProgressLabel}</strong>
                </div>
              ) : null}
              {sessionContextMenu && contextMenuSession ? (
                <SessionContextMenu
                  addToReviewDisabled={contextMenuAddToReviewDisabled}
                  addToReviewPending={contextMenuAddToReviewPending}
                  deleteDisabled={contextMenuDeleteDisabled}
                  lang={lang}
                  position={sessionContextMenu}
                  session={contextMenuSession}
                  t={t}
                  onAddToReview={handleAddSessionToReview}
                  onDelete={handleDeleteSession}
                  onRename={beginRenameSession}
                />
              ) : null}
              </>
            )}
            </>
          )}
          </div>
        </aside>
      {cacheDetailOpen && cacheDetailAvailable ? (
        <div className={styles.cacheDetailOverlay} role="presentation" onClick={closeCacheDetail}>
          <section
            id="cache-detail-dialog"
            className={styles.cacheDetailDialog}
            role="dialog"
            aria-modal="true"
            aria-label={cacheDetailDialogTitle}
            onClick={(event) => event.stopPropagation()}
          >
            <header className={styles.cacheDetailHeader}>
              <div>
                <p>{t("previousCacheHit")}</p>
                <h3>{cacheDetailDialogTitle}</h3>
              </div>
              <button
                type="button"
                className={styles.cacheDetailCloseButton}
                onClick={closeCacheDetail}
                aria-label={lang === "zh" ? "关闭缓存详情" : "Close cache details"}
              >
                <X size={16} />
              </button>
            </header>

            <div className={styles.cacheDetailSummaryGrid}>
              <div>
                <span>{lang === "zh" ? "真实命中" : "True hit"}</span>
                <strong>{cacheCompositionPercent}%</strong>
                <small>{numberFormatter.format(providerCachedInputTokens)} / {numberFormatter.format(providerCacheInputTokens)}</small>
              </div>
              <div>
                <span>{lang === "zh" ? "计算命中" : "Computed hit"}</span>
                <strong>{computedCacheCompositionPercent}%</strong>
                <small>{numberFormatter.format(lastCacheComposition?.computedCachedInputTokens ?? 0)} / {numberFormatter.format(computedCacheCompositionTotalTokens)}</small>
              </div>
              <div>
                <span>{lang === "zh" ? "总平均命中" : "Average hit"}</span>
                <strong>{cacheCompositionAverageValue}</strong>
                <small>{lang === "zh" ? "轮次" : "turns"} {numberFormatter.format(averageCacheObservedTurnCount)}</small>
              </div>
            </div>

            {cacheCalibrationReason || cacheComputedOverestimatedInputTokens > 0 || cacheProviderExtraCachedInputTokens > 0 ? (
              <div className={styles.cacheDetailCalibrationNote} title={cacheCalibrationReason || cacheCalibrationSummaryText}>
                <strong>{lang === "zh" ? "厂商校准" : "Provider calibration"}</strong>
                <span>{cacheCalibrationSummaryText}</span>
                <em>
                  {cacheComputedOverestimatedInputTokens > 0 ? `${lang === "zh" ? "预测未兑现" : "predicted not observed"} ${numberFormatter.format(cacheComputedOverestimatedInputTokens)}` : ""}
                  {cacheComputedOverestimatedInputTokens > 0 && cacheProviderExtraCachedInputTokens > 0 ? " · " : ""}
                  {cacheProviderExtraCachedInputTokens > 0 ? `${lang === "zh" ? "厂商额外命中" : "provider extra hit"} ${numberFormatter.format(cacheProviderExtraCachedInputTokens)}` : ""}
                </em>
              </div>
            ) : null}

            <div className={styles.cacheDetailBody}>
              <div className={styles.cacheDetailDonutPanel}>
                <div className={styles.cacheDetailDonutShell}>
                  <svg
                    className={`${styles.cacheDonutSvg} ${styles.cacheDetailDonutSvg}`}
                    viewBox="0 0 100 100"
                    role="img"
                    aria-label={cacheCompositionTitle}
                  >
                    <circle className={`${styles.cacheDonutTrack} ${styles.cacheDonutOuterTrack}`} cx="50" cy="50" r="42" pathLength={100} />
                    {cachePromptDonutSegments.map((segment, index) => (
                      <circle
                        key={`detail-computed-${segment.key}-${segment.status}-${index}`}
                        className={`${styles.cacheDonutSegment} ${styles.cacheDonutOuterSegment} ${cachePromptSegmentClass(segment)}`}
                        cx="50"
                        cy="50"
                        r="42"
                        pathLength={100}
                        style={cacheDonutSegmentStyle(segment, cachePromptDonutSegments.length > 1 ? 0.55 : 0)}
                      >
                        <title>{cacheDonutSegmentTitle(segment, cachePromptCompositionTotalTokens, numberFormatter, lang)}</title>
                      </circle>
                    ))}
                    <circle className={`${styles.cacheDonutTrack} ${styles.cacheDonutInnerTrack}`} cx="50" cy="50" r="31" pathLength={100} />
                    {trueCacheDonutSegments.map((segment, index) => (
                      <circle
                        key={`detail-true-${segment.key}-${segment.status}-${index}`}
                        className={`${styles.cacheDonutSegment} ${styles.cacheDonutInnerSegment} ${cacheDonutSegmentClass(segment.status || segment.key)}`}
                        cx="50"
                        cy="50"
                        r="31"
                        pathLength={100}
                        style={cacheDonutSegmentStyle(segment, trueCacheDonutSegments.length > 1 ? 0.4 : 0)}
                      >
                        <title>{cacheDonutSegmentTitle(segment, providerCacheInputTokens, numberFormatter, lang)}</title>
                      </circle>
                    ))}
                  </svg>
                <div className={`${styles.cacheDonutCenter} ${styles.cacheDetailDonutCenter}`} title={cacheCompositionTitle}>
                  <strong>{cacheCompositionPercent}%</strong>
                  <span>{cacheCompositionComputedLabel} {computedCacheCompositionPercent}%</span>
                  <small>{cacheCompositionAverageLabel} {cacheCompositionAverageValue}</small>
                </div>
              </div>
                <div className={styles.cacheDetailDonutLegend}>
                  <span><b>{lang === "zh" ? "外环" : "outer"}</b>{lang === "zh" ? "提示词来源" : "prompt sources"}</span>
                  <span><b>{lang === "zh" ? "内环" : "inner"}</b>{lang === "zh" ? "厂商真实命中" : "provider hits"}</span>
                </div>
              </div>

              <div className={styles.cacheDetailSegmentList}>
                <section className={styles.cacheDetailSegmentGroup}>
                  <div className={styles.cacheDetailSegmentHeader}>
                    <strong>{lang === "zh" ? "提示词分段校准" : "Prompt segment calibration"}</strong>
                    <span>{numberFormatter.format(cachePromptCompositionTotalTokens)} tokens</span>
                  </div>
                  {cachePromptDonutSegments.length ? (
                    cachePromptDonutSegments.map((segment, index) => (
                      <div
                        key={`detail-computed-row-${segment.key}-${segment.status}-${index}`}
                        className={styles.cacheDetailSegmentRow}
                        title={cacheDonutSegmentTitle(segment, cachePromptCompositionTotalTokens, numberFormatter, lang)}
                      >
                        <i className={`${styles.cacheDetailSwatch} ${cachePromptLegendSegmentClass(segment)}`} />
                        <div className={styles.cacheDetailSegmentText}>
                          <strong>{segment.key === "computed_missing" ? cacheCompositionSegmentLabel("missing", segment.label, t) : segment.label}</strong>
                          <span className={styles.cacheDetailSegmentSource}>
                            {promptSegmentCategoryLabel(segment, lang)}
                            {promptSegmentAccuracyLabel(segment, lang) ? ` · ${promptSegmentAccuracyLabel(segment, lang)}` : ""}
                            {segment.cachePolicy ? ` · ${segment.cachePolicy}` : ""}
                          </span>
                          <span className={styles.cacheDetailSegmentMeta}>
                            <b>{cacheComputedStatusLabel(segment.status, lang)}</b>
                            <b data-status={segment.observedStatus || "not_observed"}>
                              {cacheObservedStatusLabel(segment.observedStatus, lang)}
                            </b>
                            {(segment.computedOverestimatedInputTokens ?? 0) > 0 ? (
                              <b data-status="observed_miss">
                                {lang === "zh" ? "预测未兑现" : "not observed"} {numberFormatter.format(segment.computedOverestimatedInputTokens ?? 0)}
                              </b>
                            ) : null}
                            {(segment.providerExtraCachedInputTokens ?? 0) > 0 ? (
                              <b data-status="observed_hit">
                                {lang === "zh" ? "厂商额外" : "provider extra"} {numberFormatter.format(segment.providerExtraCachedInputTokens ?? 0)}
                              </b>
                            ) : null}
                          </span>
                          {segment.contentPreview ? <small>{segment.contentPreview}</small> : null}
                        </div>
                        <em>
                          {numberFormatter.format(segment.tokens ?? 0)} · {Math.round(segment.actualPercent)}%
                          {(segment.observedCachedInputTokens ?? 0) > 0 || (segment.observedMissedInputTokens ?? 0) > 0 ? (
                            <small>
                              {lang === "zh" ? "真" : "obs"} {numberFormatter.format(segment.observedCachedInputTokens ?? 0)}
                              {" / "}
                              {numberFormatter.format(segment.observedMissedInputTokens ?? 0)}
                            </small>
                          ) : null}
                        </em>
                      </div>
                    ))
                  ) : (
                    <div className={styles.cacheDetailEmpty}>{lang === "zh" ? "暂无计算段数据" : "No computed segment data"}</div>
                  )}
                </section>

                <section className={styles.cacheDetailSegmentGroup}>
                  <div className={styles.cacheDetailSegmentHeader}>
                    <strong>{lang === "zh" ? "Provider 真实命中" : "Provider true hits"}</strong>
                    <span>{numberFormatter.format(providerCacheInputTokens)} tokens</span>
                  </div>
                  {trueCacheDonutSegments.length ? (
                    trueCacheDonutSegments.map((segment, index) => (
                      <div
                        key={`detail-true-row-${segment.key}-${segment.status}-${index}`}
                        className={styles.cacheDetailSegmentRow}
                        title={cacheDonutSegmentTitle(segment, providerCacheInputTokens, numberFormatter, lang)}
                      >
                        <i className={`${styles.cacheDetailSwatch} ${cacheDonutSegmentClass(segment.status || segment.key)}`} />
                        <div className={styles.cacheDetailSegmentText}>
                          <strong>{segment.label || segment.key}</strong>
                          <span>{segment.source || segment.status || segment.key}</span>
                          {segment.description ? <small>{segment.description}</small> : null}
                        </div>
                        <em>{numberFormatter.format(segment.tokens ?? 0)} · {Math.round(segment.actualPercent)}%</em>
                      </div>
                    ))
                  ) : (
                    <div className={styles.cacheDetailEmpty}>{lang === "zh" ? "暂无真实命中数据" : "No provider hit data"}</div>
                  )}
                </section>
              </div>
            </div>
          </section>
        </div>
      ) : null}
    </div>
  );
}
