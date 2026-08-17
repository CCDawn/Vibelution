import { describe, expect, it } from "vitest";

import source from "./ChatComposerPlusMenu.tsx?raw";
import stylesSource from "./ChatComposerPlusMenu.styles.ts?raw";

describe("ChatComposerPlusMenu contract", () => {
  it("uses one vertical primary list and one adjacent secondary panel", () => {
    expect(stylesSource).toContain('primaryPanel: "vui-routes-chatcomposerplusmenu primaryPanel grid w-60');
    expect(stylesSource).toContain('secondaryPanel: "vui-routes-chatcomposerplusmenu secondaryPanel grid w-72');
    expect(source).toContain('data-testid="chat-composer-plus-primary"');
    expect(source).toContain('data-testid="chat-composer-plus-secondary"');
    expect(source).toContain("const visibleCluster = hoverCluster ?? activeCluster");
    expect(source).not.toContain("tertiaryPanel");
    expect(source).not.toContain("thirdPanel");
  });

  it("clusters the approved actions and renders capabilities as direct switches", () => {
    expect(source).toContain('label: lang === "zh" ? "添加与引用"');
    expect(source).toContain('label: lang === "zh" ? "对话能力"');
    expect(source).toContain('label: lang === "zh" ? "会话与陪伴"');
    expect(source).toContain('label: lang === "zh" ? "群聊与团队"');
    expect(source).toContain('role="menuitemcheckbox"');
    expect(source).toContain('label: lang === "zh" ? "心智模型"');
    expect(source).toContain('label: lang === "zh" ? "运行状态注入"');
    expect(source).toContain('id: "manage-group"');
    expect(source).toContain('id: "companion-feed"');
  });

  it("keeps slash commands, skills, and cache status out of the plus menu", () => {
    expect(source).not.toContain("slashCommand");
    expect(source).not.toContain("Skill");
    expect(source).not.toContain("缓存状态");
    expect(source).not.toContain("Context cache");
  });

  it("uses VUI overlays and exposes icon and chevron affordances", () => {
    expect(source).toContain("<VPopover");
    expect(source).toContain("<VDialog");
    expect(source).toContain('data-slot="cluster-icon"');
    expect(source).toContain("<ChevronRight");
  });
});
