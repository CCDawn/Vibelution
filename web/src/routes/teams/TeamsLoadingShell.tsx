import { LoaderCircle } from "lucide-react";
import { useEffect, useState } from "react";

import { VBoardWorkbenchPage, VSkeleton } from "../../components/vui";
import {
  TEAMS_BOARD_INSPECTOR_PANE,
  TEAMS_LAYOUT_ID,
  TEAMS_RAIL_PANE,
  teamsWorkbenchStyles as styles,
} from "./teamsWorkbenchChrome";

type TeamsLoadingShellProps = {
  lang: "zh" | "en";
};

const TEAMS_LOADING_RESIZE = {
  sidebar: { ...TEAMS_RAIL_PANE },
  aside: { ...TEAMS_BOARD_INSPECTOR_PANE },
};

function useNarrowLoadingShell(): boolean {
  const [narrow, setNarrow] = useState(() =>
    typeof window === "undefined"
      ? false
      : !window.matchMedia("(min-width: 900px)").matches,
  );

  useEffect(() => {
    const media = window.matchMedia("(min-width: 900px)");
    const sync = () => setNarrow(!media.matches);
    sync();
    media.addEventListener("change", sync);
    return () => media.removeEventListener("change", sync);
  }, []);

  return narrow;
}

function LoadingRail({ lang }: { lang: "zh" | "en" }) {
  return (
    <div
      className="flex h-full min-h-0 min-w-0 flex-col gap-3 overflow-hidden p-2.5"
      aria-hidden="true"
      data-vui-region="teams-sidebar"
    >
      <div className="flex min-h-6 items-center justify-between gap-3">
        <strong className="text-[13px] font-[760]">{lang === "zh" ? "团队" : "Teams"}</strong>
        <VSkeleton shape="circle" className="!size-4" />
      </div>
      <VSkeleton shape="block" className="!min-h-8 rounded-[var(--radius-control)]" />
      <div className="grid min-h-0 flex-1 content-start gap-1.5 overflow-hidden">
        {Array.from({ length: 5 }, (_, index) => (
          <div
            key={index}
            className="grid min-h-[4.5rem] gap-2 rounded-lg border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] px-2.5 py-2"
          >
            <div className="flex items-center justify-between gap-3">
              <VSkeleton className={index % 2 ? "!w-[58%]" : "!w-[68%]"} />
              <VSkeleton className="!w-10" />
            </div>
            <VSkeleton className="!w-[72%] opacity-80" />
            <VSkeleton className="!w-[90%] opacity-70" />
          </div>
        ))}
      </div>
      <div className="grid gap-1.5">
        <VSkeleton className="!w-full opacity-70" />
        <VSkeleton className="!w-[76%] opacity-60" />
      </div>
    </div>
  );
}

function LoadingToolbar({ label }: { label: string }) {
  return (
    <div className="flex w-full min-w-0 items-center justify-between gap-3">
      <div className="grid min-w-0 flex-1 gap-1.5" aria-hidden="true">
        <VSkeleton className="!w-40" />
        <VSkeleton className="!w-[min(22rem,68%)] opacity-75" />
      </div>
      <span className="flex shrink-0 items-center gap-2 text-[11px] text-[var(--fg-secondary)]">
        <LoaderCircle className="size-3.5 animate-spin motion-reduce:animate-none" aria-hidden="true" />
        {label}
      </span>
    </div>
  );
}

function LoadingCanvas({ narrow }: { narrow: boolean }) {
  return (
    <div className={`${styles.canvas} !h-full !min-h-0 !overflow-hidden !p-4`} aria-hidden="true">
      <div className="grid h-full min-h-0 place-items-center overflow-hidden">
        <div className={`grid w-full max-w-4xl gap-6 ${narrow ? "grid-cols-2" : "grid-cols-3"}`}>
          {Array.from({ length: 6 }, (_, index) => (
            <div
              key={index}
              className="grid min-h-20 min-w-0 content-center gap-2.5 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] p-3.5 shadow-[var(--vui-shadow-hairline)]"
            >
              <VSkeleton className={index % 2 ? "!w-[46%]" : "!w-[58%]"} />
              <VSkeleton className="!w-full opacity-80" />
              <VSkeleton className="!w-[72%] opacity-65" />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function LoadingInspector({ lang }: { lang: "zh" | "en" }) {
  return (
    <div className="grid h-full min-h-0 content-start gap-3 overflow-hidden p-3" aria-hidden="true">
      <div className="flex min-h-6 items-center justify-between gap-3">
        <strong className="whitespace-nowrap text-[13px] font-[760]">{lang === "zh" ? "检查器" : "Inspector"}</strong>
        <VSkeleton className="!w-14" />
      </div>
      {Array.from({ length: 2 }, (_, index) => (
        <div
          key={index}
          className="grid gap-2.5 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-3"
        >
          <VSkeleton className={index ? "!w-[38%]" : "!w-[48%]"} />
          <VSkeleton className="!w-full opacity-80" />
          <VSkeleton className="!w-[88%] opacity-70" />
          <VSkeleton className="!w-[68%] opacity-60" />
        </div>
      ))}
    </div>
  );
}

export function TeamsLoadingShell({ lang }: TeamsLoadingShellProps) {
  const narrow = useNarrowLoadingShell();
  const label = lang === "zh" ? "正在载入团队数据…" : "Loading team data…";

  return (
    <VBoardWorkbenchPage
      className={styles.route}
      hideHeader
      domainRecipe="teams-organization-workbench"
      layoutId={TEAMS_LAYOUT_ID}
      resize={TEAMS_LOADING_RESIZE}
      shellTestId="team-shell-workspace"
      shellMode="loading"
      ariaLabel={label}
      title={lang === "zh" ? "团队工作台" : "Team workbench"}
      rail={<LoadingRail lang={lang} />}
      toolbar={<LoadingToolbar label={label} />}
      boardClassName="!h-full !min-h-0 !overflow-hidden !p-0"
      board={<LoadingCanvas narrow={narrow} />}
      aside={narrow ? undefined : <LoadingInspector lang={lang} />}
      role="status"
      aria-live="polite"
      aria-busy="true"
      data-testid="teams-loading-shell"
    />
  );
}
