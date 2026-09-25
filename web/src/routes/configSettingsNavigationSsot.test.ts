import { describe, expect, it } from "vitest";

import type { ConfigSummary } from "../api/types";
import {
  buildConfigSettingsGroups,
  type ConfigSettingsGroupCopy,
} from "./ConfigSettingsNavigation";

/**
 * Settings-align wave 3 — new-section registration single source of truth.
 *
 * Acceptance script: the backend `_config_sections` (core/web/services/
 * config_service.py) is the only registration authority. Adding a section on
 * the backend (with `group`/`page` membership) must surface it in the right
 * settings page with ZERO frontend edits, and a section whose membership does
 * not match any declared page must land in the explicit fallback page instead
 * of being silently dropped.
 */

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

describe("settings navigation SSOT (wave 3)", () => {
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

  it("keeps unannotated sections on the frozen legacy member tables", () => {
    const groups = buildConfigSettingsGroups(
      [section("overview"), section("diagnostics"), section("shell"), section("ui")],
      groupCopy,
      "zh",
    );
    expect(pageMembers(groups, "overview-apply", "overview-save")).toEqual(["overview", "diagnostics"]);
    expect(pageMembers(groups, "workbench-interface", "workbench-interface")).toEqual(["shell", "ui"]);
  });

  it("lets backend membership override the legacy static table", () => {
    // Backend re-grouping wins: "ui" is statically listed under
    // workbench-interface but annotated to runtime-context. Newcomers append
    // after the page's legacy members (documented ordering).
    const groups = buildConfigSettingsGroups(
      [section("ui", "runtime-context", "runtime-context"), section("context-compression", "runtime-context", "runtime-context")],
      groupCopy,
      "zh",
    );
    expect(pageMembers(groups, "runtime-context", "runtime-context")).toEqual(["context-compression", "ui"]);
    expect(pageMembers(groups, "workbench-interface", "workbench-interface")).toEqual([]);
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
    // mystery-a is annotated but its (group, page) is undeclared -> fallback.
    expect(pageMembers(groups, "tooling-diagnostics", "tooling-other")).toEqual(["mystery-a"]);
    // Unannotated sections are not silently re-homed either — they simply stay
    // off the page cards unless the legacy table lists them (existing behavior).
    expect(pageMembers(groups, "tooling-diagnostics", "tooling-access")).toEqual(["network"]);
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
});
