import { VTabs } from "../../components/vui";
import type { TeamShellMode } from "./teamShellModel";
import { teamShellModeLabel } from "./teamShellModel";

export type TeamShellModeSwitchProps = {
  lang: "zh" | "en";
  mode: TeamShellMode;
  onChange: (mode: TeamShellMode) => void;
  className?: string;
};

/**
 * Board vs Canvas mode switch — VTabs segment control for dense ops.
 */
export function TeamShellModeSwitch({
  lang,
  mode,
  onChange,
  className = "",
}: TeamShellModeSwitchProps) {
  return (
    <div
      className={["teamShellModeSwitch inline-grid w-fit max-w-full min-w-0", className].filter(Boolean).join(" ")}
      data-testid="team-shell-mode-switch"
      data-vui="team-shell-mode-switch"
    >
      <VTabs
        density="compact"
        className="inline-grid w-fit max-w-full min-w-0 gap-0"
        listClassName="inline-flex items-center gap-0.5 rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-0.5"
        triggerClassName={
          "!min-h-8 !rounded-full !px-3.5 !text-[12.5px] !font-[700] border-transparent bg-transparent text-[var(--fg-secondary)] " +
          "data-[state=active]:!border-[var(--vui-border-subtle)] data-[state=active]:!bg-[var(--vui-surface-base)] " +
          "data-[state=active]:!text-[var(--fg-primary)] data-[state=active]:!shadow-[var(--vui-shadow-hairline,0_1px_2px_rgba(0,0,0,0.06))] " +
          "hover:!bg-[var(--vui-control-muted)] hover:!text-[var(--fg-primary)]"
        }
        aria-label={lang === "zh" ? "展示模式" : "Presentation mode"}
        value={mode}
        onValueChange={(value) => {
          if (value === "board" || value === "canvas") {
            onChange(value);
          }
        }}
        items={[
          {
            id: "board",
            label: (
              <span data-testid="team-shell-mode-board">{teamShellModeLabel("board", lang)}</span>
            ),
          },
          {
            id: "canvas",
            label: (
              <span data-testid="team-shell-mode-canvas">{teamShellModeLabel("canvas", lang)}</span>
            ),
          },
        ]}
      />
    </div>
  );
}
