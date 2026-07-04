import type { AgentMessageTimelineItem } from "./agentMessageTimeline";

type TimelineMessageStreamingState = {
  streaming?: boolean;
};

export function activeAgentMessageTimelineItemId(
  message: TimelineMessageStreamingState,
  items: AgentMessageTimelineItem[],
) {
  if (!message.streaming) {
    return "";
  }
  for (let index = items.length - 1; index >= 0; index -= 1) {
    const item = items[index];
    if (item?.kind !== "assistant_text" && item?.status === "running") {
      return item.id;
    }
  }
  return "";
}
