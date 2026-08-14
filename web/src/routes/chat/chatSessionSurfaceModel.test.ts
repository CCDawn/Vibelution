import { describe, expect, it } from "vitest";

import {
  buildAgentSessionTabs,
  buildChatActiveSkillViewModel,
  buildChatMentalStateViewModel,
  buildChatPetCompanionViewModel,
  buildChatSessionStateViewModel,
} from "./chatSessionSurfaceModel";

describe("chatSessionSurfaceModel", () => {
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

  it("builds pet vitals and companion line", () => {
    const model = buildChatPetCompanionViewModel({
      pet: {
        hunger: 80,
        energy: 80,
        health: 90,
        love: 70,
        totalTokens: 1200,
        heartActive: true,
        inDream: false,
        avatarPreset: "cat",
        name: "Mika",
      } as never,
      petQueryError: false,
      petQueryErrorMessage: "",
      petActionPending: false,
      lang: "en",
      t: ((key: string) => key) as never,
      numberFormatter: new Intl.NumberFormat("en-US"),
    });
    expect(model.petVitals).toHaveLength(4);
    expect(model.petAvatarPresetKey).toBe("cat");
    expect(model.petCompanionLine).toBe("petCompanionStable");
  });

  it("builds session surface and compact rows for direct session", () => {
    const model = buildChatSessionStateViewModel({
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
      detail: {
        id: "s1",
        title: "Hello",
        agentDisplayName: "Agent A",
        currentPhase: "idle",
        status: "ready",
        defaultFileContext: "src/app.ts",
        taskSummary: "working",
      } as never,
      directSessionActiveSummary: null,
      runtimeMatchesSelectedSession: true,
      runtimeSessionState: "thinking",
      runtimeSessionStateLine: "thinking hard",
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
    expect(model.activeSurfaceTitle).toBe("Agent A");
    expect(model.sessionStateLabel).toBe("sessionStateThinking");
    expect(model.sessionStateLine).toBe("thinking hard");
    expect(model.sessionCompactRows[0]?.value).toBe("src/app.ts");
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
