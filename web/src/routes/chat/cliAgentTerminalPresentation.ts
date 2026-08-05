/**
 * Pure presentation helpers for CliAgent terminal (Wave 4 extract).
 */
import type { CliAgentTerminalSession } from "../ChatCodingRoute";

export function terminalStatusText(
  session: CliAgentTerminalSession | null,
  connecting: boolean,
  lang: "zh" | "en",
) {
  if (connecting && !session) {
    return lang === "zh" ? "连接中" : "Connecting";
  }
  if (!session) {
    return lang === "zh" ? "未连接" : "Disconnected";
  }
  const interactionState = String(session.interactionState || "").trim().toLowerCase();
  if (session.canInput === true || interactionState === "live" || session.alive) {
    return session.resumed ? (lang === "zh" ? "已恢复" : "Resumed") : (lang === "zh" ? "运行中" : "Running");
  }
  if (interactionState === "resumable" || session.canResume) {
    return lang === "zh" ? "可恢复" : "Resumable";
  }
  if (interactionState === "history") {
    return lang === "zh" ? "只读历史" : "History";
  }
  const status = String(session.status || "").trim().toLowerCase();
  if (interactionState === "closed" || session.userClosed || status === "closed") {
    return lang === "zh" ? "已关闭" : "Closed";
  }
  if (status === "exited") {
    return lang === "zh" ? "已退出" : "Exited";
  }
  if (status === "stopping") {
    return lang === "zh" ? "停止中" : "Stopping";
  }
  return lang === "zh" ? "未运行" : "Stopped";
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

export function parseTerminalErrorSession(error: unknown): Partial<CliAgentTerminalSession> | null {
  const message = error instanceof Error ? error.message : String(error || "");
  if (!message.trim()) {
    return null;
  }
  try {
    const payload = JSON.parse(message) as { detail?: unknown };
    const detail = payload.detail;
    if (!detail || typeof detail !== "object") {
      return null;
    }
    const record = detail as Record<string, unknown>;
    return {
      terminalSessionId: typeof record.terminalSessionId === "string" ? record.terminalSessionId : undefined,
      cliSessionId: typeof record.cliSessionId === "string" ? record.cliSessionId : undefined,
      status: typeof record.status === "string" ? record.status : undefined,
      alive: typeof record.alive === "boolean" ? record.alive : undefined,
      interactionState: typeof record.interactionState === "string" ? record.interactionState : undefined,
      canInput: typeof record.canInput === "boolean" ? record.canInput : undefined,
      canResume: typeof record.canResume === "boolean" ? record.canResume : undefined,
      canStart: typeof record.canStart === "boolean" ? record.canStart : undefined,
      resumeAction: typeof record.resumeAction === "string" ? record.resumeAction : undefined,
      displayMode: typeof record.displayMode === "string" ? record.displayMode : undefined,
      stateReason: typeof record.stateReason === "string" ? record.stateReason : undefined,
    };
  } catch {
    return null;
  }
}

export function terminalErrorMessage(error: unknown, lang: "zh" | "en") {
  const patch = parseTerminalErrorSession(error);
  if (patch?.interactionState === "resumable" || patch?.canResume) {
    return lang === "zh" ? "终端未运行，恢复会话后才能继续输入。" : "Terminal is not running. Resume the session before typing.";
  }
  if (patch?.interactionState === "closed") {
    return lang === "zh" ? "终端已关闭，不能继续输入。" : "Terminal is closed and cannot accept input.";
  }
  const message = error instanceof Error ? error.message : String(error || "");
  return message.trim() || (lang === "zh" ? "终端请求失败。" : "Terminal request failed.");
}
