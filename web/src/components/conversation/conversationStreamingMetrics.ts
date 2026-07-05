export type ConversationStreamingFramePaintMetrics = {
  sessionId: string;
  paintedAtMs: number;
  streamingMessageCount: number;
  renderedTextLength: number;
  scrollSignal: string;
};
