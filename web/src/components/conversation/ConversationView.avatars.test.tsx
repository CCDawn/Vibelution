import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Window } from "happy-dom";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { ConversationMessage } from "../../api/types";
import { ConversationView } from "./ConversationView";
import styles from "./ConversationView.styles";

function message(id: string, role: "user" | "assistant"): ConversationMessage {
  const content = `Message ${id}`;
  return {
    id,
    role,
    content,
    timestamp: "2026-11-06T02:00:00Z",
    ...(role === "assistant" ? {
      turnId: `turn-${id}`,
      status: "completed",
      turnItems: [{
        id: `answer-${id}`, itemId: `answer-${id}`, version: 3,
        sessionId: "session-avatars", turnId: `turn-${id}`,
        type: "agent_message", phase: "final_answer", text: content,
        status: "completed", revision: 1, sequence: 1, terminal: true,
      }],
    } : {}),
  };
}

function renderConversation(
  messages: ConversationMessage[],
  overrides: Partial<React.ComponentProps<typeof ConversationView>> = {},
) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const html = renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <ConversationView
        sessionId="session-avatars"
        title="Assistant"
        phase="ready"
        messages={messages}
        showHeader={false}
        showSessionOverview={false}
        showComposer={false}
        composerVariant="codex"
        assistantDisplayName="Assistant"
        assistantAvatarImageUrl="/avatars/assistant.png"
        userDisplayName="Owner"
        userAvatarImageUrl="/avatars/owner.png"
        composerValue=""
        composerPlaceholder="Type"
        composerDisabled={false}
        composerPending={false}
        defaultFileContext="workspace"
        onComposerChange={() => undefined}
        onSubmit={() => undefined}
        onStop={() => undefined}
        onClear={() => undefined}
        onJumpToLatest={() => undefined}
        onCreateNewSession={() => undefined}
        {...overrides}
      />
    </QueryClientProvider>,
  );
  const document = new Window().document;
  document.body.innerHTML = html;
  return document.body;
}

describe("configured conversation avatars", () => {
  it("renders each consecutive message's configured avatar outside the minimal header body", () => {
    const messages = [
      message("user-1", "user"),
      message("user-2", "user"),
      message("assistant-1", "assistant"),
      message("assistant-2", "assistant"),
    ];
    const body = renderConversation(messages);
    const turns = [...body.querySelectorAll("article[data-conversation-message-key]")];
    expect(turns).toHaveLength(messages.length);
    turns.forEach((turn, index) => {
      const role = messages[index].role;
      expect(turn.classList.contains("turnWithAvatarGutters")).toBe(true);
      expect(turn.classList.contains(`${role}Turn`)).toBe(true);
      expect(turn.getAttribute("data-conversation-identity")).toBe("minimal");
      expect(turn.querySelector(".turnMeta")).toBeNull();
      const avatar = turn.querySelector('[data-conversation-avatar="true"]');
      expect(avatar?.parentElement).toBe(turn);
      expect(avatar?.querySelector("img")?.getAttribute("src"))
        .toBe(role === "assistant" ? "/avatars/assistant.png" : "/avatars/owner.png");
      expect(turn.querySelector(".turnContent")?.contains(avatar ?? null)).toBe(false);
    });
  });

  it("uses configured fallback symbols when profile images are absent", () => {
    const body = renderConversation([message("user", "user"), message("assistant", "assistant")], {
      assistantAvatarImageUrl: undefined,
      assistantAvatarFallback: "鲸",
      userAvatarImageUrl: undefined,
      userAvatarPreset: "codex",
    });
    expect([...body.querySelectorAll('[data-conversation-avatar="true"]')].map(node => node.textContent))
      .toEqual(["C", "鲸"]);
  });

  it.each([
    { name: "Companion", companionMode: true },
    { name: "legacy compact", composerVariant: "compact" as const },
  ])("preserves $name speaker and avatar presentation", ({ name: _name, ...overrides }) => {
    const body = renderConversation([message("assistant", "assistant")], overrides);
    const turn = body.querySelector("article[data-conversation-message-key]");
    expect(turn?.classList.contains("turnWithAvatarGutters")).toBe(false);
    expect(turn?.getAttribute("data-conversation-identity")).toBe("speaker");
    expect(turn?.querySelector(".turnMeta")).toBeTruthy();
    expect(turn?.querySelector('[data-conversation-avatar="true"] img')?.getAttribute("src"))
      .toBe("/avatars/assistant.png");
    expect(body.querySelector(".timelineWithAvatarGutters")).toBeNull();
  });

  it.each(["agent_inbox_message", "group_room_transcript"])("preserves %s identity and routing", (kind) => {
    const body = renderConversation([{
      ...message("external", "user"),
      metadata: { kind, sourceAgentCode: "A011", sourceAgentName: "External" },
    }], { resolveTurnAvatar: () => ({ imageUrl: "/avatars/external.png", fallback: "E" }) });
    const turn = body.querySelector("article[data-conversation-message-key]");
    expect(turn?.classList.contains("turnWithAvatarGutters")).toBe(false);
    expect(turn?.getAttribute("data-conversation-identity")).toBe("speaker");
    expect(turn?.querySelector(".turnMeta")).toBeTruthy();
    if (kind === "agent_inbox_message") {
      expect(turn?.classList.contains("agentInboxTurn")).toBe(true);
      expect(turn?.querySelector('[data-conversation-avatar="true"] img')?.getAttribute("src"))
        .toBe("/avatars/external.png");
    } else {
      expect(turn?.classList.contains("groupTranscriptTurn")).toBe(true);
      expect(turn?.querySelector('[data-conversation-avatar="true"] svg')).toBeTruthy();
    }
  });

  it("reserves symmetric outside gutters and reduces avatar size within narrow scroll areas", () => {
    expect(styles.composerCodex).toContain("max-w-[760px]");
    for (const turn of [styles.assistantTurnWithAvatarGutters, styles.userTurnWithAvatarGutters]) {
      // 848px minus two 32px avatars and two 12px gaps leaves 760px for text.
      expect(turn).toContain("max-w-[848px]");
      expect(turn).toContain("mx-auto");
      expect(turn).toContain("grid-cols-[2rem_minmax(0,1fr)_2rem]");
      expect(turn).toContain("[&_.turnContent]:col-start-2");
      expect(turn).toContain("[&_.turnAvatar]:mt-0");
      expect(turn).toContain("max-[719px]:grid-cols-[1.75rem_minmax(0,1fr)_1.75rem]");
      expect(turn).toContain("max-[719px]:[&_.turnAvatar]:size-7");
    }
    expect(styles.assistantTurnWithAvatarGutters).toContain("[&_.turnAvatar]:col-start-1");
    expect(styles.userTurnWithAvatarGutters).toContain("[&_.turnAvatar]:col-start-3");
    expect(styles.timelineWithAvatarGutters).toContain("px-3");
    expect(styles.timelineWithAvatarGutters).toContain("[scrollbar-gutter:stable_both-edges]");
    expect(styles.timelineAreaWithAvatarGutters).toContain("@min-[960px]/conversation:");
  });
});
