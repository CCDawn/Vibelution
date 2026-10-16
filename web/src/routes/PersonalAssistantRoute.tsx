import "./personalAssistant/personal-assistant.tailwind.css";
import { useMemo, useState } from "react";
import { controlDesktopAssistant } from "../api/desktopPet";
import { WORKBENCH_LAYOUT_IDS } from "../components/layout/workbenchLayoutIds";
import { VButton, VDialog, VSplitWorkspace } from "../components/vui";
import { ChatCodingRoute } from "./ChatCodingRoute";
import { PersonalAssistantOverview } from "./personalAssistant/PersonalAssistantOverview";
import { PersonalAssistantState } from "./personalAssistant/PersonalAssistantState";
import { usePersonalAssistant } from "./personalAssistant/usePersonalAssistant";
import { useAssistantNarrowLayout } from "./personalAssistant/useAssistantNarrowLayout";
import styles from "./personalAssistant/PersonalAssistant.styles";

export function PersonalAssistantRoute() {
  const state = usePersonalAssistant();
  const narrow = useAssistantNarrowLayout();
  const [overviewOpen, setOverviewOpen] = useState(false);
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
    <header className={styles.header}><div><h1 className={styles.title}>{state.assistant?.displayName || "个人助理"}</h1>
      <p className={styles.caption}>大肥鲸 · 帮你管理 Vibelution</p></div><div className={styles.actions}>
      {narrow ? <VButton variant="secondary" isDisabled={!state.verified} onClick={() => setOverviewOpen(true)}>平台概览</VButton> : null}
      <VButton variant="secondary" isDisabled={!state.verified} isPending={desktopPending} onClick={() => void openDesktop()}>桌面模式</VButton>
    </div></header>
    {desktopError ? <p className={styles.error} role="alert">{desktopError}</p> : null}
    <VSplitWorkspace className={styles.split} chrome="workbench" resize={{ layoutId: WORKBENCH_LAYOUT_IDS.personalAssistant,
      aside: { defaultWidth: 280, minWidth: 220, maxWidth: 420 },
      collapse: { aside: { separatorLabel: "调整平台概览宽度", collapseLabel: "收起平台概览", expandLabel: "展开平台概览" } } }}
      main={<div className={styles.main}>{state.verified ? nativeWorkspace : <PersonalAssistantState state={state} />}</div>}
      aside={state.verified && !narrow ? <PersonalAssistantOverview onOpenSession={id => state.route.openSession(id, { surface: "chat", replace: false })} /> : undefined} />
    <VDialog open={narrow && overviewOpen} onOpenChange={setOverviewOpen} title="平台概览" size="sm">
      <div className={styles.narrowOverview}><PersonalAssistantOverview onOpenSession={id => {
        setOverviewOpen(false); state.route.openSession(id, { surface: "chat", replace: false });
      }} /></div>
    </VDialog>
  </div>;
}
