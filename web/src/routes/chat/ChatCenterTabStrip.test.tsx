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
  it("places the browse entry alongside existing session tabs without replacing their content", () => {
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <ChatCenterTabStrip
          {...props}
          chatReturnTarget={null}
          showSessionTabs
          sessionTabs={<span>原会话标签</span>}
          sessionBrowserControl={<button type="button" aria-pressed>浏览会话</button>}
        />
      </MemoryRouter>,
    );
    expect(html).toContain("原会话标签");
    expect(html).toContain("浏览会话");
    expect(html).not.toContain("<img");
  });
});
