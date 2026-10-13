import React, { type ComponentProps } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { ChatSessionWorkspacePanel } from "./ChatSessionWorkspacePanel";

import panelSource from "./ChatSessionWorkspacePanel.tsx?raw";
import panelStyles from "./ChatSessionWorkspacePanel.styles";
import workbenchSource from "./ChatCodingRouteWorkbench.tsx?raw";

vi.mock("./ChatConversationComposerBridge", () => ({ ChatConversationComposerBridge: () => <div>原会话与草稿</div> }));
vi.mock("./ChatRuntimeNoticeStack", () => ({ ChatRuntimeNoticeStack: () => null }));

const props = {
  activeSessionId: "sess-9", activeCliAgentRunId: "", activeCliAgentRunAvailable: false,
  conversation: { sessionId: "sess-9", messages: [], composer: {} }, conversationFocused: false,
  lang: "zh", workspaceActiveTab: "agent", notices: [], sessionsPending: false,
  toolApproval: null, filePreview: {}, hasBlockingError: false, hasTransientError: false,
  invalidChildSessionLinkMessage: "", onApproveToolApproval: () => {}, onRejectToolApproval: () => {},
} as unknown as ComponentProps<typeof ChatSessionWorkspacePanel>;

describe("ChatSessionWorkspacePanel share export wiring", () => {
  it("renders the conversation share export entry from the direct-session conversation model", () => {
    expect(panelSource).toContain("<ConversationShareExportButton");
    expect(panelSource).toContain("sessionId={conversation.sessionId}");
    expect(panelSource).toContain("messages={conversation.messages}");
    expect(panelSource).toContain("language={lang}");
    // Specialized surfaces retain their existing fallback above the body.
    expect(panelSource).toContain("styles.conversationToolbar");
    expect(panelStyles.conversationToolbar).toContain("shrink-0");
    expect(panelStyles.conversationToolbar).toContain("justify-end");
  });

  it("removes the ordinary Chat export row while retaining the specialized fallback", () => {
    const ordinary = renderToStaticMarkup(<ChatSessionWorkspacePanel {...props} hideExportControl />);
    const specialized = renderToStaticMarkup(<ChatSessionWorkspacePanel {...props} />);
    expect(ordinary).toContain("原会话与草稿");
    expect(ordinary).not.toContain("导出 HTML");
    expect(ordinary).not.toContain("conversationToolbar");
    expect(specialized).toContain("导出 HTML");
  });

  it("uses the same direct-session transcript in the header and keeps specialized surfaces separate", () => {
    expect(workbenchSource).toContain("const headerExportVisible = !verifiedCompanionMode && !groupPanelActive && !financeSurface");
    expect(workbenchSource).toContain('conversationWorkspaceTab === "agent" && Boolean(conversationModel)');
    expect(workbenchSource).toContain("&& !activeCliAgentRunId && !sessionDetailErrorState.blockingError && !invalidChildSessionLinkMessage");
    expect(workbenchSource).toContain("sessionId={conversationModel.sessionId}");
    expect(workbenchSource).toContain("messages={conversationModel.messages}");
    expect(workbenchSource).toContain("key={conversationModel.sessionId}");
    expect(workbenchSource).toContain("hideExportControl={headerExportVisible}");
  });

  it("keeps the export entry out of ConversationView (W4 decoupling contract)", () => {
    // The W4 guard test pins ConversationView decoupling; this panel is the
    // single integrator, so lazy-loading the button here must not leak the
    // import into the memoized transcript surface.
    expect(panelSource).toContain('from "../../components/conversation/ConversationShareExportButton"');
  });
});
