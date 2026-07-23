import { type ComponentPropsWithoutRef, type ReactNode } from "react";

export type VRouteHeaderProps = ComponentPropsWithoutRef<"header"> & {
  actions?: ReactNode;
  eyebrow?: ReactNode;
  meta?: ReactNode;
  title: ReactNode;
  /**
   * Hide the eyebrow/title column so actions own the full header width.
   * Prefer this over CSS `[&>div:first-child]:hidden` — hiding the intro
   * node with display:none still leaves a broken 1fr/auto grid track and can
   * make top toolbar buttons unclickable (Evolution supervised focus mode).
   */
  hideIntro?: boolean;
};

export function VRouteHeader({
  actions,
  className,
  eyebrow,
  meta,
  title,
  hideIntro = false,
  ...props
}: VRouteHeaderProps) {
  return (
    <header
      {...props}
      data-vui="route-header"
      data-hide-intro={hideIntro ? "true" : undefined}
      className={[
        hideIntro
          ? "grid min-w-0 grid-cols-1 items-center justify-items-end gap-2"
          : "grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-2",
        "rounded-[var(--radius-panel)] border border-vui-border-subtle bg-vui-surface-glass px-3 py-2",
        "shadow-[var(--vui-shadow-hairline)] backdrop-blur-md",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {hideIntro ? null : (
        <div className="grid min-w-0 gap-0.5">
          {eyebrow ? (
            <span className="truncate text-[var(--font-size-micro)] font-semibold tracking-normal text-vui-fg-tertiary">
              {eyebrow}
            </span>
          ) : null}
          <div className="flex min-w-0 flex-wrap items-baseline gap-1.5">
            <h1 className="m-0 min-w-0 truncate text-[var(--font-size-title)] font-bold leading-tight text-vui-fg-primary">
              {title}
            </h1>
            {meta ? (
              <span className="min-w-0 truncate text-[var(--font-size-caption)] font-semibold text-vui-fg-tertiary">
                {meta}
              </span>
            ) : null}
          </div>
        </div>
      )}
      {actions ? (
        <div
          className={[
            "relative z-[1] flex min-w-0 max-w-full items-center justify-end gap-1",
            hideIntro ? "w-full" : "justify-self-end",
          ].join(" ")}
        >
          {actions}
        </div>
      ) : null}
    </header>
  );
}
