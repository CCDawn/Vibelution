import { type ReactNode, useState } from "react";
import { PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen } from "lucide-react";
import { VIconButton, VSplitWorkspace, VSkeleton, VToolbar } from "../../components/vui";
import { WORKBENCH_LAYOUT_IDS } from "../../components/layout/workbenchLayoutIds";
import { persistPaneVisibility, readPaneVisibility } from "../../components/layout/paneVisibilityPersistence";
import styles from "../FinanceRoute.styles";

export function FinanceResearchFrame({
  zh, sidebar, aside, children, loading = true, title, meta, actions, asideHeader,
}: {
  zh: boolean;
  sidebar?: ReactNode;
  aside?: ReactNode;
  children: ReactNode;
  loading?: boolean;
  title?: ReactNode;
  meta?: ReactNode;
  actions?: ReactNode;
  asideHeader?: ReactNode;
}) {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => !readPaneVisibility(WORKBENCH_LAYOUT_IDS.finance, "sidebar", true));
  const [asideCollapsed, setAsideCollapsed] = useState(() => !readPaneVisibility(WORKBENCH_LAYOUT_IDS.finance, "aside", true));
  return (
    <section className={styles.frame} aria-label={zh ? "炒股智能体" : "Investment assistant"} data-vui-domain-recipe="financial-assistant-workspace">
      <VSplitWorkspace
        resize={{ layoutId: WORKBENCH_LAYOUT_IDS.finance,
          sidebar: { defaultWidth: 244, minWidth: 220, maxWidth: 340 },
          aside: { defaultWidth: 292, minWidth: 260, maxWidth: 380 },
          collapse: {
            sidebar: { placement: "header", separatorLabel: zh ? "调整会话栏宽度" : "Resize sessions", collapseLabel: zh ? "收起会话栏" : "Collapse sessions", expandLabel: zh ? "展开会话栏" : "Expand sessions", collapsed: sidebarCollapsed, onCollapsedChange: (collapsed) => {
              setSidebarCollapsed(collapsed);
              persistPaneVisibility(WORKBENCH_LAYOUT_IDS.finance, "sidebar", !collapsed);
            } },
            aside: { placement: "header", separatorLabel: zh ? "调整辅助栏宽度" : "Resize inspector", collapseLabel: zh ? "收起辅助栏" : "Collapse inspector", expandLabel: zh ? "展开辅助栏" : "Expand inspector", collapsed: asideCollapsed, onCollapsedChange: (collapsed) => {
              setAsideCollapsed(collapsed);
              persistPaneVisibility(WORKBENCH_LAYOUT_IDS.finance, "aside", !collapsed);
            } },
          } }}
        className={styles.split}
        sidebar={<div className={styles.workspacePane}><VToolbar wrap={false} className={styles.workspacePaneHeader} ariaLabel={zh ? "会话栏操作" : "Session pane actions"}><strong className={styles.workspacePaneTitle}>{zh ? "研究会话" : "Research sessions"}</strong><VIconButton variant="ghost" className={styles.workspacePaneAction} label={zh ? "收起会话栏" : "Collapse sessions"} icon={<PanelLeftClose size={16} />} onPress={() => { setSidebarCollapsed(true); persistPaneVisibility(WORKBENCH_LAYOUT_IDS.finance, "sidebar", false); }} /></VToolbar>{sidebar ?? <FramePlaceholder loading={loading} />}</div>}
        aside={<div className={styles.workspacePane}><VToolbar wrap={false} className={styles.workspaceAsideHeader} ariaLabel={zh ? "辅助栏操作" : "Inspector actions"}><div className={styles.workspaceAsideTabs}>{asideHeader ?? <strong className={styles.workspaceAsideTitle}>{zh ? "研究过程与引用" : "Activity and sources"}</strong>}</div><VIconButton variant="ghost" className={styles.workspacePaneAction} label={zh ? "收起辅助栏" : "Collapse inspector"} icon={<PanelRightClose size={16} />} onPress={() => { setAsideCollapsed(true); persistPaneVisibility(WORKBENCH_LAYOUT_IDS.finance, "aside", false); }} /></VToolbar>{aside ?? <FramePlaceholder loading={loading} />}</div>}
        main={<><VToolbar wrap={false} className={styles.workspaceToolbar} ariaLabel={zh ? "当前研究操作" : "Current research actions"}><div className={styles.workspaceHeaderContent}>{sidebarCollapsed ? <VIconButton variant="ghost" className={styles.workspacePaneAction} label={zh ? "展开会话栏" : "Expand sessions"} icon={<PanelLeftOpen size={16} />} onPress={() => { setSidebarCollapsed(false); persistPaneVisibility(WORKBENCH_LAYOUT_IDS.finance, "sidebar", true); }} /> : null}<h1 className={styles.workspaceHeaderTitle} title={typeof title === "string" ? title : undefined}>{title ?? (zh ? "研究工作台" : "Research workspace")}</h1>{meta ? <span className={styles.workspaceHeaderMeta}>{meta}</span> : null}</div><div className={styles.workspaceHeaderActions}>{actions}{asideCollapsed ? <VIconButton variant="ghost" className={styles.workspacePaneAction} label={zh ? "展开辅助栏" : "Expand inspector"} icon={<PanelRightOpen size={16} />} onPress={() => { setAsideCollapsed(false); persistPaneVisibility(WORKBENCH_LAYOUT_IDS.finance, "aside", true); }} /> : null}</div></VToolbar>{children}</>}
      />
    </section>
  );
}

function FramePlaceholder({ loading }: { loading: boolean }) {
  return <div className={styles.workspacePlaceholder}>
    {loading ? <div className={styles.skeleton} aria-hidden="true"><VSkeleton /><VSkeleton /><VSkeleton /></div> : null}
  </div>;
}

export function FinanceResearchLoading({ zh = true }: { zh?: boolean }) {
  return <FinanceResearchFrame zh={zh}>
    <div className={styles.frameLoading} role="status" aria-label={zh ? "正在加载研究工作台" : "Loading research workspace"} aria-busy="true" data-vui-app="workbench" data-route-loading="finance" data-finance-entry-state="loading">
      <VSkeleton className={styles.frameLoadingBar} /><div className={styles.frameLoadingQuestion}><VSkeleton className={styles.frameLoadingQuestionBar} /></div>
      <div className={styles.frameLoadingReply}><VSkeleton className={styles.frameLoadingReplyLabel} /><VSkeleton className={styles.frameLoadingReplyTitle} /><VSkeleton className={styles.frameLoadingReplyText} /><VSkeleton className={styles.frameLoadingReplyBody} /></div>
      <VSkeleton className={styles.frameLoadingComposer} />
    </div>
  </FinanceResearchFrame>;
}
