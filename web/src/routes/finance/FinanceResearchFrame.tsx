import { type ReactNode, useState } from "react";
import { TrendingUp } from "lucide-react";
import { VSplitWorkspace, VSkeleton } from "../../components/vui";
import { WORKBENCH_LAYOUT_IDS } from "../../components/layout/workbenchLayoutIds";
import { persistPaneVisibility, readPaneVisibility } from "../../components/layout/paneVisibilityPersistence";
import styles from "../FinanceRoute.styles";

export function FinanceResearchFrame({
  zh, sidebar, aside, children, actions, loading = true,
}: {
  zh: boolean;
  sidebar?: ReactNode;
  aside?: ReactNode;
  children: ReactNode;
  actions?: ReactNode;
  loading?: boolean;
}) {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => !readPaneVisibility(WORKBENCH_LAYOUT_IDS.finance, "sidebar", true));
  const [asideCollapsed, setAsideCollapsed] = useState(() => !readPaneVisibility(WORKBENCH_LAYOUT_IDS.finance, "aside", true));
  return (
    <section className={styles.frame} aria-label={zh ? "炒股智能体" : "Investment assistant"} data-vui-domain-recipe="financial-assistant-workspace">
      <header className={styles.heading}>
        <div className={styles.brand}><span className={styles.brandIcon}><TrendingUp size={18} aria-hidden="true" /></span>{zh ? "炒股智能体" : "Investment assistant"}</div>
        <div className={styles.actions}>
          <span className={styles.market}>{zh ? "A 股研究 · 只读" : "A-share research · Read-only"}</span>
          {actions}
        </div>
      </header>
      <VSplitWorkspace
        resize={{ layoutId: WORKBENCH_LAYOUT_IDS.finance,
          sidebar: { defaultWidth: 230, minWidth: 200, maxWidth: 360 },
          aside: { defaultWidth: 310, minWidth: 260, maxWidth: 460 },
          collapse: {
            sidebar: { separatorLabel: "调整自选栏宽度", collapseLabel: "收起自选栏", expandLabel: "展开自选栏", collapsed: sidebarCollapsed, onCollapsedChange: (collapsed) => {
              setSidebarCollapsed(collapsed);
              persistPaneVisibility(WORKBENCH_LAYOUT_IDS.finance, "sidebar", !collapsed);
            } },
            aside: { separatorLabel: "调整研究资料栏宽度", collapseLabel: "收起研究资料栏", expandLabel: "展开研究资料栏", collapsed: asideCollapsed, onCollapsedChange: (collapsed) => {
              setAsideCollapsed(collapsed);
              persistPaneVisibility(WORKBENCH_LAYOUT_IDS.finance, "aside", !collapsed);
            } },
          } }}
        className={styles.split}
        sidebar={sidebar ?? <FramePlaceholder zh={zh} loading={loading} />}
        aside={aside ?? <FramePlaceholder zh={zh} loading={loading} evidence />}
        main={children}
      />
    </section>
  );
}

function FramePlaceholder({ zh, evidence = false, loading }: { zh: boolean; evidence?: boolean; loading: boolean }) {
  return <div className={evidence ? styles.aside : styles.rail}>
    <span className={styles.sectionHeading}>{evidence ? (zh ? "研究过程与引用" : "Research and sources") : (zh ? "自选与研究" : "Watchlist and research")}</span>
    {loading ? <div className={styles.skeleton} aria-hidden="true"><VSkeleton /><VSkeleton /><VSkeleton /></div> : null}
  </div>;
}

export function FinanceResearchLoading({ zh = true }: { zh?: boolean }) {
  return <FinanceResearchFrame zh={zh}>
    <div className="flex min-h-0 flex-1 flex-col gap-5 p-6 overflow-hidden" role="status" aria-label={zh ? "正在加载研究工作台" : "Loading research workspace"} aria-busy="true" data-vui-app="workbench" data-route-loading="finance" data-finance-entry-state="loading">
      <div className="grid grid-cols-[2fr_1fr] gap-6"><VSkeleton className="h-12" /><VSkeleton className="h-12" /></div>
      <div className="grid grid-cols-6 gap-5"><VSkeleton /><VSkeleton /><VSkeleton /><VSkeleton /><VSkeleton /><VSkeleton /></div>
      <VSkeleton className="min-h-[290px] flex-1" /><VSkeleton className="h-24" />
    </div>
  </FinanceResearchFrame>;
}
