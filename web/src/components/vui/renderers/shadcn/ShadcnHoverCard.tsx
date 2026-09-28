import * as HoverCardPrimitive from "@radix-ui/react-hover-card";
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

export type ShadcnHoverCardSide = "top" | "right" | "bottom" | "left";
export type ShadcnHoverCardAlign = "start" | "center" | "end";
export type ShadcnHoverCardWidth = "default" | "wide";

export type ShadcnHoverCardProps = {
  children: ReactNode;
  content: ReactNode;
  className?: string;
  side?: ShadcnHoverCardSide;
  align?: ShadcnHoverCardAlign;
  sideOffset?: number;
  openDelay?: number;
  closeDelay?: number;
  width?: ShadcnHoverCardWidth;
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
};

const widthClassName: Record<ShadcnHoverCardWidth, string> = {
  default: "max-w-80",
  wide: "max-w-[min(26rem,calc(100vw-1.5rem))]",
};

const triggerSlotProps = {
  "data-slot": "hover-card-trigger",
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

function resolveTrigger(children: ReactNode): ReactElement {
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
 * Radix/shadcn-style hover card renderer.
 * Pages must not import this — only VUI primitives consume it.
 *
 * Same idle intent-mount discipline as ShadcnTooltip: the hover-card overlay
 * must not mount Radix Root/Trigger/Content per idle trigger. The turn rail
 * renders 100+ triggers, so mounting every overlay up front re-creates the
 * React 19 nested-update (#185) crash documented in ShadcnTooltip. Pointer
 * open waits `openDelay` before the mount; leaving before the wait elapses
 * cancels. Keyboard focus still mounts immediately, matching Radix focus.
 * The first pointer mount uses `defaultOpen` so the outside wait is not
 * followed by a second Radix `openDelay`. Later hovers stay mounted and use
 * the Root's `openDelay`/`closeDelay`.
 *
 * Do not cloneElement the trigger on the armed Radix path: a fresh element
 * identity makes Slot recompose refs, and React 19 then loops through overlay
 * setRef (see ShadcnTooltip). Cloning is only used on the idle host.
 */
export function ShadcnHoverCard({
  children,
  content,
  className,
  side = "bottom",
  align = "center",
  sideOffset = 8,
  openDelay = 120,
  closeDelay = 80,
  width = "default",
  open,
  defaultOpen,
  onOpenChange,
}: ShadcnHoverCardProps) {
  const eager = open !== undefined || Boolean(defaultOpen);
  const [overlayMounted, setOverlayMounted] = useState(eager);
  const intentRef = useRef({ pointer: false, focus: false });
  const openTimerRef = useRef<ReturnType<typeof window.setTimeout> | null>(null);
  const trigger = resolveTrigger(children);

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
      const wait = Math.max(0, openDelay);
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
    <HoverCardPrimitive.Root
      open={open}
      defaultOpen={eager ? defaultOpen : true}
      onOpenChange={onOpenChange}
      openDelay={openDelay}
      closeDelay={closeDelay}
    >
      <HoverCardPrimitive.Trigger asChild {...triggerSlotProps}>
        {trigger}
      </HoverCardPrimitive.Trigger>
      <HoverCardPrimitive.Portal>
        <HoverCardPrimitive.Content
          data-vui="hover-card-content"
          data-renderer="radix"
          side={side}
          sideOffset={sideOffset}
          align={align}
          collisionPadding={8}
          className={[
            "z-[95] select-none whitespace-normal break-words rounded-[var(--radius-panel)] border",
            "border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] p-3 text-vui-fg-primary",
            "[font-size:var(--vui-font-sm)] leading-[1.6] [text-wrap:pretty]",
            "shadow-[var(--vui-elevation-overlay)] outline-none",
            widthClassName[width],
            className,
          ]
            .filter(Boolean)
            .join(" ")}
        >
          {content}
        </HoverCardPrimitive.Content>
      </HoverCardPrimitive.Portal>
    </HoverCardPrimitive.Root>
  );
}
