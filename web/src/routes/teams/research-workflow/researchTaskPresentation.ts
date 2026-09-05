import type { VStatusTone } from "../../../components/vui";
import type { ResearchWorkflowTaskStatus } from "./researchWorkflowContextModel";

export const STATUS_LABEL: Record<ResearchWorkflowTaskStatus, string> = {
  not_started: "未开始",
  running: "进行中",
  waiting_system: "处理中",
  waiting_user: "待确认",
  recoverable_error: "可恢复",
  blocked: "已阻塞",
  never_started: "从未启动",
  failed_to_dispatch: "启动失败",
  completed: "已完成",
};

export const STATUS_TONE: Record<ResearchWorkflowTaskStatus, VStatusTone> = {
  not_started: "neutral",
  running: "accent",
  waiting_system: "accent",
  waiting_user: "warning",
  recoverable_error: "danger",
  blocked: "danger",
  never_started: "warning",
  failed_to_dispatch: "danger",
  completed: "success",
};
