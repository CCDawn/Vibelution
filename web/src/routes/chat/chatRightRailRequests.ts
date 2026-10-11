import type { ChatRightRailKind } from "./chatRightRailModel";

export type ChatRightRailOpenRequest = {
  sessionId: string;
  kind: Extract<ChatRightRailKind, "subagent" | "directory" | "file" | "plan" | "workflow" | "trajectory" | "bash">;
  title: string;
  targetId?: string;
  filePath?: string;
};

type ChatRightRailOpenHandler = (request: ChatRightRailOpenRequest) => boolean;

let openHandler: ChatRightRailOpenHandler | null = null;

export function subscribeChatRightRailOpen(handler: ChatRightRailOpenHandler): () => void {
  openHandler = handler;
  return () => {
    if (openHandler === handler) {
      openHandler = null;
    }
  };
}

export function requestChatRightRailOpen(request: ChatRightRailOpenRequest): boolean {
  return openHandler?.(request) ?? false;
}
