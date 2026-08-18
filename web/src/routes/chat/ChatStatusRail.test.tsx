import { describe, expect, it } from "vitest";

import source from "./ChatStatusRail.tsx?raw";

describe("ChatStatusRail read-only contract", () => {
  it("keeps status evidence while removing action controls and cache status", () => {
    expect(source).toContain("ChatPromptAssemblyInspector");
    expect(source).toContain("LlmPayloadTracePanel");
    expect(source).toContain('lang === "zh" ? "群资料"');
    expect(source).toContain("standardGroupRoomActive && groupRoomInitialLoading");
    expect(source).toContain("正在加载群聊资料");
    expect(source).toContain('lang === "zh" ? "陪伴"');
    expect(source).not.toContain("mental-runtime-module");
    expect(source).not.toContain("TokenCoreStatusPanel");
    expect(source).not.toContain("TurnStatusTailPanel");
    expect(source).not.toContain("petShowcaseActions");
    expect(source).not.toContain("onPetInteraction");
    expect(source).not.toContain("onOpenDirectSession");
    expect(source).not.toContain("groupManagementPanel");
  });
});
