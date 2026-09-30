import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  ArrowDown,
  BookOpen,
  Database,
  Ellipsis,
  History,
  MessageSquareText,
  PanelLeft,
  PanelRightClose,
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
  VTabs,
} from "../components/vui";
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
  onSelect: () => void;
};

export type EvolutionWorkspaceRunGroup = {
  id: EvolutionTrack;
  label: string;
  runs: readonly EvolutionWorkspaceRun[];
};

export type SupervisedConversationWorkspaceProps = {
  lang: "zh" | "en";
  title: string;
  sourceLabel: string;
  sourceTitle?: string;
  sourceIcon?: ReactNode;
  sourceSummary?: ReactNode;
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
  defaultWidth: 400,
  minWidth: 320,
  maxWidth: 560,
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
      evidence: "Evidence",
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
      evidenceTitle: "Run evidence",
      navigation: "Run context",
      progress: "Phase progress",
      noRuns: "No runs yet",
    };
  }
  return {
    product: "监督进化",
    selfProduct: "自进化",
    trackNavigation: "进化类型",
    supervisedTrack: "监督",
    selfTrack: "自进化",
    newRun: "新建",
    dataset: "评估集",
    evidence: "证据",
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
    evidenceTitle: "运行证据",
    navigation: "运行导航",
    progress: "阶段进度",
    noRuns: "暂无运行",
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
  const narrow = workspaceWidth < 880;
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const [navigationOpen, setNavigationOpen] = useState(false);
  const [desktopNavigationOpen, setDesktopNavigationOpen] = useState(true);
  const [selectedEvidenceTabId, setSelectedEvidenceTabId] = useState("");
  const evidenceTab = evidenceTabs.find((tab) => tab.id === selectedEvidenceTabId)
    ?? evidenceTabs[0];
  const showEvidence = !setupOpen && evidenceOpen && hasRun && evidenceTabs.length > 0;
  const showDesktopEvidence = showEvidence && workspaceWidth >= 960;
  const showMobileEvidence = showEvidence && !showDesktopEvidence;
  const showDesktopNavigation = desktopNavigationOpen && (!showDesktopEvidence || workspaceWidth >= 1200);
  const showTrackSwitcher = activeTrack !== undefined && onTrackChange !== undefined;
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
      setEvidenceOpen(false);
      setNavigationOpen(false);
    }
  }, [setupOpen]);

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

  const tabItems = evidenceTabs.map((tab) => ({
    id: tab.id,
    label: tab.label,
    content: <div className={styles.evidenceTabBody}>{tab.content}</div>,
  }));
  const navigationOptions = steps.map((step) => ({
    value: step.id,
    label: step.label,
    disabled: step.disabled,
  }));
  const showPhaseNavigation = !setupOpen && hasRun && navigationOptions.length > 0;
  const hasRunGroups = Boolean(runGroups?.length);
  const showNavigation = hasRunGroups || trackContext != null || (!setupOpen && hasRun);
  const showContext = showNavigation;
  const closeNavigation = () => setNavigationOpen(false);
  const contextPanel = (
    <VSurface as="aside" padding="none" className={styles.contextPanel} aria-label={labels.navigation}>
      {hasRunGroups ? (
        <nav aria-label={labels.navigation} className={styles.contextRunGroups}>
          {runGroups?.map((group) => (
            <section key={group.id} className={styles.runGroup} aria-label={group.label}>
              <h2 className={styles.runGroupHeading}>
                <span>{group.label}</span>
                <span className={styles.runGroupCount}>{group.runs.length}</span>
              </h2>
              {group.runs.length ? (
                <div className={styles.runGroupItems}>
                  {group.runs.map((run) => (
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
                  ))}
                </div>
              ) : (
                <p className={styles.runGroupEmpty}>{labels.noRuns}</p>
              )}
            </section>
          ))}
        </nav>
      ) : null}
      {trackContext != null ? <section className={styles.trackContext}>{trackContext}</section> : null}
      {!setupOpen && hasRun ? (
        <>
          <section className={styles.sourceSection}>
            <h2 className={styles.contextHeading}>{sourceTitle || labels.dataset}</h2>
            <VButton aria-label={sourceTitle || labels.dataset} title={sourceLabel} contentLayout="plain" variant="ghost" className={styles.contextSourceButton}
              onPress={() => { closeNavigation(); onSource(); }} icon={sourceIcon ?? <Database size={15} />}>
              <span className={styles.contextSourceName}>{sourceLabel || sourceTitle || labels.dataset}</span>
            </VButton>
            {sourceSummary ? <div className={styles.sourceSummary}>{sourceSummary}</div> : null}
          </section>
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
          <div className={styles.contextLinks}>
            <VButton contentLayout="plain" variant="ghost" className={styles.contextLink} icon={<History size={15} />} onPress={() => { closeNavigation(); onHistory(); }}>{labels.history}</VButton>
            <VButton contentLayout="plain" variant="ghost" className={styles.contextLink} icon={<Settings2 size={15} />} onPress={() => { closeNavigation(); onSettings(); }}>{labels.settings}</VButton>
          </div>
        </>
      ) : null}
    </VSurface>
  );

  const evidenceTabsView = evidenceTabs.length ? (
    <VTabs
      aria-label={labels.evidenceTitle}
      className={styles.evidenceTabs}
      listClassName={styles.evidenceTabList}
      triggerClassName={styles.evidenceTabTrigger}
      value={evidenceTab?.id}
      onValueChange={setSelectedEvidenceTabId}
      items={tabItems}
    />
  ) : null;

  const desktopEvidence = showDesktopEvidence ? (
    <VSurface
      as="aside"
      aria-label={labels.evidenceTitle}
      className={styles.evidencePanel}
      padding="none"
    >
      <div className={styles.evidenceHeading}>
        <strong className={styles.evidenceHeadingTitle}>{labels.evidenceTitle}</strong>
        <VIconButton
          label={labels.closeEvidence}
          variant="ghost"
          className={styles.evidenceClose}
          icon={<PanelRightClose size={16} />}
          onPress={() => setEvidenceOpen(false)}
        />
      </div>
      {evidenceTabsView}
    </VSurface>
  ) : undefined;

  const mainContent = (
    <main className={styles.mainPane}>
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
          {footer ? <div className={styles.footer}>{footer}</div> : null}
        </>
      ) : (
        <div className={styles.setupFrame}>{setup}</div>
      )}
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
      <header className={`${styles.header} ${showTrackSwitcher || showPhaseNavigation ? styles.headerWithNavigation : styles.headerWithoutNavigation} ${narrow ? styles.narrowHeader : ""} ${narrow && (showTrackSwitcher || showPhaseNavigation) ? styles.narrowHeaderWithNavigation : ""}`}>
        <div className={styles.runIdentity} data-has-source={!setupOpen && sourceLabel ? "true" : "false"}>
          {showContext ? <VIconButton label={labels.navigation} variant="ghost" icon={<PanelLeft size={16} />}
            aria-expanded={narrow ? navigationOpen : showDesktopNavigation}
            onPress={() => {
              if (narrow) setNavigationOpen((open) => !open);
              else if (desktopNavigationOpen && !showDesktopNavigation) setEvidenceOpen(false);
              else setDesktopNavigationOpen((open) => !open);
            }} /> : null}
          <h1 className={styles.title} title={setupOpen ? setupTitle || labels.setupTitle : title}>
            {setupOpen ? setupTitle || labels.setupTitle : title}
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
            {showPhaseNavigation ? (
              <VStringSelect
                ariaLabel={labels.phaseNavigation}
                className={styles.phaseSelect}
                value={selectedStepId}
                onValueChange={onSelectStep}
                options={navigationOptions}
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
              <VButton
                aria-expanded={showEvidence}
                aria-label={labels.evidence}
                contentLayout="plain"
                variant={showEvidence ? "secondary" : "ghost"}
                className={styles.toolbarButton}
                isDisabled={!hasRun || evidenceTabs.length === 0}
                onPress={() => setEvidenceOpen((open) => !open)}
                icon={<PanelRightOpen size={15} />}
              >
                {labels.evidence}
              </VButton>
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
      {showContext && !narrow && showDesktopNavigation ? contextPanel : null}
      <VSplitWorkspace
        aside={desktopEvidence}
        className={styles.splitWorkspace}
        columnsClassName=""
        main={mainContent}
        resize={LIVE_RUN_RESIZE}
      />
      </div>

      <VDialog className={styles.mobileNavigationDialog} open={showContext && narrow && navigationOpen}
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
        <div className={styles.mobileEvidenceBody}>{evidenceTabsView}</div>
      </VDialog>
    </section>
  );
}
