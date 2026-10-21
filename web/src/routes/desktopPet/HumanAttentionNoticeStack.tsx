import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { CheckCircle2, CircleAlert, X } from "lucide-react";
import { VIconButton, VNativeButton } from "../../components/vui";
import { useShellI18n } from "../../i18n/useShellI18n";
import {
  humanAttentionBridge,
  humanAttentionTargetFor,
  isHumanAttentionKind,
  subscribeHumanAttentionEvents,
  type HumanAttentionKind,
  type HumanAttentionNotificationPayload,
} from "../personalAssistant/humanAttentionNotifications";
import { humanGateScopeFor, submitHumanGateDecision } from "../personalAssistant/humanGateDecision";
import styles from "./HumanAttentionNoticeStack.styles";

const DISMISS_AFTER_MS = 12_000;
const MAX_STACKED_CARDS = 3;

/** 完成类是好消息（severity info）：信息卡 + 一个“查看结果”跳转，无决策按钮。 */
const COMPLETION_KINDS: ReadonlySet<HumanAttentionKind> = new Set([
  "dispatch_receipt",
  "run_completed",
  "session_completed",
]);

function isCompletionKind(kind: string): boolean {
  return isHumanAttentionKind(kind) && COMPLETION_KINDS.has(kind);
}

const COPY = {
  zh: {
    region: "人工注意通知",
    close: "关闭通知",
    open: "查看该事项",
    fallbackTitle: "需要你的关注",
    kinds: {
      knowledge_review: "知识复核",
      anomaly: "研究异常",
      affair_reminder: "事务提醒",
      human_gate: "人工审批",
      dispatch_receipt: "派遣回执",
      run_completed: "运行完成",
      session_completed: "会话完成",
    },
    confirmPrefix: "确认",
    cancel: "取消",
    submitting: "提交中…",
    failedPrefix: "审批失败：",
  },
  en: {
    region: "Attention notifications",
    close: "Dismiss notification",
    open: "Open the related item",
    fallbackTitle: "Needs your attention",
    kinds: {
      knowledge_review: "Knowledge review",
      anomaly: "Anomaly",
      affair_reminder: "Affair",
      human_gate: "Human gate",
      dispatch_receipt: "Dispatch receipt",
      run_completed: "Run finished",
      session_completed: "Session done",
    },
    confirmPrefix: "Confirm ",
    cancel: "Cancel",
    submitting: "Submitting…",
    failedPrefix: "Approval failed: ",
  },
} as const;

type NoticeCard = {
  key: string;
  payload: HumanAttentionNotificationPayload;
};

type GateCardState = {
  submitting: boolean;
  errorText: string;
  /** Decision currently armed for its two-step confirmation. */
  armedDecision: string | null;
};

const IDLE_GATE_STATE: GateCardState = { submitting: false, errorText: "", armedDecision: null };

/** Inline approve buttons need the meta routing facts; anything less is a plain card. */
function isActionableCard(payload: HumanAttentionNotificationPayload): boolean {
  return (payload.actions?.length ?? 0) > 0 && humanGateScopeFor(payload) !== null;
}

/**
 * In-window notice cards for dual-channel human-attention notifications.
 * The Electron shell delivers assistant-window notifications through the
 * preload subscription (`launcher:human-attention-opened` channel exposed as
 * `onHumanAttentionOpened`); full payloads become stacked cards (title, body,
 * severity styling, click-to-locate, 12s auto-dismiss with hover pause, max
 * 3), bare opened clicks navigate immediately. Cards carrying human-gate
 * actions render inline accept/reject buttons instead of auto-dismissing:
 * accept submits directly through the run snapshot + command offer; any other
 * decision arms a two-step inline confirmation first.
 */
export function HumanAttentionNoticeStack({ onBeforeNavigate }: {
  /** Called before an in-window navigation (e.g. expand the collapsed pet). */
  onBeforeNavigate?: () => void | Promise<void>;
}) {
  const { lang } = useShellI18n();
  const copy = COPY[lang];
  const navigate = useNavigate();
  const [cards, setCards] = useState<NoticeCard[]>([]);
  const [gateStates, setGateStates] = useState<Record<string, GateCardState>>({});
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
    setGateStates(previous => {
      if (!(key in previous)) {
        return previous;
      }
      const next = { ...previous };
      delete next[key];
      return next;
    });
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

  const patchGateState = useCallback((key: string, patch: Partial<GateCardState>) => {
    setGateStates(previous => ({ ...previous, [key]: { ...IDLE_GATE_STATE, ...previous[key], ...patch } }));
  }, []);

  const runGateDecision = useCallback(async (card: NoticeCard, decision: string) => {
    const scope = humanGateScopeFor(card.payload);
    if (!scope) {
      openCard(card);
      return;
    }
    patchGateState(card.key, { submitting: true, errorText: "", armedDecision: null });
    let outcome;
    try {
      outcome = await submitHumanGateDecision({ ...scope, decision });
    } catch (reason) {
      patchGateState(card.key, {
        submitting: false,
        errorText: `${COPY[lang].failedPrefix}${reason instanceof Error ? reason.message : String(reason)}`,
      });
      return;
    }
    if (outcome.outcome === "submitted") {
      dismissCard(card.key);
      return;
    }
    // The gate offer expired or was already decided: fall back to the run panel.
    openCard(card);
  }, [dismissCard, lang, openCard, patchGateState]);

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
  // Actionable gate cards stay until answered so the user is never raced.
  useEffect(() => {
    for (const card of cards) {
      if (!timers.current.has(card.key) && !isActionableCard(card.payload)) {
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
        const gateActions = isActionableCard(card.payload) ? card.payload.actions ?? [] : [];
        const gateState = gateStates[card.key] ?? IDLE_GATE_STATE;
        return (
          <div
            key={card.key}
            className={gateActions.length > 0 ? `${styles.card} ${styles.cardColumn}` : styles.card}
            data-severity={card.payload.severity}
            data-vui="human-attention-notice"
            onMouseEnter={() => clearDismissTimer(card.key)}
            onMouseLeave={() => {
              if (gateActions.length === 0) {
                scheduleDismiss(card.key);
              }
            }}
          >
            <VNativeButton
              className={styles.cardMain}
              aria-label={`${copy.open}: ${card.payload.title}`}
              onClick={() => openCard(card)}
            >
              {isCompletionKind(card.payload.kind)
                ? <CheckCircle2 size={14} aria-hidden="true" className={styles.cardIcon} />
                : <CircleAlert size={14} aria-hidden="true" className={styles.cardIcon} />}
              <span className={styles.cardCopy}>
                <strong className={styles.cardTitle} title={card.payload.title}>
                  {card.payload.title || copy.fallbackTitle}
                </strong>
                {card.payload.body ? <span className={styles.cardBody}>{card.payload.body}</span> : null}
                {kindLabel ? <span className={styles.cardKind}>{kindLabel}</span> : null}
              </span>
            </VNativeButton>
            {gateActions.length > 0 ? (
              <div className={styles.cardActions} data-testid="notice-gate-actions">
                {gateActions.map(action => {
                  const needsConfirm = action.decision !== "accept";
                  const armed = gateState.armedDecision === action.decision;
                  if (!needsConfirm || !armed) {
                    return (
                      <VNativeButton
                        key={action.decision}
                        className={action.decision === "accept" ? styles.gateAcceptButton : styles.gateActionButton}
                        data-testid={`notice-gate-${action.decision}`}
                        disabled={gateState.submitting}
                        aria-label={`${action.label}: ${card.payload.title}`}
                        onClick={() => {
                          if (needsConfirm) {
                            patchGateState(card.key, { armedDecision: action.decision, errorText: "" });
                            return;
                          }
                          void runGateDecision(card, action.decision);
                        }}
                      >
                        {gateState.submitting ? copy.submitting : action.label}
                      </VNativeButton>
                    );
                  }
                  return (
                    <span key={action.decision} className={styles.gateConfirmRow}>
                      <VNativeButton
                        className={styles.gateDangerButton}
                        data-testid="notice-gate-confirm"
                        disabled={gateState.submitting}
                        aria-label={`${copy.confirmPrefix}${action.label}: ${card.payload.title}`}
                        onClick={() => void runGateDecision(card, action.decision)}
                      >
                        {gateState.submitting ? copy.submitting : `${copy.confirmPrefix}${action.label}`}
                      </VNativeButton>
                      <VNativeButton
                        className={styles.gateActionButton}
                        data-testid="notice-gate-cancel"
                        disabled={gateState.submitting}
                        onClick={() => patchGateState(card.key, { armedDecision: null })}
                      >
                        {copy.cancel}
                      </VNativeButton>
                    </span>
                  );
                })}
                {gateState.errorText ? (
                  <span className={styles.gateError} data-testid="notice-gate-error">
                    {gateState.errorText}
                  </span>
                ) : null}
              </div>
            ) : null}
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
