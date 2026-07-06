import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { AgentContextSectionsView } from "./AgentContextSectionsView";
import type { AgentMessageContextSection } from "./agentMessageSections";
import styles from "./AgentContextSectionsView.styles";

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
    expect(html).toContain('data-agent-context-attachment-name="context.png"');
    expect(html).toContain('data-agent-context-reference-kind="session"');
    expect(html).toContain('src="/api/sessions/session-agent-thread/artifacts/context-image.png"');
    expect(html).toContain('href="/api/sessions/session-agent-thread/artifacts/context-image.png?download=1"');
    expect(html).toContain("context.png");
    expect(html).toContain("下载图片");
    expect(html).toContain('aria-label="用户上下文附件 context.png"');
    expect(html).toContain('title="下载图片 context.png"');
    expect(html).toContain("旧会话摘录");
    expect(html).toContain("前端代理");
    expect(html).toContain('aria-label="用户上下文引用 旧会话摘录 前端代理"');
    expect(html).toContain('data-agent-context-reference-title="旧会话摘录"');
    expect(html).toContain('data-agent-context-reference-agent="前端代理"');
    expect(html).toContain('data-agent-context-group="attachments"');
    expect(html).toContain('data-agent-context-group="references"');
    expect(html).toContain('data-agent-context-group-count="1"');
    expect(html).toContain('aria-label="用户上下文附件"');
    expect(html).toContain('aria-label="用户上下文引用"');
    expect(html).toContain('role="list"');
    expect(html).toContain('role="listitem"');
    expect(html).toContain("composerReferenceTitle");
    expect(html).toContain("composerReferenceMeta");
    expect(html).not.toContain("旧会话摘录 · 前端代理");
  });

  it("keeps attachments and reference chips bounded for dense conversation rows", () => {
    expect(styles.userAttachmentGrid).toContain("grid-cols-[repeat(auto-fit,minmax(min(12rem,100%),1fr))]");
    expect(styles.userAttachment).toContain("overflow-hidden");
    expect(styles.userAttachmentImage).toContain("aspect-[16/9]");
    expect(styles.userAttachmentImage).toContain("object-cover");
    expect(styles.userAttachmentImage).toContain("max-h-44");
    expect(styles.userAttachmentMeta).toContain("minmax(0,1fr)");
    expect(styles.userAttachmentMeta).toContain("[&>span]:truncate");
    expect(styles.composerReferenceChip).toContain("max-w-[min(100%,32rem)]");
    expect(styles.composerReferenceCopy).toContain("grid");
    expect(styles.composerReferenceCopy).toContain("gap-0.5");
    expect(styles.composerReferenceTitle).toContain("truncate");
    expect(styles.composerReferenceTitle).toContain("[overflow-wrap:anywhere]");
    expect(styles.composerReferenceMeta).toContain("truncate");
    expect(styles.composerReferenceMeta).toContain("text-[var(--fg-tertiary)]");
    expect(styles.userContextReferences).toContain("justify-end");
  });
});
