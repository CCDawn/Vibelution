import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { AgentContextSectionsView } from "./AgentContextSectionsView";
import type { AgentMessageContextSection } from "./agentMessageSections";

describe("AgentContextSectionsView", () => {
  it("renders attachment and reference context sections with stable AgentMessage metadata", () => {
    const sections: AgentMessageContextSection[] = [
      {
        id: "user-context-section-context-1",
        kind: "context",
        parts: [
          {
            id: "user-context-attachment-context-image",
            type: "attachment",
            attachment: {
              artifactId: "context-image.png",
              filename: "context.png",
              url: "/api/sessions/session-agent-thread/artifacts/context-image.png",
              imageUrl: "/api/sessions/session-agent-thread/artifacts/context-image.png",
              downloadUrl: "/api/sessions/session-agent-thread/artifacts/context-image.png?download=1",
              contentType: "image/png",
              sizeBytes: 128,
              kind: "user_image",
              status: "ready",
            },
          },
          {
            id: "user-context-reference-session-context-ref",
            type: "reference",
            reference: {
              kind: "session",
              referenceId: "session:context-ref",
              sessionId: "context-ref",
              title: "旧会话摘录",
              agentDisplayName: "前端代理",
            },
          },
        ],
      },
    ];

    const html = renderToStaticMarkup(
      <AgentContextSectionsView sections={sections} lang="zh" />,
    );

    expect(html).toContain('data-agent-context-section-id="user-context-section-context-1"');
    expect(html).toContain('data-agent-context-part-count="2"');
    expect(html).toContain('data-agent-context-part-type="attachment"');
    expect(html).toContain('data-agent-context-part-type="reference"');
    expect(html).toContain('src="/api/sessions/session-agent-thread/artifacts/context-image.png"');
    expect(html).toContain('href="/api/sessions/session-agent-thread/artifacts/context-image.png?download=1"');
    expect(html).toContain("context.png");
    expect(html).toContain("下载图片");
    expect(html).toContain("旧会话摘录");
    expect(html).toContain("前端代理");
  });
});
