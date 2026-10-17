import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { ChatCenterTabStrip, type ChatCenterTabStripProps } from "./ChatCenterTabStrip";

const props: ChatCenterTabStripProps = {
  styles: {}, lang: "zh", agentSessionLabel: "Agent", chatReturnTarget: "/teams", chatReturnLabel: "返回团队",
  groupPanelActive: false, projectBusActive: false, showSessionTabs: false, showAgentFallbackTab: false,
  workspaceActiveTab: "agent", sessionTabs: null, fileTabs: null, leftOverlayVisible: true,
  rightOverlayVisible: true, statusRailAvailable: false, conversationIndexOverlayOpen: false,
  statusRailOverlayOpen: false, onActivateAgentFallbackTab: () => {}, onToggleLeftOverlay: () => {}, onToggleRightOverlay: () => {},
};
const render = (groupPanelActive: boolean) => renderToStaticMarkup(
  <MemoryRouter><ChatCenterTabStrip {...props} groupPanelActive={groupPanelActive} /></MemoryRouter>,
);
describe("ChatCenterTabStrip return navigation", () => {
  it("keeps the ordinary conversation return link", () => {
    expect(render(false)).toContain('href="/teams"');
  });
  it("leaves group return navigation to the shell and uses a static group label", () => {
    const html = render(true);
    expect(html).not.toContain('href="/teams"');
    expect(html).toContain("群聊</span>");
    expect(html).not.toContain("<button");
  });
  it("keeps session tabs mounted alongside the active group label", () => {
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <ChatCenterTabStrip
          {...props}
          chatReturnTarget={null}
          groupPanelActive
          showSessionTabs
          sessionTabs={<span>原会话标签</span>}
        />
      </MemoryRouter>,
    );
    expect(html).toContain("群聊</span>");
    expect(html).toContain("原会话标签");
  });
  it("places the browse entry alongside existing session tabs without replacing their content", () => {
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <ChatCenterTabStrip
          {...props}
          styles={{ overlayPaneControls: "overlay-controls" }}
          chatReturnTarget={null}
          showSessionTabs
          sessionTabs={<span>原会话标签</span>}
          sessionBrowserControl={<button type="button" aria-label="浏览会话">浏览会话</button>}
          sessionActionsControl={<button type="button" aria-label="会话操作">会话操作</button>}
        />
      </MemoryRouter>,
    );
    expect(html).toContain("原会话标签");
    expect(html).toContain("浏览会话");
    expect(html).toContain("会话操作");
    expect(html).not.toContain("<img");

    const controlsRow = html.match(/<div class="overlay-controls"[^>]*>([\s\S]*?)<\/div>/)?.[1] ?? "";
    expect(controlsRow).toContain('aria-label="浏览会话"');
    expect(controlsRow).toContain('aria-label="会话操作"');
  });

  it("keeps a named expand control while the right rail is closed", () => {
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <ChatCenterTabStrip
          {...props}
          styles={{ overlayPaneControls: "overlay-controls", toolbarIconButton: "toolbar-icon" }}
          chatReturnTarget={null}
          rightRailLabel="侧栏"
          rightRailOpen={false}
        />
      </MemoryRouter>,
    );

    expect(html).toContain('id="chat-status-toggle"');
    expect(html).toContain('aria-label="展开侧栏"');
    expect(html).toContain('aria-expanded="false"');
    expect(html).toContain('aria-controls="chat-status-pane"');
    expect(html).toMatch(/class="[^"]*toolbar-icon[^"]*"/);
  });

  it("leaves collapse to the open right rail's own header", () => {
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <ChatCenterTabStrip {...props} chatReturnTarget={null} rightRailLabel="侧栏" rightRailOpen />
      </MemoryRouter>,
    );

    expect(html).not.toContain('id="chat-status-toggle"');
    expect(html).not.toContain('aria-label="收起侧栏"');
  });
});
