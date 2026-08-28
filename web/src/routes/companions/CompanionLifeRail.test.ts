import { describe, expect, it } from "vitest";

import railSource from "./CompanionLifeRail.tsx?raw";
import styles from "./CompanionChatRails.styles";

describe("virtual-human life rail memory projection", () => {
  it("renders real episodic memories with salience, time, and event provenance", () => {
    expect(railSource).toContain("fetchVirtualHumanMemories");
    expect(railSource).toContain("queryKeys.virtualHumanMemories");
    expect(railSource).toContain("MemoryRows");
    expect(railSource).toContain("memory.text");
    expect(railSource).toContain("memory.salienceScore");
    expect(railSource).toContain("memory.sourceEventIds");
    expect(railSource).toContain("memory.promotedAt");
    expect(railSource).toContain("sort((left, right) => memoryTimestamp(right) - memoryTimestamp(left))");
    expect(railSource).toContain("只展示从真实生活经历晋升的记忆");
  });

  it("keeps legacy backends usable when the memories endpoint is unavailable", () => {
    expect(railSource).toContain("memoriesQuery.isError");
    expect(railSource).toContain("长期记忆暂不可用");
    expect(railSource).toContain("日记和关系仍可查看");
    expect(railSource).toContain("retry: false");
  });

  it("uses a stable scroll region and compact desktop density", () => {
    expect(styles.lifeContent).toContain("overscroll-contain");
    expect(styles.lifeContent).toContain("scrollbar-gutter:stable");
    expect(styles.lifeContent).toContain("max-[1100px]:p-2.5");
    expect(styles.lifeCard).toContain("max-[1100px]:p-2");
    expect(styles.personRail).toContain("max-[1100px]:p-2.5");
  });
});
