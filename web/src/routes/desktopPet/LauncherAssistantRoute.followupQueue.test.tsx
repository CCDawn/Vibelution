// @vitest-environment happy-dom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, createElement, useContext } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { SessionDetail, SessionQueuedTurn } from "../../api/types";
import type { ConversationViewProps } from "../../components/conversation/conversationViewTypes";
import { FollowupQueueTogglePauseContext } from "../../components/conversation/ConversationFollowupQueueBar";
import { LauncherAssistantEmbeddedRoute } from "./LauncherAssistantRoute";

let surface: ConversationViewProps;
let togglePause: ((id: string, paused: boolean) => void) | null;
vi.mock("./DesktopPetCharacter", () => ({ DesktopPetCharacter: () => null }));
vi.mock("../../components/conversation/LazyConversationView", () => ({
  LazyConversationView: (props: ConversationViewProps) => {
    surface = props;
    togglePause = useContext(FollowupQueueTogglePauseContext);
    return createElement("div", { "data-testid": "shared-conversation" },
      props.followupQueue?.map(row => createElement("p", { key: row.id }, row.text)));
  },
}));

const STATUS = {
  assistant: { agentId: "a", directSessionId: "s", displayName: "助理" },
  followupQueueVersion: 1,
  settings: { ok: true, displayName: "助理", modelId: "model-1",
    preferences: { characterId: "dafeiyu", showStatus: true, showTitles: true, showCompletion: true, idleMessage: "在的。" } },
};
const row = (id: string, position: number, extra: Partial<SessionQueuedTurn> = {}): SessionQueuedTurn =>
  ({ id, position, status: "queued", content: `消息 ${id}`, ...extra });
const key = ["launcher-assistant", "detail", "s"];
let root: Root | undefined;
let container: HTMLDivElement;
let client: QueryClient;
let invoke: ReturnType<typeof vi.fn>;
let native: SessionDetail;
let failOperation = "";
let events: string[];
let resume: (() => void) | undefined;

afterEach(async () => {
  await act(async () => root?.unmount()); root = undefined;
  client?.clear(); container?.remove();
  vi.unstubAllGlobals(); vi.clearAllMocks();
});
async function settle() {
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 20)); });
}
async function renderAssistant({ capability = true, rows = [row("q1", 1), row("q2", 2)] } = {}) {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  failOperation = ""; events = []; resume = undefined;
  native = { id: "s", agentId: "a", status: "running", activeTurnId: "turn-1", messages: [], queuedTurns: rows } as SessionDetail;
  vi.stubGlobal("fetch", vi.fn(() => { throw new Error("HTTP forbidden in assistant window"); }));
  invoke = vi.fn(async (request: Record<string, unknown>) => {
    const op = String(request.operation);
    if (op === failOperation) throw new Error("queue write failed");
    switch (op) {
      case "status": return { ...STATUS, followupQueueVersion: capability ? 1 : undefined };
      case "config": return { language: "zh" };
      case "detail": return native;
      case "approvals": return [];
      case "dispatches": return { dispatches: [] };
      case "operatorAsset": return { schemaVersion: 1, kind: request.kind, image: null, readability: "standard" };
      case "updateQueuedTurn": {
        events.push(op);
        if (resume) await new Promise<void>(resolve => { resume = resolve; });
        let rows = native.queuedTurns!.map(item => item.id === request.queuedTurnId ? { ...item,
          ...(request.content !== undefined ? { content: String(request.content) } : {}),
          ...(request.status !== undefined ? { status: String(request.status) } : {}),
        } : item);
        if (request.position !== undefined) {
          const item = rows.find(item => item.id === request.queuedTurnId)!;
          rows = rows.filter(row => row !== item); rows.splice(Number(request.position) - 1, 0, item);
          rows = rows.map((item, index) => ({ ...item, position: index + 1 }));
        }
        native = { ...native, queuedTurns: rows };
        return { queuedTurns: rows };
      }
      case "removeQueuedTurn":
        events.push(op);
        native = { ...native, queuedTurns: native.queuedTurns!.filter(item => item.id !== request.queuedTurnId) };
        return { queuedTurns: native.queuedTurns };
      case "sendNowQueuedTurn":
        events.push(op);
        native = { ...native, queuedTurns: [native.queuedTurns!.find(item => item.id === request.queuedTurnId)!,
          ...native.queuedTurns!.filter(item => item.id !== request.queuedTurnId)].map((item, index) =>
          ({ ...item, position: index + 1, sendNow: index === 0 })) };
        return { queuedTurns: native.queuedTurns, stopRequested: true };
      case "guidance": events.push(op); return native;
      default: throw new Error(`unexpected operation: ${op}`);
    }
  });
  vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
  client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 30_000 } } });
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);
  await act(async () => root!.render(createElement(QueryClientProvider, { client }, createElement(LauncherAssistantEmbeddedRoute))));
  await settle(); await settle();
}
async function action(callback: () => void) {
  await act(async () => callback()); await settle();
}

describe("assistant shared follow-up queue wiring", () => {
  it("projects native rows once and wires editing, reordering, pause/resume and withdrawal over IPC", async () => {
    await renderAssistant();
    // Check queue operations independently of the shell's initial bootstrap.
    vi.mocked(fetch).mockClear();
    expect(surface.composerVariant).toBe("codex");
    expect(surface.followupQueue?.map(item => item.id)).toEqual(["q1", "q2"]);
    expect(togglePause).toBeTypeOf("function");
    expect(container.querySelector("[data-launcher-assistant-queue]")).toBeNull();
    await action(() => surface.onFollowupQueueUpdate!("q1", "编辑后的内容"));
    expect(surface.followupQueue?.[0].text).toBe("编辑后的内容");
    await action(() => surface.onFollowupQueueMove!(0, 1));
    expect(surface.followupQueue?.map(item => item.id)).toEqual(["q2", "q1"]);
    await action(() => togglePause!("q2", true));
    expect(surface.followupQueue?.[0].status).toBe("paused");
    await action(() => togglePause!("q2", false));
    expect(surface.followupQueue?.[0].status).toBe("queued");
    await action(() => surface.onFollowupQueueRemove!("q2"));
    expect(surface.followupQueue?.map(item => item.id)).toEqual(["q1"]);
    expect(invoke).toHaveBeenCalledWith({ operation: "updateQueuedTurn", sessionId: "s", queuedTurnId: "q1", content: "编辑后的内容" });
    expect(invoke).toHaveBeenCalledWith({ operation: "removeQueuedTurn", sessionId: "s", queuedTurnId: "q2" });
    expect(client.getQueryData(["session", "s"])).toBeUndefined();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("restores failed writes and surfaces the queue error through the shared composer", async () => {
    await renderAssistant(); failOperation = "updateQueuedTurn";
    await action(() => surface.onFollowupQueueUpdate!("q1", "will fail"));
    expect(surface.followupQueue?.[0].text).toBe("消息 q1");
    expect(surface.composerError).toContain("queue write failed");
    failOperation = "removeQueuedTurn";
    await action(() => surface.onFollowupQueueRemove!("q1"));
    expect(surface.followupQueue?.map(item => item.id)).toEqual(["q1", "q2"]);
    expect(client.getQueryData<SessionDetail>(key)?.queuedTurns).toHaveLength(2);
  });

  it("steers text through existing guidance, withdraws once and preserves an unrelated composer draft", async () => {
    await renderAssistant();
    await action(() => surface.onComposerChange!("下一条尚未发送的草稿"));
    await action(() => { surface.onFollowupQueueSteer!("q1"); surface.onFollowupQueueSteer!("q1"); });
    expect(invoke).toHaveBeenCalledWith({ operation: "guidance", content: "消息 q1", mode: "safe" });
    expect(events).toEqual(["guidance", "removeQueuedTurn"]);
    expect(surface.composerValue).toBe("下一条尚未发送的草稿");
    expect(surface.followupQueue?.map(item => item.id)).toEqual(["q2"]);
  });

  it("marks attachment/reference/system messages ineligible for safe steering", async () => {
    await renderAssistant({ rows: [row("q1", 1, { references: [{ sessionId: "other" } as never] }),
      row("q2", 2, { attachments: [{ id: "attachment" } as never] }), row("q3", 3, { kind: "task_notification" })] });
    expect(surface.followupQueue?.every(item => item.canSteer === false)).toBe(true);
    await action(() => surface.onFollowupQueueSteer!("q1"));
    expect(events).toEqual([]);
    expect(surface.composerError).toContain("无法立即引导");
  });

  it("keeps a newer streamed queue when guidance arrives late and withdrawal fails", async () => {
    await renderAssistant();
    const lateDetail = { ...native, ledgerSeq: 1 };
    const originalInvoke = invoke.getMockImplementation()!;
    let releaseGuidance!: (value: SessionDetail) => void;
    invoke.mockImplementation((request: Record<string, unknown>) => request.operation === "guidance"
      ? new Promise<SessionDetail>(resolve => { releaseGuidance = resolve; }) : originalInvoke(request));
    failOperation = "removeQueuedTurn";
    await action(() => surface.onFollowupQueueSteer!("q1"));
    await action(() => client.setQueryData(key, { ...native, ledgerSeq: 4, queuedTurns: [row("q3", 1)] }));
    await action(() => releaseGuidance(lateDetail));
    expect(surface.followupQueue?.map(item => item.id)).toEqual(["q1", "q3"]);
    expect(client.getQueryData<SessionDetail>(key)?.ledgerSeq).toBe(4);
    expect(surface.composerError).toContain("queue write failed");
  });

  it("waits for resume and deduplicates send-now with the current native turn fence", async () => {
    await renderAssistant({ rows: [row("q1", 1, { status: "paused" }), row("q2", 2)] });
    resume = () => {};
    await action(() => togglePause!("q1", false));
    await action(() => { surface.onFollowupQueueSendNow!("q1"); surface.onFollowupQueueSendNow!("q1"); });
    expect(events).toEqual(["updateQueuedTurn"]);
    await action(() => resume!());
    expect(events).toEqual(["updateQueuedTurn", "sendNowQueuedTurn"]);
    expect(invoke).toHaveBeenCalledWith({ operation: "sendNowQueuedTurn", sessionId: "s", queuedTurnId: "q1", expectedTurnId: "turn-1" });
    expect(surface.followupQueue?.[0].sendNow).toBe(true);
  });

  it("keeps the read-only receipt fallback when an older host has no queue capability", async () => {
    await renderAssistant({ capability: false });
    expect(surface.followupQueue ?? []).toEqual([]);
    expect(surface.onFollowupQueueUpdate).toBeUndefined();
    expect(togglePause).toBeNull();
    expect(container.querySelector("[data-launcher-assistant-queue]")?.textContent).toContain("已排队");
  });
});
