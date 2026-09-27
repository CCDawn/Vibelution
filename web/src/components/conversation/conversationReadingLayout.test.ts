import { describe, expect, it } from "vitest";
import styles from "./ConversationView.styles";
import agentStyles from "./AgentMessageTurnView.styles";
import userStyles from "./AgentUserContentSectionView.styles";

describe("approved conversation reading hierarchy", () => {
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
    for (const surface of [styles.composerCodex, styles.userMessageBody, userStyles.userMessageBody]) {
      expect(surface).toContain("rounded-xl");
      expect(surface).toContain("shadow-none");
      expect(surface).toContain("border-[var(--vui-border-subtle)]");
    }
  });
});
