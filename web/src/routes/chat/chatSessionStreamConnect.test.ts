import { describe, expect, it } from "vitest";

import {
  nextSessionStreamGraceWindow,
  resolveSessionStreamRouteSettling,
  resolveSessionStreamRouteSwitchGraceActive,
  resolveSessionStreamRouteTargetMatches,
  resolveSessionStreamShouldConnect,
  SESSION_STREAM_ROUTE_SWITCH_GRACE_MS,
} from "./chatSessionStreamConnect";

describe("chatSessionStreamConnect", () => {
  it("matches route target only for the active direct session", () => {
    expect(resolveSessionStreamRouteTargetMatches({
      activeSessionId: "s1",
      groupPanelActive: false,
      requestedSessionId: "",
    })).toBe(true);
    expect(resolveSessionStreamRouteTargetMatches({
      activeSessionId: "s1",
      groupPanelActive: false,
      requestedSessionId: "s1",
    })).toBe(true);
    expect(resolveSessionStreamRouteTargetMatches({
      activeSessionId: "s1",
      groupPanelActive: false,
      requestedSessionId: "s2",
    })).toBe(false);
    expect(resolveSessionStreamRouteTargetMatches({
      activeSessionId: "s1",
      groupPanelActive: true,
      requestedSessionId: "s1",
    })).toBe(false);
  });

  it("detects route settling when requested session lags the store", () => {
    expect(resolveSessionStreamRouteSettling({
      activeSessionId: "s1",
      groupPanelActive: false,
      requestedSessionId: "s2",
    })).toBe(true);
    expect(resolveSessionStreamRouteSettling({
      activeSessionId: "s1",
      groupPanelActive: false,
      requestedSessionId: "s1",
    })).toBe(false);
  });

  it("opens a grace window only when the active session changes", () => {
    const first = nextSessionStreamGraceWindow({
      activeSessionId: "s1",
      currentGraceSessionId: "",
      currentGraceUntilMs: 0,
      nowMs: 1000,
    });
    expect(first.changed).toBe(true);
    expect(first.graceSessionId).toBe("s1");
    expect(first.graceUntilMs).toBe(1000 + SESSION_STREAM_ROUTE_SWITCH_GRACE_MS);

    const same = nextSessionStreamGraceWindow({
      activeSessionId: "s1",
      currentGraceSessionId: first.graceSessionId,
      currentGraceUntilMs: first.graceUntilMs,
      nowMs: 1500,
    });
    expect(same.changed).toBe(false);
    expect(same.graceUntilMs).toBe(first.graceUntilMs);
  });

  it("connects when polling is visible or grace is active", () => {
    expect(resolveSessionStreamShouldConnect({
      activeSessionId: "s1",
      routeTargetMatches: true,
      chatPollingVisible: true,
      routeSwitchGraceActive: false,
    })).toBe(true);
    expect(resolveSessionStreamShouldConnect({
      activeSessionId: "s1",
      routeTargetMatches: true,
      chatPollingVisible: false,
      routeSwitchGraceActive: true,
    })).toBe(true);
    expect(resolveSessionStreamShouldConnect({
      activeSessionId: "s1",
      routeTargetMatches: true,
      chatPollingVisible: false,
      routeSwitchGraceActive: false,
    })).toBe(false);
  });

  it("evaluates grace active window", () => {
    expect(resolveSessionStreamRouteSwitchGraceActive({
      activeSessionId: "s1",
      routeTargetMatches: true,
      graceSessionId: "s1",
      graceUntilMs: 2000,
      nowMs: 1500,
    })).toBe(true);
    expect(resolveSessionStreamRouteSwitchGraceActive({
      activeSessionId: "s1",
      routeTargetMatches: true,
      graceSessionId: "s1",
      graceUntilMs: 2000,
      nowMs: 2000,
    })).toBe(false);
  });
});
