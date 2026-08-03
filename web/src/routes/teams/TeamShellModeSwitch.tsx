import { VNativeButton } from "../../components/vui";
import type { TeamShellMode } from "./teamShellModel";
import { teamShellModeLabel } from "./teamShellModel";

export type TeamShellModeSwitchProps = {
  lang: "zh" | "en";
  mode: TeamShellMode;
  onChange: (mode: TeamShellMode) => void;
  className?: string;
};

/**
 * Board vs Canvas mode switch — VNativeButton segment control for dense ops.
 */
export function TeamShellModeSwitch({
  lang,
  mode,
  onChange,
  className = "",
}: TeamShellModeSwitchProps) {
  return (
    <div
      className={[
        "teamShellModeSwitch inline-flex items-center gap-0.5 rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-0.5",
        className,
      ].filter(Boolean).join(" ")}
      role="tablist"
      aria-label={lang === "zh" ? "展示模式" : "Presentation mode"}
      data-testid="team-shell-mode-switch"
      data-vui="team-shell-mode-switch"
    >
      {(["board", "canvas"] as const).map((item) => {
        const active = mode === item;
        return (
          <VNativeButton
            key={item}
            type="button"
            role="tab"
            aria-selected={active}
            data-active={active ? "true" : "false"}
            data-testid={`team-shell-mode-${item}`}
            className={[
              "!min-h-8 !rounded-full !px-3.5 !text-[12.5px] !font-[700]",
              active
                ? "!border-transparent !bg-[var(--fg-primary)] !text-[var(--vui-surface-base)]"
                : "!border-transparent !bg-transparent !text-[var(--fg-secondary)] hover:!text-[var(--fg-primary)]",
            ].join(" ")}
            onClick={() => onChange(item)}
          >
            {teamShellModeLabel(item, lang)}
          </VNativeButton>
        );
      })}
    </div>
  );
}
