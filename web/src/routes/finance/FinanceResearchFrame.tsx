import { type ReactNode, useEffect, useRef, useState } from "react";
import { PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen } from "lucide-react";
import {
  VIconButton,
  VSplitWorkspace,
  VSkeleton,
  VToolbar,
  VUI_WORKBENCH_RAIL_CLASS,
  VUI_WORKBENCH_TOOLBAR_CLASS,
} from "../../components/vui";
import { WORKBENCH_LAYOUT_IDS } from "../../components/layout/workbenchLayoutIds";
import { persistPaneVisibility, readPaneVisibility } from "../../components/layout/paneVisibilityPersistence";
import styles from "../FinanceRoute.styles";

export function FinanceResearchFrame({
  zh, sidebar, aside, children, loading = true, title, meta, actions, sessionTabs, asideTitle, conversationRevealKey = 0, asideHeader, asideMeta, asideFooter, hideAside = false,
}: {
  zh: boolean;
  sidebar?: ReactNode | ((onCollapse: () => void) => ReactNode);
  aside?: ReactNode;
  children: ReactNode;
  loading?: boolean;
  title?: ReactNode;
  meta?: ReactNode;
  actions?: ReactNode;
  sessionTabs?: ReactNode;
  asideTitle?: ReactNode;
  conversationRevealKey?: number;
  asideHeader?: ReactNode;
  asideMeta?: ReactNode;
  asideFooter?: ReactNode;
  hideAside?: boolean;
}) {
  const frameRef = useRef<HTMLElement>(null);
  const [wideDesktop, setWideDesktop] = useState(false);
  useEffect(() => {
    if (!frameRef.current || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(entries => setWideDesktop(entries[0].contentRect.width >= 1500));
    observer.observe(frameRef.current);
    return () => observer.disconnect();
  }, []);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => !readPaneVisibility(WORKBENCH_LAYOUT_IDS.finance, "sidebar", true));
  const [asideCollapsed, setAsideCollapsed] = useState(() => !readPaneVisibility(WORKBENCH_LAYOUT_IDS.finance, "aside", true));
  useEffect(() => {
    if (!conversationRevealKey) return;
    setAsideCollapsed(false);
    persistPaneVisibility(WORKBENCH_LAYOUT_IDS.finance, "aside", true);
  }, [conversationRevealKey]);
  useEffect(() => {
    if (conversationRevealKey && !asideCollapsed) frameRef.current?.querySelector<HTMLTextAreaElement>("[data-finance-native-conversation] textarea")?.focus({ preventScroll: true });
  }, [conversationRevealKey, asideCollapsed]);
  const collapseSidebar = () => { setSidebarCollapsed(true); persistPaneVisibility(WORKBENCH_LAYOUT_IDS.finance, "sidebar", false); };
  return (
    <section ref={frameRef} className={styles.frame} data-vui-page="workspace" aria-label={zh ? "炒股智能体" : "Investment assistant"} data-vui-domain-recipe="financial-assistant-workspace">
      <VSplitWorkspace
        chrome="workbench"
        resize={{ layoutId: WORKBENCH_LAYOUT_IDS.finance,
          sidebar: { defaultWidth: 216, minWidth: 200, maxWidth: wideDesktop ? 280 : 240 },
          aside: { defaultWidth: 420, minWidth: 360, maxWidth: wideDesktop ? 620 : 480 },
          collapse: {
            sidebar: { placement: "header", separatorLabel: zh ? "调整功能栏宽度" : "Resize functions", collapseLabel: zh ? "收起功能栏" : "Collapse functions", expandLabel: zh ? "展开功能栏" : "Expand functions", collapsed: sidebarCollapsed, onCollapsedChange: (collapsed) => {
              setSidebarCollapsed(collapsed);
              persistPaneVisibility(WORKBENCH_LAYOUT_IDS.finance, "sidebar", !collapsed);
            } },
            aside: { placement: "header", separatorLabel: zh ? "调整对话栏宽度" : "Resize conversation", collapseLabel: zh ? "收起对话栏" : "Collapse conversation", expandLabel: zh ? "展开对话栏" : "Expand conversation", collapsed: asideCollapsed, onCollapsedChange: (collapsed) => {
              setAsideCollapsed(collapsed);
              persistPaneVisibility(WORKBENCH_LAYOUT_IDS.finance, "aside", !collapsed);
            } },
          } }}
        className={styles.split}
        sidebar={<div className={`${VUI_WORKBENCH_RAIL_CLASS} ${styles.workspacePane}`}>{typeof sidebar === "function" ? sidebar(collapseSidebar) : <><VToolbar wrap={false} className={`${VUI_WORKBENCH_TOOLBAR_CLASS} ${styles.workspacePaneHeader}`} ariaLabel={zh ? "功能栏操作" : "Function pane actions"}><strong className={styles.workspacePaneTitle}>{zh ? "功能" : "Functions"}</strong><VIconButton variant="ghost" className={styles.workspacePaneAction} label={zh ? "收起功能栏" : "Collapse functions"} icon={<PanelLeftClose size={16} />} onPress={collapseSidebar} /></VToolbar>{sidebar ?? <FramePlaceholder loading={loading} />}</>}</div>}
        aside={hideAside ? undefined : <div className={styles.workspacePane}><header className={styles.workspaceAsideHead}><VToolbar wrap={false} className={`${VUI_WORKBENCH_TOOLBAR_CLASS} ${styles.workspaceAsideHeader}`} ariaLabel={zh ? "对话栏操作" : "Conversation actions"}><strong className={styles.workspaceAsideTitle}>{asideTitle ?? (zh ? "研究对话" : "Research conversation")}</strong><VIconButton variant="ghost" className={styles.workspacePaneAction} label={zh ? "收起对话栏" : "Collapse conversation"} icon={<PanelRightClose size={16} />} onPress={() => { setAsideCollapsed(true); persistPaneVisibility(WORKBENCH_LAYOUT_IDS.finance, "aside", false); }} /></VToolbar>{asideMeta ? <div className={styles.workspaceAsideMeta}>{asideMeta}</div> : null}{asideHeader ? <div className={styles.workspaceAsideTabs}>{asideHeader}</div> : null}</header>{aside ?? <FramePlaceholder loading={loading} />}{asideFooter ? <footer className={styles.workspaceAsideFooter}>{asideFooter}</footer> : null}</div>}
        main={<>{sessionTabs}<VToolbar wrap={false} className={`${VUI_WORKBENCH_TOOLBAR_CLASS} ${styles.workspaceToolbar}`} ariaLabel={zh ? "当前研究操作" : "Current research actions"}><div className={styles.workspaceHeaderContent}>{sidebarCollapsed ? <VIconButton variant="ghost" className={styles.workspacePaneAction} label={zh ? "展开功能栏" : "Expand functions"} icon={<PanelLeftOpen size={16} />} onPress={() => { setSidebarCollapsed(false); persistPaneVisibility(WORKBENCH_LAYOUT_IDS.finance, "sidebar", true); }} /> : null}<h1 className={styles.workspaceHeaderTitle} title={typeof title === "string" ? title : undefined}>{title ?? (zh ? "研究工作台" : "Research workspace")}</h1>{meta ? <span className={styles.workspaceHeaderMeta}>{meta}</span> : null}</div><div className={styles.workspaceHeaderActions}>{actions}{asideCollapsed && !hideAside ? <VIconButton variant="ghost" className={styles.workspacePaneAction} label={zh ? "展开对话栏" : "Expand conversation"} icon={<PanelRightOpen size={16} />} onPress={() => { setAsideCollapsed(false); persistPaneVisibility(WORKBENCH_LAYOUT_IDS.finance, "aside", true); }} /> : null}</div></VToolbar>{children}</>}
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
