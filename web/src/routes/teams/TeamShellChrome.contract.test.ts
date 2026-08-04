import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const modeSwitchSource = readFileSync(new URL("./TeamShellModeSwitch.tsx", import.meta.url), "utf8");
const railSource = readFileSync(new URL("./TeamShellRail.tsx", import.meta.url), "utf8");
const kanbanSource = readFileSync(new URL("./ResearchBoardKanban.tsx", import.meta.url), "utf8");

describe("Team shell chrome selection + board layout", () => {
  it("mode switch active segment is raised surface, not ink slab", () => {
    expect(modeSwitchSource).toContain("raised surface, not ink slab");
    expect(modeSwitchSource).toContain("!bg-[var(--vui-surface-base)]");
    expect(modeSwitchSource).toContain("!text-[var(--fg-primary)]");
    // Guard against regression to monochrome selected segment.
    expect(modeSwitchSource).not.toContain("!bg-[var(--fg-primary)]");
    expect(modeSwitchSource).not.toContain("!text-[var(--vui-surface-base)]");
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

  it("stage board stays three columns with horizontal scroll instead of stacking", () => {
    expect(kanbanSource).toContain("Always three columns");
    expect(kanbanSource).toContain("grid-cols-[repeat(3,minmax(240px,1fr))]");
    expect(kanbanSource).toContain("overflow-x-auto");
    expect(kanbanSource).toContain("min-w-[240px]");
    expect(kanbanSource).toContain('data-testid="research-board-columns"');
    // Guard against responsive single-column collapse that flattens the board into a list.
    expect(kanbanSource).not.toContain("grid-cols-1");
    expect(kanbanSource).not.toContain("md:grid-cols-3");
  });
});
