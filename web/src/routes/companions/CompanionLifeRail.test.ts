import { describe, expect, it } from "vitest";

import railSource from "./CompanionLifeRail.tsx?raw";
import preferenceSource from "./CompanionPreferenceCard.tsx?raw";
import styles from "./CompanionChatRails.styles";

describe("virtual-human life rail memory projection", () => {
  it("renders real episodic memories with salience, time, and event provenance", () => {
    expect(railSource).toContain("fetchVirtualHumanMemories");
    expect(railSource).toContain("CompanionLifeWorldCard");
    expect(railSource).toContain("queryKeys.virtualHumanMemories");
    expect(railSource).toContain("MemoryRows");
    expect(railSource).toContain("memory.text");
    expect(railSource).toContain("memory.salienceScore");
    expect(railSource).toContain("memory.sourceEventIds");
    expect(railSource).toContain("memory.promotedAt");
    expect(railSource).toContain("memory.memoryStrengthScore");
    expect(railSource).toContain("memory.scoreBreakdown");
    expect(railSource).toContain("memory.reinforcedAt");
    expect(railSource).toContain("sort((left, right) => memoryTimestamp(right) - memoryTimestamp(left))");
    expect(railSource).toContain("styles.memoryVisual");
    expect(railSource).toContain("段重要生活片段");
  });

  it("opens the hidden life steward through the Chat route owner", () => {
    expect(railSource).toContain("onOpenLifeSteward");
    expect(railSource).not.toContain("/chat?session=");
  });

  it("projects causal life continuity without adding another chat or data route", () => {
    expect(railSource).toContain("snapshot.causal");
    expect(railSource).toContain("locationStatus");
    expect(railSource).toContain("environment.currentFacts");
    expect(railSource).toContain("recentReflections");
    expect(railSource).toContain('item.status === "approved"');
    expect(railSource).toContain('item.sourceKind !== "dream"');
    expect(railSource).toContain("proactiveCandidates");
    expect(railSource).toContain("个人目标");
    expect(railSource).toContain("自我人生线");
    expect(railSource).toContain("夜间回想");
    expect(railSource).toContain("想说的话");
    expect(railSource).toContain("生活节律");
    expect(railSource).toContain("呈现与表达");
    expect(railSource).toContain("长期日历");
    expect(railSource).toContain("兴趣成长");
    expect(railSource).toContain("生活动态");
    expect(railSource).toContain("待审核的变化");
    expect(railSource).toContain("executeVirtualHumanCommand");
    expect(railSource).toContain('command: "reviewReflectionProposal"');
    expect(railSource).toContain('reviewerKind: "operator"');
    expect(railSource).toContain("companion.snapshot.state?.stateVersion");
    expect(railSource).toContain("reflectionReviewIdempotencyKey");
    expect(railSource).toContain("Math.imul(hash, 16777619)");
    expect(railSource).toContain("批准变化");
    expect(railSource).toContain("拒绝");
    expect(railSource).toContain("她的社会圈");
    expect(railSource).toContain("熟悉的地点与物品");
    expect(railSource).toContain("snapshot.todayCalendar");
    expect(railSource).toContain("snapshot.rhythms");
    expect(railSource).not.toContain("fetchVirtualHumanTimeline");
    expect(railSource).not.toContain("事实边界");
  });

  it("keeps legacy backends usable when the memories endpoint is unavailable", () => {
    expect(railSource).toContain("memoriesQuery.isError");
    expect(railSource).toContain("长期记忆暂不可用");
    expect(railSource).toContain("日记和关系仍可查看");
    expect(railSource).toContain("retry: false");
  });

  it("reviews, corrects, and deletes Agent-scoped companion preferences", () => {
    expect(railSource).toContain("CompanionPreferenceCard");
    expect(preferenceSource).toContain('command: operation === "upsert" ? "upsertCompanionPreference" : "deleteCompanionPreference"');
    expect(preferenceSource).not.toContain("fetchVirtualHumanMemories");
    expect(preferenceSource).toContain("只使用你确认过的偏好");
    expect(preferenceSource).toContain("VSelect");
    expect(preferenceSource).toContain("VInput");
    expect(preferenceSource).toContain("VButton");
    expect(preferenceSource).toContain("expectedVersion: stateVersion");
    expect(preferenceSource).not.toContain("/api/sessions/");
  });

  it("uses a stable visual desktop rail with progressive detail disclosure", () => {
    expect(styles.lifeContent).toContain("overscroll-contain");
    expect(styles.lifeContent).toContain("scrollbar-gutter:stable");
    expect(styles.lifeContent).toContain("max-[1100px]:p-2.5");
    expect(styles.lifeCard).toContain("max-[1100px]:p-2");
    expect(styles.personRail).toContain("overflow-hidden");
    expect(styles.sceneCard).toContain("radial-gradient");
    expect(styles.vitalGrid).toContain("grid-cols");
    expect(styles.meterTrack).toContain("rounded-full");
    expect(styles.scheduleItem).toContain("grid-cols-[44px_10px_minmax(0,1fr)]");
    expect(styles.detailDisclosure).toContain("group");
    expect(railSource).toContain('role="meter"');
    expect(railSource).toContain("<details className={styles.detailDisclosure}>");
  });
});
