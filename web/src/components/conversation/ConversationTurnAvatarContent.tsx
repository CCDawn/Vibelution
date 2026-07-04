import { MessageSquarePlus } from "lucide-react";
import React from "react";

import type { TurnAvatarContent } from "./conversationTurnAvatar";

type ConversationTurnAvatarContentProps = {
  content: TurnAvatarContent;
  imageClassName: string;
};

export function ConversationTurnAvatarContent({
  content,
  imageClassName,
}: ConversationTurnAvatarContentProps) {
  if ("icon" in content) {
    return <MessageSquarePlus size={17} />;
  }
  if (content.imageUrl) {
    return <img src={content.imageUrl} alt="" className={imageClassName} />;
  }
  return content.fallback;
}
