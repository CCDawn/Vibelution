import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { fetchPersonalAssistantHumanAttention } from "../../api/personalAssistant";
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
 * Polls the dedicated human-attention feed without loading Session overview
 * pages and forwards unseen rows to `bridge.notifyHumanAttention`. A shell
 * "opened" broadcast navigates the workbench to the entry target. Renders
 * nothing; the assistant window and the system tray own the visible layer.
 */
export function HumanAttentionNotifier({ startupReady = true }: { startupReady?: boolean }) {
  const navigate = useNavigate();
  const bridge = useMemo(() => humanAttentionBridge(), []);
  const [affairMode, setAffairMode] = useState<"legacy" | "probing" | "main_owned">(
    () => bridge?.getHumanAttentionCapabilities ? "probing" : "legacy",
  );
  const ledger = useMemo(
    () => createHumanAttentionLedger(browserHumanAttentionStorage(), localDayKey(new Date())),
    [],
  );
  const latestNavigate = useRef(navigate);
  latestNavigate.current = navigate;
  const kindById = useRef(new Map<string, string>());

  useEffect(() => {
    if (!bridge?.getHumanAttentionCapabilities) return;
    let active = true;
    let attempt = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const probe = () => {
      const current = ++attempt;
      // A lost reply may follow a committed grant. Retry the same document,
      // and ignore late results from an older attempt instead of guessing.
      timer = setTimeout(probe, 1000);
      void Promise.resolve().then(() => bridge.getHumanAttentionCapabilities!()).then(value => {
        if (!active || current !== attempt) return;
        const result = value && typeof value === "object" ? value as Record<string, unknown> : {};
        if (result.schemaVersion !== 1 || (result.legacyAffairReminder !== "main_owned" && result.legacyAffairReminder !== "legacy")) return;
        clearTimeout(timer);
        setAffairMode(result.legacyAffairReminder);
      }, () => undefined);
    };
    probe();
    return () => { active = false; clearTimeout(timer); };
  }, [bridge]);

  const attention = useQuery({
    queryKey: queryKeys.personalAssistantHumanAttention(),
    queryFn: ({ signal }) => fetchPersonalAssistantHumanAttention({ signal }),
    enabled: startupReady,
    refetchInterval: 5000,
    // 双通道通知的主场景就是工作台最小化/助理窗关闭：此时窗口 hidden 会暂停
    // 默认后台轮询，人类关注事项将永远无法升级为系统 toast，因此显式保持轮询
    // （Chromium 对隐藏窗口的定时器节流把实际节奏降到约每分钟一次，可接受）。
    refetchIntervalInBackground: true,
    retry: 1,
  });

  useEffect(() => {
    const rows = attention.data?.humanAttention;
    if (!rows) {
      return;
    }
    for (const payload of emitNewHumanAttentionNotifications({ rows, bridge, ledger, affairMode })) {
      kindById.current.set(payload.id, payload.kind);
    }
  }, [attention.data, attention.dataUpdatedAt, bridge, ledger, affairMode]);

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
