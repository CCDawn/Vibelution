import { type ComponentPropsWithoutRef, type ReactNode } from "react";

import { type TeamSourceResultTone } from "./teamSourceTone";

export type TeamStatusLabelProps = Omit<ComponentPropsWithoutRef<"span">, "children"> & {
  children: ReactNode;
  tone: TeamSourceResultTone;
};

const TONE_CLASS: Record<TeamSourceResultTone, string> = {
  ready: "text-[var(--fg-secondary)]",
  neutral: "text-[var(--fg-tertiary)]",
  warning: "text-[var(--state-warning)]",
  danger: "text-[var(--state-danger)]",
};

/**
 * Non-interactive Team status presentation. It deliberately avoids chip/button
 * chrome so only actual actions read as controls.
 */
export function TeamStatusLabel({
  children,
  tone,
  className,
  ...props
}: TeamStatusLabelProps) {
  return (
    <span
      data-vui-product="team-status-label"
      data-tone={tone}
      className={[
        "inline-flex min-w-0 max-w-full items-center gap-1.5 whitespace-nowrap",
        "[font-size:var(--vui-font-xs)] font-[720] leading-none",
        TONE_CLASS[tone],
        className,
      ]
        .filter(Boolean)
        .join(" ")}
      {...props}
    >
      <span
        aria-hidden="true"
        className="size-1.5 shrink-0 rounded-full bg-current opacity-65"
      />
      <span className="min-w-0 truncate">{children}</span>
    </span>
  );
}
