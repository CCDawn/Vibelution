import { LoaderCircle } from "lucide-react";
import { useEffect, useState } from "react";

import { VBoardWorkbenchPage, VSkeleton } from "../../components/vui";
import styles from "./TeamsLoadingShell.styles";
import {
  TEAMS_BOARD_INSPECTOR_PANE,
  TEAMS_LAYOUT_ID,
  TEAMS_RAIL_PANE,
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
      className={styles.rail}
      aria-hidden="true"
      data-vui-region="teams-sidebar"
    >
      <div className={styles.railHeader}>
        <strong className={styles.railTitle}>{lang === "zh" ? "团队" : "Teams"}</strong>
        <VSkeleton shape="circle" className={styles.railHeaderSkeleton} />
      </div>
      <VSkeleton shape="block" className={styles.railControlSkeleton} />
      <div className={styles.railList}>
        {Array.from({ length: 5 }, (_, index) => (
          <div
            key={index}
            className={styles.railItem}
          >
            <div className={styles.railItemHeader}>
              <VSkeleton className={index % 2 ? styles.railItemTitleAlternate : styles.railItemTitle} />
              <VSkeleton className={styles.railItemMetric} />
            </div>
            <VSkeleton className={styles.railItemPrimaryLine} />
            <VSkeleton className={styles.railItemSecondaryLine} />
          </div>
        ))}
      </div>
      <div className={styles.railFooter}>
        <VSkeleton className={styles.railFooterPrimaryLine} />
        <VSkeleton className={styles.railFooterSecondaryLine} />
      </div>
    </div>
  );
}

function LoadingToolbar({ label }: { label: string }) {
  return (
    <div className={styles.toolbar}>
      <div className={styles.toolbarSkeletons} aria-hidden="true">
        <VSkeleton className={styles.toolbarTitle} />
        <VSkeleton className={styles.toolbarSubtitle} />
      </div>
      <span className={styles.toolbarStatus}>
        <LoaderCircle className={styles.toolbarSpinner} aria-hidden="true" />
        {label}
      </span>
    </div>
  );
}

function LoadingCanvas({ narrow }: { narrow: boolean }) {
  return (
    <div className={styles.canvas} aria-hidden="true">
      <div className={styles.canvasViewport}>
        <div className={narrow ? styles.canvasGridNarrow : styles.canvasGridWide}>
          {Array.from({ length: 6 }, (_, index) => (
            <div
              key={index}
              className={styles.canvasNode}
            >
              <VSkeleton className={index % 2 ? styles.canvasNodeTitleAlternate : styles.canvasNodeTitle} />
              <VSkeleton className={styles.canvasNodePrimaryLine} />
              <VSkeleton className={styles.canvasNodeSecondaryLine} />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function LoadingInspector({ lang }: { lang: "zh" | "en" }) {
  return (
    <div className={styles.inspector} aria-hidden="true">
      <div className={styles.inspectorHeader}>
        <strong className={styles.inspectorTitle}>{lang === "zh" ? "检查器" : "Inspector"}</strong>
        <VSkeleton className={styles.inspectorHeaderSkeleton} />
      </div>
      {Array.from({ length: 2 }, (_, index) => (
        <div
          key={index}
          className={styles.inspectorCard}
        >
          <VSkeleton className={index ? styles.inspectorCardTitleAlternate : styles.inspectorCardTitle} />
          <VSkeleton className={styles.inspectorCardPrimaryLine} />
          <VSkeleton className={styles.inspectorCardSecondaryLine} />
          <VSkeleton className={styles.inspectorCardTertiaryLine} />
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
      boardClassName={styles.board}
      board={<LoadingCanvas narrow={narrow} />}
      aside={narrow ? undefined : <LoadingInspector lang={lang} />}
      role="status"
      aria-live="polite"
      aria-busy="true"
      data-testid="teams-loading-shell"
    />
  );
}
