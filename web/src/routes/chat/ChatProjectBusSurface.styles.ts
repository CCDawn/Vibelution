import group from "./ChatGroupCenterSurface.styles";

export default {
  ...group,
  groupConversationFrame: `${group.groupConversationFrame} !flex !flex-col`,
  messageDetailFrame: "min-h-0 flex-1 overflow-hidden",
  revokeRow: "shrink-0 px-5 pb-2",
} as const;
