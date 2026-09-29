import { describe, expect, it } from "vitest";

import panelSource from "./ChatSessionWorkspacePanel.tsx?raw";
import panelStyles from "./ChatSessionWorkspacePanel.styles";

describe("ChatSessionWorkspacePanel share export wiring", () => {
  it("renders the conversation share export entry from the direct-session conversation model", () => {
    expect(panelSource).toContain("<ConversationShareExportButton");
    expect(panelSource).toContain("sessionId={conversation.sessionId}");
    expect(panelSource).toContain("messages={conversation.messages}");
    expect(panelSource).toContain("language={lang}");
    // The entry lives in a dedicated session-level toolbar row above the
    // transcript body, not inside the composer or the transcript itself.
    expect(panelSource).toContain("styles.conversationToolbar");
    expect(panelStyles.conversationToolbar).toContain("shrink-0");
    expect(panelStyles.conversationToolbar).toContain("justify-end");
  });

  it("keeps the export entry out of ConversationView (W4 decoupling contract)", () => {
    // The W4 guard test pins ConversationView decoupling; this panel is the
    // single integrator, so lazy-loading the button here must not leak the
    // import into the memoized transcript surface.
    expect(panelSource).toContain('from "../../components/conversation/ConversationShareExportButton"');
  });
});
