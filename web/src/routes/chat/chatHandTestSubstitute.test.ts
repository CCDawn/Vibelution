/**
 * Hand-test substitute suite for ChatCodingRoute split regressions.
 *
 * Maps the manual smoke checklist to deterministic automated checks:
 * pure view-models, SSR markup, stream ownership contracts, and optional
 * live runtime probes when the workbench is already up.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { planAppliedAssistantDeltaDrain } from "../chatStreamApplyController";
import { routeSessionStreamEvent } from "../chatSessionStreamProtocol";
import {
  buildChatActiveSkillViewModel,
  buildChatSessionStateViewModel,
  buildAgentSessionTabs,
} from "./chatSessionSurfaceModel";
import { buildChatTokenStatusViewModel } from "./chatTokenStatusModel";
import { buildChatCacheDetailViewModel } from "./chatCacheDetailModel";
import {
  isCliAgentRunActiveForClose,
  cliAgentRunTabId,
  cliAgentRunIdFromTabId,
} from "./cliAgentRunModel";
import { resolveSessionStreamShouldConnect } from "./chatSessionStreamConnect";

const routeSource = readFileSync(resolve(import.meta.dirname, "../ChatCodingRoute.tsx"), "utf8");
const sessionStreamSource = readFileSync(resolve(import.meta.dirname, "useSessionDetailStream.ts"), "utf8");
const groupStreamSource = readFileSync(resolve(import.meta.dirname, "useGroupRoomStream.ts"), "utf8");
const cacheDialogSource = readFileSync(resolve(import.meta.dirname, "useChatCacheDetailDialog.ts"), "utf8");
const cliTerminalHookSource = readFileSync(resolve(import.meta.dirname, "useChatCliAgentTerminal.ts"), "utf8");

const t = ((key: string) => key) as never;
const numberFormatter = new Intl.NumberFormat("zh-CN");
const compactNumberFormatter = new Intl.NumberFormat("zh-CN", { notation: "compact", maximumFractionDigits: 1 });

describe("chat hand-test substitute: direct session surface", () => {
  it("shows ready direct session title/status without group bus copy", () => {
    const model = buildChatSessionStateViewModel({
      lang: "zh",
      t,
      statusLabel: (value) => `status:${value}`,
      groupPanelActive: false,
      projectBusActive: false,
      activeSessionId: "session-1",
      activeGroupRoomTitle: null,
      activeGroupRoomStatus: null,
      activeGroupRoomMode: null,
      activeGroupRoomPurpose: null,
      activeGroupRoundSummary: null,
      availableGroupParticipantCount: 0,
      projectBusActiveAgentCount: 0,
      detail: {
        id: "session-1",
        title: "会话A",
        agentDisplayName: "周望舒",
        currentPhase: "ready",
        status: "ready",
        defaultFileContext: "src/app.ts",
        taskSummary: "待命",
      } as never,
      directSessionActiveSummary: null,
      runtimeMatchesSelectedSession: true,
      runtimeSessionState: "idle",
      runtimeSessionStateLine: "会话空闲",
      runtimeTaskSummary: "",
      runtimeDefaultRoute: "workspace",
      runtimeMismatchLine: "",
      sessionDetailBlockingError: false,
      sessionDetailErrorMessage: "",
      sessionDetailLoadingForActiveSession: false,
      activeAgentStatusMessage: "",
      latestControlSignalLine: "",
      latestControlSignalTitle: "",
      hasLatestControlSignal: false,
    });
    expect(model.activeSurfaceTitle).toBe("周望舒");
    expect(model.sessionStateLine).toBe("会话空闲");
    expect(model.sessionStateValue).toBe("idle");
    expect(model.sessionCompactRows.some((row) => row.value === "src/app.ts")).toBe(true);
  });

  it("compacts provider/turn failure into status line for status rail", () => {
    const model = buildChatSessionStateViewModel({
      lang: "zh",
      t,
      statusLabel: (value) => value,
      groupPanelActive: false,
      projectBusActive: false,
      activeSessionId: "session-1",
      activeGroupRoomTitle: null,
      activeGroupRoomStatus: null,
      activeGroupRoomMode: null,
      activeGroupRoomPurpose: null,
      activeGroupRoundSummary: null,
      availableGroupParticipantCount: 0,
      projectBusActiveAgentCount: 0,
      detail: {
        id: "session-1",
        title: "会话A",
        agentDisplayName: "Agent",
        currentPhase: "failed",
        status: "failed",
        defaultFileContext: "workspace",
        lastTurnError: { httpStatus: 429, reasonCode: "rate_limited", message: "too many" },
      } as never,
      directSessionActiveSummary: null,
      runtimeMatchesSelectedSession: false,
      runtimeSessionState: "",
      runtimeSessionStateLine: "",
      runtimeTaskSummary: "",
      runtimeDefaultRoute: "workspace",
      runtimeMismatchLine: "",
      sessionDetailBlockingError: false,
      sessionDetailErrorMessage: "",
      sessionDetailLoadingForActiveSession: false,
      activeAgentStatusMessage: "",
      latestControlSignalLine: "",
      latestControlSignalTitle: "",
      hasLatestControlSignal: false,
    });
    // compact line prefers httpStatus then reasonCode
    expect(model.compactSessionStateLine).toContain("429");
    expect(model.compactSessionStateLine).toMatch(/failed|429/);
  });

  it("surfaces historical-session binding mismatch for switch action", () => {
    const model = buildChatSessionStateViewModel({
      lang: "zh",
      t,
      statusLabel: (value) => value,
      groupPanelActive: false,
      projectBusActive: false,
      activeSessionId: "session-old",
      activeGroupRoomTitle: null,
      activeGroupRoomStatus: null,
      activeGroupRoomMode: null,
      activeGroupRoomPurpose: null,
      activeGroupRoundSummary: null,
      availableGroupParticipantCount: 0,
      projectBusActiveAgentCount: 0,
      detail: {
        id: "session-old",
        title: "旧会话",
        agentDisplayName: "Agent",
        currentPhase: "ready",
        status: "ready",
        defaultFileContext: "workspace",
        agentDirectSessionMismatch: true,
        agentPrimaryDirectSessionId: "session-primary",
      } as never,
      directSessionActiveSummary: null,
      runtimeMatchesSelectedSession: true,
      runtimeSessionState: "idle",
      runtimeSessionStateLine: "ok",
      runtimeTaskSummary: "",
      runtimeDefaultRoute: "workspace",
      runtimeMismatchLine: "",
      sessionDetailBlockingError: false,
      sessionDetailErrorMessage: "",
      sessionDetailLoadingForActiveSession: false,
      activeAgentStatusMessage: "",
      latestControlSignalLine: "",
      latestControlSignalTitle: "",
      hasLatestControlSignal: false,
    });
    expect(model.agentDirectSessionMismatch).toBe(true);
    expect(model.agentPrimaryDirectSessionId).toBe("session-primary");
    expect(model.sessionCompactRows.some((row) => row.label === "sessionBinding")).toBe(true);
  });
});

describe("chat hand-test substitute: token/cache panel", () => {
  it("builds four core metrics with provider cache hit percent", () => {
    const cache = buildChatCacheDetailViewModel({
      detail: undefined,
      lastCacheComposition: {
        source: "provider_usage",
        inputTokens: 1000,
        cachedInputTokens: 400,
        uncachedInputTokens: 600,
        cacheHitRate: 0.4,
        calibratedInputTokens: 1000,
        calibratedCachedInputTokens: 400,
        cacheCreationInputTokens: 0,
      } as never,
      lastCacheDiagnostics: {
        upperBoundInputTokens: 1000,
        upperBoundCachedInputTokens: 500,
        upperBoundCacheHitRate: 0.5,
      } as never,
      lang: "zh",
      t,
      numberFormatter,
    });
    const token = buildChatTokenStatusViewModel({
      detail: {
        llmUsage: {
          source: "provider_usage",
          inputTokens: 1000,
          outputTokens: 200,
          totalTokens: 1200,
          cachedInputTokens: 400,
          cacheCreationInputTokens: 0,
          uncachedInputTokens: 600,
          cacheHitRate: 0.4,
        },
      } as never,
      lastCacheComposition: {
        source: "provider_usage",
        calibratedInputTokens: 1000,
        calibratedCachedInputTokens: 400,
        inputTokens: 1000,
        cachedInputTokens: 400,
        cacheHitRate: 0.4,
      } as never,
      lastContextComposition: { limitTokens: 200000, totalTokens: 5000 } as never,
      compression: {
        enabled: true,
        currentTokens: 8000,
        effectiveTokenLimit: 100000,
        contextWindowLimit: 200000,
        usageRatio: 0.08,
        currentLevel: "normal",
        source: "runtime_state",
        policySource: "global",
        strategy: { levels: [], preserveErrors: true, errorProtectionKeywords: [], summaryStorage: "", algorithm: "" },
        lastCompression: null,
        compressionCount: 0,
        updatedAt: "",
      } as never,
      cache: {
        cacheDetailAvailable: cache.cacheDetailAvailable,
        cacheCompositionPercent: cache.cacheCompositionPercent,
        providerCachedInputTokens: cache.providerCachedInputTokens,
        providerCacheInputTokens: cache.providerCacheInputTokens,
        cacheCompositionSummary: cache.cacheCompositionSummary,
        cacheDetailOpenLabel: cache.cacheDetailOpenLabel,
        cacheCompositionTitle: cache.cacheCompositionTitle,
      },
      tokenSpeedTracker: { tokensPerSecond: 12.4, tokenCount: 88 } as never,
      activeSessionId: "session-1",
      groupPanelActive: false,
      sessionStateValue: "answering",
      sessionStateLabel: "回答中",
      sessionStateLine: "生成中",
      lang: "zh",
      t,
      numberFormatter,
      compactNumberFormatter,
      locale: "zh-CN",
      formatTime: (value) => value,
    });
    expect(token.tokenStatusMetrics.map((item) => item.key)).toEqual(["cache", "modelInput", "compression", "speed"]);
    expect(token.tokenStatusMetrics[0]?.value).toBe("40%");
    expect(token.tokenStatusMetrics[1]?.value).not.toBe("--");
    expect(token.tokenStatusMetrics[2]?.value).toBe("8%");
    expect(token.tokenStatusMetrics[3]?.value).toMatch(/t\/s|12/);
    expect(cache.cacheDetailAvailable).toBe(true);
    expect(cache.cacheDetailOpenLabel).toContain("缓存");
  });

  it("keeps cache dialog Escape close contract after split", () => {
    expect(cacheDialogSource).toContain("event.key === \"Escape\"");
    expect(cacheDialogSource).toContain("closeCacheDetail");
    expect(routeSource).toContain("useChatCacheDetailDialog");
    expect(routeSource).toContain("buildChatCacheDetailViewModel");
  });
});

describe("chat hand-test substitute: CLI terminal lifecycle", () => {
  it("wires open tab id + close-stop confirmation path", () => {
    expect(cliAgentRunIdFromTabId(cliAgentRunTabId("run-7"))).toBe("run-7");
    expect(isCliAgentRunActiveForClose(
      { id: "run-7", status: "running", terminalSessionId: "term-7" } as never,
      { alive: true, status: "running", terminalSessionId: "term-7" } as never,
    )).toBe(true);
    expect(cliTerminalHookSource).toContain("window.confirm(");
    expect(cliTerminalHookSource).toContain("/api/cli-agents/terminal-sessions/");
    expect(cliTerminalHookSource).toContain("/stop");
    expect(routeSource).toContain("useChatCliAgentTerminal");
    expect(routeSource).toContain("<ChatCliAgentTerminalStack");
  });
});

describe("chat hand-test substitute: stream ownership + apply", () => {
  it("keeps sole session/group EventSource owners and route wiring", () => {
    expect(sessionStreamSource).toContain("new EventSource(`/api/sessions/${streamSessionId}/events?initial=none`)");
    expect(sessionStreamSource).not.toContain("/events?initial=light");
    expect(groupStreamSource).toContain("new EventSource(`/api/chat-rooms/${streamRoomId}/events`)");
    expect(routeSource).toContain("useSessionDetailStream");
    expect(routeSource).toContain("useGroupRoomStream");
    // route itself must not open these two EventSources
    expect(routeSource).not.toContain("new EventSource(`/api/sessions/");
    expect(routeSource).not.toContain("new EventSource(`/api/chat-rooms/");
  });

  it("applies assistant delta drain and commits rendered answer text", () => {
    const decision = planAppliedAssistantDeltaDrain({
      streamSessionId: "session-1",
      reason: "frame",
      drain: {
        reason: "frame",
        mode: "smooth",
        entries: [
          {
            payload: {
              type: "assistant_delta",
              sessionId: "session-1",
              turnId: "turn-1",
              ledgerSeq: 2,
              stage: "responding",
              content: "",
              thought: "",
              contentDelta: "你好，世界",
              thoughtDelta: "",
              replaceContent: false,
              replaceThought: false,
              feedbackEvents: [],
              updatedAt: "2026-07-20T00:00:01Z",
              done: false,
            },
            payloadLength: 12,
            receivedAtMs: 100,
          },
        ],
        pendingBefore: 1,
        pendingAfter: 0,
        batchSize: 1,
        oldestQueuedAgeMs: 0,
        shouldContinue: false,
        telemetry: {
          payloadLength: 12,
          turnId: "turn-1",
          stage: "responding",
          contentDeltaLength: 5,
          thoughtDeltaLength: 0,
          batchSize: 1,
          done: false,
          oldestReceivedAtMs: 100,
          newestReceivedAtMs: 100,
          frameScheduledAtMs: 90,
          turnRenderProtocol: "legacy_assistant_delta",
        },
      } as never,
      committedLayer: {
        id: "layer-1",
        sessionId: "session-1",
        turnId: "turn-1",
        updatedAt: "2026-07-20T00:00:00Z",
        streaming: true,
        processStage: "responding",
        answerContent: "你好",
        thoughtContent: "",
        toolCalls: [],
      } as never,
      stats: { received: 1, applied: 0, dropped: 0 },
      applyStartedAtMs: 100,
      applyFinishedAtMs: 120,
    });
    expect(decision.applied).toBe(true);
    if (!decision.applied) {
      throw new Error("expected applied assistant delta");
    }
    expect(decision.nextCommittedLayer?.answerContent || "").toContain("你好");
    expect(decision.appliedPayloadCount).toBe(1);
  });

  it("routes assistant_delta payloads with explicit protocol acceptance", () => {
    const routed = routeSessionStreamEvent({
      activeSessionId: "session-1",
      expectedType: "assistant_delta",
      rawData: JSON.stringify({
        type: "assistant_delta",
        sessionId: "session-1",
        turnId: "turn-1",
        ledgerSeq: 2,
        stage: "responding",
        content: "",
        thought: "",
        contentDelta: "hello",
        thoughtDelta: "",
        replaceContent: false,
        replaceThought: false,
        feedbackEvents: [],
        updatedAt: "2026-07-20T00:00:00Z",
        done: false,
      }),
    });
    expect(routed.accepted).toBe(true);
    if (!routed.accepted) {
      throw new Error("expected accepted assistant_delta");
    }
    expect(routed.trace.eventRoute).toBe("assistant_delta");
  });

  it("connects stream only when route decision says connect", () => {
    expect(routeSource).toContain("resolveSessionStreamShouldConnect");
    expect(resolveSessionStreamShouldConnect({
      activeSessionId: "session-1",
      routeTargetMatches: true,
      chatPollingVisible: true,
      routeSwitchGraceActive: false,
    })).toBe(true);
    expect(resolveSessionStreamShouldConnect({
      activeSessionId: "session-1",
      routeTargetMatches: false,
      chatPollingVisible: true,
      routeSwitchGraceActive: false,
    })).toBe(false);
  });
});

describe("chat hand-test substitute: group/project-bus wiring", () => {
  it("keeps center surface extraction and action handler wiring", () => {
    expect(routeSource).toContain("<ChatGroupCenterSurface");
    expect(routeSource).toContain("onSendProjectBusMessage={handleSendProjectBusMessage}");
    expect(routeSource).toContain("onStartGroupRound={handleStartGroupRound}");
    expect(routeSource).toContain("onStopGroupRound={handleStopGroupRound}");
    expect(routeSource).toContain("onRevokeProjectBusMessage={handleRevokeProjectBusMessage}");
  });

  it("shows project-bus surface copy in session state when bus active", () => {
    const model = buildChatSessionStateViewModel({
      lang: "zh",
      t,
      statusLabel: (value) => value,
      groupPanelActive: true,
      projectBusActive: true,
      activeSessionId: "",
      activeGroupRoomTitle: null,
      activeGroupRoomStatus: "ready",
      activeGroupRoomMode: "round_robin",
      activeGroupRoomPurpose: "discussion",
      activeGroupRoundSummary: null,
      availableGroupParticipantCount: 0,
      projectBusActiveAgentCount: 4,
      detail: null,
      directSessionActiveSummary: null,
      runtimeMatchesSelectedSession: false,
      runtimeSessionState: "",
      runtimeSessionStateLine: "",
      runtimeTaskSummary: "",
      runtimeDefaultRoute: "",
      runtimeMismatchLine: "",
      sessionDetailBlockingError: false,
      sessionDetailErrorMessage: "",
      sessionDetailLoadingForActiveSession: false,
      activeAgentStatusMessage: "",
      latestControlSignalLine: "",
      latestControlSignalTitle: "",
      hasLatestControlSignal: false,
    });
    expect(model.activeSurfaceTitle).toBe("助手通知流");
    expect(model.activeSurfaceLine).toContain("4");
    expect(model.activeSurfaceLine).toContain("全局广播");
  });
});

describe("chat hand-test substitute: agent tabs + skill chip", () => {
  it("sorts flat Agent sessions by recent activity for the top strip", () => {
    const tabs = buildAgentSessionTabs({
      sessions: [
        { id: "other", sessionKind: "direct", updatedAt: "2026-07-20T03:00:00Z" } as never,
        { id: "child", sessionKind: "child", updatedAt: "2026-07-20T02:00:00Z" } as never,
        { id: "primary", sessionKind: "direct", updatedAt: "2026-07-20T01:00:00Z" } as never,
      ],
      selectedChatAgentDirectSessionId: "primary",
    });
    expect(tabs.map((item) => item.id)).toEqual(["other", "child", "primary"]);
  });

  it("builds stale skill chip labels for status rail", () => {
    const skill = buildChatActiveSkillViewModel({
      contract: { status: "stale", command: "review", skillName: "Review", skillHash: "deadbeef00" },
      lang: "zh",
      numberFormatter,
      formatTime: (value) => value,
    });
    expect(skill.hasActiveSkill).toBe(true);
    expect(skill.activeSkillStatusLabel).toBe("已变更");
    expect(routeSource).toContain("buildChatActiveSkillViewModel");
  });
});

const liveWorkbenchBase = process.env.VIBELUTION_WORKBENCH_BASE?.trim();

describe("chat hand-test substitute: optional live runtime probe", () => {
  it.skipIf(!liveWorkbenchBase)("probes health/sessions/chat/sse when explicitly enabled", async () => {
    const base = liveWorkbenchBase!;
    const health = await fetch(`${base}/api/health`, { signal: AbortSignal.timeout(2500) });
    expect(health.ok).toBe(true);
    const healthJson = await health.json() as { status?: string };
    expect(healthJson.status).toBe("ok");

    const sessionsRes = await fetch(`${base}/api/sessions`, { signal: AbortSignal.timeout(5000) });
    expect(sessionsRes.ok).toBe(true);
    const sessions = await sessionsRes.json() as Array<{ id?: string }> | { items?: Array<{ id?: string }> };
    const list = Array.isArray(sessions) ? sessions : (sessions.items ?? []);
    expect(list.length).toBeGreaterThan(0);
    const sessionId = String(list[0]?.id || "");
    expect(sessionId).toBeTruthy();

    const detailRes = await fetch(`${base}/api/sessions/${encodeURIComponent(sessionId)}`, {
      signal: AbortSignal.timeout(8000),
    });
    expect(detailRes.ok).toBe(true);

    const chatRes = await fetch(`${base}/chat`, { signal: AbortSignal.timeout(5000) });
    expect(chatRes.ok).toBe(true);

    const sseRes = await fetch(
      `${base}/api/sessions/${encodeURIComponent(sessionId)}/events?initial=light`,
      { signal: AbortSignal.timeout(3000) },
    );
    expect(sseRes.ok).toBe(true);
    const reader = sseRes.body?.getReader();
    expect(reader).toBeTruthy();
    if (!reader) {
      return;
    }
    const { value } = await reader.read();
    reader.cancel().catch(() => undefined);
    const text = value ? new TextDecoder().decode(value) : "";
    expect(text).toContain("session_initial");
  }, 20_000);
});
