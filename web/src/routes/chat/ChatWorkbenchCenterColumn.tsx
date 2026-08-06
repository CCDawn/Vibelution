/**
 * Center column host for the Chat session workbench shell `center` slot.
 */
import type { ReactNode } from "react";

export type ChatWorkbenchCenterColumnProps = {
  className: string;
  surfaceClassName: string;
  tabStrip: ReactNode;
  surface: ReactNode;
};

export function ChatWorkbenchCenterColumn({
  className,
  surfaceClassName,
  tabStrip,
  surface,
}: ChatWorkbenchCenterColumnProps) {
  return (
    <section className={className} data-vui-region="chat-conversation-center">
      {tabStrip}
      <div className={surfaceClassName}>{surface}</div>
    </section>
  );
}
