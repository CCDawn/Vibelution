import { existsSync, readFileSync } from "node:fs";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

const conversationViewSource = readFileSync(new URL("./ConversationView.tsx", import.meta.url), "utf8");
const componentModuleUrl = new URL("./ConversationTurnAvatarContent.tsx", import.meta.url);

describe("ConversationTurnAvatarContent", () => {
  it("keeps turn avatar content rendering outside ConversationView", () => {
    expect(existsSync(componentModuleUrl)).toBe(true);
    expect(conversationViewSource).toContain('from "./ConversationTurnAvatarContent"');
    expect(conversationViewSource).not.toContain("function renderTurnAvatarContent");
    expect(conversationViewSource).not.toContain("MessageSquarePlus");
  });

  it("renders image avatar content with the caller-owned class name", async () => {
    const { ConversationTurnAvatarContent } = await import("./ConversationTurnAvatarContent");

    const html = renderToStaticMarkup(
      <ConversationTurnAvatarContent
        content={{ imageUrl: "/avatar/assistant.png", fallback: "AI" }}
        imageClassName="turn-avatar-image"
      />,
    );

    expect(html).toContain("<img");
    expect(html).toContain('src="/avatar/assistant.png"');
    expect(html).toContain('alt=""');
    expect(html).toContain('class="turn-avatar-image"');
  });

  it("renders fallback text avatar content", async () => {
    const { ConversationTurnAvatarContent } = await import("./ConversationTurnAvatarContent");

    const html = renderToStaticMarkup(
      <ConversationTurnAvatarContent
        content={{ fallback: "助" }}
        imageClassName="turn-avatar-image"
      />,
    );

    expect(html).toContain("助");
    expect(html).not.toContain("<img");
  });

  it("renders the group transcript icon avatar content", async () => {
    const { ConversationTurnAvatarContent } = await import("./ConversationTurnAvatarContent");

    const html = renderToStaticMarkup(
      <ConversationTurnAvatarContent
        content={{ icon: "groupTranscript" }}
        imageClassName="turn-avatar-image"
      />,
    );

    expect(html).toContain("<svg");
    expect(html).toContain('width="17"');
  });
});
