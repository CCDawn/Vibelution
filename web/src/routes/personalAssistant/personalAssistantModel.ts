import type { PersonalAssistant, PersonalAssistantAppearance } from "../../api/types/personalAssistant";

export function personalAssistantReturnTarget(sessionId: string): { pathname: string; search: string } {
  return { pathname: "/personal-assistant", search: `?${new URLSearchParams({ session: sessionId }).toString()}` };
}

/** Renderer contract whitelist: whale rig and Xiao Luo Live2D. */
export const PERSONAL_ASSISTANT_RENDERERS = ["whale", "xiaoluo"] as const;

export function personalAssistantAppearance(renderer: string): PersonalAssistantAppearance {
  return renderer === "xiaoluo" ? "xiaoluo" : "dafeiyu";
}

export function validPersonalAssistant(assistant: PersonalAssistant | null | undefined): assistant is PersonalAssistant {
  return Boolean(assistant?.agentId && assistant.directSessionId && assistant.status === "active"
    && assistant.setupStatus === "ready" && assistant.profile === "personal_assistant_v1"
    && PERSONAL_ASSISTANT_RENDERERS.includes(assistant.renderer));
}

export function personalAssistantSessionMatches(
  assistant: PersonalAssistant,
  session: { id: string; agentId?: string; agentMissing?: boolean; sessionKind?: string } | undefined,
): boolean {
  return Boolean(session && session.id === assistant.directSessionId && session.agentId === assistant.agentId
    && !session.agentMissing && (!session.sessionKind || session.sessionKind === "main"));
}

export function assistantStatusLabel(status: string, lang: "zh" | "en" = "zh"): string {
  const labels: Record<string, readonly [string, string]> = {
    running: ["运行中", "Running"], active: ["就绪", "Ready"], ready: ["就绪", "Ready"], idle: ["空闲", "Idle"],
    waiting: ["等待处理", "Waiting"], waiting_approval: ["等待确认", "Awaiting confirmation"],
    failed: ["失败", "Failed"], error: ["异常", "Error"], completed: ["已完成", "Completed"], stopped: ["已停止", "Stopped"], cancelled: ["已取消", "Cancelled"],
    thinking: ["思考中", "Thinking"], tooling: ["操作工具中", "Using tools"], answering: ["回复中", "Responding"], verifying: ["验证中", "Verifying"],
    reading: ["读取中", "Reading"], queued: ["排队中", "Queued"], failed_runtime: ["运行异常", "Runtime error"], failed_provider: ["模型异常", "Model error"],
  };
  return labels[status]?.[lang === "zh" ? 0 : 1] ?? status;
}
