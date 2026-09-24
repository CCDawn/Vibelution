import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";

import {
  createProjectionStore,
  describeDecision,
  type ProjectionState,
} from "../next/projectionMock";

/**
 * Tab ③: projection invariant demo on a mock sequence. The invariant store
 * (seq gate / watermark resubscribe / single-flight backoff / optimistic
 * overlay reconciliation) runs beside a naive store that applies every delta
 * as it arrives, so fault injection shows the difference concretely.
 */

type LogLine = { line: string; tone: "ok" | "hold" | "err" | "dim" };

function useProjectionState(store: ReturnType<typeof createProjectionStore>): ProjectionState {
  return useSyncExternalStore(store.subscribe, store.getState);
}

export function ProjectionPanel() {
  const storeRef = useRef(createProjectionStore());
  const store = storeRef.current;
  const state = useProjectionState(store);
  const [log, setLog] = useState<LogLine[]>([]);

  const naiveRef = useRef({ lastSeq: 0, text: "" });
  const [naiveText, setNaiveText] = useState("");
  const prevRecoveryRef = useRef(false);

  // Log the recovery completion when the mock snapshot lands.
  useEffect(() => {
    if (prevRecoveryRef.current && !state.recoveryInFlight && state.lastAppliedSeq > 0) {
      setLog((current) => [
        ...current,
        describeDecision({ kind: "recovery-done", through: state.lastAppliedSeq }),
      ].slice(-120));
    }
    prevRecoveryRef.current = state.recoveryInFlight;
  }, [state.recoveryInFlight, state.lastAppliedSeq]);

  const pushLog = useCallback((entries: Array<{ line: string; tone: LogLine["tone"] }>) => {
    setLog((current) => [...current, ...entries].slice(-120));
  }, []);

  const playNormal = useCallback(() => {
    const entries: LogLine[] = [];
    for (let offset = 0; offset < 4; offset += 1) {
      const seq = naiveRef.current.lastSeq + 1;
      const text = `seq${seq}✓ `;
      const decision = store.applyDelta(seq, text);
      entries.push(describeDecision(decision));
      naiveRef.current = { lastSeq: seq, text: naiveRef.current.text + text };
    }
    setNaiveText(naiveRef.current.text);
    pushLog(entries);
  }, [pushLog, store]);

  const injectGap = useCallback(() => {
    const skipped = 2;
    const seq = naiveRef.current.lastSeq + 1 + skipped;
    const text = `seq${seq}✓ `;
    const decision = store.applyDelta(seq, text);
    naiveRef.current = { lastSeq: seq, text: naiveRef.current.text + text };
    setNaiveText(naiveRef.current.text);
    const entries: LogLine[] = [
      { line: `FAULT  服务器跳过 seq=${seq - skipped}..${seq - 1}，直接到达 seq=${seq}`, tone: "err" },
      describeDecision(decision),
    ];
    // applyDelta already started single-flight recovery synchronously when the
    // gap was real; surface it in the log.
    const fresh = store.getState();
    if (fresh.recoveryInFlight) {
      entries.push(describeDecision({ kind: "recovery-start", watermark: fresh.watermark }));
    }
    if (state.overlayIds.length > 0) {
      entries.push({ line: "注：断档期间乐观 overlay 冻结，恢复后由权威投影对账。", tone: "dim" });
    }
    pushLog(entries);
  }, [pushLog, state.overlayIds.length, store]);

  const injectDuplicate = useCallback(() => {
    const seq = Math.max(1, naiveRef.current.lastSeq);
    const text = `seq${seq}✓ `;
    const decision = store.applyDelta(seq - 1, text);
    naiveRef.current = { lastSeq: naiveRef.current.lastSeq, text: naiveRef.current.text + text + "⟲" };
    setNaiveText(naiveRef.current.text);
    pushLog([describeDecision(decision)]);
  }, [pushLog, store]);

  const sendOptimistic = useCallback(() => {
    const overlayId = `local-${Date.now() % 10000}`;
    pushLog([describeDecision(store.addOverlay(overlayId))]);
  }, [pushLog, store]);

  const reconcileOptimistic = useCallback(() => {
    const overlayId = state.overlayIds[0];
    if (!overlayId) {
      pushLog([{ line: "没有待对账的乐观消息", tone: "dim" }]);
      return;
    }
    pushLog([describeDecision(store.reconcileOverlay(overlayId))]);
  }, [pushLog, state.overlayIds, store]);

  const reset = useCallback(() => {
    store.reset();
    naiveRef.current = { lastSeq: 0, text: "" };
    setNaiveText("");
    setLog([]);
  }, [store]);

  return (
    <div className="proj-grid" style={{ flex: 1, minHeight: 0 }}>
      <div className="proj-side">
        <div className="proj-card">
          <h2>故障注入</h2>
          <div className="control-bar" style={{ flexDirection: "column", alignItems: "stretch", gap: 6 }}>
            <button className="primary" onClick={playNormal}>① 正常序列 ×4</button>
            <button className="danger" onClick={injectGap}>② 注入 seq 断档（跳过 2 个）</button>
            <button className="danger" onClick={injectDuplicate}>③ 注入重复 seq</button>
            <button onClick={sendOptimistic}>④ 发送乐观消息（overlay）</button>
            <button onClick={reconcileOptimistic}>⑤ 权威对账 overlay</button>
            <button onClick={reset}>重置</button>
          </div>
          <div className="state-badges" style={{ marginTop: 8 }}>
            <span className={`state-badge ${state.recoveryInFlight ? "warn" : ""}`}>
              {state.recoveryInFlight ? `恢复中（单飞 · 第 ${state.recoveryAttempt} 次退避）` : "无恢复飞行"}
            </span>
            <span className="state-badge">水位 {state.watermark}</span>
            <span className="state-badge">已应用至 seq {state.lastAppliedSeq}</span>
            <span className="state-badge">暂存 {state.heldCount}</span>
          </div>
          <div className={state.overlayCleared ? "overlay-note cleared" : "overlay-note"}>
            {state.overlayIds.length > 0
              ? `乐观 overlay 挂起：${state.overlayIds.join("、")}（等待权威对账）`
              : state.overlayCleared
                ? "乐观 overlay 已被权威投影对账移除 ✓"
                : "无乐观 overlay"}
          </div>
        </div>
        <div className="proj-card" style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
          <h2>决策日志</h2>
          <div className="log-pane" style={{ flex: 1, minHeight: 120 }}>
            {log.length === 0 ? <span className="log-line dim">等待操作……</span> : null}
            {log.map((entry, index) => (
              <div key={index} className={`log-line ${entry.tone}`}>{entry.line}</div>
            ))}
          </div>
        </div>
      </div>
      <div className="proj-card" style={{ display: "flex", flexDirection: "column", minHeight: 0 }}>
        <h2>不变量投影（新方案）</h2>
        <div className="state-badges" style={{ marginBottom: 8 }}>
          <span className="state-badge on">seq 连续才应用</span>
          <span className="state-badge on">断档 HOLD + 水位重订阅</span>
          <span className="state-badge on">overlay 权威对账</span>
        </div>
        <div className="md-body" style={{ flex: 1, minHeight: 80 }}>
          {state.text || <span className="panel-note">（空）</span>}
        </div>
        <div style={{ marginTop: 8 }}>
          <div className="msg-meta">seq 记录（最近 48 条）</div>
          <div className="seq-strip">
            {state.appliedSeqs.length === 0 ? <span className="seq-chip">空</span> : null}
            {state.appliedSeqs.map((chip, index) => (
              <span key={index} className={`seq-chip ${chip.status}`}>
                {chip.seq}:{chip.status === "applied" ? "A" : chip.status === "held" ? "H" : "D"}
              </span>
            ))}
          </div>
        </div>
      </div>
      <div className="proj-card" style={{ display: "flex", flexDirection: "column", minHeight: 0 }}>
        <h2>朴素投影（无不变量对照）</h2>
        <div className="state-badges" style={{ marginBottom: 8 }}>
          <span className="state-badge err">来一个应用一个</span>
          <span className="state-badge err">断档静默丢字</span>
          <span className="state-badge err">无对账</span>
        </div>
        <div className="md-body" style={{ flex: 1, minHeight: 80 }}>
          {naiveText || <span className="panel-note">（空）</span>}
        </div>
        <p className="panel-note" style={{ margin: 0 }}>
          同样按下 ②：右盘文本直接缺两段（服务器重发也接不上，无水位）；按 ③ 会出现重复片段。
          左盘则 HOLD 断档、从水位单飞恢复，最终文本与真实序列一致。
        </p>
      </div>
    </div>
  );
}
