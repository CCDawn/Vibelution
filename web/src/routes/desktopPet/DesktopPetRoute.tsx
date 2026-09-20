import "../../design/route-css/desktop-pet.tailwind.css";

import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronUp, RefreshCw, Settings, X } from "lucide-react";
import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";

import { fetchPetActivity } from "../../api/pet";
import { queryKeys } from "../../api/queryKeys";
import type { PetActivity } from "../../api/types/petActivity";
import { VCheckbox, VIconButton, VInput, VNativeButton } from "../../components/vui";
import { useShellI18n } from "../../i18n/useShellI18n";
import { DesktopPetCharacter } from "./DesktopPetCharacter";
import {
  nextDesktopPetCharacter,
  type DesktopPetCharacterId,
} from "./desktopPetCharacterModel";
import styles from "./DesktopPetRoute.styles";
import { readPetPreferences, savePetPreferences, type DesktopPetPreferences } from "./desktopPetPreferences";
import {
  openSessionFromDesktopPet,
  petActivityRefetchInterval,
  petPhaseLabel,
  petToneLabel,
} from "./desktopPetModel";
import {
  beginDesktopPetDrag,
  desktopPetWindowDragBridge,
  updateDesktopPetDrag,
  type DesktopPetDragPoint,
  type DesktopPetDragState,
  type DesktopPetWindowDragBridge,
} from "./desktopPetWindowDrag";

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
    sessions: "实时对话",
    empty: "现在没有运行中的对话",
    open: "展开实时对话",
    collapse: "收起实时对话",
    close: "关闭桌面伙伴",
    unavailable: "暂时无法读取对话状态",
    settings: "桌宠设置",
    showStatus: "显示状态提示",
    showTitles: "显示会话标题",
    showCompletion: "显示完成提示和庆祝动作",
    idleMessage: "空闲提示语",
    idleHint: "留空使用默认提示",
    saveFailed: "设置仅本次生效：无法保存到本机",
    openFailed: "未能打开对话，请稍后重试",
    anonymous: "会话",
  },
  en: {
    names: { xiaoluo: "Xiao Luo", dafeiyu: "DeepSeek Whale" },
    switchTo: { xiaoluo: "Switch to Xiao Luo", dafeiyu: "Switch to DeepSeek Whale" },
    sessions: "Live conversations",
    empty: "No conversations are running",
    open: "Show live conversations",
    collapse: "Hide live conversations",
    close: "Close desktop companion",
    unavailable: "Conversation status is unavailable",
    settings: "Pet settings",
    showStatus: "Show status",
    showTitles: "Show conversation titles",
    showCompletion: "Show completion and celebration",
    idleMessage: "Idle message",
    idleHint: "Leave blank for the default",
    saveFailed: "Settings apply this time only: local storage unavailable",
    openFailed: "Could not open the conversation. Try again.",
    anonymous: "Conversation",
  },
} as const;

export function DesktopPetRoute() {
  const { lang } = useShellI18n();
  const copy = COPY[lang];
  const [preferences, setPreferences] = useState(readPetPreferences);
  const characterId = preferences.characterId;
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [feedback, setFeedback] = useState("");
  const [expanded, setExpanded] = useState(false);
  const [dragging, setDragging] = useState(false);
  const dragStateRef = useRef<DesktopPetDragState | null>(null);
  const dragBridgeRef = useRef<DesktopPetWindowDragBridge | null>(desktopPetWindowDragBridge());
  const pendingDragPointRef = useRef<DesktopPetDragPoint | null>(null);
  const dragFrameRef = useRef<number | null>(null);
  const nativeDragActiveRef = useRef(false);
  const suppressClickRef = useRef(false);
  const activityQuery = useQuery({
    queryKey: queryKeys.petActivity(),
    queryFn: fetchPetActivity,
    refetchInterval: (query) => petActivityRefetchInterval(query.state.data),
    retry: 1,
  });
  const activity = activityQuery.data ?? EMPTY_ACTIVITY;

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

  async function openSession(sessionId: string) {
    setFeedback("");
    if (await openSessionFromDesktopPet(sessionId)) {
      setExpanded(false);
    } else {
      setFeedback(copy.openFailed);
    }
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

  function toggleExpanded() {
    if (suppressClickRef.current) {
      suppressClickRef.current = false;
      return;
    }
    setSettingsOpen(false);
    setExpanded((value) => !value);
  }

  function updatePreferences(patch: Partial<DesktopPetPreferences>) {
    const next = { ...preferences, ...patch };
    setPreferences(next);
    setFeedback(savePetPreferences(next) ? "" : copy.saveFailed);
  }

  function setCharacterId(next: DesktopPetCharacterId) {
    updatePreferences({ characterId: next });
  }

  function switchCharacter() {
    setCharacterId(nextDesktopPetCharacter(characterId));
  }

  const visibleSessions = activity.sessions.filter((session) => preferences.showCompletion || session.tone !== "completed");
  const tone = activityQuery.isError ? "idle"
    : activity.aggregateTone === "completed" && !preferences.showCompletion ? "idle" : activity.aggregateTone;
  const animationState = activityQuery.isError || (activity.aggregateTone === "completed" && !preferences.showCompletion)
    ? "idle" : activity.animationState;
  const statusText = activityQuery.isError
    ? copy.unavailable
    : tone === "idle" && preferences.idleMessage.trim() ? preferences.idleMessage : petToneLabel(tone, lang);
  const characterName = copy.names[characterId];
  const nextCharacterId = nextDesktopPetCharacter(characterId);

  return (
    <main
      className={styles.root}
      data-desktop-pet-root="true"
      data-vui-domain-recipe="desktop-pet"
      data-tone={tone}
      data-dragging={dragging ? "true" : "false"}
      aria-label={characterName}
    >
      <div className={styles.stage}>
        <div className={styles.toolbar}>
          {preferences.showStatus || activityQuery.isError ? <span className={styles.status} role="status" aria-live="polite">
            <span className={styles.statusDot} aria-hidden="true" />
            {statusText}
          </span> : <span />}
          <div className={styles.toolbarActions}>
            <VIconButton
              label={copy.settings}
              icon={<Settings size={14} aria-hidden="true" />}
              variant="ghost"
              className={styles.switchCharacter}
              aria-expanded={settingsOpen}
              onPress={() => { setSettingsOpen((value) => !value); setExpanded(false); }}
            />
            <VIconButton
              label={copy.switchTo[nextCharacterId]}
              icon={<RefreshCw size={14} aria-hidden="true" />}
              variant="ghost"
              className={styles.switchCharacter}
              onPress={switchCharacter}
            />
            <VIconButton
              label={copy.close}
              icon={<X size={14} aria-hidden="true" />}
              variant="ghost"
              className={styles.close}
              onPress={() => window.close()}
            />
          </div>
        </div>

        {settingsOpen ? (
          <section className={styles.hud} aria-label={copy.settings}>
            <header className={styles.hudHeader}><strong>{copy.settings}</strong></header>
            <div className={styles.hudList}>
              <VCheckbox isSelected={preferences.showStatus} onChange={(showStatus) => updatePreferences({ showStatus })}><span className="text-white">{copy.showStatus}</span></VCheckbox>
              <VCheckbox isSelected={preferences.showTitles} onChange={(showTitles) => updatePreferences({ showTitles })}><span className="text-white">{copy.showTitles}</span></VCheckbox>
              <VCheckbox isSelected={preferences.showCompletion} onChange={(showCompletion) => updatePreferences({ showCompletion })}><span className="text-white">{copy.showCompletion}</span></VCheckbox>
              <label>
                {copy.idleMessage}
                <VInput value={preferences.idleMessage} maxLength={48} placeholder={copy.idleHint}
                  onChange={(event) => updatePreferences({ idleMessage: event.target.value })} />
              </label>
              {feedback ? <p role="status" className={styles.hudEmpty}>{feedback}</p> : null}
            </div>
          </section>
        ) : expanded ? (
          <section className={styles.hud} aria-label={copy.sessions}>
            <header className={styles.hudHeader}>
              <strong>{copy.sessions}</strong>
              <span>{activity.activeCount}</span>
            </header>
            <div className={styles.hudList}>
              {feedback ? <p role="status" className={styles.hudEmpty}>{feedback}</p> : null}
              {activityQuery.isError ? <p role="status" className={styles.hudEmpty}>{copy.unavailable}</p> : null}
              {visibleSessions.length > 0 ? visibleSessions.map((session, index) => (
                <VNativeButton
                  key={session.sessionId}
                  className={styles.session}
                  data-tone={session.tone}
                  onClick={() => void openSession(session.sessionId)}
                >
                  <span className={styles.sessionMarker} aria-hidden="true" />
                  <span className={styles.sessionCopy}>
                    <strong>{preferences.showTitles ? session.title : `${copy.anonymous} ${index + 1}`}</strong>
                    <span>
                      {preferences.showTitles && session.agentDisplayName ? `${session.agentDisplayName} · ` : ""}
                      {petPhaseLabel(session.phase, lang)}
                    </span>
                  </span>
                </VNativeButton>
              )) : (
                <p className={styles.hudEmpty}>{copy.empty}</p>
              )}
            </div>
          </section>
        ) : null}

        <VNativeButton
          className={styles.characterButton}
          aria-expanded={expanded}
          aria-label={expanded ? copy.collapse : copy.open}
          onClick={toggleExpanded}
          onPointerDown={beginCharacterDrag}
          onPointerMove={moveCharacterDrag}
          onPointerUp={endCharacterDrag}
          onPointerCancel={cancelCharacterDrag}
        >
          <DesktopPetCharacter
            characterId={characterId}
            name={characterName}
            tone={tone}
            animationState={animationState}
          />
          <span className={styles.expandCue} aria-hidden="true">
            {expanded ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
          </span>
        </VNativeButton>
      </div>
    </main>
  );
}
