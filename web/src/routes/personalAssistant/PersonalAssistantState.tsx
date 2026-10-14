import { VButton, VStateSurface } from "../../components/vui";
import type { usePersonalAssistant } from "./usePersonalAssistant";
import { personalAssistantSessionMatches } from "./personalAssistantModel";

export function PersonalAssistantState({ state }: { state: ReturnType<typeof usePersonalAssistant> }) {
  if (state.selectionMismatch) return <VStateSurface fill tone="error" title="会话与个人助理身份不匹配"
    actions={<VButton onClick={() => state.route.openSession(state.assistant!.directSessionId)}>返回个人助理会话</VButton>}>
    这个入口只接受个人助理自己的原生会话。
  </VStateSurface>;
  const error = state.setup.error || state.binding.error;
  if (error) return <VStateSurface fill tone="error" title="个人助理暂时无法连接"
    actions={<VButton onClick={() => { void (state.setup.isError ? state.setup.refetch() : state.binding.refetch()); }}>重试</VButton>}>
    {error instanceof Error ? error.message : "请稍后重试。"}
  </VStateSurface>;
  if (state.ready && state.assistant && state.binding.isSuccess && !personalAssistantSessionMatches(state.assistant, state.binding.data)) return <VStateSurface fill tone="error" title="原生会话与个人助理身份不匹配"
    actions={<VButton onClick={() => void state.binding.refetch()}>重新确认身份</VButton>}>
    会话归属与个人助理的 Agent 不一致，暂时不能开始聊天。
  </VStateSurface>;
  if (state.setup.isPending || (state.ready && (state.binding.isPending || state.route.selection.kind === "bare"))) {
    return <VStateSurface fill tone="loading" busy skeletonLines title="正在连接个人助理">正在确认智能体与原生会话。</VStateSurface>;
  }
  return <VStateSurface fill tone="unavailable" title="个人助理需要恢复"
    actions={<VButton onClick={() => { void state.setup.refetch(); }}>恢复并重试</VButton>}>
    智能体与会话绑定尚未就绪，暂时不能开始聊天。
  </VStateSurface>;
}
