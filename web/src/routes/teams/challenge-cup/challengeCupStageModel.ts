import type { TeamStageTone } from "../../../components/vui/product/team-management";

export const CHALLENGE_CUP_STAGES = [
  "knowledge_collection",
  "experiment",
  "iteration",
] as const;

export type ChallengeCupStage = (typeof CHALLENGE_CUP_STAGES)[number];
export type ChallengeCupStageStatusTone = "neutral" | "active" | "ready" | "warning";

export type ChallengeCupStageStatus = {
  label: string;
  tone: ChallengeCupStageStatusTone;
  count: string;
};

export type ChallengeCupQuestion = {
  id: string;
  kind: "黄金样例" | "试运行题";
  machinePassed: boolean;
  humanApproved: boolean;
  humanStatus: "approved" | "pending" | "revision_requested" | "rejected";
};

export const CHALLENGE_CUP_STAGE_META: Record<ChallengeCupStage, {
  index: string;
  label: string;
  detail: string;
}> = {
  knowledge_collection: { index: "01", label: "知识搜集", detail: "资料与证据" },
  experiment: { index: "02", label: "实验设计", detail: "假设与方案" },
  iteration: { index: "03", label: "执行与迭代", detail: "运行与结论" },
};

export function challengeCupStageTone(tone: ChallengeCupStageStatusTone): TeamStageTone {
  if (tone === "warning") return "failed";
  if (tone === "neutral") return "idle";
  return "active";
}
