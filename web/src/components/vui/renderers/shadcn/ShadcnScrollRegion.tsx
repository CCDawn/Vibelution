import {
  forwardRef,
  useCallback,
  useEffect,
  useRef,
  useState,
  type ComponentPropsWithoutRef,
  type KeyboardEvent,
  type PointerEvent,
} from "react";

import { cn } from "../../lib/cn";
import styles from "./ShadcnScrollRegion.styles";

type Props = ComponentPropsWithoutRef<"div"> & { "data-vui"?: string };

const scrollKeys = new Set(["ArrowUp", "ArrowDown", "PageUp", "PageDown", "Home", "End", " ", "Spacebar"]);

function hasVerticalOverflow(element: HTMLDivElement) {
  return element.clientHeight > 0 && element.scrollHeight > element.clientHeight;
}

function isScrollKey(event: KeyboardEvent<HTMLDivElement>) {
  if (!scrollKeys.has(event.key) || event.altKey || event.ctrlKey || event.metaKey) return false;
  const target = event.target;
  if (!(target instanceof HTMLElement)) return true;
  if (
    target.isContentEditable
    || target.closest("input, textarea, select, [contenteditable]:not([contenteditable='false']), [role='textbox'], [role='combobox'], [role='spinbutton']")
  ) return false;
  // Space activates buttons; on links it retains its native scrolling behavior.
  return !((event.key === " " || event.key === "Spacebar") && target.closest("button, [role='button']"));
}

function isNativeScrollbarPointer(event: PointerEvent<HTMLDivElement>) {
  const element = event.currentTarget;
  if (event.button !== 0 || event.isPrimary === false || event.pointerType !== "mouse"
    || event.target !== element || !hasVerticalOverflow(element)) return false;

  const computed = getComputedStyle(element);
  const borderLeft = parseFloat(computed.borderLeftWidth) || 0;
  const borderRight = parseFloat(computed.borderRightWidth) || 0;
  const gutterWidth = element.offsetWidth - element.clientWidth - borderLeft - borderRight;
  if (gutterWidth <= 0 || element.offsetWidth <= 0) return false;

  const rect = element.getBoundingClientRect();
  const scale = rect.width / element.offsetWidth;
  // clientLeft is rounded to CSS pixels; a fractional border alone is not an RTL gutter.
  const leftGutter = element.clientLeft - borderLeft > gutterWidth / 2;
  const gutterStart = rect.left + (leftGutter ? borderLeft : element.clientLeft + element.clientWidth) * scale;
  const gutterEnd = gutterStart + gutterWidth * scale;
  return event.clientX >= gutterStart && event.clientX < gutterEnd
    && event.clientY >= rect.top && event.clientY < rect.bottom;
}

/** A single native div: scrollTop, focus semantics and virtualizer refs stay native. */
export const ShadcnScrollRegion = forwardRef<HTMLDivElement, Props>(function ShadcnScrollRegion(
  { className, onWheel, onTouchMove, onKeyDown, onPointerDown, ...props },
  ref,
) {
  const [active, setActive] = useState(false);
  const [dragging, setDragging] = useState(false);
  const hideTimer = useRef<number | undefined>(undefined);
  const draggingRef = useRef(false);
  const dragPointerId = useRef<number | undefined>(undefined);

  const hideAfterIdle = useCallback(() => {
    window.clearTimeout(hideTimer.current);
    hideTimer.current = window.setTimeout(() => {
      hideTimer.current = undefined;
      setActive(false);
    }, 800);
  }, []);

  const showForUserScroll = (element: HTMLDivElement) => {
    if (!hasVerticalOverflow(element)) return;
    setActive(true);
    if (!draggingRef.current) hideAfterIdle();
  };

  useEffect(() => () => window.clearTimeout(hideTimer.current), []);

  useEffect(() => {
    if (!dragging) return;
    const finishDrag = (event: Event) => {
      if ("pointerId" in event && event.pointerId !== dragPointerId.current) return;
      draggingRef.current = false;
      setDragging(false);
      hideAfterIdle();
    };
    window.addEventListener("pointerup", finishDrag);
    window.addEventListener("pointercancel", finishDrag);
    window.addEventListener("blur", finishDrag);
    return () => {
      window.removeEventListener("pointerup", finishDrag);
      window.removeEventListener("pointercancel", finishDrag);
      window.removeEventListener("blur", finishDrag);
    };
  }, [dragging, hideAfterIdle]);

  return (
    <div
      {...props}
      ref={ref}
      className={cn(styles.root, className)}
      data-scroll-active={active ? "true" : "false"}
      data-scroll-dragging={dragging ? "true" : "false"}
      onWheel={(event) => {
        onWheel?.(event);
        if (!event.defaultPrevented) showForUserScroll(event.currentTarget);
      }}
      onTouchMove={(event) => {
        onTouchMove?.(event);
        if (!event.defaultPrevented) showForUserScroll(event.currentTarget);
      }}
      onKeyDown={(event) => {
        onKeyDown?.(event);
        if (!event.defaultPrevented && isScrollKey(event)) showForUserScroll(event.currentTarget);
      }}
      onPointerDown={(event) => {
        onPointerDown?.(event);
        if (event.defaultPrevented || !isNativeScrollbarPointer(event)) return;
        window.clearTimeout(hideTimer.current);
        dragPointerId.current = event.pointerId;
        draggingRef.current = true;
        setActive(true);
        setDragging(true);
      }}
    />
  );
});
