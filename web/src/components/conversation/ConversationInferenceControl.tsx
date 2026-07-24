import { Check, ChevronDown } from "lucide-react";
import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import { createPortal } from "react-dom";

import type { SessionLlmModelOption } from "../../api/types";
import { VButton } from "../vui";
import styles from "./ConversationInferenceControl.styles";

type ConversationInferenceControlProps = {
  model: SessionLlmModelOption | null;
  currentReasoningEffort: string;
  disabled: boolean;
  pending: boolean;
  onReasoningEffortChange: (reasoningEffort: string) => void;
};

const MENU_WIDTH = 220;
const MENU_GAP = 8;
const VIEWPORT_PAD = 8;

export function resolveConversationInferenceEffort(
  model: SessionLlmModelOption | null,
  reasoningEffort: string,
) {
  const values = model?.reasoningEffortValues ?? [];
  const effort = values.includes(reasoningEffort)
    ? reasoningEffort
    : values.includes(model?.defaultReasoningEffort ?? "")
      ? model?.defaultReasoningEffort ?? ""
      : values[0] ?? "";
  return {
    effort,
    option: model?.reasoningEffortOptions?.find((item) => item.value === effort),
  };
}

/** Place the menu in viewport space so overflow:hidden composer shells cannot clip it. */
export function placeInferenceMenu(
  triggerRect: { top: number; bottom: number; right: number },
  viewport: { width: number; height: number } = {
    width: typeof window !== "undefined" ? window.innerWidth : 1280,
    height: typeof window !== "undefined" ? window.innerHeight : 720,
  },
): CSSProperties {
  const width = Math.min(MENU_WIDTH, Math.max(160, viewport.width - VIEWPORT_PAD * 2));
  const right = Math.max(VIEWPORT_PAD, viewport.width - triggerRect.right);
  const spaceAbove = triggerRect.top - VIEWPORT_PAD - MENU_GAP;
  const spaceBelow = viewport.height - triggerRect.bottom - VIEWPORT_PAD - MENU_GAP;
  const preferAbove = spaceAbove >= 120 || spaceAbove >= spaceBelow;
  const maxHeight = Math.max(96, Math.min(280, preferAbove ? spaceAbove : spaceBelow));

  if (preferAbove) {
    return {
      position: "fixed",
      right,
      bottom: viewport.height - triggerRect.top + MENU_GAP,
      width,
      maxHeight,
      zIndex: 80,
    };
  }
  return {
    position: "fixed",
    right,
    top: triggerRect.bottom + MENU_GAP,
    width,
    maxHeight,
    zIndex: 80,
  };
}

export function ConversationInferenceControl({
  model,
  currentReasoningEffort,
  disabled,
  pending,
  onReasoningEffortChange,
}: ConversationInferenceControlProps) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const [open, setOpen] = useState(false);
  const [menuStyle, setMenuStyle] = useState<CSSProperties>({});
  const current = useMemo(
    () => resolveConversationInferenceEffort(model, currentReasoningEffort),
    [currentReasoningEffort, model],
  );

  useLayoutEffect(() => {
    if (!open || !triggerRef.current) return;
    function place() {
      const rect = triggerRef.current?.getBoundingClientRect();
      if (!rect) return;
      setMenuStyle(placeInferenceMenu(rect));
    }
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [open, model?.reasoningEffortOptions?.length]);

  useEffect(() => {
    if (!open) return;
    function closeOnOutsidePointer(event: PointerEvent) {
      const target = event.target;
      if (!(target instanceof Node)) return;
      if (rootRef.current?.contains(target) || menuRef.current?.contains(target)) {
        return;
      }
      setOpen(false);
    }
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false);
        requestAnimationFrame(() => triggerRef.current?.focus());
      }
    }
    window.addEventListener("pointerdown", closeOnOutsidePointer);
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      window.removeEventListener("pointerdown", closeOnOutsidePointer);
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  if (!model) return null;
  if (!model.reasoningEffortValues?.length) {
    return <span className={styles.fixedLabel}>{model.label || model.model}</span>;
  }

  const menu = open
    ? createPortal(
      <div
        ref={menuRef}
        role="listbox"
        className={styles.menu}
        style={menuStyle}
        aria-label="选择推理强度"
        data-testid="conversation-inference-menu"
      >
        {model.reasoningEffortOptions.map((option) => (
          <VButton
            key={option.value}
            type="button"
            contentLayout="plain"
            className={styles.option}
            role="option"
            aria-selected={option.value === current.effort}
            onPress={() => {
              onReasoningEffortChange(option.value);
              setOpen(false);
              requestAnimationFrame(() => triggerRef.current?.focus());
            }}
          >
            <span className={styles.optionCopy}>
              <span className={styles.optionLabel}>{option.label || option.value}</span>
              {option.description ? (
                <small className={styles.optionDescription}>{option.description}</small>
              ) : null}
            </span>
            {option.value === current.effort
              ? <Check className={styles.check} size={14} aria-hidden="true" />
              : <span className={styles.checkSlot} aria-hidden="true" />}
          </VButton>
        ))}
      </div>,
      document.body,
    )
    : null;

  return (
    <div ref={rootRef} className={styles.root} data-testid="conversation-inference-control">
      <VButton
        ref={triggerRef}
        type="button"
        contentLayout="plain"
        className={styles.trigger}
        isDisabled={disabled || pending}
        aria-haspopup="listbox"
        aria-expanded={open}
        title={`${model.label || model.model} · ${current.option?.label || current.effort}`}
        onPress={() => setOpen((value) => !value)}
      >
        <span className={styles.triggerModel}>{model.label || model.model}</span>
        <span className={styles.triggerSeparator} aria-hidden="true">·</span>
        <span className={styles.triggerEffort}>{current.option?.label || current.effort}</span>
        <ChevronDown className={styles.triggerChevron} size={13} aria-hidden="true" />
      </VButton>
      {menu}
    </div>
  );
}
