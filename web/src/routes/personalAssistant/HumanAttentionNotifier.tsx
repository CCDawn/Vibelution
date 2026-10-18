import { useEffect, useMemo, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { fetchPersonalAssistantOverview } from "../../api/personalAssistant";
import { queryKeys } from "../../api/queryKeys";
import {
  browserHumanAttentionStorage,
  createHumanAttentionLedger,
  emitNewHumanAttentionNotifications,
  humanAttentionBridge,
  humanAttentionTargetFor,
  isHumanAttentionKind,
  localDayKey,
  subscribeHumanAttentionEvents,
} from "./humanAttentionNotifications";

/**
 * Main-workbench owner of the dual-channel human-attention trigger chain.
 * Polls the existing personal-assistant overview attention list (same query
 * key and cadence as the overview aside) and forwards unseen
 * knowledge_review/anomaly rows to `bridge.notifyHumanAttention`. A shell
 * "opened" broadcast navigates the workbench to the entry target. Renders
 * nothing; the assistant window and the system tray own the visible layer.
 */
export function HumanAttentionNotifier() {
  const navigate = useNavigate();
  const bridge = useMemo(() => humanAttentionBridge(), []);
  const ledger = useMemo(
    () => createHumanAttentionLedger(browserHumanAttentionStorage(), localDayKey(new Date())),
    [],
  );
  const latestNavigate = useRef(navigate);
  latestNavigate.current = navigate;
  const kindById = useRef(new Map<string, string>());

  const overview = useQuery({
    queryKey: queryKeys.personalAssistantOverview(),
    queryFn: ({ signal }) => fetchPersonalAssistantOverview({ signal }),
    refetchInterval: 5000,
    // 双通道通知的主场景就是工作台最小化/助理窗关闭：此时窗口 hidden 会暂停
    // 默认后台轮询，人类关注事项将永远无法升级为系统 toast，因此显式保持轮询
    // （Chromium 对隐藏窗口的定时器节流把实际节奏降到约每分钟一次，可接受）。
    refetchIntervalInBackground: true,
    retry: 1,
  });

  useEffect(() => {
    const rows = overview.data?.humanAttention;
    if (!rows) {
      return;
    }
    for (const payload of emitNewHumanAttentionNotifications({ rows, bridge, ledger })) {
      kindById.current.set(payload.id, payload.kind);
    }
  }, [overview.data, bridge, ledger]);

  useEffect(() => {
    if (!bridge) {
      return () => undefined;
    }
    return subscribeHumanAttentionEvents(bridge, event => {
      if (event.type !== "opened") {
        return;
      }
      const knownKind = kindById.current.get(event.payload.id);
      const target = humanAttentionTargetFor({
        targetUrl: event.payload.targetUrl,
        kind: isHumanAttentionKind(knownKind) ? knownKind : undefined,
      });
      if (target) {
        latestNavigate.current(target);
      }
    });
  }, [bridge]);

  return null;
}
