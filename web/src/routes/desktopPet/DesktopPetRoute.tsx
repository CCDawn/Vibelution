import "../../design/route-css/desktop-pet.tailwind.css";

import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronUp, X } from "lucide-react";
import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";

import { fetchPetActivity } from "../../api/pet";
import { queryKeys } from "../../api/queryKeys";
import type { PetActivity } from "../../api/types/petActivity";
import { VIconButton, VNativeButton } from "../../components/vui";
import { useShellI18n } from "../../i18n/useShellI18n";
import { DesktopPetCharacter } from "./DesktopPetCharacter";
import styles from "./DesktopPetRoute.styles";
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
    name: "小洛",
    sessions: "实时对话",
    empty: "现在没有运行中的对话",
    open: "展开实时对话",
    collapse: "收起实时对话",
    close: "关闭桌面伙伴",
    unavailable: "暂时无法读取对话状态",
  },
  en: {
    name: "Xiao Luo",
    sessions: "Live conversations",
    empty: "No conversations are running",
    open: "Show live conversations",
    collapse: "Hide live conversations",
    close: "Close desktop companion",
    unavailable: "Conversation status is unavailable",
  },
} as const;

export function DesktopPetRoute() {
  const { lang } = useShellI18n();
  const copy = COPY[lang];
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
    if (await openSessionFromDesktopPet(sessionId)) {
      setExpanded(false);
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
    setExpanded((value) => !value);
  }

  const visibleSessions = activity.sessions.slice(0, 5);
  const statusText = activityQuery.isError
    ? copy.unavailable
    : petToneLabel(activity.aggregateTone, lang);

  return (
    <main
      className={styles.root}
      data-desktop-pet-root="true"
      data-vui-domain-recipe="desktop-pet"
      data-tone={activity.aggregateTone}
      data-dragging={dragging ? "true" : "false"}
      aria-label={copy.name}
    >
      <div className={styles.stage}>
        <div className={styles.toolbar}>
          <span className={styles.status} role="status" aria-live="polite">
            <span className={styles.statusDot} aria-hidden="true" />
            {statusText}
          </span>
          <VIconButton
            label={copy.close}
            icon={<X size={14} aria-hidden="true" />}
            variant="ghost"
            className={styles.close}
            onPress={() => window.close()}
          />
        </div>

        {expanded ? (
          <section className={styles.hud} aria-label={copy.sessions}>
            <header className={styles.hudHeader}>
              <strong>{copy.sessions}</strong>
              <span>{activity.activeCount}</span>
            </header>
            <div className={styles.hudList}>
              {visibleSessions.length > 0 ? visibleSessions.map((session) => (
                <VNativeButton
                  key={session.sessionId}
                  className={styles.session}
                  data-tone={session.tone}
                  onClick={() => void openSession(session.sessionId)}
                >
                  <span className={styles.sessionMarker} aria-hidden="true" />
                  <span className={styles.sessionCopy}>
                    <strong>{session.title}</strong>
                    <span>
                      {session.agentDisplayName ? `${session.agentDisplayName} · ` : ""}
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
            name={copy.name}
            tone={activity.aggregateTone}
            animationState={activity.animationState}
          />
          <span className={styles.expandCue} aria-hidden="true">
            {expanded ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
          </span>
        </VNativeButton>
      </div>
    </main>
  );
}
