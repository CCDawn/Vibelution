import { VButton, VStateSurface } from "../../components/vui";
import { useShellI18n } from "../../i18n/useShellI18n";
import type { usePersonalAssistant } from "./usePersonalAssistant";
import { personalAssistantSessionMatches } from "./personalAssistantModel";

const COPY = {
  zh: {
    selectionMismatchTitle: "会话与个人助理身份不匹配",
    selectionMismatchBody: "这个入口只接受个人助理自己的原生会话。",
    backToAssistantSession: "返回个人助理会话",
    connectFailedTitle: "个人助理暂时无法连接",
    retry: "重试",
    retryLater: "请稍后重试。",
    bindingMismatchTitle: "原生会话与个人助理身份不匹配",
    bindingMismatchBody: "会话归属与个人助理的 Agent 不一致，暂时不能开始聊天。",
    reconfirmIdentity: "重新确认身份",
    connectingTitle: "正在连接个人助理",
    connectingBody: "正在确认智能体与原生会话。",
    recoveryTitle: "个人助理需要恢复",
    recoveryBody: "智能体与会话绑定尚未就绪，暂时不能开始聊天。",
    recoverAndRetry: "恢复并重试",
  },
  en: {
    selectionMismatchTitle: "Session does not match the personal assistant",
    selectionMismatchBody: "This entrance only accepts the personal assistant's own native session.",
    backToAssistantSession: "Back to the assistant session",
    connectFailedTitle: "The personal assistant cannot connect right now",
    retry: "Retry",
    retryLater: "Please try again later.",
    bindingMismatchTitle: "Native session does not match the personal assistant",
    bindingMismatchBody: "The session belongs to a different agent, so the chat cannot start yet.",
    reconfirmIdentity: "Reconfirm identity",
    connectingTitle: "Connecting to the personal assistant",
    connectingBody: "Confirming the agent and its native session.",
    recoveryTitle: "The personal assistant needs recovery",
    recoveryBody: "The agent and session binding is not ready yet, so the chat cannot start.",
    recoverAndRetry: "Recover and retry",
  },
} as const;

export function PersonalAssistantState({ state }: { state: ReturnType<typeof usePersonalAssistant> }) {
  const { lang } = useShellI18n();
  const copy = COPY[lang];
  if (state.selectionMismatch) return <VStateSurface fill tone="error" title={copy.selectionMismatchTitle}
    actions={<VButton onClick={() => state.route.openSession(state.assistant!.directSessionId)}>{copy.backToAssistantSession}</VButton>}>
    {copy.selectionMismatchBody}
  </VStateSurface>;
  const error = state.setup.error || state.binding.error;
  if (error) return <VStateSurface fill tone="error" title={copy.connectFailedTitle}
    actions={<VButton onClick={() => { void (state.setup.isError ? state.setup.refetch() : state.binding.refetch()); }}>{copy.retry}</VButton>}>
    {error instanceof Error ? error.message : copy.retryLater}
  </VStateSurface>;
  if (state.ready && state.assistant && state.binding.isSuccess && !personalAssistantSessionMatches(state.assistant, state.binding.data)) return <VStateSurface fill tone="error" title={copy.bindingMismatchTitle}
    actions={<VButton onClick={() => void state.binding.refetch()}>{copy.reconfirmIdentity}</VButton>}>
    {copy.bindingMismatchBody}
  </VStateSurface>;
  if (state.setup.isPending || (state.ready && (state.binding.isPending || state.route.selection.kind === "bare"))) {
    return <VStateSurface fill tone="loading" busy skeletonLines title={copy.connectingTitle}>{copy.connectingBody}</VStateSurface>;
  }
  return <VStateSurface fill tone="unavailable" title={copy.recoveryTitle}
    actions={<VButton onClick={() => { void state.setup.refetch(); }}>{copy.recoverAndRetry}</VButton>}>
    {copy.recoveryBody}
  </VStateSurface>;
}
