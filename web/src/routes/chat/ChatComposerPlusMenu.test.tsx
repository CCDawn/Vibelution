import { describe, expect, it } from "vitest";

import source from "./ChatComposerPlusMenu.tsx?raw";
import stylesSource from "./ChatComposerPlusMenu.styles.ts?raw";

describe("ChatComposerPlusMenu contract", () => {
  it("renders one compact vertical menu with grouped sections", () => {
    expect(stylesSource).toContain('popoverContent: "vui-routes-chatcomposerplusmenu popoverContent !w-80');
    expect(stylesSource).toContain('menu: "vui-routes-chatcomposerplusmenu menu grid');
    expect(stylesSource).toContain('sectionTitle: "vui-routes-chatcomposerplusmenu sectionTitle');
    expect(source).toContain('role="menu"');
    expect(source).toContain("chat-composer-plus-${section.id}");
    expect(source).not.toContain("secondaryPanel");
    expect(source).not.toContain("primaryPanel");
    expect(source).not.toContain("ChevronRight");
    expect(source).not.toContain("tertiaryPanel");
    expect(source).not.toContain("thirdPanel");
  });

  it("groups the approved actions and renders capabilities as direct switches", () => {
    expect(source).toContain('label: lang === "zh" ? "添加与引用"');
    expect(source).toContain('label: lang === "zh" ? "对话能力"');
    expect(source).toContain('label: lang === "zh" ? "会话与陪伴"');
    expect(source).toContain('label: lang === "zh" ? "群聊与团队"');
    expect(source).toContain('role="menuitemcheckbox"');
    expect(source).toContain("aria-checked={options.checked}");
    expect(source).toContain('label: lang === "zh" ? "心智模型"');
    expect(source).toContain('label: lang === "zh" ? "运行状态注入"');
    expect(source).toContain('id: "manage-group"');
    expect(source).toContain("<Check");
    // Pet interaction rows retired together with the chat status rail.
    expect(source).not.toContain('id: "companion-feed"');
  });

  it("supports arrow-key navigation across enabled menu items", () => {
    expect(source).toContain('data-plus-menu-item="true"');
    expect(source).toContain('"ArrowDown"');
    expect(source).toContain('"ArrowUp"');
    expect(source).toContain('"Home"');
    expect(source).toContain('"End"');
    expect(source).toContain(":not([disabled])");
  });

  it("keeps slash commands, skills, and cache status out of the plus menu", () => {
    expect(source).not.toContain("slashCommand");
    expect(source).not.toContain("Skill");
    expect(source).not.toContain("缓存状态");
    expect(source).not.toContain("Context cache");
  });

  it("uses VUI overlays for the menu and the reference picker", () => {
    expect(source).toContain("<VPopover");
    expect(source).toContain("<VDialog");
    expect(source).toContain("<VButton");
    expect(source).toContain("<VNativeInput");
  });
});
