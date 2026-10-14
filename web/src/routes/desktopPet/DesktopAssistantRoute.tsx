import "../../design/route-css/desktop-pet.tailwind.css";
import "../personalAssistant/personal-assistant.tailwind.css";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ExternalLink, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { getDesktopAssistantContext, setDesktopPetExpanded } from "../../api/desktopPet";
import { fetchPetActivity } from "../../api/pet";
import { queryKeys } from "../../api/queryKeys";
import { WORKBENCH_LAYOUT_IDS } from "../../components/layout/workbenchLayoutIds";
import { VButton, VIconButton, VSplitWorkspace, VStateSurface } from "../../components/vui";
import { ChatCodingRoute } from "../ChatCodingRoute";
import { PersonalAssistantOverview } from "../personalAssistant/PersonalAssistantOverview";
import { PersonalAssistantState } from "../personalAssistant/PersonalAssistantState";
import { usePersonalAssistant } from "../personalAssistant/usePersonalAssistant";
import styles from "../personalAssistant/PersonalAssistant.styles";
import { WhaleRigCharacter } from "./WhaleRigCharacter";
import { openSessionFromDesktopPet, petActivityRefetchInterval, petToneLabel } from "./desktopPetModel";

export function DesktopAssistantRoute() {
  const context = useQuery({ queryKey: ["desktop-assistant", "native-context"], queryFn: getDesktopAssistantContext,
    retry: false, staleTime: Infinity });
  const state = usePersonalAssistant(context.isSuccess);
  const activity = useQuery({ queryKey: queryKeys.petActivity(), queryFn: fetchPetActivity,
    enabled: context.isSuccess, refetchInterval: query => petActivityRefetchInterval(query.state.data),
    refetchIntervalInBackground: false, retry: false });
  const platformActivity = activity.isError ? undefined : activity.data;
  const activityLabel = activity.isError ? "暂时无法读取平台状态"
    : platformActivity ? petToneLabel(platformActivity.aggregateTone, "zh") : "正在读取平台状态…";
  const [expanded, setExpanded] = useState(false);
  const [pending, setPending] = useState(false);
  const [feedback, setFeedback] = useState("");
  const nativeWorkspace = useMemo(() => <ChatCodingRoute />, []);
  useEffect(() => {
    document.documentElement.dataset.vibelutionDesktopPet = "true";
    document.body.dataset.vibelutionDesktopPet = "true";
    return () => { delete document.documentElement.dataset.vibelutionDesktopPet; delete document.body.dataset.vibelutionDesktopPet; };
  }, []);
  async function toggle() {
    if (pending || !context.isSuccess) return;
    setPending(true); setFeedback("");
    try { await setDesktopPetExpanded(!expanded); setExpanded(value => !value); }
    catch (error) { setFeedback(error instanceof Error ? error.message : "桌面窗口调整失败。"); }
    finally { setPending(false); }
  }
  async function returnToWorkbench(sessionId: string) {
    const opened = await openSessionFromDesktopPet(sessionId);
    if (!opened) setFeedback("未能返回工作台，请稍后重试。");
  }
  if (context.isError) return <VStateSurface fill tone="error" title="桌面助理无法启用"
    actions={<><VButton onClick={() => void context.refetch()}>重试</VButton><VButton variant="secondary" onClick={() => window.close()}>关闭窗口</VButton></>}>{context.error.message}</VStateSurface>;
  return <div className={`${styles.desktop} ${expanded ? styles.desktopExpanded : styles.desktopCollapsed}`}
    data-vui-domain-recipe="desktop-assistant" data-expanded={expanded}>
    {expanded ? <>
      <header className={styles.desktopHeader}><h1 className={styles.title}>大肥鲸 · {state.assistant?.displayName || "个人助理"}</h1>
        <div className={styles.actions}><VIconButton label="返回工作台" icon={<ExternalLink size={14} />} isDisabled={!state.verified}
          onClick={() => { if (state.assistant) void returnToWorkbench(state.assistant.directSessionId); }} />
          <VIconButton label="收起个人助理" icon={<ChevronDown size={14} />} isDisabled={pending} onClick={() => void toggle()} />
          <VIconButton label="关闭桌面助理" icon={<X size={14} />} onClick={() => window.close()} /></div>
      </header>
      <VSplitWorkspace className={styles.split} chrome="workbench" resize={{ layoutId: WORKBENCH_LAYOUT_IDS.desktopAssistant,
        aside: { defaultWidth: 220, minWidth: 180, maxWidth: 300 },
        collapse: { aside: { separatorLabel: "调整平台概览宽度", collapseLabel: "收起平台概览", expandLabel: "展开平台概览" } } }}
        main={<div className={styles.main}>{state.verified ? nativeWorkspace : <PersonalAssistantState state={state} />}</div>}
        aside={state.verified ? <PersonalAssistantOverview desktop onOpenSession={id => void returnToWorkbench(id)} /> : undefined} />
    </> : <>
      <div className={styles.collapsedHeader}>
        <span className={styles.caption} role="status">{context.isPending ? "正在确认窗口身份…" : activityLabel}</span>
        <VIconButton className={styles.noDrag} label="关闭桌面助理" icon={<X size={14} />} onClick={() => window.close()} />
      </div>
      <div className={styles.whale}><VButton className={styles.whaleButton} variant="ghost" isDisabled={!context.isSuccess || pending}
        aria-label="展开个人助理聊天" onClick={() => void toggle()}>
        <WhaleRigCharacter name="大肥鲸" tone={platformActivity?.aggregateTone ?? "idle"} animationState={platformActivity?.animationState ?? "idle"} />
      </VButton></div>
      <VButton variant="secondary" isDisabled={!context.isSuccess || pending} onClick={() => void toggle()}>聊一聊</VButton>
    </>}
    {feedback ? <p className={styles.error} role="alert">{feedback}</p> : null}
  </div>;
}
