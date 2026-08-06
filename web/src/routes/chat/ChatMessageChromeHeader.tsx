/**
 * Dense message / conversation chrome headers for Chat group surfaces.
 *
 * Decision (medium-risk review):
 * - **Not** VPanelHeader — bubble density and identity layout differ from panel titles.
 * - **Not** a public VUI product export yet — only Chat group/notice surfaces consume it.
 * - Shared route-local chrome removes repeated `<header>` markup.
 * Promote to `vui/product/chat/` only when a second domain needs the same chrome.
 */
import type { ReactNode } from "react";

export type ChatMessageChromeHeaderProps = {
  className?: string;
  /**
   * Bubble: title + optional trailing as a single flex row.
   * Surface: eyebrow / title / meta column + trailing actions (conversation strip).
   */
  density?: "bubble" | "surface";
  title: ReactNode;
  trailing?: ReactNode;
  meta?: ReactNode;
  eyebrow?: ReactNode;
  titleRowClassName?: string;
};

export function ChatMessageChromeHeader({
  className,
  density = "bubble",
  title,
  trailing,
  meta,
  eyebrow,
  titleRowClassName,
}: ChatMessageChromeHeaderProps) {
  if (density === "bubble") {
    return (
      <div
        className={className}
        data-vui="chat-message-chrome-header"
        data-density="bubble"
      >
        {title}
        {trailing}
      </div>
    );
  }

  return (
    <div
      className={className}
      data-vui="chat-message-chrome-header"
      data-density="surface"
    >
      <div>
        {eyebrow}
        {titleRowClassName ? <div className={titleRowClassName}>{title}</div> : title}
        {meta}
      </div>
      {trailing}
    </div>
  );
}
