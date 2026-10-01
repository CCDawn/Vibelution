import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import {
  cloneElement,
  isValidElement,
  useEffect,
  useRef,
  useState,
  type FocusEvent,
  type PointerEvent,
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

const triggerSlotProps = {
  "data-slot": "tooltip-trigger",
  "data-renderer": "radix",
} as const;

type IntentTriggerProps = {
  onPointerEnter?: (event: PointerEvent<HTMLElement>) => void;
  onPointerLeave?: (event: PointerEvent<HTMLElement>) => void;
  onFocus?: (event: FocusEvent<HTMLElement>) => void;
  onBlur?: (event: FocusEvent<HTMLElement>) => void;
};

type IdleIntentHandlers = {
  onPointerEnter: () => void;
  onPointerLeave: () => void;
  onFocus: () => void;
  onBlur: () => void;
};

function resolveTrigger(
  children: ReactNode,
  renderTrigger: ShadcnTooltipTriggerRender | undefined,
): ReactElement {
  if (renderTrigger) {
    return renderTrigger({ ...triggerSlotProps });
  }
  if (isValidElement(children)) {
    return children as ReactElement;
  }
  return (
    <span {...triggerSlotProps} tabIndex={0} className="inline-flex max-w-full">
      {children}
    </span>
  );
}

function withIdleIntent(trigger: ReactElement, handlers: IdleIntentHandlers): ReactElement {
  const prev = trigger.props as IntentTriggerProps;
  return cloneElement(trigger, {
    ...triggerSlotProps,
    onPointerEnter: (event: PointerEvent<HTMLElement>) => {
      prev.onPointerEnter?.(event);
      handlers.onPointerEnter();
    },
    onPointerLeave: (event: PointerEvent<HTMLElement>) => {
      prev.onPointerLeave?.(event);
      handlers.onPointerLeave();
    },
    onFocus: (event: FocusEvent<HTMLElement>) => {
      prev.onFocus?.(event);
      handlers.onFocus();
    },
    onBlur: (event: FocusEvent<HTMLElement>) => {
      prev.onBlur?.(event);
      handlers.onBlur();
    },
  } as Partial<typeof trigger.props>);
}

/**
 * Radix/shadcn-style tooltip renderer.
 * Pages must not import this — only VUI primitives consume it.
 *
 * Idle tooltips must not mount Radix Root/Trigger/Popper. Each instance
 * calls `setTrigger` / `setAnchor` from composed refs during commit;
 * a chat session list of ~25 rows (2 tips each) already reaches React 19's
 * nested-update limit of 50 and crashes the workbench as #185.
 *
 * Pointer open waits `delay` before that mount. Radix `delayDuration` cannot
 * run until the overlay exists. Leaving before the wait elapses cancels.
 * Keyboard focus still mounts immediately, matching Radix focus.
 * The first pointer mount uses `defaultOpen` so the outside wait is not
 * followed by a second `delayDuration`. Later hovers stay mounted and use it.
 *
 * Do not cloneElement the trigger on the armed Radix path: a fresh element
 * identity makes Slot recompose refs, and React 19 then loops through overlay
 * setRef. Cloning is only used on the idle host, which has no Slot.
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
  const eager = controlledOpen !== undefined || Boolean(defaultOpen);
  const [overlayMounted, setOverlayMounted] = useState(eager);
  const intentRef = useRef({ pointer: false, focus: false });
  const openTimerRef = useRef<ReturnType<typeof window.setTimeout> | null>(null);
  const trigger = resolveTrigger(children, renderTrigger);

  const clearOpenTimer = () => {
    if (openTimerRef.current !== null) {
      window.clearTimeout(openTimerRef.current);
      openTimerRef.current = null;
    }
  };

  useEffect(() => {
    return () => {
      if (openTimerRef.current !== null) {
        window.clearTimeout(openTimerRef.current);
        openTimerRef.current = null;
      }
    };
  }, []);

  if (!overlayMounted) {
    const showNow = () => {
      clearOpenTimer();
      setOverlayMounted(true);
    };
    const armPointer = () => {
      intentRef.current.pointer = true;
      if (openTimerRef.current !== null) return;
      const wait = Math.max(0, delay);
      if (wait === 0) {
        showNow();
        return;
      }
      openTimerRef.current = window.setTimeout(() => {
        openTimerRef.current = null;
        if (intentRef.current.pointer || intentRef.current.focus) {
          setOverlayMounted(true);
        }
      }, wait);
    };
    return withIdleIntent(trigger, {
      onPointerEnter: armPointer,
      onPointerLeave: () => {
        intentRef.current.pointer = false;
        if (!intentRef.current.focus) clearOpenTimer();
      },
      onFocus: () => {
        intentRef.current.focus = true;
        showNow();
      },
      onBlur: () => {
        intentRef.current.focus = false;
        if (!intentRef.current.pointer) clearOpenTimer();
      },
    });
  }

  return (
    <TooltipPrimitive.Provider delayDuration={delay} skipDelayDuration={closeDelay}>
      <TooltipPrimitive.Root
        delayDuration={delay}
        open={controlledOpen}
        defaultOpen={eager ? defaultOpen : true}
        onOpenChange={onOpenChange}
      >
        <TooltipPrimitive.Trigger asChild {...triggerSlotProps}>
          {trigger}
        </TooltipPrimitive.Trigger>
        <TooltipPrimitive.Portal>
          <TooltipPrimitive.Content
            data-vui="tooltip-content"
            data-renderer="radix"
            sideOffset={6}
            collisionPadding={8}
            className={[
              "z-[100] select-none whitespace-normal break-words rounded-[var(--vui-radius-soft)] border",
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
