import {
  Check,
  ChevronDown,
  Shield,
  ShieldCheck,
  ShieldQuestion,
} from "lucide-react";
import {
  useEffect,
  useMemo,
  useState,
  type ComponentType,
} from "react";

import type { AgentPermissionPreset } from "../../../../api/types";
import { VButton, VPopover } from "../../index";
import styles from "./AgentPermissionPresetControl.styles";

export type AgentPermissionPresetControlSurface = "composer" | "settings";

export type AgentPermissionPresetOption = {
  value: AgentPermissionPreset;
  label: string;
  description: string;
  icon: ComponentType<{ className?: string; "aria-hidden"?: boolean }>;
};

export type AgentPermissionPresetControlProps = {
  value: AgentPermissionPreset | null;
  lang: "zh" | "en";
  surface: AgentPermissionPresetControlSurface;
  disabled: boolean;
  pending: boolean;
  agentName?: string;
  /** Launcher manages already-authorized projects; it never grants computer-wide access. */
  context?: "agent" | "launcher";
  side?: "top" | "bottom";
  align?: "start" | "end";
  onChange: (value: AgentPermissionPreset) => void;
};

export function agentPermissionPresetOptions(
  lang: "zh" | "en",
  context: "agent" | "launcher" = "agent",
): AgentPermissionPresetOption[] {
  if (context === "launcher") {
    const options = agentPermissionPresetOptions(lang);
    const descriptions = lang === "zh" ? [
      "创建团队、调整成员、启动任务等管理操作，执行前由你确认。",
      "常规管理自动继续；永久删除、扩大权限等高风险操作仍需确认。",
      "已授权项目内的管理操作直接执行，包括重启和永久删除；不会扩大访问范围。",
    ] : [
      "Ask before management actions such as creating teams, changing members, or starting tasks.",
      "Continue routine management; ask before permanent deletion, permission expansion, or other high-risk actions.",
      "Execute management in authorized projects, including restarts and permanent deletion, without expanding access.",
    ];
    return options.map((option, index) => ({ ...option, description: descriptions[index] }));
  }
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

export function AgentPermissionPresetControl({
  value,
  lang,
  surface,
  disabled,
  pending,
  agentName = "",
  context = "agent",
  side = "bottom",
  align = surface === "settings" ? "start" : "end",
  onChange,
}: AgentPermissionPresetControlProps) {
  const [open, setOpen] = useState(false);
  const options = useMemo(() => agentPermissionPresetOptions(lang, context), [lang, context]);
  const current = options.find((option) => option.value === value) ?? options[0];
  const known = value !== null;
  const CurrentIcon = known ? current.icon : ShieldQuestion;
  const label = known ? current.label : lang === "zh" ? "权限暂不可用" : "Permissions unavailable";
  const menuLabel = context === "launcher"
    ? (lang === "zh" ? "选择助理操作权限" : "Select assistant management permissions")
    : (lang === "zh" ? "选择 Agent 工具权限" : "Select Agent tool permissions");

  useEffect(() => {
    if (disabled || pending || !known) {
      setOpen(false);
    }
  }, [disabled, pending, known]);

  return (
    <div
      className={styles.root}
      data-testid="agent-permission-preset-control"
      data-surface={surface}
    >
      <VPopover
        open={open}
        onOpenChange={(nextOpen) => {
          if (disabled || pending || !known) {
            setOpen(false);
            return;
          }
          setOpen(nextOpen);
        }}
        side={side}
        align={align}
        sideOffset={6}
        aria-label={menuLabel}
        contentClassName={styles.menu}
        data-vui="agent-permission-preset-menu"
        trigger={(
          <VButton
            type="button"
            contentLayout="plain"
            className={`${styles.trigger} ${surface === "settings" ? styles.triggerSettings : ""}`}
            isDisabled={disabled || pending || !known}
            aria-haspopup="listbox"
            aria-expanded={open}
            data-open={open ? "true" : "false"}
            data-preset={known ? current.value : undefined}
            title={known ? `${current.label} · ${current.description}` : label}
          >
            <CurrentIcon className={styles.triggerIcon} aria-hidden />
            <span className={styles.triggerLabel}>
              {pending ? (lang === "zh" ? "保存中…" : "Saving…") : label}
            </span>
            <ChevronDown className={styles.triggerChevron} data-open={open ? "true" : "false"} aria-hidden />
          </VButton>
        )}
      >
        <div
          role="listbox"
          aria-label={menuLabel}
          data-testid="agent-permission-preset-menu"
          onKeyDown={(event) => {
            if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
            const items = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>("[role='option']"));
            if (!items.length) return;
            event.preventDefault();
            const index = items.findIndex(item => item === document.activeElement);
            const next = event.key === "Home" ? 0 : event.key === "End" ? items.length - 1
              : event.key === "ArrowDown" ? (index + 1) % items.length
              : (index < 0 ? items.length - 1 : (index - 1 + items.length) % items.length);
            items[next]?.focus();
          }}
        >
          <div className={styles.menuHeader}>
            <span>{context === "launcher" ? (lang === "zh" ? "助理操作权限" : "Assistant management permissions")
              : (lang === "zh" ? "应如何批准 Agent 操作？" : "How should Agent actions be approved?")}</span>
            {context === "launcher" ? <span>{lang === "zh" ? "仅 Launcher 助理" : "Launcher assistant only"}</span>
              : agentName ? <span title={agentName}>{agentName}</span> : null}
          </div>
          {options.map((option) => {
            const selected = known && option.value === current.value;
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
        </div>
      </VPopover>
    </div>
  );
}
