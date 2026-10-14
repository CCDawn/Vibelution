import { lazy, Suspense } from "react";
import { VStateSurface } from "../../components/vui";

const NativeChat = lazy(() => import("../ChatCodingRoute").then((module) => ({ default: module.ChatCodingRoute })));

/** Teams owns the frame; native Chat still owns admission, transcript, streaming and composer actions. */
export function TeamNativeConversation({ lang }: { lang: "zh" | "en" }) {
  return <div data-testid="team-native-conversation" className="flex h-full min-h-0 min-w-0 flex-1 flex-col overflow-hidden [&_[data-vui=chat-session-workbench-shell]]:h-full! [&_[data-vui=chat-session-workbench-shell]]:max-h-full! [&_[data-vui=chat-session-workbench-shell]]:grid-cols-[minmax(0,1fr)]! [&_[data-vui=chat-session-workbench-shell]>:not([data-vui-region=chat-conversation-center])]:hidden! [&_[data-vui-region=chat-conversation-center]]:col-start-1! [&_[data-vui-region=chat-conversation-center]]:row-start-1! [&_[data-vui-region=chat-conversation-center]]:m-0! [&_[data-vui-region=chat-conversation-center]]:border-0! [&_[data-vui-region=chat-conversation-center]]:rounded-none! [&_[data-vui-region=chat-conversation-center]]:grid-rows-[minmax(0,1fr)]! [&_.tabStrip]:hidden! [&_.groupConversationFrame]:grid-rows-[minmax(0,1fr)_auto] [&_.groupConversationHeader]:hidden">
    <Suspense fallback={<VStateSurface tone="loading" title={lang === "zh" ? "正在读取对话" : "Loading conversation"} skeletonLines={3} />}><NativeChat /></Suspense>
  </div>;
}
