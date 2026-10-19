import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { CircleAlert, X } from "lucide-react";
import { VIconButton, VNativeButton } from "../../components/vui";
import { useShellI18n } from "../../i18n/useShellI18n";
import {
  humanAttentionBridge,
  humanAttentionTargetFor,
  subscribeHumanAttentionEvents,
  type HumanAttentionNotificationPayload,
} from "../personalAssistant/humanAttentionNotifications";
import styles from "./HumanAttentionNoticeStack.styles";

const DISMISS_AFTER_MS = 12_000;
const MAX_STACKED_CARDS = 3;

const COPY = {
  zh: {
    region: "人工注意通知",
    close: "关闭通知",
    open: "查看该事项",
    fallbackTitle: "需要你的关注",
    kinds: { knowledge_review: "知识复核", anomaly: "研究异常", affair_reminder: "事务提醒" },
  },
  en: {
    region: "Attention notifications",
    close: "Dismiss notification",
    open: "Open the related item",
    fallbackTitle: "Needs your attention",
    kinds: { knowledge_review: "Knowledge review", anomaly: "Anomaly", affair_reminder: "Affair" },
  },
} as const;

type NoticeCard = {
  key: string;
  payload: HumanAttentionNotificationPayload;
};

/**
 * In-window notice cards for dual-channel human-attention notifications.
 * The Electron shell delivers assistant-window notifications through the
 * preload subscription (`launcher:human-attention-opened` channel exposed as
 * `onHumanAttentionOpened`); full payloads become stacked cards (title, body,
 * severity styling, click-to-locate, 12s auto-dismiss with hover pause, max
 * 3), bare opened clicks navigate immediately.
 */
export function HumanAttentionNoticeStack({ onBeforeNavigate }: {
  /** Called before an in-window navigation (e.g. expand the collapsed pet). */
  onBeforeNavigate?: () => void | Promise<void>;
}) {
  const { lang } = useShellI18n();
  const copy = COPY[lang];
  const navigate = useNavigate();
  const [cards, setCards] = useState<NoticeCard[]>([]);
  const sequence = useRef(0);
  const timers = useRef(new Map<string, number>());
  const beforeNavigateRef = useRef(onBeforeNavigate);
  beforeNavigateRef.current = onBeforeNavigate;
  const navigateRef = useRef(navigate);
  navigateRef.current = navigate;

  const clearDismissTimer = useCallback((key: string) => {
    const handle = timers.current.get(key);
    if (handle !== undefined) {
      window.clearTimeout(handle);
      timers.current.delete(key);
    }
  }, []);

  const dismissCard = useCallback((key: string) => {
    clearDismissTimer(key);
    setCards(previous => previous.filter(card => card.key !== key));
  }, [clearDismissTimer]);

  const scheduleDismiss = useCallback((key: string) => {
    clearDismissTimer(key);
    timers.current.set(key, window.setTimeout(() => dismissCard(key), DISMISS_AFTER_MS));
  }, [clearDismissTimer, dismissCard]);

  const openTarget = useCallback(async (target: string) => {
    try {
      await beforeNavigateRef.current?.();
    } catch {
      // Expansion failure must not block locating the attention item.
    }
    navigateRef.current(target);
  }, []);

  const openCard = useCallback((card: NoticeCard) => {
    const target = humanAttentionTargetFor(card.payload);
    dismissCard(card.key);
    if (target) {
      void openTarget(target);
    }
  }, [dismissCard, openTarget]);

  useEffect(() => {
    return subscribeHumanAttentionEvents(humanAttentionBridge(), event => {
      if (event.type === "opened") {
        const target = humanAttentionTargetFor(event.payload);
        if (target) {
          void openTarget(target);
        }
        return;
      }
      const payload = event.payload;
      setCards(previous => {
        const key = `${payload.id}:${++sequence.current}`;
        return [{ key, payload }, ...previous.filter(card => card.payload.id !== payload.id)].slice(0, MAX_STACKED_CARDS);
      });
    });
  }, [openTarget]);

  // Schedule auto-dismiss for new cards and drop timers of removed cards.
  useEffect(() => {
    for (const card of cards) {
      if (!timers.current.has(card.key)) {
        scheduleDismiss(card.key);
      }
    }
    for (const key of [...timers.current.keys()]) {
      if (!cards.some(card => card.key === key)) {
        clearDismissTimer(key);
      }
    }
  }, [cards, scheduleDismiss, clearDismissTimer]);

  useEffect(() => {
    const pending = timers.current;
    return () => {
      for (const handle of pending.values()) {
        window.clearTimeout(handle);
      }
      pending.clear();
    };
  }, []);

  if (cards.length === 0) {
    return null;
  }
  return (
    <div className={styles.stack} data-vui-domain-recipe="desktop-assistant" role="region" aria-label={copy.region}>
      {cards.map(card => {
        const kindLabel = copy.kinds[card.payload.kind];
        return (
          <div
            key={card.key}
            className={styles.card}
            data-severity={card.payload.severity}
            data-vui="human-attention-notice"
            onMouseEnter={() => clearDismissTimer(card.key)}
            onMouseLeave={() => scheduleDismiss(card.key)}
          >
            <VNativeButton
              className={styles.cardMain}
              aria-label={`${copy.open}: ${card.payload.title}`}
              onClick={() => openCard(card)}
            >
              <CircleAlert size={14} aria-hidden="true" className={styles.cardIcon} />
              <span className={styles.cardCopy}>
                <strong className={styles.cardTitle} title={card.payload.title}>
                  {card.payload.title || copy.fallbackTitle}
                </strong>
                {card.payload.body ? <span className={styles.cardBody}>{card.payload.body}</span> : null}
                {kindLabel ? <span className={styles.cardKind}>{kindLabel}</span> : null}
              </span>
            </VNativeButton>
            <VIconButton
              variant="ghost"
              className={styles.cardClose}
              label={copy.close}
              icon={<X size={12} aria-hidden="true" />}
              onPress={() => dismissCard(card.key)}
            />
          </div>
        );
      })}
    </div>
  );
}
