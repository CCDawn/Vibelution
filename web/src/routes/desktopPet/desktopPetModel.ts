import type {
  PetActivity,
  PetActivityPhase,
  PetActivityTone,
} from "../../api/types/petActivity";

type DesktopPetBridge = {
  openConversationFromPet?: (sessionId: string) => Promise<unknown>;
};

const SESSION_ID_PATTERN = /^[A-Za-z0-9._:-]{1,128}$/;

export function petActivityRefetchInterval(activity: PetActivity | undefined): number {
  if (!activity) {
    return 1_000;
  }
  return activity.activeCount > 0 || activity.attentionCount > 0 ? 1_000 : 3_000;
}

export function petToneLabel(tone: PetActivityTone, lang: "zh" | "en"): string {
  const labels = lang === "zh"
    ? {
        approval: "需要你确认",
        error: "有任务遇到问题",
        running: "正在陪你工作",
        completed: "刚刚完成",
        idle: "在这里等你",
      }
    : {
        approval: "Needs your approval",
        error: "A task needs attention",
        running: "Working with you",
        completed: "Just finished",
        idle: "Waiting for you",
      };
  return labels[tone];
}

export function petPhaseLabel(phase: PetActivityPhase, lang: "zh" | "en"): string {
  const labels = lang === "zh"
    ? {
        waiting: "等待确认",
        error: "执行异常",
        thinking: "思考中",
        reading: "阅读中",
        tooling: "操作工具中",
        verifying: "验证结果中",
        answering: "组织回复中",
        completed: "已完成",
      }
    : {
        waiting: "Awaiting approval",
        error: "Execution issue",
        thinking: "Thinking",
        reading: "Reading",
        tooling: "Using tools",
        verifying: "Verifying",
        answering: "Preparing answer",
        completed: "Completed",
      };
  return labels[phase];
}

export function desktopPetBridge(globalLike: unknown = globalThis): DesktopPetBridge | undefined {
  const bridge = (globalLike as { vibelutionLauncher?: unknown })?.vibelutionLauncher;
  if (typeof bridge !== "object" || bridge === null) {
    return undefined;
  }
  const candidate = bridge as DesktopPetBridge;
  if (typeof candidate.openConversationFromPet !== "function") {
    return undefined;
  }
  return { openConversationFromPet: candidate.openConversationFromPet };
}

export async function openSessionFromDesktopPet(
  sessionId: string,
  bridge = desktopPetBridge(),
): Promise<boolean> {
  const normalized = sessionId.trim();
  if (!SESSION_ID_PATTERN.test(normalized) || typeof bridge?.openConversationFromPet !== "function") {
    return false;
  }
  await bridge.openConversationFromPet(normalized);
  return true;
}
