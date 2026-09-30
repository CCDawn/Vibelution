import { readdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";
import styles from "./ConversationView.styles";
import agentStyles from "./AgentMessageTurnView.styles";
import userStyles from "./AgentUserContentSectionView.styles";
import todoStyles from "./ConversationTodoChecklist.styles";
import streamStyles from "./ConversationStreamingResponseContent.styles";
import { conversationMarkdownRendererStyles, conversationMarkdownCodeBlockStyles } from "./ConversationMarkdownRenderer.styles";

describe("approved conversation reading hierarchy", () => {
  it("shares every Markdown style across stable, live and settled transcript paths", () => {
    for (const [key, value] of Object.entries(conversationMarkdownRendererStyles)) {
      expect(streamStyles[key as keyof typeof conversationMarkdownRendererStyles]).toBe(value);
    }
    expect(streamStyles.messageBody).toContain("mb-3");
    expect(streamStyles.messageBody).toContain("last:mb-0");
    expect(streamStyles.markdownBody).toContain("leading-[1.8]");
    expect(streamStyles.streamingResponseText).not.toContain("text-vui-chat");
  });
  it("keeps code chrome complete and long output independently scrollable", () => {
    expect(streamStyles.responseSegmentPre).toContain("max-h-80");
    expect(streamStyles.responseSegmentPre).toContain("overflow-auto");
    expect(streamStyles.responseSegmentPre).toContain("px-4");
    expect(streamStyles.responseSegmentPre).toContain("border-[var(--vui-border-subtle)]");
    expect(conversationMarkdownCodeBlockStyles.preAttached).toContain("mt-0");
    expect(conversationMarkdownCodeBlockStyles.preAttached).toContain("border-t-0");
  });
  it("uses the shared type scale for Markdown headings", () => {
    ["xl", "lg", "md", "sm"].forEach((size, index) => {
      const heading = [styles.markdownHeading1, styles.markdownHeading2, styles.markdownHeading3, styles.markdownHeading4][index];
      expect(heading).toContain(`text-vui-${size}`);
      expect(heading).not.toMatch(/text-\[[\d.]+em\]/);
    });
  });
  it("keeps identities visible but quieter than the answer", () => {
    for (const identity of [styles.turnSpeaker, agentStyles.turnSpeaker]) {
      expect(identity).toContain("text-vui-xs");
      expect(identity).toContain("font-medium");
      expect(identity).not.toContain("hidden");
    }
  });
  it("aligns the composer rail and uses consistent bubble chrome", () => {
    expect(styles.composerCodex).toContain("max-w-[830px]");
    expect(styles.assistantTurn).toContain("max-w-[830px]");
    // One spelling of the transcript measure across the whole surface.
    expect(todoStyles.card).toContain("max-w-[830px]");
    for (const surface of [styles.composerCodex, styles.userMessageBody, userStyles.userMessageBody]) {
      expect(surface).toContain("rounded-xl");
      expect(surface).toContain("shadow-none");
      expect(surface).toContain("border-[var(--vui-border-subtle)]");
    }
  });
  // Split literal: the scan must not match its own source text.
  const STRANDED_RADIUS = "rounded-" + "[14px]";
  it("keeps every conversation corner on the approved radius ladder", () => {
    // 14px was a second bubble radius beside the approved rounded-xl; it must not return.
    const offenders: string[] = [];
    for (const file of readdirSync(import.meta.dirname)) {
      if (!file.endsWith(".ts")) continue;
      const source = readFileSync(resolve(import.meta.dirname, file), "utf8");
      if (source.includes(STRANDED_RADIUS)) offenders.push(file);
    }
    expect(offenders).toEqual([]);
  });
});
