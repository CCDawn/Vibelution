import { describe, expect, it, vi } from "vitest";
import type { Team } from "../../api/types";
import { teamContextMenuItems } from "./TeamContextMenu";

function menu(team: Team) {
  return {
    state: { x: 100, y: 200, team }, lang: "zh" as const,
    onRename: vi.fn(), onManage: vi.fn(), onOpenWorkspace: vi.fn(), onHide: vi.fn(), onArchive: vi.fn(), onDismiss: vi.fn(),
  };
}
describe("team context actions", () => {
  it("targets the right-clicked team and keeps archive separate from hiding", () => {
    const team = { teamId: "team-b", status: "active", systemManaged: false } as Team;
    const props = menu(team);
    const items = teamContextMenuItems(props);
    expect(items.map((item) => item.id)).toEqual(["rename", "manage", "workspace", "hide", "archive"]);
    items.find((item) => item.id === "hide")?.onSelect?.();
    expect(props.onHide).toHaveBeenCalledWith(team);
    expect(props.onArchive).not.toHaveBeenCalled();
    items.find((item) => item.id === "rename")?.onSelect?.();
    expect(props.onRename).toHaveBeenCalledWith(team);
    expect(items.at(-1)?.danger).toBe(true);
  });
  it("retains workflow ownership while allowing viewing, navigation and hide", () => {
    const items = teamContextMenuItems(menu({ teamId: "self-evolution-team", systemManaged: true, status: "active" } as Team));
    expect(items.filter((item) => item.disabled).map((item) => item.id)).toEqual(["rename", "archive"]);
    expect(items.find((item) => item.id === "archive")?.title).toContain("系统工作流");
    expect(items.find((item) => item.id === "manage")?.title).toContain("只读");
  });
});
