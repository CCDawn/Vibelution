import { lazy, Suspense, type ReactNode } from "react";

import type { ConversationViewProps } from "./ConversationView";

const ConversationView = lazy(async () => {
  const module = await import("./ConversationView");
  return { default: module.ConversationView };
});

type LazyConversationViewProps = ConversationViewProps & {
  fallback: ReactNode;
};

export function LazyConversationView({ fallback, ...props }: LazyConversationViewProps) {
  return (
    <Suspense fallback={fallback}>
      <ConversationView {...props} />
    </Suspense>
  );
}
