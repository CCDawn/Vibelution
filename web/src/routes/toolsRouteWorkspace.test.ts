import { describe, expect, it } from "vitest";
import { resolveToolsWorkspaceView, toolsWorkspaceParams } from "./toolsRouteWorkspace";

describe("Tools workspace navigation", () => {
  it.each([["", "library"], ["focus=policy", "policy"], ["focus=bundle&bundle=pkg", "policy"], ["focus=test&tool=search", "library"], ["focus=detail", "library"], ["agent=A110&returnTo=%2Fagents", "policy"], ["toolId=search", "library"]])("opens %s in %s", (query, expected) => {
    expect(resolveToolsWorkspaceView(new URLSearchParams(query))).toBe(expected);
  });
  it("preserves identity and return navigation while switching views", () => {
    const before = new URLSearchParams("focus=bundle&agent=A110&scope=main_agent&bundle=package&returnTo=%2Fagents&returnLabel=agents");
    const after = toolsWorkspaceParams(before, { view:"library" });
    expect(resolveToolsWorkspaceView(after)).toBe("library");
    expect(after.get("focus")).toBeNull();
    for(const key of ["agent","scope","bundle","returnTo","returnLabel"]) expect(after.get(key)).toBe(before.get(key));
    expect(before.get("focus")).toBe("bundle");
  });
  it("replaces old aliases so manual selections are not overridden by deep-link effects", () => {
    const after = toolsWorkspaceParams(new URLSearchParams("toolId=old&bundleId=old-pkg&agent=old-agent"), {tool:"new",bundle:"new-pkg",agent:"new-agent",scope:"worker"});
    expect(after.get("toolId")).toBeNull(); expect(after.get("bundleId")).toBeNull();
    expect(after.get("tool")).toBe("new"); expect(after.get("bundle")).toBe("new-pkg");
    expect(after.get("agent")).toBe("new-agent"); expect(after.get("scope")).toBe("worker");
  });
});
