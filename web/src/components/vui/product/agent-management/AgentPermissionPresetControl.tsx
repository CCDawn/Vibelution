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
  value: AgentPermissionPreset;
  lang: "zh" | "en";
  surface: AgentPermissionPresetControlSurface;
  disabled: boolean;
  pending: boolean;
  agentName?: string;
  onChange: (value: AgentPermissionPreset) => void;
};

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

export function AgentPermissionPresetControl({
  value,
  lang,
  surface,
  disabled,
  pending,
  agentName = "",
  onChange,
}: AgentPermissionPresetControlProps) {
  const [open, setOpen] = useState(false);
  const options = useMemo(() => agentPermissionPresetOptions(lang), [lang]);
  const current = options.find((option) => option.value === value) ?? options[0];
  const CurrentIcon = current.icon;

  useEffect(() => {
    if (disabled || pending) {
      setOpen(false);
    }
  }, [disabled, pending]);

  return (
    <div
      className={styles.root}
      data-testid="agent-permission-preset-control"
      data-surface={surface}
    >
      <VPopover
        open={open}
        onOpenChange={(nextOpen) => {
          if (disabled || pending) {
            setOpen(false);
            return;
          }
          setOpen(nextOpen);
        }}
        side="bottom"
        align={surface === "settings" ? "start" : "end"}
        sideOffset={6}
        aria-label={lang === "zh" ? "选择 Agent 工具权限" : "Select Agent tool permissions"}
        contentClassName={styles.menu}
        data-vui="agent-permission-preset-menu"
        trigger={(
          <VButton
            type="button"
            contentLayout="plain"
            className={`${styles.trigger} ${surface === "settings" ? styles.triggerSettings : ""}`}
            isDisabled={disabled || pending}
            aria-haspopup="listbox"
            aria-expanded={open}
            data-open={open ? "true" : "false"}
            data-preset={current.value}
            title={`${current.label} · ${current.description}`}
          >
            <CurrentIcon className={styles.triggerIcon} aria-hidden />
            <span className={styles.triggerLabel}>
              {pending ? (lang === "zh" ? "保存中…" : "Saving…") : current.label}
            </span>
            <ChevronDown className={styles.triggerChevron} data-open={open ? "true" : "false"} aria-hidden />
          </VButton>
        )}
      >
        <div
          role="listbox"
          aria-label={lang === "zh" ? "选择 Agent 工具权限" : "Select Agent tool permissions"}
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
