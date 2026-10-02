import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const chatDir = resolve(import.meta.dirname);

describe("ChatSessionWorkbenchShell geometry host", () => {
  it("adapts VSessionWorkbenchPage with Chat dual-pane slots", () => {
    const shell = readFileSync(resolve(chatDir, "ChatSessionWorkbenchShell.tsx"), "utf8");
    const workbench = readFileSync(resolve(chatDir, "ChatCodingRouteWorkbench.tsx"), "utf8");
    const layout = readFileSync(resolve(chatDir, "useChatWorkbenchLayout.ts"), "utf8");
    const recipe = readFileSync(
      resolve(chatDir, "../../components/vui/layout/VSessionWorkbenchPage.tsx"),
      "utf8",
    );

    expect(recipe).toContain("export const VSessionWorkbenchPage");
    expect(recipe).toContain('data-vui-recipe="session-workbench-page"');
    expect(recipe).toContain("session");
    expect(recipe).toContain("indexRail");
    expect(recipe).toContain("statusRail");

    expect(shell).toContain("VSessionWorkbenchPage");
    expect(shell).toContain('domainRecipe="chat-session-workbench"');
    expect(shell).toContain("WORKBENCH_LAYOUT_IDS.chat");
    expect(shell).toContain("session={center}");
    expect(shell).toContain("indexRail={conversationIndex}");
    expect(shell).toContain('data-chat-geometry="dual-pane"');

    expect(workbench).toContain("ChatSessionWorkbenchShell");
    expect(workbench).toContain("useChatWorkbenchLayout");
    expect(workbench).toContain("statusRail={");
    expect(workbench).toContain("center={");
    expect(workbench).toContain("conversationIndex={");
    expect(workbench).toContain("leftResizeHandle={");
    expect(workbench).toContain("rightResizeHandle={");
    expect(workbench).not.toContain('data-vui-recipe="chat-session-workbench"');

    expect(layout).toContain("CHAT_WORKBENCH_LAYOUT_ID");
    expect(layout).toContain("setChatPanelWidths");
    expect(layout).toContain("|| !indexRailEnabled");
    expect(layout).toContain("styles.centerPaneDocked");
    expect(layout).toContain("styles.centerPaneOverlay");

    const styles = readFileSync(resolve(chatDir, "../ChatCodingRoute.styles.ts"), "utf8");
    const centerPaneBlock = styles.slice(styles.indexOf("centerPane:"), styles.indexOf("centerPaneDocked:"));
    expect(centerPaneBlock).not.toContain("[grid-column:3]");
    expect(styles).toContain("centerPaneDocked [grid-column:3] [grid-row:1]");
    expect(styles).toContain("centerPaneOverlay [grid-column:1] [grid-row:1]");
  });
});
