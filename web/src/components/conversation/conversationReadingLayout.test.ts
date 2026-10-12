import { describe, expect, it } from "vitest";
import styles from "./ConversationView.styles";
import agentStyles from "./AgentMessageTurnView.styles";
import userStyles from "./AgentUserContentSectionView.styles";
import todoStyles from "./ConversationTodoChecklist.styles";
import streamStyles from "./ConversationStreamingResponseContent.styles";
import { conversationMarkdownRendererStyles, conversationMarkdownCodeBlockStyles } from "./ConversationMarkdownRenderer.styles";

describe("approved conversation reading hierarchy", () => {
  it("reserves navigation space only in wide conversation containers", () => {
    expect(styles.timelineArea).toContain("@container/conversation");
    expect(styles.timeline).toContain("@min-[864px]/conversation:pl-14");
    // The existing bottom-right jump control still needs its safe corridor.
    expect(styles.timeline).toContain("pr-[clamp(3rem,3vw,3.5rem)]");
  });
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
    expect(agentStyles.turnSpeaker).toContain("text-vui-2xs");
    expect(agentStyles.turnSpeaker).toContain("font-medium");
    expect(agentStyles.turnSpeaker).not.toContain("hidden");
  });
  it("aligns the composer rail and uses distinct approved bubble chrome", () => {
    expect(styles.composerCodex).toContain("max-w-[760px]");
    expect(styles.assistantTurn).toContain("max-w-[760px]");
    // The checklist is nested within the capped turn body, so its own upper
    // bound cannot widen the transcript rail.
    expect(todoStyles.card).toContain("max-w-[830px]");
    expect(styles.composerCodex).toContain("rounded-[16px]");
    expect(styles.composerCodex).toContain("shadow-[var(--vui-sheen),0_2px_5px_color-mix(in_srgb,var(--fg-primary)_4%,transparent),0_8px_24px_color-mix(in_srgb,var(--fg-primary)_3%,transparent)]");
    expect(styles.composerCodex).toContain("border-[color-mix(in_srgb,var(--fg-primary)_13%,transparent)]");
    expect(styles.composerCodex).toContain("[[data-theme=dark]_&]:bg-[var(--vui-surface-raised)]");
    expect(styles.composerCodex).toContain("[[data-theme=dark]_&]:focus-within:border-[color-mix(in_srgb,var(--accent-cool)_60%,var(--vui-border-subtle))]");
    expect(styles.composerCodex).toContain("[[data-theme=dark]_&]:focus-within:shadow-[0_0_0_2px_color-mix(in_srgb,var(--accent-cool)_10%,transparent),var(--vui-sheen),0_3px_14px_color-mix(in_srgb,var(--fg-primary)_5%,transparent)]");
    for (const bubble of [styles.userMessageBody, userStyles.userMessageBody]) {
      expect(bubble).toContain("rounded-[12px]");
      expect(bubble).toContain("shadow-[var(--vui-sheen)]");
      expect(bubble).toContain("border-[var(--border-hairline)]");
    }
  });
});
