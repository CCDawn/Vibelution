import {
  Check,
  ChevronDown,
  Shield,
  ShieldCheck,
  ShieldQuestion,
} from "lucide-react";
import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ComponentType,
} from "react";
import { createPortal } from "react-dom";

import type { AgentPermissionPreset } from "../../../../api/types";
import { VButton } from "../../index";
import styles from "./AgentPermissionPresetControl.styles";

export type AgentPermissionPresetControlSurface = "composer" | "settings";

export type AgentPermissionPresetOption = {
  value: AgentPermissionPreset;
  label: string;
  description: string;
  icon: ComponentType<{ className?: string; "aria-hidden"?: boolean }>;
};

export type AgentPermissionPresetControlProps = {
  value: AgentPermissionPreset;
  lang: "zh" | "en";
  surface: AgentPermissionPresetControlSurface;
  disabled: boolean;
  pending: boolean;
  agentName?: string;
  onChange: (value: AgentPermissionPreset) => void;
};

const MENU_GAP = 6;
const VIEWPORT_PAD = 8;
const MENU_WIDTH = 360;

export function agentPermissionPresetOptions(
  lang: "zh" | "en",
): AgentPermissionPresetOption[] {
  if (lang === "zh") {
    return [
      {
        value: "request_approval",
        label: "请求批准",
        description: "编辑工作区之外的文件、访问互联网或执行高风险操作时询问。",
        icon: ShieldQuestion,
      },
      {
        value: "auto_review",
        label: "替我审批",
        description: "工作区内的低风险操作自动继续，仅对网络、破坏性和强制审批操作询问。",
        icon: ShieldCheck,
      },
      {
        value: "full_access",
        label: "完全访问权限",
        description: "不弹窗，可访问互联网并直接操作此电脑上的文件；请仅用于可信任务。",
        icon: Shield,
      },
    ];
  }
  return [
    {
      value: "request_approval",
      label: "Request approval",
      description: "Ask before external file edits, internet access, or high-risk actions.",
      icon: ShieldQuestion,
    },
    {
      value: "auto_review",
      label: "Auto review",
      description: "Continue low-risk workspace actions and ask for network or destructive actions.",
      icon: ShieldCheck,
    },
    {
      value: "full_access",
      label: "Full access",
      description: "Do not prompt; allow internet and direct file access on this computer for trusted tasks.",
      icon: Shield,
    },
  ];
}

function placePermissionMenu(
  trigger: DOMRect,
  viewport = {
    width: typeof window === "undefined" ? 1280 : window.innerWidth,
    height: typeof window === "undefined" ? 720 : window.innerHeight,
  },
): CSSProperties {
  const width = Math.min(MENU_WIDTH, viewport.width - VIEWPORT_PAD * 2);
  const left = Math.min(
    Math.max(VIEWPORT_PAD, trigger.left),
    Math.max(VIEWPORT_PAD, viewport.width - width - VIEWPORT_PAD),
  );
  const estimatedHeight = 210;
  const placeAbove = trigger.top >= estimatedHeight + MENU_GAP + VIEWPORT_PAD;
  return placeAbove
    ? {
        position: "fixed",
        left,
        bottom: viewport.height - trigger.top + MENU_GAP,
        width,
        maxHeight: Math.max(120, trigger.top - MENU_GAP - VIEWPORT_PAD),
        zIndex: 90,
      }
    : {
        position: "fixed",
        left,
        top: trigger.bottom + MENU_GAP,
        width,
        maxHeight: Math.max(120, viewport.height - trigger.bottom - MENU_GAP - VIEWPORT_PAD),
        zIndex: 90,
      };
}

export function AgentPermissionPresetControl({
  value,
  lang,
  surface,
  disabled,
  pending,
  agentName = "",
  onChange,
}: AgentPermissionPresetControlProps) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const [open, setOpen] = useState(false);
  const [menuStyle, setMenuStyle] = useState<CSSProperties>({});
  const options = useMemo(() => agentPermissionPresetOptions(lang), [lang]);
  const current = options.find((option) => option.value === value) ?? options[0];
  const CurrentIcon = current.icon;

  useEffect(() => {
    if (disabled || pending) {
      setOpen(false);
    }
  }, [disabled, pending]);

  useLayoutEffect(() => {
    if (!open || !triggerRef.current) return;
    const place = () => {
      const rect = triggerRef.current?.getBoundingClientRect();
      if (rect) setMenuStyle(placePermissionMenu(rect));
    };
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const closeOnPointer = (event: PointerEvent) => {
      const target = event.target;
      if (!(target instanceof Node)) return;
      if (rootRef.current?.contains(target) || menuRef.current?.contains(target)) return;
      setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setOpen(false);
      requestAnimationFrame(() => triggerRef.current?.focus());
    };
    window.addEventListener("pointerdown", closeOnPointer);
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      window.removeEventListener("pointerdown", closeOnPointer);
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  const menu = open
    ? createPortal(
        <div
          ref={menuRef}
          role="listbox"
          aria-label={lang === "zh" ? "选择 Agent 工具权限" : "Select Agent tool permissions"}
          className={styles.menu}
          style={menuStyle}
          data-testid="agent-permission-preset-menu"
        >
          <div className={styles.menuHeader}>
            <span>{lang === "zh" ? "应如何批准 Agent 操作？" : "How should Agent actions be approved?"}</span>
            {agentName ? <span title={agentName}>{agentName}</span> : null}
          </div>
          {options.map((option) => {
            const selected = option.value === current.value;
            const OptionIcon = option.icon;
            return (
              <VButton
                key={option.value}
                type="button"
                contentLayout="plain"
                className={styles.option}
                role="option"
                aria-selected={selected}
                data-selected={selected ? "true" : "false"}
                data-preset={option.value}
                onPress={() => {
                  setOpen(false);
                  if (!selected) onChange(option.value);
                  requestAnimationFrame(() => triggerRef.current?.focus());
                }}
              >
                <OptionIcon className={styles.optionIcon} aria-hidden />
                <span className={styles.optionCopy}>
                  <span className={styles.optionLabel}>{option.label}</span>
                  <small className={styles.optionDescription}>{option.description}</small>
                </span>
                {selected
                  ? <Check className={styles.check} aria-hidden />
                  : <span className={styles.checkSlot} aria-hidden />}
              </VButton>
            );
          })}
        </div>,
        document.body,
      )
    : null;

  return (
    <div
      ref={rootRef}
      className={styles.root}
      data-testid="agent-permission-preset-control"
      data-surface={surface}
    >
      <VButton
        ref={triggerRef}
        type="button"
        contentLayout="plain"
        className={`${styles.trigger} ${surface === "settings" ? styles.triggerSettings : ""}`}
        isDisabled={disabled || pending}
        aria-haspopup="listbox"
        aria-expanded={open}
        data-open={open ? "true" : "false"}
        data-preset={current.value}
        title={`${current.label} · ${current.description}`}
        onPress={() => setOpen((currentOpen) => !currentOpen)}
      >
        <CurrentIcon className={styles.triggerIcon} aria-hidden />
        <span className={styles.triggerLabel}>{pending ? (lang === "zh" ? "保存中…" : "Saving…") : current.label}</span>
        <ChevronDown className={styles.triggerChevron} data-open={open ? "true" : "false"} aria-hidden />
      </VButton>
      {menu}
    </div>
  );
}
