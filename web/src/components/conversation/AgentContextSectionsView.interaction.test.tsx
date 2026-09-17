/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import { AgentContextSectionsView } from "./AgentContextSectionsView";
import type { AgentMessageContextSection } from "./agentMessageSections";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

describe("AgentContextSectionsView image fallback", () => {
  let root: Root | null = null;
  let container: HTMLDivElement | null = null;

  afterEach(async () => {
    if (root) {
      await act(async () => {
        root?.unmount();
      });
    }
    container?.remove();
    root = null;
    container = null;
  });

  it("falls back to a file card when an image attachment fails to load", async () => {
    const sections: AgentMessageContextSection[] = [
      {
        id: "user-context-section-image-fallback",
        kind: "context",
        parts: [
          {
            id: "user-context-attachment-image-fallback",
            type: "attachment",
            attachment: {
              artifactId: "missing-shot.png",
              filename: "missing-shot.png",
              url: "/api/sessions/session-agent-thread/artifacts/missing-shot.png",
              imageUrl: "/api/sessions/session-agent-thread/artifacts/missing-shot.png",
              downloadUrl: "/api/sessions/session-agent-thread/artifacts/missing-shot.png?download=1",
              contentType: "image/png",
              sizeBytes: 2048,
              kind: "user_image",
              status: "ready",
            },
          },
        ],
      },
    ];

    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root?.render(<AgentContextSectionsView sections={sections} lang="zh" />);
    });

    const image = container.querySelector("img");
    expect(image).not.toBeNull();

    await act(async () => {
      image?.dispatchEvent(new Event("error"));
    });

    expect(container.querySelector("img")).toBeNull();
    expect(
      container
        .querySelector("figure")
        ?.getAttribute("data-agent-context-attachment-name"),
    ).toBe("missing-shot.png");
    expect(container.textContent).toContain("missing-shot.png");
    expect(container.textContent).toContain("2 KB");
    expect(
      container.querySelector("a")?.getAttribute("href"),
    ).toBe("/api/sessions/session-agent-thread/artifacts/missing-shot.png?download=1");
  });
});
