import { describe, expect, it } from "vitest";

import { FetchJsonHttpError } from "../../api/client";
import {
  CHAT_SUBMIT_ERROR_KIND_KEYS,
  classifyChatSubmitErrorKind,
  describeChatRouteError,
  describeChatSubmitError,
  formatTokenSpeedValue,
  getResizeBounds,
  isBusyPhase,
  normalizePanelWidths,
  formatChatRuntimeMismatchLine,
  runtimeMatchesSelectedChatSession,
  shouldSuppressComposerErrorForTurnError,
} from "./chatCodingRouteViewModel";
import { dictionaryChat } from "../../i18n/domains/dictionaryChat";

describe("chat coding route view model", () => {
  it("keeps side panel widths within the available center-first shell", () => {
    expect(normalizePanelWidths(900, 560, 520)).toEqual({
      leftPanelWidth: 260,
      rightPanelWidth: 200,
    });
  });

  it("derives resize bounds from the reserved center conversation width", () => {
    expect(getResizeBounds("left", 900, 200)).toEqual({ min: 260, max: 260 });
    expect(getResizeBounds("right", 1200, 260)).toEqual({ min: 200, max: 200 });
  });

  it("classifies only active or stopping phases as busy", () => {
    expect(isBusyPhase("thinking")).toBe(true);
    expect(isBusyPhase("stopping")).toBe(true);
    expect(isBusyPhase("ready")).toBe(false);
  });

  it("formats token speed without inventing a value for missing samples", () => {
    expect(formatTokenSpeedValue(0.4)).toBe("<1 t/s");
    expect(formatTokenSpeedValue(3.6)).toBe("4 t/s");
    expect(formatTokenSpeedValue(0)).toBe("");
  });

  it("describes other running sessions without using a sorted first id", () => {
    expect(formatChatRuntimeMismatchLine({
      otherRunningSessionIds: ["session-flash"],
      resolveSessionLabel: () => "[stress] fl1",
      lang: "zh",
    })).toBe("运行器正在处理：[stress] fl1");
    expect(formatChatRuntimeMismatchLine({
      otherRunningSessionIds: ["session-ds", "session-flash"],
      resolveSessionLabel: () => "OpenCode DeepSeek Pro",
      lang: "zh",
    })).toBe("另有 2 个会话在运行");
    expect(formatChatRuntimeMismatchLine({
      otherRunningSessionIds: [],
      resolveSessionLabel: () => "ignored",
      lang: "en",
    })).toBe("");
  });

  it("keeps idle active-session runtime telemetry attached to the selected session", () => {
    expect(runtimeMatchesSelectedChatSession({
      selectedSessionId: "session-luna",
      activeRuntimeSessionId: "session-luna",
      activeWorkSessionIds: [],
    })).toBe(true);
    expect(runtimeMatchesSelectedChatSession({
      selectedSessionId: "session-other",
      activeRuntimeSessionId: "session-luna",
      activeWorkSessionIds: [],
    })).toBe(false);
    expect(runtimeMatchesSelectedChatSession({
      selectedSessionId: "session-luna",
      activeRuntimeSessionId: "session-other",
      activeWorkSessionIds: ["session-luna"],
    })).toBe(true);
  });

  it("suppresses composer errors already visible in the latest turn failure", () => {
    expect(shouldSuppressComposerErrorForTurnError(
      "Submit failed: Provider timeout",
      "provider timeout",
      { message: "Provider timeout", errorType: "provider_timeout" },
    )).toBe(true);
  });

  it("keeps fallback error text when no Error message exists", () => {
    expect(describeChatRouteError(new Error("network down"), "Load failed")).toBe("Load failed: network down");
    expect(describeChatRouteError("plain failure", "Load failed")).toBe("Load failed");
  });

  it("classifies direct submit failures by status and transport kind", () => {
    const httpError = (status: number) => new FetchJsonHttpError("raw transport text", { status });
    expect(classifyChatSubmitErrorKind(httpError(409))).toBe("turn_in_progress");
    expect(classifyChatSubmitErrorKind(httpError(401))).toBe("auth_failed");
    expect(classifyChatSubmitErrorKind(httpError(403))).toBe("auth_failed");
    expect(classifyChatSubmitErrorKind(httpError(429))).toBe("rate_limited");
    expect(classifyChatSubmitErrorKind(httpError(503))).toBe("upstream_unavailable");
    expect(classifyChatSubmitErrorKind(httpError(400))).toBe("request_rejected");
    expect(classifyChatSubmitErrorKind(new TypeError("Failed to fetch"))).toBe("network");
    expect(classifyChatSubmitErrorKind(new Error("conversation stream reset"))).toBe("");
    expect(classifyChatSubmitErrorKind("plain failure")).toBe("");
  });

  it("answers submit failures with human category copy and keeps the raw text out", () => {
    // The submit path resolves chat-domain keys via the app dictionary; the
    // core-domain fallback key (submitFailed) is stubbed so the assertion
    // shows the fallback is used verbatim for unclassifiable errors.
    const t = (key: Parameters<typeof describeChatSubmitError>[1] extends (k: infer K) => string ? K : never) =>
      (dictionaryChat.zh as Record<string, string>)[key] ?? `#${key}`;
    const conflictCopy = describeChatSubmitError(
      new FetchJsonHttpError("raw transport text", { status: 409 }),
      t,
      t("submitFailed"),
    );
    expect(conflictCopy).toBe(dictionaryChat.zh.composerErrorTurnInProgress);
    expect(conflictCopy).not.toContain("raw transport text");

    const unclassifiedCopy = describeChatSubmitError(new Error("stream reset"), t, t("submitFailed"));
    expect(unclassifiedCopy).toBe("#submitFailed");
    expect(unclassifiedCopy).not.toContain("stream reset");
  });

  it("maps every submit error category to a key present in both dictionary languages", () => {
    for (const key of Object.values(CHAT_SUBMIT_ERROR_KIND_KEYS)) {
      expect(dictionaryChat.zh[key], `zh missing for ${key}`).toBeTruthy();
      expect(dictionaryChat.en[key], `en missing for ${key}`).toBeTruthy();
    }
  });
});
