import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const chatDir = resolve(import.meta.dirname);

describe("Chat message chrome header decision", () => {
  it("keeps bubble chrome route-local and shared across group surfaces", () => {
    const chrome = readFileSync(resolve(chatDir, "ChatMessageChromeHeader.tsx"), "utf8");
    const group = readFileSync(resolve(chatDir, "ChatGroupCenterSurface.tsx"), "utf8");
    expect(chrome).toContain("export function ChatMessageChromeHeader");
    expect(chrome).toContain('data-vui="chat-message-chrome-header"');
    expect(chrome).toContain("density");
    expect(chrome).toContain("Not** VPanelHeader");
    expect(group).toContain("ChatMessageChromeHeader");
    expect(group).not.toMatch(/<header\b/);
  });
});
