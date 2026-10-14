type Language = "zh" | "en";

const labels: Record<string, [string, string]> = {
  simulation: ["日程模拟", "Schedule simulation"],
  simulation_isolated: ["日程模拟（已隔离）", "Schedule simulation (isolated)"],
  verified_action: ["工具行动（有回执）", "Tool action (receipt recorded)"],
  character_report: ["人物自述", "Character report"],
  unknown: ["来源未核实", "Unverified source"],
};

export function companionProvenanceLabel(
  sourceKind: string | null | undefined,
  lang: Language,
  excludedFromRecall?: boolean | null,
): string {
  const key = sourceKind === "simulation" && excludedFromRecall === true
    ? "simulation_isolated"
    : sourceKind || "unknown";
  const label = labels[key] ?? labels.unknown;
  return label[lang === "zh" ? 0 : 1];
}
