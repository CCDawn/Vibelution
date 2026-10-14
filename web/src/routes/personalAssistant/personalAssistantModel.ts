import type { PersonalAssistant } from "../../api/types/personalAssistant";

export function personalAssistantReturnTarget(sessionId: string): { pathname: string; search: string } {
  return { pathname: "/personal-assistant", search: `?${new URLSearchParams({ session: sessionId }).toString()}` };
}

export function validPersonalAssistant(assistant: PersonalAssistant | null | undefined): assistant is PersonalAssistant {
  return Boolean(assistant?.agentId && assistant.directSessionId && assistant.status === "active"
    && assistant.setupStatus === "ready" && assistant.profile === "personal_assistant_v1" && assistant.renderer === "whale");
}

export function personalAssistantSessionMatches(
  assistant: PersonalAssistant,
  session: { id: string; agentId?: string; agentMissing?: boolean; sessionKind?: string } | undefined,
): boolean {
  return Boolean(session && session.id === assistant.directSessionId && session.agentId === assistant.agentId
    && !session.agentMissing && (!session.sessionKind || session.sessionKind === "main"));
}

export function assistantStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    running: "运行中", active: "就绪", ready: "就绪", idle: "空闲", waiting: "等待处理", waiting_approval: "等待确认",
    failed: "失败", error: "异常", completed: "已完成", stopped: "已停止", cancelled: "已取消",
    thinking: "思考中", tooling: "操作工具中", answering: "回复中", verifying: "验证中", reading: "读取中", queued: "排队中", failed_runtime: "运行异常", failed_provider: "模型异常",
  };
  return labels[status] ?? status;
}
