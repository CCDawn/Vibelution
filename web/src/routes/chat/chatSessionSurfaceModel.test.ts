import { describe, expect, it } from "vitest";

import {
  buildAgentSessionTabs,
  buildChatActiveSkillViewModel,
  buildChatMentalStateViewModel,
  buildChatSessionStateViewModel,
  canLoadSessionParameters,
} from "./chatSessionSurfaceModel";

function buildDirectSessionStateModel(overrides: {
  detail?: unknown;
  directSessionActiveSummary?: unknown;
  runtimeSessionState?: string;
  runtimeSessionStateLine?: string;
} = {}) {
  const detail = "detail" in overrides
    ? overrides.detail
    : {
      id: "s1",
      title: "Hello",
      agentDisplayName: "Agent A",
      currentPhase: "ready",
      status: "ready",
      defaultFileContext: "src/app.ts",
      taskSummary: "working",
    };
  return buildChatSessionStateViewModel({
    lang: "zh",
    t: ((key: string) => key) as never,
    statusLabel: (value) => `status:${value}`,
    groupPanelActive: false,
    projectBusActive: false,
    activeSessionId: "s1",
    activeGroupRoomTitle: null,
    activeGroupRoomStatus: null,
    activeGroupRoomMode: null,
    activeGroupRoomPurpose: null,
    activeGroupRoundSummary: null,
    availableGroupParticipantCount: 0,
    projectBusActiveAgentCount: 0,
    detail: detail as never,
    directSessionActiveSummary: (overrides.directSessionActiveSummary ?? null) as never,
    runtimeMatchesSelectedSession: true,
    runtimeSessionState: overrides.runtimeSessionState ?? "",
    runtimeSessionStateLine: overrides.runtimeSessionStateLine ?? "",
    runtimeTaskSummary: "runtime task",
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
}

describe("chatSessionSurfaceModel", () => {
  it("loads parameters only after the selected session has an authoritative writable detail", () => {
    const detail = { id: "current", readOnly: false } as import("../../api/types").SessionDetail;
    expect(canLoadSessionParameters("current", undefined)).toBe(false);
    expect(canLoadSessionParameters("other", detail)).toBe(false);
    expect(canLoadSessionParameters("current", { ...detail, provisionalTranscript: true })).toBe(false);
    expect(canLoadSessionParameters("current", { ...detail, readOnly: true })).toBe(false);
    expect(canLoadSessionParameters("current", detail)).toBe(true);
    expect(canLoadSessionParameters("current", { ...detail, archiveState: { status: "archived", source: "session_archive" } })).toBe(true);
  });
  it("builds active skill summary and status labels", () => {
    const model = buildChatActiveSkillViewModel({
      contract: {
        status: "stale",
        command: "review",
        skillName: "Code Review",
        skillHash: "abcdef123456",
        keyRules: ["a", "b"],
      },
      lang: "zh",
      numberFormatter: new Intl.NumberFormat("zh-CN"),
      formatTime: (value) => value,
    });
    expect(model.activeSkillStatus).toBe("stale");
    expect(model.activeSkillStatusLabel).toBe("已变更");
    expect(model.activeSkillShortHash).toBe("abcdef12");
    expect(model.hasActiveSkill).toBe(true);
    expect(model.activeSkillSummary).toContain("/review");
  });

  it("builds mental compact line from confidence and source", () => {
    const model = buildChatMentalStateViewModel({
      mental: {
        mood: "calm",
        feeling: "steady",
        whisper: "ok",
        summary: "summary",
        cognitiveState: "normal",
        confidence: 0.82,
        sampleSize: 1,
        interventionCount: 0,
        updatedAt: "2026-01-01T00:00:00.000Z",
        source: "state",
      },
      lang: "en",
      t: ((key: string) => key) as never,
      locale: "en-US",
      nowMs: Date.parse("2026-01-01T01:00:00.000Z"),
    });
    expect(model.mentalStateLabel).toBe("calm");
    expect(model.mentalConfidence).toBe("82%");
    expect(model.mentalCompactLine).toContain("mentalSourceState");
  });

  it("never surfaces raw mental i18n keys as the badge label", () => {
    const model = buildChatMentalStateViewModel({
      mental: {
        mood: "mentalCognitiveState_unknown",
        cognitiveState: "unknown",
        confidence: 0,
        sampleSize: 0,
        interventionCount: 0,
        updatedAt: "",
        source: "unavailable",
      },
      lang: "zh",
      t: ((key: string) => (key === "mentalCognitiveState_unknown" ? "未判定" : key)) as never,
      locale: "zh-CN",
    });
    expect(model.mentalStateLabel).toBe("未判定");
    expect(model.mentalStateLabel).not.toContain("mentalCognitiveState_");
  });

  it("keeps an explicit ready Session at rest despite stale runtime thinking", () => {
    const model = buildDirectSessionStateModel({
      runtimeSessionState: "thinking",
      runtimeSessionStateLine: "thinking hard",
    });
    expect(model.activeSurfaceTitle).toBe("Agent A");
    expect(model.sessionStateValue).toBe("idle");
    expect(model.sessionStateLabel).toBe("空闲");
    expect(model.sessionStateLine).toBe("working");
    expect(model.sessionCompactRows[0]?.value).toBe("src/app.ts");
  });

  it("keeps a paused execution ahead of historical success", () => {
    const model = buildDirectSessionStateModel({
      detail: {
        id: "s1",
        status: "paused",
        currentPhase: "thinking",
        lastTurnStatus: "success",
        terminalReason: "completed",
        activeTurnId: "turn-current",
        lastTurnTerminalTurnId: "turn-old",
      },
      runtimeSessionState: "answering",
    });

    expect(model.sessionStateValue).toBe("paused");
    expect(model.sessionStateLabel).toBe("已暂停");
  });

  it("uses the detail execution status when its phase disagrees", () => {
    const model = buildDirectSessionStateModel({
      detail: { id: "s1", status: "running", currentPhase: "ready" },
    });

    expect(model.sessionStateValue).toBe("running");
    expect(model.sessionStateLabel).toBe("进行中");
  });

  it("prefers the Session phase and uses matching runtime activity only to fill a missing phase", () => {
    const authoritativePhase = buildDirectSessionStateModel({
      detail: { id: "s1", status: "running", currentPhase: "planning" },
      runtimeSessionState: "answering",
    });
    const refinedPhase = buildDirectSessionStateModel({
      detail: { id: "s1", status: "running", currentPhase: "" },
      runtimeSessionState: "thinking",
    });

    expect(authoritativePhase.sessionStateValue).toBe("planning");
    expect(authoritativePhase.sessionStateLabel).toBe("规划中");
    expect(refinedPhase.sessionStateValue).toBe("thinking");
    expect(refinedPhase.sessionStateLabel).toBe("思考中");
  });

  it("uses the summary when detail is absent and hides unknown raw activity", () => {
    const model = buildDirectSessionStateModel({
      detail: null,
      directSessionActiveSummary: { id: "s1", status: "unrecognized_phase", currentPhase: "" },
      runtimeSessionState: "thinking",
    });

    expect(model.sessionStateValue).toBe("unknown");
    expect(model.sessionStateLabel).toBe("未知状态");
    expect(model.sessionStateLabel).not.toContain("unrecognized_phase");
    expect(model.sessionStateValue).not.toContain("unrecognized_phase");
  });

  it("keeps Agent session tab order stable when activity timestamps change", () => {
    const tabs = buildAgentSessionTabs({
      sessions: [
        { id: "child", sessionKind: "child", createdAt: "2026-01-02", updatedAt: "2026-08-14T12:00:00Z" } as never,
        { id: "primary", sessionKind: "direct", createdAt: "2026-01-01", updatedAt: "2026-08-14T12:00:02Z" } as never,
        { id: "other", sessionKind: "direct", createdAt: "2026-01-03", updatedAt: "2026-08-14T12:00:01Z" } as never,
      ],
      selectedChatAgentDirectSessionId: "primary",
    });
    expect(tabs.map((item) => item.id)).toEqual(["primary", "child", "other"]);
  });

  it("removes archived sessions from ordinary Agent tabs even when cached lists retain them", () => {
    const tabs = buildAgentSessionTabs({
      sessions: [
        { id: "active", createdAt: "2026-01-01", updatedAt: "2026-08-14T12:00:00Z" } as never,
        { id: "archived", createdAt: "2026-01-02", updatedAt: "2026-08-14T12:00:01Z", archiveState: { status: "archived" } } as never,
      ],
      selectedChatAgentDirectSessionId: "active",
    });
    expect(tabs.map((item) => item.id)).toEqual(["active"]);
  });

  it("does not reshuffle tabs when a background session becomes more recent", () => {
    const first = buildAgentSessionTabs({
      sessions: [
        { id: "alpha", createdAt: "2026-01-01", updatedAt: "2026-08-14T10:00:00Z" } as never,
        { id: "beta", createdAt: "2026-01-02", updatedAt: "2026-08-14T10:00:01Z" } as never,
      ],
      selectedChatAgentDirectSessionId: "alpha",
    });
    const afterBackgroundActivity = buildAgentSessionTabs({
      sessions: [
        { id: "alpha", createdAt: "2026-01-01", updatedAt: "2026-08-14T10:00:01Z" } as never,
        { id: "beta", createdAt: "2026-01-02", updatedAt: "2026-08-14T10:00:09Z" } as never,
      ],
      selectedChatAgentDirectSessionId: "alpha",
    });
    expect(first.map((item) => item.id)).toEqual(["alpha", "beta"]);
    expect(afterBackgroundActivity.map((item) => item.id)).toEqual(["alpha", "beta"]);
  });
});
