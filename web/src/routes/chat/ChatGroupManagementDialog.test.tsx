import { describe, expect, it } from "vitest";

import source from "./ChatGroupManagementDialog.tsx?raw";

describe("ChatGroupManagementDialog contract", () => {
  it("preserves the existing group management controls in a VUI dialog", () => {
    expect(source).toContain("<VDialog");
    expect(source).toContain('title={lang === "zh" ? "管理群聊"');
    expect(source).toContain('lang === "zh" ? "群名"');
    expect(source).toContain('lang === "zh" ? "调度模式"');
    expect(source).toContain('lang === "zh" ? "对话目的"');
    expect(source).toContain("onToggleGroupManageSession(session.id)");
    expect(source).toContain("onApplyGroupRoomManagement");
    expect(source).toContain("onDeleteActiveGroupRoom");
    expect(source).toContain("onResetActiveGroupRoom");
  });
});
