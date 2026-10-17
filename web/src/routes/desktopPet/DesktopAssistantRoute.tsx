import "../../design/route-css/desktop-pet.tailwind.css";
import "../personalAssistant/personal-assistant.tailwind.css";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ExternalLink, MessageCircle, RefreshCw, Settings, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { getDesktopAssistantContext, setDesktopPetExpanded } from "../../api/desktopPet";
import { fetchPetActivity } from "../../api/pet";
import { queryKeys } from "../../api/queryKeys";
import type { PetActivity } from "../../api/types/petActivity";
import { WORKBENCH_LAYOUT_IDS } from "../../components/layout/workbenchLayoutIds";
import { VButton, VCheckbox, VIconButton, VInput, VNativeButton, VSplitWorkspace, VStateSurface } from "../../components/vui";
import { useShellI18n } from "../../i18n/useShellI18n";
import { ChatCodingRoute } from "../ChatCodingRoute";
import { PersonalAssistantOverview } from "../personalAssistant/PersonalAssistantOverview";
import { PersonalAssistantState } from "../personalAssistant/PersonalAssistantState";
import { usePersonalAssistant } from "../personalAssistant/usePersonalAssistant";
import styles from "../personalAssistant/PersonalAssistant.styles";
import { DesktopPetCharacter } from "./DesktopPetCharacter";
import { nextDesktopPetCharacter } from "./desktopPetCharacterModel";
import { readPetPreferences, savePetPreferences, type DesktopPetPreferences } from "./desktopPetPreferences";
import { openSessionFromDesktopPet, petActivityRefetchInterval, petPhaseLabel, petToneLabel } from "./desktopPetModel";
import {
  beginDesktopPetDrag,
  desktopPetWindowDragBridge,
  updateDesktopPetDrag,
  type DesktopPetDragPoint,
  type DesktopPetDragState,
  type DesktopPetWindowDragBridge,
} from "./desktopPetWindowDrag";
import petStyles from "./DesktopAssistantRoute.styles";

const EMPTY_ACTIVITY: PetActivity = {
  schemaVersion: 1,
  aggregateTone: "idle",
  animationState: "idle",
  activeCount: 0,
  attentionCount: 0,
  generatedAt: "",
  sessions: [],
};

const COPY = {
  zh: {
    names: { xiaoluo: "小洛", dafeiyu: "DeepSeek 大肥鲸" },
    switchTo: { xiaoluo: "切换到小洛", dafeiyu: "切换到大肥鲸" },
    settings: "助理设置",
    showStatus: "显示状态提示",
    showTitles: "显示会话标题",
    showCompletion: "显示完成提示和庆祝动作",
    idleMessage: "空闲提示语",
    idleHint: "留空使用默认提示",
    saveFailed: "设置仅本次生效：无法保存到本机",
    chat: "聊一聊",
    expand: "展开个人助理聊天",
    collapse: "收起个人助理聊天",
    sessions: "实时对话",
    empty: "现在没有运行中的对话",
    unavailable: "暂时无法读取平台状态",
    openFailed: "未能返回工作台，请稍后重试",
    anonymous: "会话",
    returnToWorkbench: "返回工作台",
    close: "关闭个人助理",
    titleFallback: "个人助理",
    checkingIdentity: "正在确认窗口身份…",
    readingStatus: "正在读取平台状态…",
    expandFailed: "窗口调整失败。",
    enableFailed: "个人助理无法启用",
    retry: "重试",
    closeWindow: "关闭窗口",
    overviewSeparator: "调整平台概览宽度",
    overviewCollapse: "收起平台概览",
    overviewExpand: "展开平台概览",
  },
  en: {
    names: { xiaoluo: "Xiao Luo", dafeiyu: "DeepSeek Whale" },
    switchTo: { xiaoluo: "Switch to Xiao Luo", dafeiyu: "Switch to the whale" },
    settings: "Assistant settings",
    showStatus: "Show status",
    showTitles: "Show conversation titles",
    showCompletion: "Show completion and celebration",
    idleMessage: "Idle message",
    idleHint: "Leave blank for the default",
    saveFailed: "Settings apply this time only: local storage unavailable",
    chat: "Chat",
    expand: "Open the assistant chat",
    collapse: "Collapse the assistant chat",
    sessions: "Live conversations",
    empty: "No conversations are running",
    unavailable: "Platform status is unavailable",
    openFailed: "Could not return to the workbench. Try again.",
    anonymous: "Conversation",
    returnToWorkbench: "Return to workbench",
    close: "Close the personal assistant",
    titleFallback: "Personal assistant",
    checkingIdentity: "Verifying this window…",
    readingStatus: "Reading platform status…",
    expandFailed: "Could not resize the window.",
    enableFailed: "The personal assistant cannot start",
    retry: "Retry",
    closeWindow: "Close window",
    overviewSeparator: "Resize the overview",
    overviewCollapse: "Collapse the overview",
    overviewExpand: "Expand the overview",
  },
} as const;

/**
 * The single floating personal-assistant window. The collapsed body and the
 * expanded chat are the same assistant (one Agent, one native Session); the
 * visible character (whale rig or Xiao Luo Live2D) is a pure appearance
 * preference stored in the shared desktop-pet preferences.
 */
export function DesktopAssistantRoute() {
  const { lang } = useShellI18n();
  const copy = COPY[lang];
  const context = useQuery({ queryKey: ["desktop-assistant", "native-context"], queryFn: getDesktopAssistantContext,
    retry: false, staleTime: Infinity });
  const state = usePersonalAssistant(context.isSuccess);
  const activityQuery = useQuery({ queryKey: queryKeys.petActivity(), queryFn: fetchPetActivity,
    enabled: context.isSuccess, refetchInterval: query => petActivityRefetchInterval(query.state.data),
    refetchIntervalInBackground: false, retry: false });
  const activity = activityQuery.data ?? EMPTY_ACTIVITY;
  const [expanded, setExpanded] = useState(false);
  const [pending, setPending] = useState(false);
  const [feedback, setFeedback] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [preferences, setPreferences] = useState(readPetPreferences);
  const characterId = preferences.characterId;
  const dragStateRef = useRef<DesktopPetDragState | null>(null);
  const dragBridgeRef = useRef<DesktopPetWindowDragBridge | null>(desktopPetWindowDragBridge());
  const pendingDragPointRef = useRef<DesktopPetDragPoint | null>(null);
  const dragFrameRef = useRef<number | null>(null);
  const nativeDragActiveRef = useRef(false);
  const suppressClickRef = useRef(false);
  const nativeWorkspace = useMemo(() => <ChatCodingRoute />, []);
  useEffect(() => {
    document.documentElement.dataset.vibelutionDesktopPet = "true";
    document.body.dataset.vibelutionDesktopPet = "true";
    return () => {
      finishWindowDrag();
      delete document.documentElement.dataset.vibelutionDesktopPet;
      delete document.body.dataset.vibelutionDesktopPet;
    };
  }, []);

  function flushWindowDrag() {
    dragFrameRef.current = null;
    const point = pendingDragPointRef.current;
    pendingDragPointRef.current = null;
    if (point !== null && nativeDragActiveRef.current) {
      dragBridgeRef.current?.moveDesktopPetWindowDrag(point);
    }
  }

  function queueWindowDrag(point: DesktopPetDragPoint) {
    pendingDragPointRef.current = point;
    if (dragFrameRef.current === null) {
      dragFrameRef.current = window.requestAnimationFrame(flushWindowDrag);
    }
  }

  function finishWindowDrag(finalPoint?: DesktopPetDragPoint) {
    if (finalPoint) {
      pendingDragPointRef.current = finalPoint;
    }
    if (dragFrameRef.current !== null) {
      window.cancelAnimationFrame(dragFrameRef.current);
      dragFrameRef.current = null;
    }
    flushWindowDrag();
    if (nativeDragActiveRef.current) {
      dragBridgeRef.current?.endDesktopPetWindowDrag();
      nativeDragActiveRef.current = false;
    }
  }

  async function toggle() {
    if (pending || !context.isSuccess) return;
    setPending(true);
    setFeedback("");
    try { await setDesktopPetExpanded(!expanded); setExpanded(value => !value); }
    catch (error) { setFeedback(error instanceof Error ? error.message : copy.expandFailed); }
    finally { setPending(false); }
  }

  async function openSession(sessionId: string) {
    setFeedback("");
    if (await openSessionFromDesktopPet(sessionId)) return;
    setFeedback(copy.openFailed);
  }

  function updatePreferences(patch: Partial<DesktopPetPreferences>) {
    const next = { ...preferences, ...patch };
    setPreferences(next);
    setFeedback(savePetPreferences(next) ? "" : copy.saveFailed);
  }

  function beginCharacterDrag(event: ReactPointerEvent<HTMLButtonElement>) {
    if (event.button !== 0) {
      return;
    }
    suppressClickRef.current = false;
    dragStateRef.current = beginDesktopPetDrag(event.pointerId, {
      screenX: event.screenX,
      screenY: event.screenY,
    });
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function moveCharacterDrag(event: ReactPointerEvent<HTMLButtonElement>) {
    const current = dragStateRef.current;
    if (current === null) {
      return;
    }
    const update = updateDesktopPetDrag(current, event.pointerId, {
      screenX: event.screenX,
      screenY: event.screenY,
    });
    if (update === null) {
      return;
    }
    dragStateRef.current = update.state;
    if (!current.moved && update.state.moved) {
      suppressClickRef.current = true;
      setDragging(true);
    }
    if (update.delta !== null) {
      event.preventDefault();
      const bridge = dragBridgeRef.current;
      if (!nativeDragActiveRef.current && bridge !== null) {
        bridge.beginDesktopPetWindowDrag(current.start);
        nativeDragActiveRef.current = true;
      }
      if (nativeDragActiveRef.current) {
        queueWindowDrag({ screenX: event.screenX, screenY: event.screenY });
      }
    }
  }

  function endCharacterDrag(event: ReactPointerEvent<HTMLButtonElement>) {
    const current = dragStateRef.current;
    if (current === null || current.pointerId !== event.pointerId) {
      return;
    }
    dragStateRef.current = null;
    finishWindowDrag({ screenX: event.screenX, screenY: event.screenY });
    setDragging(false);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  }

  function cancelCharacterDrag(event: ReactPointerEvent<HTMLButtonElement>) {
    endCharacterDrag(event);
    suppressClickRef.current = false;
  }

  function toggleFromBody() {
    if (suppressClickRef.current) {
      suppressClickRef.current = false;
      return;
    }
    setSettingsOpen(false);
    void toggle();
  }

  const visibleSessions = activity.sessions.filter((session) => preferences.showCompletion || session.tone !== "completed");
  const tone = activityQuery.isError ? "idle"
    : activity.aggregateTone === "completed" && !preferences.showCompletion ? "idle" : activity.aggregateTone;
  const animationState = activityQuery.isError || (activity.aggregateTone === "completed" && !preferences.showCompletion)
    ? "idle" : activity.animationState;
  const statusText = activityQuery.isError ? copy.unavailable
    : tone === "idle" && preferences.idleMessage.trim() ? preferences.idleMessage : petToneLabel(tone, lang);
  const appearanceName = copy.names[characterId];
  const nextCharacterId = nextDesktopPetCharacter(characterId);

  if (context.isError) return <VStateSurface fill tone="error" title={copy.enableFailed}
    actions={<><VButton onClick={() => void context.refetch()}>{copy.retry}</VButton><VButton variant="secondary" onClick={() => window.close()}>{copy.closeWindow}</VButton></>}>{context.error.message}</VStateSurface>;
  if (!expanded) return <main
    className={petStyles.root}
    data-vui-domain-recipe="desktop-assistant"
    data-expanded="false"
    data-tone={tone}
    data-dragging={dragging ? "true" : "false"}
    aria-label={state.assistant?.displayName || copy.titleFallback}
  >
    <div className={petStyles.stage}>
      <div className={petStyles.toolbar}>
        {preferences.showStatus || activityQuery.isError || feedback ? <span className={petStyles.status} role="status" aria-live="polite">
          <span className={petStyles.statusDot} aria-hidden="true" />
          {feedback || (context.isPending ? copy.checkingIdentity
            : activityQuery.isError ? copy.unavailable
              : activityQuery.data ? statusText : copy.readingStatus)}
        </span> : <span />}
        <div className={petStyles.toolbarActions}>
          <VIconButton
            label={copy.settings}
            icon={<Settings size={14} aria-hidden="true" />}
            variant="ghost"
            className={petStyles.switchAppearance}
            aria-expanded={settingsOpen}
            onPress={() => { setSettingsOpen((value) => !value); setFeedback(""); }}
          />
          <VIconButton
            label={copy.switchTo[nextCharacterId]}
            icon={<RefreshCw size={14} aria-hidden="true" />}
            variant="ghost"
            className={petStyles.switchAppearance}
            onPress={() => updatePreferences({ characterId: nextCharacterId })}
          />
          <VIconButton
            label={copy.close}
            icon={<X size={14} aria-hidden="true" />}
            variant="ghost"
            className={petStyles.close}
            onPress={() => window.close()}
          />
        </div>
      </div>

      {settingsOpen ? (
        <section className={petStyles.hud} aria-label={copy.settings}>
          <header className={petStyles.hudHeader}><strong>{copy.settings}</strong></header>
          <div className={petStyles.hudList}>
            <VCheckbox isSelected={preferences.showStatus} onChange={(showStatus) => updatePreferences({ showStatus })}><span className={petStyles.settingsLabel}>{copy.showStatus}</span></VCheckbox>
            <VCheckbox isSelected={preferences.showTitles} onChange={(showTitles) => updatePreferences({ showTitles })}><span className={petStyles.settingsLabel}>{copy.showTitles}</span></VCheckbox>
            <VCheckbox isSelected={preferences.showCompletion} onChange={(showCompletion) => updatePreferences({ showCompletion })}><span className={petStyles.settingsLabel}>{copy.showCompletion}</span></VCheckbox>
            <label>
              {copy.idleMessage}
              <VInput value={preferences.idleMessage} maxLength={48} placeholder={copy.idleHint}
                onChange={(event) => updatePreferences({ idleMessage: event.target.value })} />
            </label>
            {feedback ? <p role="status" className={petStyles.hudEmpty}>{feedback}</p> : null}
          </div>
        </section>
      ) : null}

      <VNativeButton
        className={petStyles.characterButton}
        aria-label={copy.expand}
        onClick={toggleFromBody}
        onPointerDown={beginCharacterDrag}
        onPointerMove={moveCharacterDrag}
        onPointerUp={endCharacterDrag}
        onPointerCancel={cancelCharacterDrag}
      >
        <DesktopPetCharacter
          characterId={characterId}
          name={appearanceName}
          tone={tone}
          animationState={animationState}
        />
      </VNativeButton>
      <VNativeButton className={petStyles.chatCue} aria-label={copy.expand} onClick={() => void toggle()}>
        <MessageCircle size={13} aria-hidden="true" />
        {copy.chat}
      </VNativeButton>
    </div>
  </main>;
  return <div className={`${styles.desktop} ${styles.desktopExpanded}`}
    data-vui-domain-recipe="desktop-assistant" data-expanded="true">
    <header className={styles.desktopHeader}><h1 className={styles.title}>{state.assistant?.displayName || copy.titleFallback}</h1>
      <div className={styles.actions}><VIconButton label={copy.returnToWorkbench} icon={<ExternalLink size={14} />} isDisabled={!state.verified}
        onClick={() => { if (state.assistant) void openSession(state.assistant.directSessionId); }} />
        <VIconButton label={copy.collapse} icon={<ChevronDown size={14} />} isDisabled={pending} onClick={() => void toggle()} />
        <VIconButton label={copy.close} icon={<X size={14} />} onClick={() => window.close()} /></div>
    </header>
    <VSplitWorkspace className={styles.split} chrome="workbench" resize={{ layoutId: WORKBENCH_LAYOUT_IDS.desktopAssistant,
      aside: { defaultWidth: 220, minWidth: 180, maxWidth: 300 },
      collapse: { aside: { separatorLabel: copy.overviewSeparator, collapseLabel: copy.overviewCollapse, expandLabel: copy.overviewExpand } } }}
      main={<div className={styles.main}>{state.verified ? nativeWorkspace : <PersonalAssistantState state={state} />}</div>}
      aside={state.verified ? <aside className={styles.asideColumn}>
        <section className={styles.sessions} aria-label={copy.sessions}>
          <h2 className={styles.sessionsHeader}>{copy.sessions}<span className={styles.sessionsCount}>{activity.activeCount}</span></h2>
          <div className={styles.sessionsList}>
            {activityQuery.isError ? <p role="status" className={styles.sessionsEmpty}>{copy.unavailable}</p> : null}
            {visibleSessions.length > 0 ? visibleSessions.map((session, index) => (
              <VNativeButton
                key={session.sessionId}
                className={styles.sessionRow}
                data-tone={session.tone}
                onClick={() => void openSession(session.sessionId)}
              >
                <span className={styles.sessionMarker} data-tone={session.tone} aria-hidden="true" />
                <span className={styles.sessionCopy}>
                  <strong className={styles.sessionTitle}>{preferences.showTitles ? session.title : `${copy.anonymous} ${index + 1}`}</strong>
                  <span className={styles.sessionMeta}>
                    {preferences.showTitles && session.agentDisplayName ? `${session.agentDisplayName} · ` : ""}
                    {petPhaseLabel(session.phase, lang)}
                  </span>
                </span>
              </VNativeButton>
            )) : !activityQuery.isError ? <p className={styles.sessionsEmpty}>{copy.empty}</p> : null}
          </div>
        </section>
        <div className={styles.overviewFill}>
          <PersonalAssistantOverview desktop showTitles={preferences.showTitles} onOpenSession={id => void openSession(id)} />
        </div>
      </aside> : undefined} />
    {feedback ? <p className={styles.error} role="alert">{feedback}</p> : null}
  </div>;
}
