import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import {
  cloneElement,
  isValidElement,
  useEffect,
  useLayoutEffect,
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
  onPointerDown?: (event: PointerEvent<HTMLElement>) => void;
  onFocus?: (event: FocusEvent<HTMLElement>) => void;
  onBlur?: (event: FocusEvent<HTMLElement>) => void;
};

type IdleIntentHandlers = {
  onPointerEnter: () => void;
  onPointerLeave: () => void;
  onPointerDown: (event: PointerEvent<HTMLElement>) => void;
  onFocus: (event: FocusEvent<HTMLElement>) => void;
  onBlur: (event: FocusEvent<HTMLElement>) => void;
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
    onPointerDown: (event: PointerEvent<HTMLElement>) => {
      prev.onPointerDown?.(event);
      handlers.onPointerDown(event);
    },
    onFocus: (event: FocusEvent<HTMLElement>) => {
      prev.onFocus?.(event);
      handlers.onFocus(event);
    },
    onBlur: (event: FocusEvent<HTMLElement>) => {
      prev.onBlur?.(event);
      handlers.onBlur(event);
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
  const pointerReleaseTimerRef = useRef<ReturnType<typeof window.setTimeout> | null>(null);
  const pointerPressedRef = useRef(false);
  const pointerReleaseCleanupRef = useRef<(() => void) | null>(null);
  const armedTriggerRef = useRef<HTMLButtonElement | null>(null);
  const pendingFocusPathRef = useRef<number[] | null>(null);
  const trigger = resolveTrigger(children, renderTrigger);

  useLayoutEffect(() => {
    const path = pendingFocusPathRef.current;
    if (!overlayMounted || path === null) return;
    pendingFocusPathRef.current = null;
    const host = armedTriggerRef.current;
    if (!host) return;
    const active = host.ownerDocument.activeElement;
    if (active && active !== host.ownerDocument.body) return;
    // Arming replaces the idle host. Restore its focused descendant without
    // stealing focus from another control or moving a virtualized viewport.
    let target: Element | undefined = host;
    for (const index of path) target = target?.children[index];
    if (target instanceof HTMLElement) target.focus({ preventScroll: true });
  }, [overlayMounted]);

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
      if (pointerReleaseTimerRef.current !== null) {
        window.clearTimeout(pointerReleaseTimerRef.current);
        pointerReleaseTimerRef.current = null;
      }
      pointerReleaseCleanupRef.current?.();
    };
  }, []);

  if (!overlayMounted) {
    const showNow = () => {
      clearOpenTimer();
      setOverlayMounted(true);
    };
    const armPointer = () => {
      intentRef.current.pointer = true;
      if (pointerPressedRef.current) return;
      if (openTimerRef.current !== null) return;
      const wait = Math.max(0, delay);
      if (wait === 0) {
        showNow();
        return;
      }
      openTimerRef.current = window.setTimeout(() => {
        openTimerRef.current = null;
        if (!pointerPressedRef.current && (intentRef.current.pointer || intentRef.current.focus)) {
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
      onPointerDown: (event) => {
        // Keep the native host through mouseup/click, including label default
        // actions. Arming during pointer focus would swallow the first click.
        clearOpenTimer();
        if (pointerReleaseTimerRef.current !== null) {
          window.clearTimeout(pointerReleaseTimerRef.current);
          pointerReleaseTimerRef.current = null;
        }
        pointerPressedRef.current = true;
        pointerReleaseCleanupRef.current?.();
        const owner = event.currentTarget.ownerDocument;
        const cleanup = () => {
          owner.removeEventListener("pointerup", release);
          owner.removeEventListener("pointercancel", release);
        };
        const release = () => {
          cleanup();
          pointerReleaseCleanupRef.current = null;
          // Defer past click/default label actions even when delay is zero.
          pointerReleaseTimerRef.current = window.setTimeout(() => {
            pointerReleaseTimerRef.current = null;
            pointerPressedRef.current = false;
            if (intentRef.current.pointer || intentRef.current.focus) armPointer();
          }, 0);
        };
        pointerReleaseCleanupRef.current = cleanup;
        owner.addEventListener("pointerup", release);
        owner.addEventListener("pointercancel", release);
      },
      onFocus: (event) => {
        const path: number[] = [];
        let target: Element | null = event.target as Element;
        while (target && target !== event.currentTarget) {
          const parent: HTMLElement | null = target.parentElement;
          if (!parent) return;
          path.unshift(Array.from(parent.children).indexOf(target));
          target = parent;
        }
        pendingFocusPathRef.current = path;
        intentRef.current.focus = true;
        if (!pointerPressedRef.current) showNow();
      },
      onBlur: (event) => {
        if (event.currentTarget.isConnected) pendingFocusPathRef.current = null;
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
        <TooltipPrimitive.Trigger ref={armedTriggerRef} asChild {...triggerSlotProps}>
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
