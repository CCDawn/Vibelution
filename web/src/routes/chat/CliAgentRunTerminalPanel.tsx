import { FitAddon } from "@xterm/addon-fit";
import { Terminal } from "@xterm/xterm";
import { RotateCcw, SquareTerminal } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { fetchJson } from "../../api/client";
import type { CliAgentRunView, CliAgentTerminalSession } from "../ChatCodingRoute";
import styles from "../ChatCodingRoute.module.css";
import "@xterm/xterm/css/xterm.css";

type CliAgentTerminalEvent = {
  type?: string;
  chunk?: string;
  session?: CliAgentTerminalSession;
};

type CliAgentTerminalAck = {
  status?: string;
  semanticStatus?: string;
  code?: string;
  action?: string;
  terminalSessionId?: string;
  alive?: boolean;
  interactionState?: string;
  canInput?: boolean;
  canResume?: boolean;
  canStart?: boolean;
  resumeAction?: string;
  displayMode?: string;
  stateReason?: string;
  rows?: number;
  cols?: number;
  updatedAt?: string;
};

function terminalStatusText(session: CliAgentTerminalSession | null, connecting: boolean, lang: "zh" | "en") {
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

function canInputTerminal(session: CliAgentTerminalSession | null) {
  if (!session) {
    return false;
  }
  if (typeof session.canInput === "boolean") {
    return session.canInput;
  }
  return Boolean(session.alive);
}

function parseTerminalErrorSession(error: unknown): Partial<CliAgentTerminalSession> | null {
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

function terminalErrorMessage(error: unknown, lang: "zh" | "en") {
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

export function CliAgentRunTerminalPanel({
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
  const terminalCliSessionIdRef = useRef("");
  const terminalCanInputRef = useRef(false);
  const terminalHasOutputRef = useRef(false);
  const lastPostedSizeRef = useRef<{ rows: number; cols: number } | null>(null);
  const terminalSessionId = String(terminalSession?.terminalSessionId || "").trim();
  const terminalCanInput = canInputTerminal(terminalSession);
  const terminalCanResume = Boolean(terminalSession?.canResume && terminalSession?.resumeAction === "resume_session");
  const terminalCanStart = Boolean(terminalSession?.canStart && terminalSession?.resumeAction === "start_new");
  const terminalReadonly = Boolean(terminalSession && !terminalCanInput && terminalSession.displayMode === "readonly_replay");
  const terminalCliSessionId = String(terminalSession?.cliSessionId || run.cliSessionId || run.result?.cliSessionId || "").trim();
  const taskLocked = String(run.result?.semanticStatus || run.result?.status || run.status || "").trim().toLowerCase() === "task_locked"
    || String(run.result?.code || "").trim() === "CLI_AGENT_TASK_LOCKED";
  const taskLockedMessage = taskLocked
    ? String(run.result?.message || (lang === "zh" ? "指令未发送：当前 CLI Agent 终端已有任务在运行。" : "Instruction was not sent: this CLI Agent terminal already has a running task.")).trim()
    : "";
  const statusText = taskLocked
    ? (lang === "zh" ? "未发送" : "Not sent")
    : terminalStatusText(terminalSession, connecting, lang);
  const visibleCommand = taskLockedMessage || (Array.isArray(terminalSession?.commandPreview) && terminalSession?.commandPreview.length
    ? terminalSession.commandPreview.join(" ")
    : run.commandLine);
  const snapshotFallbackAvailable = Boolean(String(terminalSession?.screenText || "").trim());
  const transcriptReplayBlocked = terminalReadonly && terminalSession?.transcriptTailReplayable === false && !snapshotFallbackAvailable;
  const emptyText = terminalError
    || (terminalReadonly
      ? (terminalCanResume
        ? (lang === "zh" ? "当前显示的是历史终端。恢复会话后才能继续输入。" : "This is terminal history. Resume the session before typing.")
        : (lang === "zh" ? "当前显示的是只读历史。新开 CLI 后才能输入。" : "This is read-only history. Start a new CLI before typing."))
      : "")
    || (connecting
      ? (lang === "zh" ? "正在连接命令会话..." : "Connecting terminal session...")
      : transcriptReplayBlocked
        ? (lang === "zh"
          ? "终端已连接；历史 TUI 画面无法安全重放，等待新的可渲染输出。"
          : "Terminal connected; the historical TUI screen cannot be safely replayed. Waiting for new renderable output.")
        : terminalSession?.interactionState === "live" && terminalSession?.resumed
          ? (lang === "zh" ? "已恢复，等待终端输出。" : "Resumed. Waiting for terminal output.")
      : (lang === "zh" ? "命令会话还没有输出。" : "No terminal output yet."));

  useEffect(() => {
    terminalSessionIdRef.current = terminalSessionId;
    terminalCliSessionIdRef.current = terminalCliSessionId;
    terminalCanInputRef.current = terminalCanInput;
  }, [terminalCanInput, terminalCliSessionId, terminalSessionId]);

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
    const transcriptTail = String(session.transcriptTail || "");
    if (transcriptTail) {
      writeTerminalChunk(transcriptTail, { reset: true });
      return;
    }
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
    if (!data) {
      return;
    }
    if (!sessionId || !terminalCanInputRef.current) {
      setTerminalError(lang === "zh" ? "终端未运行，请先恢复会话。" : "Terminal is not running. Resume the session first.");
      return;
    }
    setTerminalError("");
    fetchJson<CliAgentTerminalAck>(`/api/cli-agents/terminal-sessions/${encodeURIComponent(sessionId)}/input`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ data }),
    })
      .then((ack) => {
        if (ack.alive === false) {
          setTerminalSession((current) => current ? { ...current, ...ack, alive: false } : current);
        }
      })
      .catch((error) => {
        const errorSession = parseTerminalErrorSession(error);
        if (errorSession) {
          setTerminalSession((current) => current ? { ...current, ...errorSession } : current);
        }
        setTerminalError(terminalErrorMessage(error, lang));
      });
  }, [lang]);

  const postTerminalSize = useCallback((rows: number, cols: number) => {
    const sessionId = terminalSessionIdRef.current;
    if (!sessionId || !terminalCanInputRef.current || rows <= 0 || cols <= 0) {
      return;
    }
    const previous = lastPostedSizeRef.current;
    if (previous?.rows === rows && previous.cols === cols) {
      return;
    }
    lastPostedSizeRef.current = { rows, cols };
    fetchJson<CliAgentTerminalAck>(`/api/cli-agents/terminal-sessions/${encodeURIComponent(sessionId)}/resize`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rows, cols }),
    })
      .then((ack) => {
        setTerminalSession((current) => {
          if (!current || ack.terminalSessionId !== current.terminalSessionId) {
            return current;
          }
          return {
            ...current,
            alive: typeof ack.alive === "boolean" ? ack.alive : current.alive,
            rows: typeof ack.rows === "number" ? ack.rows : current.rows,
            cols: typeof ack.cols === "number" ? ack.cols : current.cols,
            updatedAt: ack.updatedAt || current.updatedAt,
          };
        });
      })
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

  const terminalSizeForRequest = useCallback(() => {
    const terminal = terminalRef.current;
    const fitAddon = fitAddonRef.current;
    if (!terminal || !fitAddon) {
      return { rows: 28, cols: 100 };
    }
    try {
      fitAddon.fit();
    } catch {
      return { rows: terminal.rows || 28, cols: terminal.cols || 100 };
    }
    return { rows: terminal.rows || 28, cols: terminal.cols || 100 };
  }, []);

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

  const fetchTerminalSession = useCallback((intent: "view" | "resume" | "start", signal?: AbortSignal) => {
    const terminalSize = terminalSizeForRequest();
    return fetchJson<CliAgentTerminalSession>("/api/cli-agents/terminal-sessions/ensure", {
      method: "POST",
      signal,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        agentType: run.agentType,
        task: run.task,
        cwd: run.cwd,
        mode: run.mode || "readonly",
        intent,
        sourceSessionId,
        sourceMessageId: run.messageId,
        sourceRunId: run.sourceRunId,
        cliSessionId: intent === "start" ? "" : terminalCliSessionIdRef.current,
        rows: terminalSize.rows,
        cols: terminalSize.cols,
      }),
    })
      .then((session) => {
        setTerminalSession(session);
        if (intent === "view" || !canInputTerminal(session)) {
          replayTerminalSnapshot(session);
        } else {
          writeTerminalChunk("", { reset: true });
          window.requestAnimationFrame(fitTerminal);
        }
        return session;
      });
  }, [fitTerminal, replayTerminalSnapshot, run.agentType, run.cwd, run.messageId, run.mode, run.sourceRunId, run.task, sourceSessionId, terminalSizeForRequest, writeTerminalChunk]);

  const requestTerminalSession = useCallback((intent: "resume" | "start") => {
    setConnecting(true);
    setTerminalError("");
    fetchTerminalSession(intent)
      .catch((error) => {
        const errorSession = parseTerminalErrorSession(error);
        if (errorSession) {
          setTerminalSession((current) => current ? { ...current, ...errorSession } : current);
        }
        setTerminalError(terminalErrorMessage(error, lang));
      })
      .finally(() => setConnecting(false));
  }, [fetchTerminalSession, lang]);

  useEffect(() => {
    let disposed = false;
    const controller = new AbortController();
    setConnecting(true);
    setTerminalError("");
    setTerminalSession(null);
    lastPostedSizeRef.current = null;
    writeTerminalChunk("", { reset: true });

    fetchTerminalSession("view", controller.signal)
      .then(() => {
        if (disposed) {
          return;
        }
      })
      .catch((error) => {
        if (disposed || controller.signal.aborted) {
          return;
        }
        setTerminalError(terminalErrorMessage(error, lang));
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
  }, [fetchTerminalSession, lang, writeTerminalChunk]);

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
        if (payload.type === "terminal_output" && payload.chunk) {
          writeTerminalChunk(payload.chunk);
          return;
        }
        if (payload.session) {
          setTerminalSession(payload.session);
          if (payload.type === "terminal_snapshot" && !canInputTerminal(payload.session)) {
            replayTerminalSnapshot(payload.session);
          }
        }
      } catch {
        return;
      }
    };
    stream.addEventListener("terminal_snapshot", handleEvent as EventListener);
    stream.addEventListener("terminal_output", handleEvent as EventListener);
    stream.addEventListener("terminal_status", handleEvent as EventListener);
    stream.onerror = () => {
      setTerminalSession((current) => current ? { ...current, alive: false, canInput: false } : current);
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
          {terminalCanResume || terminalCanStart ? (
            <button
              type="button"
              className={styles.cliAgentTerminalAction}
              onClick={() => requestTerminalSession(terminalCanResume ? "resume" : "start")}
              disabled={connecting}
              title={terminalCanResume
                ? (lang === "zh" ? "恢复这个 CLI 会话" : "Resume this CLI session")
                : (lang === "zh" ? "新开一个 CLI 会话" : "Start a new CLI session")}
            >
              <RotateCcw size={13} aria-hidden="true" />
              <span>{terminalCanResume ? (lang === "zh" ? "恢复" : "Resume") : (lang === "zh" ? "新开" : "Start")}</span>
            </button>
          ) : null}
        </div>
        <div className={styles.cliAgentTerminalOutputShell}>
          <div ref={terminalElementRef} className={styles.cliAgentTerminalOutput} />
          {terminalError || terminalReadonly || !terminalHasOutput ? (
            <div className={styles.cliAgentTerminalOverlay} data-tone={terminalError ? "error" : "muted"}>
              {emptyText}
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}
