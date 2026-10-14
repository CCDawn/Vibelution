import { describe, expect, it } from "vitest";

import railSource from "./CompanionLifeRail.tsx?raw";
import memorySource from "./CompanionMemoryRecords.tsx?raw";
import preferenceSource from "./CompanionPreferenceCard.tsx?raw";
import provenanceSource from "./companionProvenance.ts?raw";
import styles from "./CompanionChatRails.styles";

describe("virtual-human life rail memory projection", () => {
  it("uses one provenance label across memories, events, diary, and life feed", () => {
    expect(memorySource).toContain("companionProvenanceLabel(memory.sourceKind, lang, memory.excludedFromRecall)");
    expect(memorySource).toContain("companionProvenanceLabel(selected.sourceKind, lang, selected.excludedFromRecall)");
    expect(railSource).toContain("companionProvenanceLabel(event.sourceKind, lang)");
    expect(railSource).toContain("companionProvenanceLabel(entry.sourceKind, lang)");
    expect(railSource).toContain("companionProvenanceLabel(item.sourceKind, lang)");
    expect(railSource).toContain('"经历记录" : "Experience record"');
    expect(railSource).toContain('"还没有生活动态记录。" : "No life feed entries are available yet."');
    expect(provenanceSource).toContain('sourceKind === "simulation" && excludedFromRecall === true');
    expect(provenanceSource).toContain('simulation: ["日程模拟", "Schedule simulation"]');
    expect(provenanceSource).toContain('simulation_isolated: ["日程模拟（已隔离）", "Schedule simulation (isolated)"]');
  });

  it("uses ongoing action counts and readable Chinese rhythm labels", () => {
    expect(railSource).toContain('const isOngoing = drive.progressBasis === "ongoing";');
    expect(railSource).toContain('lang === "zh" ? "持续进行" : "Ongoing"');
    expect(railSource).toContain("已记录 ${verifiedActivityCount} 次行动");
    expect(railSource).toContain('morning: ["偏早型", "Morning-oriented"]');
    expect(railSource).toContain('balanced: ["均衡型", "Balanced"]');
    expect(railSource).toContain('evening: ["偏晚型", "Evening-oriented"]');
    expect(railSource).toContain('sleep_window: ["睡眠时段", "Sleep window"]');
    expect(railSource).toContain("circadianPhaseLabel(rhythms.circadian?.phase || \"day\", lang)");
  });

  it("opens stored episodic memory text and source records without claiming shared experiences", () => {
    expect(railSource).toContain("fetchVirtualHumanMemories");
    expect(railSource).toContain("CompanionLifeWorldCard");
    expect(railSource).toContain("queryKeys.virtualHumanMemories");
    expect(railSource).toContain("CompanionMemoryRecords");
    expect(memorySource).toContain("memory.text");
    expect(memorySource).toContain("selected.salienceScore");
    expect(memorySource).toContain("memory.sourceEventIds");
    expect(memorySource).toContain("selected.promotedAt");
    expect(memorySource).toContain("selected.reinforcedAt");
    expect(memorySource).toContain("sort((left, right) => memoryTimestamp(right) - memoryTimestamp(left))");
    expect(memorySource).not.toContain("progressTrack");
    expect(memorySource).not.toContain("memoryStrengthScore");
    expect(railSource).toContain("条长期记忆");
    expect(railSource).not.toContain("共同回忆");
    expect(railSource).not.toContain("心跳在线");
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
