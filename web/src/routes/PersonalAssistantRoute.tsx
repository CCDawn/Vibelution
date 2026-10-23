import "./personalAssistant/personal-assistant.tailwind.css";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useLocation, useSearchParams } from "react-router-dom";
import { PanelRightClose } from "lucide-react";
import { controlDesktopAssistant } from "../api/desktopPet";
import { WORKBENCH_LAYOUT_IDS } from "../components/layout/workbenchLayoutIds";
import { VButton, VDialog, VIconButton, VSplitWorkspace, VTabs } from "../components/vui";
import { ChatCodingRoute } from "./ChatCodingRoute";
import { PersonalAssistantOverview } from "./personalAssistant/PersonalAssistantOverview";
import { PersonalAssistantDialoguePreferences } from "./personalAssistant/PersonalAssistantDialoguePreferences";
import { PersonalAssistantAffairs } from "./personalAssistant/PersonalAssistantAffairs";
import { PersonalAssistantDispatches } from "./personalAssistant/PersonalAssistantDispatches";
import { PersonalAssistantState } from "./personalAssistant/PersonalAssistantState";
import { usePersonalAssistant } from "./personalAssistant/usePersonalAssistant";
import { useAssistantNarrowLayout } from "./personalAssistant/useAssistantNarrowLayout";
import styles from "./personalAssistant/PersonalAssistant.styles";
import { PersonalAssistantCharacterRail } from "./personalAssistant/PersonalAssistantCharacterRail";
import { PersonalAssistantSettings } from "./personalAssistant/PersonalAssistantSettings";
import { PersonalAssistantComputerPanel } from "./personalAssistant/PersonalAssistantComputerPanel";
import computerStyles from "./personalAssistant/PersonalAssistantComputerPanel.styles";
import { useShellI18n } from "../i18n/useShellI18n";
import { PERSONAL_ASSISTANT_COPY } from "./personalAssistant/personalAssistantCopy";

type DesktopError = { key: "desktopBusy" | "desktopFailed" | "desktopOpenFailed" } | { message: string };

export function PersonalAssistantRoute() {
  const { lang } = useShellI18n();
  const copy = PERSONAL_ASSISTANT_COPY[lang];
  const state = usePersonalAssistant();
  const narrow = useAssistantNarrowLayout();
  const [overviewOpen, setOverviewOpen] = useState(false);
  const [overviewCollapsed, setOverviewCollapsed] = useState(false);
  // 每次导航都重新打开通知目标，包括重复点击相同 URL；普通重渲染不重置面板。
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const dispatchesDeepLink = searchParams.get("panel") === "dispatches";
  const affairsDeepLink = searchParams.get("panel") === "affairs";
  const focusItemId = affairsDeepLink ? searchParams.get("item") ?? undefined : undefined;
  const [affairFocusReceipt, setAffairFocusReceipt] = useState<{
    requestKey: string; result: "found" | "missing";
  } | null>(null);
  const onAffairFocusHandled = useCallback((requestKey: string, result: "found" | "missing") => {
    setAffairFocusReceipt({ requestKey, result });
  }, []);
  const focusRequestResult = affairFocusReceipt?.requestKey === location.key ? affairFocusReceipt.result : undefined;
  const searchParamsString = searchParams.toString();
  const [rightTab, setRightTab] = useState(() => (dispatchesDeepLink ? "dispatches" : affairsDeepLink ? "affairs" : "overview"));
  const [computerOpen, setComputerOpen] = useState(false);
  const [preferencesOpen, setPreferencesOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [affairsOpen, setAffairsOpen] = useState(affairsDeepLink);
  const [dispatchesOpen, setDispatchesOpen] = useState(dispatchesDeepLink);
  useEffect(() => {
    const panel = new URLSearchParams(searchParamsString).get("panel");
    if (panel !== "dispatches" && panel !== "affairs") return;
    setOverviewCollapsed(false);
    setRightTab(panel);
    setDispatchesOpen(panel === "dispatches");
    setAffairsOpen(panel === "affairs");
  }, [location.key, searchParamsString]);
  const nativeWorkspace = useMemo(() => <ChatCodingRoute />, []);
  const assistantAgentId = state.assistant?.agentId ?? "";
  const [desktopPending, setDesktopPending] = useState(false);
  const [desktopError, setDesktopError] = useState<DesktopError | null>(null);
  const desktopErrorText = desktopError && ("key" in desktopError ? copy[desktopError.key] : desktopError.message);
  async function openDesktop() {
    if (desktopPending) return;
    setDesktopPending(true); setDesktopError(null);
    try {
      const result = await controlDesktopAssistant(true);
      if (result.busyElsewhere) setDesktopError({ key: "desktopBusy" });
      else if (!result.open || result.mode !== "assistant") setDesktopError({ key: "desktopFailed" });
    } catch (error) { setDesktopError(error instanceof Error ? { message: error.message } : { key: "desktopOpenFailed" }); }
    finally { setDesktopPending(false); }
  }
  return <div className={styles.root} data-vui-domain-recipe="personal-assistant">
    {narrow ? <div className={styles.narrowActions} aria-label={copy.assistantActions}>
      <VButton variant="secondary" isDisabled={!state.verified} onClick={() => setOverviewOpen(true)}>{copy.overview}</VButton>
      <VButton variant="secondary" isDisabled={!state.verified} onClick={() => setComputerOpen(true)}>{copy.computerControl}</VButton>
      <VButton variant="secondary" isDisabled={!state.verified} onClick={() => setPreferencesOpen(true)}>{copy.dialoguePreferences}</VButton>
      <VButton variant="secondary" isDisabled={!state.verified} onClick={() => setAffairsOpen(true)}>{copy.affairs}</VButton>
      <VButton variant="secondary" isDisabled={!state.verified} onClick={() => setDispatchesOpen(true)}>{copy.dispatches}</VButton>
      <VButton variant="secondary" isDisabled={!state.verified} onClick={() => setSettingsOpen(true)}>{copy.settings}</VButton>
      <VButton variant="secondary" isDisabled={!state.verified} isPending={desktopPending} onClick={() => void openDesktop()}>{copy.desktopMode}</VButton>
    </div> : null}
    {desktopErrorText ? <p className={styles.error} role="alert">{desktopErrorText}</p> : null}
    <VSplitWorkspace className={styles.split} chrome="workbench" resize={{ layoutId: WORKBENCH_LAYOUT_IDS.personalAssistant,
      sidebar: { defaultWidth: 176, minWidth: 148, maxWidth: 220 },
      aside: { defaultWidth: 340, minWidth: 280, maxWidth: 440 },
      collapse: { aside: { separatorLabel: copy.resizeOverview, collapseLabel: copy.collapseOverview, expandLabel: copy.expandOverview,
        placement: "header", restoreInRail: true, collapsed: overviewCollapsed, onCollapsedChange: setOverviewCollapsed } } }}
      sidebar={state.verified && !narrow ? <PersonalAssistantCharacterRail assistant={state.assistant!} desktopPending={desktopPending} onOpenDesktop={() => void openDesktop()} /> : undefined}
      main={<div className={styles.main}>{state.verified ? nativeWorkspace : <PersonalAssistantState state={state} />}</div>}
      aside={state.verified && !narrow ? <VTabs className={computerStyles.rail} listClassName={computerStyles.tabs}
        contentClassName="min-h-0 flex-1 overflow-hidden" aria-label={copy.assistantRail} value={rightTab} onValueChange={setRightTab} items={[
          { id: "overview", label: copy.overview, content: <PersonalAssistantOverview headerAction={<VIconButton variant="ghost" label={copy.collapseOverview}
            icon={<PanelRightClose size={14} />} onClick={() => setOverviewCollapsed(true)} />}
            onOpenSession={id => state.route.openSession(id, { surface: "chat", replace: false })} /> },
          { id: "computer", label: copy.computerControl, content: <PersonalAssistantComputerPanel active={!overviewCollapsed && rightTab === "computer"}
            onCollapse={() => setOverviewCollapsed(true)} /> },
          { id: "preferences", label: copy.dialoguePreferences, content: <PersonalAssistantDialoguePreferences agentId={assistantAgentId}
            headerAction={<VIconButton variant="ghost" label={copy.collapseOverview}
              icon={<PanelRightClose size={14} />} onClick={() => setOverviewCollapsed(true)} />} /> },
          { id: "affairs", label: copy.affairs, content: <PersonalAssistantAffairs agentId={assistantAgentId}
            focusItemId={focusItemId} focusRequestKey={location.key}
            focusRequestResult={focusRequestResult} onFocusRequestHandled={onAffairFocusHandled}
            headerAction={<VIconButton variant="ghost" label={copy.collapseOverview}
              icon={<PanelRightClose size={14} />} onClick={() => setOverviewCollapsed(true)} />} /> },
          { id: "dispatches", label: copy.dispatches, content: <PersonalAssistantDispatches agentId={assistantAgentId}
            onOpenSession={id => state.route.openSession(id, { surface: "chat", replace: false })}
            headerAction={<VIconButton variant="ghost" label={copy.collapseOverview}
              icon={<PanelRightClose size={14} />} onClick={() => setOverviewCollapsed(true)} />} /> },
        ]} /> : undefined} />
    <VDialog open={narrow && overviewOpen} onOpenChange={setOverviewOpen} title={copy.overview} size="sm">
      <div className={styles.narrowOverview}><PersonalAssistantOverview onOpenSession={id => {
        setOverviewOpen(false); state.route.openSession(id, { surface: "chat", replace: false });
      }} /></div>
    </VDialog>
    <VDialog open={narrow && computerOpen && state.verified} onOpenChange={setComputerOpen} title={copy.computerControl} size="sm">
      <div className={styles.narrowOverview}><PersonalAssistantComputerPanel active={narrow && computerOpen}
        onCollapse={() => setComputerOpen(false)} /></div>
    </VDialog>
    <VDialog open={narrow && preferencesOpen && state.verified} onOpenChange={setPreferencesOpen} title={copy.dialoguePreferences} size="sm">
      <div className={styles.narrowOverview}><PersonalAssistantDialoguePreferences agentId={assistantAgentId} /></div>
    </VDialog>
    <VDialog open={narrow && affairsOpen && state.verified} onOpenChange={setAffairsOpen} title={copy.affairs} size="sm">
      <div className={styles.narrowOverview}><PersonalAssistantAffairs agentId={assistantAgentId}
        focusItemId={focusItemId} focusRequestKey={location.key}
        focusRequestResult={focusRequestResult} onFocusRequestHandled={onAffairFocusHandled} /></div>
    </VDialog>
    <VDialog open={narrow && dispatchesOpen && state.verified} onOpenChange={setDispatchesOpen} title={copy.dispatches} size="sm">
      <div className={styles.narrowOverview}><PersonalAssistantDispatches agentId={assistantAgentId}
        onOpenSession={id => { setDispatchesOpen(false); state.route.openSession(id, { surface: "chat", replace: false }); }} /></div>
    </VDialog>
    <PersonalAssistantSettings open={narrow && settingsOpen && state.verified} onOpenChange={setSettingsOpen} />
  </div>;
}
