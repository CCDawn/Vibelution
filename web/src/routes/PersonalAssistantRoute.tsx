import "./personalAssistant/personal-assistant.tailwind.css";
import { useMemo, useState } from "react";
import { PanelRightClose } from "lucide-react";
import { controlDesktopAssistant } from "../api/desktopPet";
import { WORKBENCH_LAYOUT_IDS } from "../components/layout/workbenchLayoutIds";
import { VButton, VDialog, VIconButton, VSplitWorkspace, VTabs } from "../components/vui";
import { ChatCodingRoute } from "./ChatCodingRoute";
import { PersonalAssistantOverview } from "./personalAssistant/PersonalAssistantOverview";
import { PersonalAssistantState } from "./personalAssistant/PersonalAssistantState";
import { usePersonalAssistant } from "./personalAssistant/usePersonalAssistant";
import { useAssistantNarrowLayout } from "./personalAssistant/useAssistantNarrowLayout";
import styles from "./personalAssistant/PersonalAssistant.styles";
import { PersonalAssistantCharacterRail } from "./personalAssistant/PersonalAssistantCharacterRail";
import { PersonalAssistantComputerPanel } from "./personalAssistant/PersonalAssistantComputerPanel";
import computerStyles from "./personalAssistant/PersonalAssistantComputerPanel.styles";

export function PersonalAssistantRoute() {
  const state = usePersonalAssistant();
  const narrow = useAssistantNarrowLayout();
  const [overviewOpen, setOverviewOpen] = useState(false);
  const [overviewCollapsed, setOverviewCollapsed] = useState(false);
  const [rightTab, setRightTab] = useState("overview");
  const [computerOpen, setComputerOpen] = useState(false);
  const nativeWorkspace = useMemo(() => <ChatCodingRoute />, []);
  const [desktopPending, setDesktopPending] = useState(false);
  const [desktopError, setDesktopError] = useState("");
  async function openDesktop() {
    if (desktopPending) return;
    setDesktopPending(true); setDesktopError("");
    try {
      const result = await controlDesktopAssistant(true);
      if (result.busyElsewhere) setDesktopError("桌面窗口正在另一个工作台使用，请先在那个工作台关闭窗口。");
      else if (!result.open || result.mode !== "assistant") setDesktopError("个人助理窗口未能打开，请稍后重试。");
    } catch (error) { setDesktopError(error instanceof Error ? error.message : "个人助理窗口未能打开。"); }
    finally { setDesktopPending(false); }
  }
  return <div className={styles.root} data-vui-domain-recipe="personal-assistant">
    {narrow ? <div className={styles.narrowActions} aria-label="个人助理操作">
      <VButton variant="secondary" isDisabled={!state.verified} onClick={() => setOverviewOpen(true)}>平台概览</VButton>
      <VButton variant="secondary" isDisabled={!state.verified} onClick={() => setComputerOpen(true)}>电脑操作</VButton>
      <VButton variant="secondary" isDisabled={!state.verified} isPending={desktopPending} onClick={() => void openDesktop()}>桌面模式</VButton>
    </div> : null}
    {desktopError ? <p className={styles.error} role="alert">{desktopError}</p> : null}
    <VSplitWorkspace className={styles.split} chrome="workbench" resize={{ layoutId: WORKBENCH_LAYOUT_IDS.personalAssistant,
      sidebar: { defaultWidth: 176, minWidth: 148, maxWidth: 220 },
      aside: { defaultWidth: 340, minWidth: 280, maxWidth: 440 },
      collapse: { aside: { separatorLabel: "调整平台概览宽度", collapseLabel: "收起平台概览", expandLabel: "展开平台概览",
        placement: "header", restoreInRail: true, collapsed: overviewCollapsed, onCollapsedChange: setOverviewCollapsed } } }}
      sidebar={state.verified && !narrow ? <PersonalAssistantCharacterRail assistant={state.assistant!} desktopPending={desktopPending} onOpenDesktop={() => void openDesktop()} /> : undefined}
      main={<div className={styles.main}>{state.verified ? nativeWorkspace : <PersonalAssistantState state={state} />}</div>}
      aside={state.verified && !narrow ? <VTabs className={computerStyles.rail} listClassName={computerStyles.tabs}
        contentClassName="min-h-0 flex-1 overflow-hidden" aria-label="助理侧栏" value={rightTab} onValueChange={setRightTab} items={[
          { id: "overview", label: "平台概览", content: <PersonalAssistantOverview headerAction={<VIconButton variant="ghost" label="收起平台概览"
            icon={<PanelRightClose size={14} />} onClick={() => setOverviewCollapsed(true)} />}
            onOpenSession={id => state.route.openSession(id, { surface: "chat", replace: false })} /> },
          { id: "computer", label: "电脑操作", content: <PersonalAssistantComputerPanel active={!overviewCollapsed && rightTab === "computer"}
            onCollapse={() => setOverviewCollapsed(true)} /> },
        ]} /> : undefined} />
    <VDialog open={narrow && overviewOpen} onOpenChange={setOverviewOpen} title="平台概览" size="sm">
      <div className={styles.narrowOverview}><PersonalAssistantOverview onOpenSession={id => {
        setOverviewOpen(false); state.route.openSession(id, { surface: "chat", replace: false });
      }} /></div>
    </VDialog>
    <VDialog open={narrow && computerOpen && state.verified} onOpenChange={setComputerOpen} title="电脑操作" size="sm">
      <div className={styles.narrowOverview}><PersonalAssistantComputerPanel active={narrow && computerOpen}
        onCollapse={() => setComputerOpen(false)} /></div>
    </VDialog>
  </div>;
}
