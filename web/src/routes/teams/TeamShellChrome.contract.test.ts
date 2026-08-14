import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const toolbarSource = readFileSync(new URL("./TeamShellToolbar.tsx", import.meta.url), "utf8");
const railSource = readFileSync(new URL("./TeamShellRail.tsx", import.meta.url), "utf8");
const kanbanSource = readFileSync(new URL("./ResearchBoardKanban.tsx", import.meta.url), "utf8");

describe("Team shell chrome selection + board layout", () => {
  it("toolbar is identity-only (no board/canvas switch or refresh)", () => {
    expect(toolbarSource).toContain("team-shell-toolbar-identity");
    expect(toolbarSource).not.toContain("TeamShellModeSwitch");
    expect(toolbarSource).not.toContain("VIconButton");
    expect(toolbarSource).not.toContain("刷新团队");
    expect(toolbarSource).toContain("teamName");
  });

  it("keeps the team rail free of instructional footer copy", () => {
    expect(railSource).not.toContain("左侧选团队，右侧展示整队内容");
    expect(railSource).not.toContain("Drag the separator to resize");
  });

  it("rail selected team is muted row + inset edge, not full ink fill", () => {
    expect(railSource).toContain("not full ink fill");
    expect(railSource).toContain("!bg-[var(--vui-surface-row)]");
    expect(railSource).toContain("shadow-[inset_3px_0_0_0_var(--fg-primary)]");
    expect(railSource).toContain("!text-[var(--fg-primary)]");
    // Guard against white-on-ink selected card regression.
    expect(railSource).not.toContain("!bg-[var(--fg-primary)]");
    expect(railSource).not.toContain("[&_*]:!text-white");
    expect(railSource).not.toContain("!text-white");
  });

  it("legacy stage board (if mounted) stays three columns with horizontal scroll", () => {
    // End-user home no longer mounts this kanban; keep geometry contract if reused.
    expect(kanbanSource).toContain("grid-cols-[repeat(3,minmax(0,1fr))]");
    expect(kanbanSource).toContain("overflow-x-auto");
    expect(kanbanSource).toContain('data-testid="research-board-columns"');
    expect(kanbanSource).not.toContain("grid-cols-1");
    expect(kanbanSource).not.toContain("md:grid-cols-3");
  });
});
