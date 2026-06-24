import { describe, expect, it } from "vitest";

import {
  appendReturnNavigationEntry,
  consumeReturnNavigationTarget,
  fallbackReturnRoute,
  parseReturnNavigationStack,
  resolveReturnTarget,
  routeLocationKey,
  safeReturnToPath,
  serializeReturnNavigationStack,
} from "./navigationReturn";

describe("navigation return contract", () => {
  it("keeps only same-origin relative return paths", () => {
    expect(safeReturnToPath("/teams?team=research-team#stage")).toBe("/teams?team=research-team#stage");
    expect(safeReturnToPath("https://example.com/teams")).toBe("");
    expect(safeReturnToPath("//example.com/teams")).toBe("");
    expect(safeReturnToPath("/\\example")).toBe("");
    expect(safeReturnToPath("")).toBe("");
  });

  it("builds stable route keys from pathname search and hash", () => {
    expect(routeLocationKey({ pathname: "/chat", search: "?session=s1", hash: "#run" })).toBe("/chat?session=s1#run");
  });

  it("prioritizes explicit returnTo before internal stack and fallback routes", () => {
    expect(
      resolveReturnTarget(
        { pathname: "/chat", search: "?session=s1&returnTo=%2Fteams%3Fteam%3Dresearch-team&returnLabel=Back" },
        [{ path: "/agents" }],
      ),
    ).toEqual({ path: "/teams?team=research-team", source: "explicit" });
  });

  it("uses the last different internal stack entry when no explicit source exists", () => {
    expect(
      resolveReturnTarget(
        { pathname: "/agents", search: "?pane=config&agent=a1" },
        [{ path: "/teams?team=research-team" }, { path: "/chat?session=s1" }],
      ),
    ).toEqual({ path: "/chat?session=s1", source: "stack" });
  });

  it("falls back to module parent routes for directly opened detail views", () => {
    expect(fallbackReturnRoute({ pathname: "/chat", search: "?session=s1" })).toBe("/chat");
    expect(fallbackReturnRoute({ pathname: "/agents/tools", search: "?agent=a1" })).toBe("/agents");
    expect(fallbackReturnRoute({ pathname: "/memory/agents", search: "?agentId=a1" })).toBe("/memory");
    expect(fallbackReturnRoute({ pathname: "/config", search: "?agent=a1" })).toBe("/config");
    expect(fallbackReturnRoute({ pathname: "/git", search: "" })).toBe("");
  });

  it("records previous route entries and consumes the clicked target", () => {
    const stack = appendReturnNavigationEntry(
      [{ path: "/teams" }],
      { pathname: "/chat", search: "?session=s1" },
      { pathname: "/agents", search: "?agent=a1" },
    );
    expect(stack).toEqual([{ path: "/teams" }, { path: "/chat?session=s1" }]);
    expect(consumeReturnNavigationTarget(stack, "/chat?session=s1")).toEqual([{ path: "/teams" }]);
  });

  it("serializes and parses only valid return stack paths", () => {
    const serialized = serializeReturnNavigationStack([
      { path: "/teams" },
      { path: "https://example.com" },
      { path: "/chat?session=s1" },
    ]);
    expect(parseReturnNavigationStack(serialized)).toEqual([{ path: "/teams" }, { path: "/chat?session=s1" }]);
    expect(parseReturnNavigationStack("not json")).toEqual([]);
  });
});
