import { lazy, Suspense } from "react";
import { VStateSurface } from "../../components/vui";
import styles from "./TeamNativeConversation.styles";

const NativeChat = lazy(() => import("../ChatCodingRoute").then((module) => ({ default: module.ChatCodingRoute })));

/** Teams owns the frame; native Chat still owns admission, transcript, streaming and composer actions. */
export function TeamNativeConversation({ lang }: { lang: "zh" | "en" }) {
  return <div data-testid="team-native-conversation" className={styles.root}>
    <Suspense fallback={<VStateSurface tone="loading" title={lang === "zh" ? "正在读取对话" : "Loading conversation"} skeletonLines={3} />}><NativeChat /></Suspense>
  </div>;
}
