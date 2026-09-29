import { useEffect, useState, type ReactNode } from "react";
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

export type SupervisedConversationWorkspaceProps = {
  lang: "zh" | "en";
  title: string;
  sourceLabel: string;
  sourceSummary?: ReactNode;
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
    };
  }
  return {
    product: "监督进化",
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
  };
}

function useNarrowViewport() {
  const [narrow, setNarrow] = useState(
    () => typeof window !== "undefined" && window.innerWidth < 880,
  );

  useEffect(() => {
    const update = () => setNarrow(window.innerWidth < 880);
    window.addEventListener("resize", update);
    update();
    return () => window.removeEventListener("resize", update);
  }, []);

  return narrow;
}

export function SupervisedConversationWorkspace({
  lang,
  title,
  sourceLabel,
  sourceSummary,
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
  const narrow = useNarrowViewport();
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const [navigationOpen, setNavigationOpen] = useState(false);
  const [desktopNavigationOpen, setDesktopNavigationOpen] = useState(true);
  const [selectedEvidenceTabId, setSelectedEvidenceTabId] = useState("");
  const evidenceTab = evidenceTabs.find((tab) => tab.id === selectedEvidenceTabId)
    ?? evidenceTabs[0];
  const showEvidence = !setupOpen && evidenceOpen && hasRun && evidenceTabs.length > 0;
  const showDesktopEvidence = showEvidence && !narrow;
  const showMobileEvidence = showEvidence && narrow;

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
  const showNavigation = !setupOpen && hasRun && navigationOptions.length > 0;
  const showContext = !setupOpen && hasRun;
  const closeNavigation = () => setNavigationOpen(false);
  const contextPanel = (
    <VSurface as="aside" padding="none" className={styles.contextPanel} aria-label={labels.navigation}>
      <section className={styles.sourceSection}>
        <h2 className={styles.contextHeading}>{labels.dataset}</h2>
        <VButton aria-label={labels.dataset} title={sourceLabel} contentLayout="plain" variant="ghost" className={styles.contextSourceButton}
          onPress={() => { closeNavigation(); onSource(); }} icon={<Database size={15} />}>
          <span className={styles.contextSourceName}>{sourceLabel || labels.dataset}</span>
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
      aria-label={labels.product}
      className={styles.root}
      data-has-run={hasRun ? "true" : "false"}
      data-vui-region="supervised-conversation-workspace"
    >
      <header className={`${styles.header} ${showNavigation ? styles.headerWithNavigation : styles.headerWithoutNavigation}`}>
        <div className={styles.runIdentity} data-has-source={!setupOpen && sourceLabel ? "true" : "false"}>
          {showContext ? <VIconButton label={labels.navigation} variant="ghost" icon={<PanelLeft size={16} />}
            aria-expanded={narrow ? navigationOpen : desktopNavigationOpen}
            onPress={() => narrow ? setNavigationOpen((open) => !open) : setDesktopNavigationOpen((open) => !open)} /> : null}
          <h1 className={styles.title} title={setupOpen ? labels.setupTitle : title}>
            {setupOpen ? labels.setupTitle : title}
          </h1>
          {!setupOpen && !hasRun ? (
            <VButton
              aria-label={labels.dataset}
              title={sourceLabel || labels.dataset}
              contentLayout="plain"
              variant="ghost"
              className={styles.sourceButton}
              onPress={onSource}
              icon={<Database size={14} />}
            >
              <span>{labels.dataset}</span>
              {sourceLabel ? <span className={styles.sourceValue}>{sourceLabel}</span> : null}
            </VButton>
          ) : null}
        </div>

        {showNavigation ? (
          <div className={styles.phaseNavigation}>
            <VStringSelect
              ariaLabel={labels.phaseNavigation}
              className={styles.phaseSelect}
              value={selectedStepId}
              onValueChange={onSelectStep}
              options={navigationOptions}
            />
          </div>
        ) : null}

        <div className={`${styles.toolbar} ${showNavigation ? "" : styles.toolbarWithoutNavigation}`} role="toolbar" aria-label={labels.product}>
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
      {showContext && !narrow && desktopNavigationOpen ? contextPanel : null}
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
