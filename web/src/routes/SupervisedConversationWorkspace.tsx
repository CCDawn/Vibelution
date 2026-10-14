import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  ArrowDown,
  BookOpen,
  ChevronDown,
  ChevronRight,
  Database,
  Ellipsis,
  History,
  MessageSquareText,
  PanelLeft,
  PanelRightOpen,
  Plus,
  Settings2,
} from "lucide-react";

import { WORKBENCH_LAYOUT_IDS } from "../components/layout/workbenchLayoutIds";
import {
  VButton,
  VDialog,
  VDropdownMenu,
  VIconButton,
  VSplitWorkspace,
  VSurface,
  VStringSelect,
  VStateSurface,
  VTabs,
  VUI_WORKBENCH_RAIL_CLASS,
  VUI_WORKBENCH_TOOLBAR_CLASS,
} from "../components/vui";
import { persistPaneVisibility, readPaneVisibility } from "../components/layout/paneVisibilityPersistence";
import styles from "./SupervisedConversationWorkspace.styles";

export type SupervisedConversationWorkspaceStep = {
  id: string;
  label: ReactNode;
  disabled?: boolean;
};

export type SupervisedConversationEvidenceTab = {
  id: string;
  label: ReactNode;
  content: ReactNode;
};

export type EvolutionTrack = "supervised" | "self";

export type EvolutionWorkspaceRun = {
  id: string;
  title: string;
  status: string;
  selected: boolean;
  history?: boolean;
  onSelect: () => void;
};

export type EvolutionWorkspaceRunGroup = {
  id: EvolutionTrack;
  label: string;
  runs: readonly EvolutionWorkspaceRun[];
  onHistory?: () => void;
};

export type SupervisedConversationWorkspaceProps = {
  lang: "zh" | "en";
  title: string;
  sourceLabel: string;
  sourceTitle?: string;
  sourceIcon?: ReactNode;
  sourceSummary?: ReactNode;
  resultSummary?: ReactNode;
  trackContext?: ReactNode;
  activeTrack?: EvolutionTrack;
  onTrackChange?: (track: EvolutionTrack) => void;
  trackAvailability?: Partial<Record<EvolutionTrack, boolean>>;
  runGroups?: readonly EvolutionWorkspaceRunGroup[];
  setupTitle?: string;
  phases?: readonly { id: string; label: string; statusLabel: string; current: boolean; disabled?: boolean }[];
  selectedStepId: string;
  steps: readonly SupervisedConversationWorkspaceStep[];
  onSelectStep: (id: string) => void;
  showFollowLive: boolean;
  onFollowLive: () => void;
  onNew: () => void;
  onSource: () => void;
  onHistory: () => void;
  onLibrary: () => void;
  onSettings: () => void;
  onOpenConversation?: () => void;
  setupOpen: boolean;
  setup: ReactNode;
  conversation: ReactNode;
  footer: ReactNode;
  evidenceTabs: readonly SupervisedConversationEvidenceTab[];
  hasRun: boolean;
};

const LIVE_RUN_PANE = {
  id: "live-run",
  defaultWidth: 340,
  minWidth: 300,
  maxWidth: 440,
} as const;

const LIVE_RUN_RESIZE = {
  layoutId: WORKBENCH_LAYOUT_IDS.evolution,
  aside: LIVE_RUN_PANE,
} as const;

function labelsFor(lang: "zh" | "en") {
  if (lang === "en") {
    return {
      product: "Supervised evolution",
      selfProduct: "Self evolution",
      trackNavigation: "Evolution type",
      supervisedTrack: "Supervised",
      selfTrack: "Self",
      newRun: "New run",
      dataset: "Dataset",
      evidence: "Results and actions",
      more: "More",
      setupTitle: "New supervised run",
      history: "Run history",
      library: "Evaluation library",
      settings: "Run settings",
      fullConversation: "Open full conversation",
      phaseNavigation: "Evolution phases",
      followLiveContext: "Viewing an earlier phase",
      followLive: "Return to current",
      closeEvidence: "Close evidence",
      evidenceTitle: "Results and actions",
      overview: "Overview",
      conversation: "Agent conversation",
      prepare: "Confirm the goal before starting",
      prepareHint: "Use the results and actions panel to configure this run. The Agent conversation will appear here after it starts.",
      navigation: "Run context",
      progress: "Phase progress",
      noRuns: "No runs yet",
      historyRuns: "History",
      viewAllHistory: (count: number) => `View all history (${count})`,
    };
  }
  return {
    product: "监督进化",
    selfProduct: "自进化",
    trackNavigation: "进化类型",
    supervisedTrack: "监督进化",
    selfTrack: "自进化",
    newRun: "新建",
    dataset: "评估集",
    evidence: "结果与操作",
    more: "更多",
    setupTitle: "新建监督运行",
    history: "运行历史",
    library: "评测库",
    settings: "运行配置",
    fullConversation: "打开完整会话",
    phaseNavigation: "进化阶段",
    followLiveContext: "正在查看历史阶段",
    followLive: "返回当前运行",
    closeEvidence: "关闭证据",
    evidenceTitle: "结果与操作",
    overview: "概览",
    conversation: "Agent 对话",
    prepare: "先确认目标，再看进化过程",
    prepareHint: "在结果与操作面板中配置这轮运行。启动后，这里显示 Agent 的真实对话和工具记录。",
    navigation: "运行导航",
    progress: "阶段进度",
    noRuns: "暂无运行",
    historyRuns: "历史记录",
    viewAllHistory: (count: number) => `查看全部历史（${count}）`,
  };
}

function useWorkspaceWidth() {
  const rootRef = useRef<HTMLElement>(null);
  const [width, setWidth] = useState(() => typeof window !== "undefined" ? window.innerWidth : 1280);

  useEffect(() => {
    const update = () => setWidth(rootRef.current?.getBoundingClientRect().width || window.innerWidth);
    const observer = typeof ResizeObserver !== "undefined" ? new ResizeObserver(update) : null;
    if (rootRef.current) observer?.observe(rootRef.current);
    window.addEventListener("resize", update);
    update();
    return () => { window.removeEventListener("resize", update); observer?.disconnect(); };
  }, []);

  return { rootRef, width };
}

export function SupervisedConversationWorkspace({
  lang,
  title,
  sourceLabel,
  sourceTitle,
  sourceIcon,
  sourceSummary,
  resultSummary,
  trackContext,
  activeTrack,
  onTrackChange,
  trackAvailability,
  runGroups,
  setupTitle,
  phases = [],
  selectedStepId,
  steps,
  onSelectStep,
  showFollowLive,
  onFollowLive,
  onNew,
  onSource,
  onHistory,
  onLibrary,
  onSettings,
  onOpenConversation,
  setupOpen,
  setup,
  conversation,
  footer,
  evidenceTabs,
  hasRun,
}: SupervisedConversationWorkspaceProps) {
  const labels = labelsFor(lang);
  const workspaceLabel = activeTrack === "self" ? labels.selfProduct : labels.product;
  const { rootRef, width: workspaceWidth } = useWorkspaceWidth();
  const narrow = workspaceWidth < 900;
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const [navigationOpen, setNavigationOpen] = useState(false);
  const [desktopNavigationOpen, setDesktopNavigationOpen] = useState(() =>
    readPaneVisibility(WORKBENCH_LAYOUT_IDS.evolution, "run-navigation", true),
  );
  const [expandedHistoryGroups, setExpandedHistoryGroups] = useState<Record<string, boolean>>({});
  const [selectedEvidenceTabId, setSelectedEvidenceTabId] = useState("");
  const showDesktopEvidence = !narrow;
  const showMobileEvidence = narrow && evidenceOpen;
  const showDesktopNavigation = desktopNavigationOpen && workspaceWidth >= 1180;
  const showTrackSwitcher = activeTrack !== undefined && onTrackChange !== undefined;

  useEffect(() => {
    persistPaneVisibility(WORKBENCH_LAYOUT_IDS.evolution, "run-navigation", desktopNavigationOpen);
  }, [desktopNavigationOpen]);
  const trackItems = [
    {
      id: "supervised",
      label: labels.supervisedTrack,
      disabled: trackAvailability?.supervised === false,
    },
    {
      id: "self",
      label: labels.selfTrack,
      disabled: trackAvailability?.self === false,
    },
  ];

  useEffect(() => {
    if (setupOpen) {
      setEvidenceOpen(narrow);
      setNavigationOpen(false);
    }
  }, [setupOpen, narrow]);

  const moreItems = [
    ...(onOpenConversation
      ? [{
          id: "open-conversation",
          label: labels.fullConversation,
          icon: <MessageSquareText size={15} />,
          onSelect: onOpenConversation,
        }]
      : []),
    {
      id: "history",
      label: labels.history,
      icon: <History size={15} />,
      onSelect: onHistory,
    },
    {
      id: "library",
      label: labels.library,
      icon: <BookOpen size={15} />,
      onSelect: onLibrary,
    },
    {
      id: "settings",
      label: labels.settings,
      icon: <Settings2 size={15} />,
      onSelect: onSettings,
    },
  ];

  const navigationOptions = steps.map((step) => ({
    value: step.id,
    label: step.label,
    disabled: step.disabled,
  }));
  const showPhaseNavigation = !setupOpen && hasRun && navigationOptions.length > 0;
  const hasRunGroups = Boolean(runGroups?.length);
  const showNavigation = hasRunGroups || (!setupOpen && hasRun);
  const showContext = showNavigation;
  const closeNavigation = () => setNavigationOpen(false);
  const contextPanel = (
    <VSurface as="aside" padding="none" className={`${VUI_WORKBENCH_RAIL_CLASS} ${styles.contextPanel}`} aria-label={labels.navigation}>
      <div className={styles.navigationHeading}>
        <h2 className={styles.contextHeading}>{labels.navigation}</h2>
        <VIconButton label={labels.newRun} variant="ghost" icon={<Plus size={16} />} onPress={() => { closeNavigation(); onNew(); }} />
      </div>
      {hasRunGroups ? (
        <nav aria-label={labels.navigation} className={styles.contextRunGroups}>
          {runGroups?.filter((group) => !activeTrack || group.id === activeTrack).map((group) => {
            const currentRuns = group.runs.filter((run) => !run.history || run.selected);
            const historyRuns = group.runs.filter((run) => run.history && !run.selected);
            const historyExpanded = expandedHistoryGroups[group.id] === true;
            const selectRun = (run: EvolutionWorkspaceRun) => (
              <VButton
                key={run.id}
                contentLayout="plain"
                variant="ghost"
                className={styles.runItem}
                aria-pressed={run.selected}
                aria-current={run.selected ? "page" : undefined}
                title={run.title}
                onPress={() => { run.onSelect(); closeNavigation(); }}
              >
                <span className={styles.runItemText}>
                  <span className={styles.runItemTitle}>{run.title}</span>
                  <span className={styles.runItemStatus}>{run.status}</span>
                </span>
              </VButton>
            );
            return (
              <section key={group.id} className={styles.runGroup} aria-label={group.label}>
                <h2 className={styles.runGroupHeading}>
                  <span>{group.label}</span>
                  <span className={styles.runGroupCount}>{group.runs.length}</span>
                </h2>
                {group.runs.length ? (
                  <>
                    {currentRuns.length ? (
                      <div className={styles.runGroupItems}>{currentRuns.map(selectRun)}</div>
                    ) : null}
                    {historyRuns.length ? (
                      <div className={styles.runHistory}>
                        <VButton
                          contentLayout="plain"
                          variant="ghost"
                          className={styles.runHistoryToggle}
                          aria-expanded={historyExpanded}
                          aria-controls={`evolution-history-${group.id}`}
                          onPress={() => setExpandedHistoryGroups((current) => ({
                            ...current,
                            [group.id]: !historyExpanded,
                          }))}
                        >
                          <span className={styles.runHistoryLabel}>
                            {historyExpanded ? <ChevronDown size={14} aria-hidden="true" /> : <ChevronRight size={14} aria-hidden="true" />}
                            <span>{labels.historyRuns}</span>
                          </span>
                          <span className={styles.runGroupCount}>{historyRuns.length}</span>
                        </VButton>
                        <div
                          id={`evolution-history-${group.id}`}
                          className={`${styles.runGroupItems} ${historyExpanded ? "" : "hidden"}`}
                          hidden={!historyExpanded}
                        >
                          {historyRuns.slice(0, 5).map(selectRun)}
                          {historyRuns.length > 5 ? (
                            <VButton
                              contentLayout="plain"
                              variant="ghost"
                              className={styles.runHistoryAll}
                              onPress={() => {
                                closeNavigation();
                                if (group.onHistory) group.onHistory();
                                else onHistory();
                              }}
                            >
                              {labels.viewAllHistory(historyRuns.length)}
                            </VButton>
                          ) : null}
                        </div>
                      </div>
                    ) : null}
                  </>
                ) : (
                  <p className={styles.runGroupEmpty}>{labels.noRuns}</p>
                )}
              </section>
            );
          })}
        </nav>
      ) : null}
      <div className={styles.contextLinks}>
        <VButton contentLayout="plain" variant="ghost" className={styles.contextLink} icon={<History size={15} />} onPress={() => { closeNavigation(); onHistory(); }}>{labels.history}</VButton>
      </div>
    </VSurface>
  );

  const overview = (
    <div className={styles.resultOverview}>
      {trackContext != null ? <section className={styles.trackContext}>{trackContext}</section> : null}
      {hasRun ? <>
          <section className={styles.sourceSection}>
            <h2 className={styles.contextHeading}>{sourceTitle || labels.dataset}</h2>
            <VButton aria-label={sourceTitle || labels.dataset} title={sourceLabel} contentLayout="plain" variant="ghost" className={styles.contextSourceButton}
              onPress={() => { closeNavigation(); onSource(); }} icon={sourceIcon ?? <Database size={15} />}>
              <span className={styles.contextSourceName}>{sourceLabel || sourceTitle || labels.dataset}</span>
            </VButton>
            {sourceSummary ? <div className={styles.sourceSummary}>{sourceSummary}</div> : null}
          </section>
          {resultSummary}
          <nav aria-label={labels.progress} className={styles.contextPhases}>
            <h2 className={styles.contextHeading}>{labels.progress}</h2>
            {phases.map((phase, index) => (
              <VButton key={phase.id} contentLayout="plain" variant="ghost" className={styles.contextPhase}
                aria-pressed={selectedStepId === phase.id} aria-current={phase.current ? "step" : undefined}
                isDisabled={phase.disabled} onPress={() => { onSelectStep(phase.id); closeNavigation(); }}>
                <span className={styles.phaseNumber}>{index + 1}</span>
                <span className={styles.contextPhaseName}>{phase.label}</span>
                <span className={styles.contextPhaseStatus}>{phase.statusLabel}</span>
              </VButton>
            ))}
          </nav>
      </> : null}
      <VButton contentLayout="plain" variant="ghost" className={styles.contextLink} icon={<Settings2 size={15} />} onPress={onSettings}>{labels.settings}</VButton>
    </div>
  );

  const tabItems = [{ id: "overview", label: labels.overview, content: overview }, ...evidenceTabs.map((tab) => ({
    id: tab.id, label: tab.label, content: <div className={styles.evidenceTabBody}>{tab.content}</div>,
  }))];
  const evidenceTab = tabItems.find((tab) => tab.id === selectedEvidenceTabId) ?? tabItems[0];
  const evidenceTabsView = (
    <VTabs
      aria-label={labels.evidenceTitle}
      className={styles.evidenceTabs}
      contentClassName={styles.evidenceTabContent}
      listClassName={styles.evidenceTabList}
      triggerClassName={styles.evidenceTabTrigger}
      value={evidenceTab?.id}
      onValueChange={setSelectedEvidenceTabId}
      items={tabItems}
    />
  );

  const resultPanel = (
    <VSurface
      as="aside"
      aria-label={labels.evidenceTitle}
      className={styles.evidencePanel}
      padding="none"
    >
      <div className={`${styles.evidenceHeading} ${narrow ? "!hidden" : ""}`}>
        <strong className={styles.evidenceHeadingTitle}>{labels.evidenceTitle}</strong>
      </div>
      {setupOpen ? <div className={styles.setupFrame}>{setup}</div> : <>
        {footer ? <div className={styles.resultActions} data-vui-region="evolution-current-actions">{footer}</div> : null}
        <div className={styles.resultBody}>{evidenceTabsView}</div>
      </>}
    </VSurface>
  );

  const mainContent = (
    <main className={styles.mainPane}>
      <div className={styles.conversationHeading}>
        <h2>{labels.conversation}</h2>
        {showPhaseNavigation ? <VStringSelect ariaLabel={labels.phaseNavigation} className={styles.phaseSelect} value={selectedStepId} onValueChange={onSelectStep} options={navigationOptions} /> : null}
      </div>
      {!setupOpen ? (
        <>
          {showFollowLive ? (
            <div className={styles.followLiveNotice} role="status">
              <span>{labels.followLiveContext}</span>
              <VButton
                contentLayout="plain"
                variant="ghost"
                className={styles.followLiveButton}
                onPress={onFollowLive}
                icon={<ArrowDown size={14} />}
              >
                {labels.followLive}
              </VButton>
            </div>
          ) : null}
          <div className={styles.conversationFrame}>{conversation}</div>
        </>
      ) : (
        <VStateSurface title={labels.prepare} tone="empty" fill skeletonLines={false}><p>{labels.prepareHint}</p></VStateSurface>
      )}
      {narrow ? <div className={styles.mobileActionEntry}><VButton variant="primary" icon={<PanelRightOpen size={16} />} onPress={() => setEvidenceOpen(true)}>{labels.evidence}</VButton></div> : null}
    </main>
  );

  return (
    <section
      ref={rootRef}
      aria-label={workspaceLabel}
      className={styles.root}
      data-has-run={hasRun ? "true" : "false"}
      data-vui-region="supervised-conversation-workspace"
    >
      <header className={`${VUI_WORKBENCH_TOOLBAR_CLASS} ${styles.header} ${showTrackSwitcher || showPhaseNavigation ? styles.headerWithNavigation : styles.headerWithoutNavigation} ${narrow ? styles.narrowHeader : ""} ${narrow && (showTrackSwitcher || showPhaseNavigation) ? styles.narrowHeaderWithNavigation : ""}`}>
        <div className={styles.runIdentity} data-has-source={!setupOpen && sourceLabel ? "true" : "false"}>
          {showContext ? <VIconButton label={labels.navigation} variant="ghost" icon={<PanelLeft size={16} />}
            aria-expanded={workspaceWidth < 1180 ? navigationOpen : showDesktopNavigation}
            onPress={() => {
              if (workspaceWidth < 1180) setNavigationOpen((open) => !open);
              else setDesktopNavigationOpen((open) => !open);
            }} /> : null}
          <h1 className={styles.title} title={setupOpen ? setupTitle || labels.setupTitle : title}>
            {lang === "zh" ? "进化工作台" : "Evolution workspace"}
          </h1>
          {!setupOpen && !hasRun ? (
            <VButton
              aria-label={sourceTitle || labels.dataset}
              title={sourceLabel || sourceTitle || labels.dataset}
              contentLayout="plain"
              variant="ghost"
              className={styles.sourceButton}
              onPress={onSource}
              icon={sourceIcon ?? <Database size={14} />}
            >
              <span>{sourceTitle || labels.dataset}</span>
              {sourceLabel ? <span className={styles.sourceValue}>{sourceLabel}</span> : null}
            </VButton>
          ) : null}
        </div>

        {showTrackSwitcher || showPhaseNavigation ? (
          <div className={`${styles.phaseNavigation} ${narrow ? styles.narrowPhaseNavigation : ""}`}>
            {showTrackSwitcher ? (
              <VTabs
                aria-label={labels.trackNavigation}
                className={styles.trackTabs}
                listClassName={styles.trackTabList}
                triggerClassName={styles.trackTabTrigger}
                value={activeTrack}
                onValueChange={(value) => {
                  if (value === "self" || value === "supervised") onTrackChange?.(value);
                }}
                items={trackItems}
              />
            ) : null}
          </div>
        ) : null}

        <div className={`${styles.toolbar} ${showTrackSwitcher || showPhaseNavigation ? "" : styles.toolbarWithoutNavigation} ${narrow ? styles.narrowToolbar : ""}`} role="toolbar" aria-label={workspaceLabel}>
          {!setupOpen ? (
            <>
              <VButton
                aria-label={labels.newRun}
                contentLayout="plain"
                variant="secondary"
                className={styles.toolbarButton}
                onPress={onNew}
                icon={<Plus size={15} />}
              >
                {labels.newRun}
              </VButton>
              {narrow ? <VButton
                aria-expanded={showMobileEvidence}
                aria-label={labels.evidence}
                contentLayout="plain"
                variant="ghost"
                className={styles.toolbarButton}
                onPress={() => setEvidenceOpen((open) => !open)}
                icon={<PanelRightOpen size={15} />}
              >
                {labels.evidence}
              </VButton> : null}
            </>
          ) : null}
          <VDropdownMenu
            aria-label={labels.more}
            align="end"
            items={moreItems}
            trigger={(
              <VButton
                aria-label={labels.more}
                contentLayout="plain"
                variant="ghost"
                className={styles.toolbarButton}
                icon={<Ellipsis size={16} />}
              >
                <span className={styles.moreLabel}>{labels.more}</span>
              </VButton>
            )}
          />
        </div>
      </header>

      <div className={styles.workspaceBody}>
      {showContext && showDesktopNavigation ? contextPanel : null}
      <VSplitWorkspace
        aside={showDesktopEvidence ? resultPanel : undefined}
        chrome="workbench"
        className={styles.splitWorkspace}
        columnsClassName=""
        main={mainContent}
        resize={LIVE_RUN_RESIZE}
      />
      </div>

      <VDialog className={styles.mobileNavigationDialog} open={showContext && workspaceWidth < 1180 && navigationOpen}
        onOpenChange={setNavigationOpen} size="md" title={labels.navigation}>
        {contextPanel}
      </VDialog>

      <VDialog
        className={styles.mobileEvidenceDialog}
        open={showMobileEvidence}
        onOpenChange={setEvidenceOpen}
        size="md"
        title={labels.evidenceTitle}
      >
        <div className={styles.mobileEvidenceBody}>{resultPanel}</div>
      </VDialog>
    </section>
  );
}
