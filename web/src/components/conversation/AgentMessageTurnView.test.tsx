import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { AgentMessageTurnView } from "./AgentMessageTurnView";
import styles from "./AgentMessageTurnView.styles";

describe("AgentMessageTurnView", () => {
  it("renders the turn shell with stable AgentMessage metadata and header slots", () => {
    const html = renderToStaticMarkup(
      <AgentMessageTurnView
        rowKey="row-assistant-1"
        messageKey="message-assistant-1"
        agentMessageId="agent-message-1"
        sectionCount={4}
        sectionKinds="user,context,process,answer"
        className="assistant-turn"
        compactHeader={false}
        avatar={<span>avatar-slot</span>}
        speakerLabel="Assistant"
        identityAccessory={<span>editing</span>}
        metaActions={<span>19:50</span>}
      >
        <p>turn body</p>
      </AgentMessageTurnView>,
    );

    expect(html).toContain('class="assistant-turn"');
    expect(html).toContain('data-conversation-row-key="row-assistant-1"');
    expect(html).toContain('data-conversation-message-key="message-assistant-1"');
    expect(html).toContain('data-agent-message-id="agent-message-1"');
    expect(html).toContain('data-agent-section-count="4"');
    expect(html).toContain('data-agent-section-kinds="user,context,process,answer"');
    expect(html).toContain("turnAvatar");
    expect(html).toContain("turnMeta");
    expect(html).toContain("turnSpeaker");
    expect(html).toContain("avatar-slot");
    expect(html).toContain("Assistant");
    expect(html).toContain("editing");
    expect(html).toContain("19:50");
    expect(html).toContain("turn body");
  });

  it("keeps the body and metadata while omitting avatar and header slots for compact continuation turns", () => {
    const html = renderToStaticMarkup(
      <AgentMessageTurnView
        rowKey="row-assistant-2"
        messageKey="message-assistant-2"
        agentMessageId="agent-message-2"
        sectionCount={1}
        className="assistant-turn-continuation"
        compactHeader={true}
        avatar={<span>hidden-avatar</span>}
        speakerLabel="Hidden speaker"
        metaActions={<span>hidden-meta</span>}
      >
        <p>continued body</p>
      </AgentMessageTurnView>,
    );

    expect(html).toContain('data-conversation-row-key="row-assistant-2"');
    expect(html).toContain('data-agent-message-id="agent-message-2"');
    expect(html).toContain('data-agent-section-count="1"');
    expect(html).not.toContain("data-agent-section-kinds");
    expect(html).toContain("turnAvatar");
    expect(html).not.toContain("turnMeta");
    expect(html).not.toContain("hidden-avatar");
    expect(html).not.toContain("Hidden speaker");
    expect(html).not.toContain("hidden-meta");
    expect(html).toContain("continued body");
  });

  it("keeps turn header slots bounded on narrow conversation surfaces", () => {
    expect(styles.turnMeta).toContain("max-w-full");
    expect(styles.turnMeta).toContain("flex-wrap");
    expect(styles.turnMeta).toContain("gap-x-2");
    expect(styles.turnMetaIdentity).toContain("minmax(0,auto)");
    expect(styles.turnMetaIdentity).toContain("max-w-full");
    expect(styles.turnMetaActions).toContain("shrink-0");
    expect(styles.turnSpeaker).toContain("max-w-full");
    expect(styles.turnSpeaker).toContain("[overflow-wrap:anywhere]");
  });
});
