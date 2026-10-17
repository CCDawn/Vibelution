import { describe, expect, it } from "vitest";

import type { ConfigSummary } from "../api/types";
import {
  buildConfigSettingsGroups,
  type ConfigSettingsGroupCopy,
} from "./ConfigSettingsNavigation";

/** Backend sections remain the registration authority. Known section IDs have
 * an explicit frontend projection; unknown sections follow backend annotations. */

const groupCopy: ConfigSettingsGroupCopy = {
  "overview-apply": { title: "总览与保存", summary: "状态与保存" },
  "workbench-interface": { title: "界面与工作台", summary: "工作台与界面" },
  "avatar-pet": { title: "用户、终端形象与陪伴体", summary: "用户与形象" },
  "models-profiles": { title: "模型库", summary: "模型连接与发现" },
  "runtime-context": { title: "运行时与上下文", summary: "运行时设置" },
  "tooling-diagnostics": { title: "工具与诊断", summary: "工具和诊断" },
};

function section(id: string, group?: string, page?: string): ConfigSummary["sections"][number] {
  return group && page ? { id, title: id, summary: id, group, page } : { id, title: id, summary: id };
}

function pageMembers(groups: ReturnType<typeof buildConfigSettingsGroups>, groupId: string, pageId: string): string[] {
  const group = groups.find((candidate) => candidate.id === groupId);
  const page = group?.pages.find((candidate) => candidate.id === pageId);
  return page?.memberSectionIds ?? [];
}

describe("settings navigation registration and presentation", () => {
  it("places a newly registered backend section with zero frontend edits", () => {
    // Acceptance script: simulate the backend registering a brand-new section
    // with membership — no frontend change is involved in this test at all.
    const groups = buildConfigSettingsGroups(
      [section("theme-editor", "workbench-interface", "workbench-interface")],
      groupCopy,
      "zh",
    );
    expect(pageMembers(groups, "workbench-interface", "workbench-interface")).toContain("theme-editor");
    // Page summary still derives from members (single member -> its summary).
    const group = groups.find((candidate) => candidate.id === "workbench-interface");
    const page = group?.pages.find((candidate) => candidate.id === "workbench-interface");
    expect(page?.summary).toBe("theme-editor");
  });

  it("places registered unannotated known sections in the presentation mapping", () => {
    const groups = buildConfigSettingsGroups(
      [section("overview"), section("diagnostics"), section("shell"), section("ui")],
      groupCopy,
      "zh",
    );
    expect(pageMembers(groups, "overview-apply", "overview-save")).toEqual(["overview", "diagnostics"]);
    expect(pageMembers(groups, "workbench-interface", "workbench-interface")).toEqual(["shell", "ui"]);
  });

  it("projects known sections independently of legacy backend page membership", () => {
    const groups = buildConfigSettingsGroups(
      [section("ui", "runtime-context", "runtime-context"), section("context-compression", "runtime-context", "runtime-context")],
      groupCopy,
      "zh",
    );
    expect(pageMembers(groups, "runtime-context", "runtime-context")).toEqual(["context-compression"]);
    expect(pageMembers(groups, "workbench-interface", "workbench-interface")).toEqual(["ui"]);
  });

  it("collects annotated sections with undeclared membership in the explicit fallback page", () => {
    const groups = buildConfigSettingsGroups(
      [
        section("mystery-a", "space-zone", "no-such-page"),
        section("mystery-b"),
        section("network", "tooling-diagnostics", "tooling-access"),
      ],
      groupCopy,
      "zh",
    );
    expect(pageMembers(groups, "tooling-diagnostics", "tooling-other")).toEqual(["mystery-a", "mystery-b"]);
    expect(pageMembers(groups, "tooling-diagnostics", "tooling-network")).toEqual(["network"]);
  });

  it("hides the fallback page entirely when every annotation is declared", () => {
    const groups = buildConfigSettingsGroups(
      [section("network", "tooling-diagnostics", "tooling-access")],
      groupCopy,
      "zh",
    );
    expect(pageMembers(groups, "tooling-diagnostics", "tooling-other")).toEqual([]);
    const toolingGroup = groups.find((candidate) => candidate.id === "tooling-diagnostics");
    expect(toolingGroup?.pages.some((page) => page.id === "tooling-other")).toBe(false);
  });

  it("keeps unknown sections on declared pages and maps the retired access page", () => {
    const registered = [
      section("new-security-control", "tooling-diagnostics", "tooling-security"),
      section("new-network-control", "tooling-diagnostics", "tooling-access"),
      section("new-assistant-control", "avatar-pet", "personal-assistant"),
      section("unknown-page", "avatar-pet", "future-page"),
      section("unannotated"),
    ];
    const groups = buildConfigSettingsGroups(registered, groupCopy, "zh");
    expect(pageMembers(groups, "tooling-diagnostics", "tooling-security")).toEqual(["new-security-control"]);
    expect(pageMembers(groups, "tooling-diagnostics", "tooling-network")).toEqual(["new-network-control"]);
    expect(pageMembers(groups, "avatar-pet", "personal-assistant")).toEqual(["new-assistant-control"]);
    expect(pageMembers(groups, "tooling-diagnostics", "tooling-other")).toEqual(["unknown-page", "unannotated"]);
    const visible = groups.flatMap((group) => group.pages.flatMap((page) => page.memberSectionIds));
    expect(visible.sort()).toEqual(registered.map((entry) => entry.id).sort());
  });

});
