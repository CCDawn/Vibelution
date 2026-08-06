import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const chatDir = resolve(import.meta.dirname);

describe("ChatSessionWorkbenchShell geometry host", () => {
  it("owns session recipe markers and is consumed by the workbench composer", () => {
    const shell = readFileSync(resolve(chatDir, "ChatSessionWorkbenchShell.tsx"), "utf8");
    const workbench = readFileSync(resolve(chatDir, "ChatCodingRouteWorkbench.tsx"), "utf8");
    const layout = readFileSync(resolve(chatDir, "useChatWorkbenchLayout.ts"), "utf8");

    expect(shell).toContain("export function ChatSessionWorkbenchShell");
    expect(shell).toContain('data-vui="chat-session-workbench-shell"');
    expect(shell).toContain('data-vui-recipe="chat-session-workbench"');
    expect(shell).toContain('data-vui-domain-recipe="chat-dual-pane"');
    expect(shell).toContain("WORKBENCH_LAYOUT_IDS.chat");
    expect(shell).toContain("layoutRef");
    expect(shell).toContain("statusRail");
    expect(shell).toContain("conversationIndex");
    expect(shell).toContain("center");

    expect(workbench).toContain("ChatSessionWorkbenchShell");
    expect(workbench).toContain("useChatWorkbenchLayout");
    expect(workbench).not.toContain('data-vui-recipe="chat-session-workbench"');

    expect(layout).toContain("CHAT_WORKBENCH_LAYOUT_ID");
    expect(layout).toContain("setChatPanelWidths");
  });
});
