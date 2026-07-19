import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import {
  cloneElement,
  isValidElement,
  type ReactElement,
  type ReactNode,
} from "react";

export type ShadcnTooltipTriggerRender = (props: Record<string, unknown>) => ReactElement;

export type ShadcnTooltipTone = "neutral" | "warning" | "danger";
export type ShadcnTooltipWidth = "compact" | "default" | "wide";

export type ShadcnTooltipProps = {
  children: ReactNode;
  content: ReactNode;
  className?: string;
  delay?: number;
  closeDelay?: number;
  renderTrigger?: ShadcnTooltipTriggerRender;
  showArrow?: boolean;
  tone?: ShadcnTooltipTone;
  width?: ShadcnTooltipWidth;
  /** Controlled open (HeroUI-era `isOpen` maps here). */
  open?: boolean;
  /** @deprecated Prefer `open`; kept for existing call sites/tests. */
  isOpen?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
};

const toneClassName: Record<ShadcnTooltipTone, string> = {
  neutral:
    "border-[color-mix(in_srgb,var(--vui-border-subtle)_82%,var(--accent-cool)_18%)] text-vui-fg-secondary",
  warning:
    "border-[color-mix(in_srgb,var(--state-warning)_42%,var(--vui-border-subtle))] text-vui-fg-primary",
  danger:
    "border-[color-mix(in_srgb,var(--state-error)_44%,var(--vui-border-subtle))] text-vui-fg-primary",
};

const widthClassName: Record<ShadcnTooltipWidth, string> = {
  compact: "max-w-56",
  default: "max-w-80",
  wide: "max-w-[min(26rem,calc(100vw-1.5rem))]",
};

function withTriggerSlot(node: ReactElement): ReactElement {
  const existing = (node.props as { "data-slot"?: string })["data-slot"];
  return cloneElement(node, {
    "data-slot": existing ?? "tooltip-trigger",
    "data-renderer": "radix",
  } as never);
}

/**
 * Radix/shadcn-style tooltip renderer.
 * Pages must not import this — only VUI primitives consume it.
 */
export function ShadcnTooltip({
  delay = 320,
  closeDelay = 100,
  children,
  content,
  className,
  renderTrigger,
  showArrow = true,
  tone = "neutral",
  width = "default",
  open,
  isOpen,
  defaultOpen,
  onOpenChange,
}: ShadcnTooltipProps) {
  const controlledOpen = open ?? isOpen;
  let trigger: ReactElement;
  if (renderTrigger) {
    trigger = withTriggerSlot(
      renderTrigger({
        "data-slot": "tooltip-trigger",
        "data-renderer": "radix",
      }),
    );
  } else if (isValidElement(children)) {
    trigger = withTriggerSlot(children as ReactElement);
  } else {
    trigger = (
      <span data-slot="tooltip-trigger" data-renderer="radix" tabIndex={0} className="inline-flex max-w-full">
        {children}
      </span>
    );
  }

  return (
    <TooltipPrimitive.Provider delayDuration={delay} skipDelayDuration={closeDelay}>
      <TooltipPrimitive.Root
        open={controlledOpen}
        defaultOpen={defaultOpen}
        onOpenChange={onOpenChange}
      >
        <TooltipPrimitive.Trigger asChild>{trigger}</TooltipPrimitive.Trigger>
        <TooltipPrimitive.Portal>
          <TooltipPrimitive.Content
            data-vui="tooltip-content"
            data-renderer="radix"
            sideOffset={6}
            collisionPadding={8}
            className={[
              "z-[100] select-none whitespace-normal break-words rounded-[10px] border",
              "bg-[color-mix(in_srgb,var(--vui-surface-panel)_96%,transparent)] px-3 py-2",
              "[font-size:var(--vui-font-xs)] font-medium leading-[1.5]",
              "shadow-[var(--vui-elevation-overlay)] backdrop-blur-xl [text-wrap:pretty]",
              widthClassName[width],
              toneClassName[tone],
              className,
            ]
              .filter(Boolean)
              .join(" ")}
          >
            {content}
            {showArrow ? (
              <TooltipPrimitive.Arrow
                className="fill-[color-mix(in_srgb,var(--vui-surface-panel)_96%,transparent)]"
                width={11}
                height={6}
              />
            ) : null}
          </TooltipPrimitive.Content>
        </TooltipPrimitive.Portal>
      </TooltipPrimitive.Root>
    </TooltipPrimitive.Provider>
  );
}
