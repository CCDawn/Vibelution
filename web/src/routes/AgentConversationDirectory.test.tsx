import { describe, expect, it } from "vitest";

import directorySource from "./AgentConversationDirectory.tsx?raw";
import styles from "./AgentConversationDirectory.styles";

describe("AgentConversationDirectory", () => {
  it("renders Agent identity as the left navigation item and keeps session count as metadata", () => {
    expect(directorySource).toContain('aria-label={lang === "zh" ? "Agent 管理" : "Agent management"}');
    expect(directorySource).toContain("agent.displayName");
    expect(directorySource).toContain("agent.llmBindings?.dialogue?.modelId");
    expect(directorySource).toContain("sessionCountByAgentId");
    expect(directorySource).toContain('aria-current={active ? "page" : undefined}');
    expect(directorySource).toContain("onContextMenu={(event) => onContextMenu(event, agent, latestSession ?? null)}");
  });

  it("uses plain multi-line button layout so avatar/title/meta are not crushed into a nowrap label", () => {
    expect(directorySource).toContain('contentLayout="plain"');
    expect(styles.agentRow).toContain("!grid");
    expect(styles.agentRow).toContain("!h-auto");
    expect(styles.agentRow).toContain("!w-full");
    expect(styles.agentRow).toContain("grid-cols-[32px_minmax(0,1fr)]");
    expect(styles.agentTitle).toContain("[font-size:var(--vui-font-sm)]");
    expect(styles.agentTitle).toContain("[color:var(--fg-primary)]");
    expect(styles.agentMeta).toContain("[font-size:var(--vui-font-xs)]");
    expect(styles.agentMeta).not.toContain("text-[var(--vui-font-xs)]");
  });
});
