import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Hand, Monitor, PanelRightClose, Pause, Play, RefreshCw } from "lucide-react";
import { confirmPersonalAssistantComputer, controlPersonalAssistantComputer, fetchPersonalAssistantComputer,
  fetchPersonalAssistantComputerWindows, grantPersonalAssistantComputer } from "../../api/personalAssistantComputer";
import { queryKeys } from "../../api/queryKeys";
import type { ComputerControlAction, ComputerState } from "../../api/types/personalAssistantComputer";
import { VButton, VCheckbox, VIconButton, VStateSurface, VSurface } from "../../components/vui";
import styles from "./PersonalAssistantComputerPanel.styles";

const labels: Record<ComputerState["status"], string> = { idle: "未授权", ready: "已授权", working: "操作中",
  waiting_confirmation: "待确认", paused: "已暂停", manual: "你正在操作", ended: "授权已结束", error: "操作已停止" };
type Command = { kind: "grant"; selectionId: string } | { kind: "control"; grantId: string; action: ComputerControlAction }
  | { kind: "confirm"; grantId: string; pendingId: string; approved: boolean };

export function PersonalAssistantComputerPanel({ active = true, onCollapse }: { active?: boolean; onCollapse: () => void }) {
  const client = useQueryClient();
  const [visible, setVisible] = useState(() => document.visibilityState !== "hidden");
  const [selectionId, setSelectionId] = useState("");
  const [allowVision, setAllowVision] = useState(false);
  const [commandError, setCommandError] = useState("");
  const inFlight = useRef(false);
  const enabled = active && visible;
  useEffect(() => {
    const update = () => setVisible(document.visibilityState !== "hidden");
    document.addEventListener("visibilitychange", update);
    return () => document.removeEventListener("visibilitychange", update);
  }, []);
  const computer = useQuery({ queryKey: queryKeys.personalAssistantComputer(), queryFn: ({ signal }) => fetchPersonalAssistantComputer({ signal }),
    enabled, refetchInterval: enabled ? 1000 : false, refetchIntervalInBackground: false, retry: false });
  const state = computer.data;
  const granted = Boolean(state?.grantId);
  // Only an explicit panel visit/refresh enumerates windows. Status polling never invalidates this query.
  const windows = useQuery({ queryKey: queryKeys.personalAssistantComputerWindows(), queryFn: ({ signal }) => fetchPersonalAssistantComputerWindows({ signal }),
    enabled: active, staleTime: Infinity, refetchOnMount: "always", refetchOnWindowFocus: false, refetchOnReconnect: false, retry: false });
  const mutation = useMutation({ mutationFn: (command: Command) => command.kind === "grant"
    ? grantPersonalAssistantComputer({ selectionId: command.selectionId, allowVision: true })
    : command.kind === "control" ? controlPersonalAssistantComputer({ grantId: command.grantId, action: command.action })
      : confirmPersonalAssistantComputer({ grantId: command.grantId, pendingId: command.pendingId, approved: command.approved }),
    onMutate: async () => { setCommandError(""); await client.cancelQueries({ queryKey: queryKeys.personalAssistantComputer(), exact: true }); },
    onSuccess: async (data, command) => {
      await client.cancelQueries({ queryKey: queryKeys.personalAssistantComputer(), exact: true });
      client.setQueryData(queryKeys.personalAssistantComputer(), data);
      if (command.kind === "grant" || !data.grantId) { setSelectionId(""); setAllowVision(false); }
      if (command.kind === "control" && command.action === "end") void windows.refetch();
      void client.invalidateQueries({ queryKey: queryKeys.personalAssistantComputer(), exact: true });
    },
    onError: error => setCommandError(error instanceof Error ? error.message : "操作未成功，请重试。"),
    onSettled: () => { inFlight.current = false; },
  });
  function run(command: Command) {
    if (inFlight.current) return;
    inFlight.current = true;
    mutation.mutate(command);
  }
  function control(action: ComputerControlAction) { if (state?.grantId) run({ kind: "control", grantId: state.grantId, action }); }
  const busy = mutation.isPending;
  const operational = granted && state?.available && !["ended", "error"].includes(state.status);
  const selected = windows.data?.windows.find(row => row.selectionId === selectionId);
  return <section className={styles.root} aria-label="电脑操作">
    <header className={styles.header}>
      <h2 className={styles.heading}>电脑操作 <span className={styles.badge}>{state ? labels[state.status] : "读取中"}</span></h2>
      <div className={styles.actions}>
        {operational && state.status !== "manual" ? <VIconButton variant="ghost" label={state.status === "paused" ? "继续电脑操作" : "暂停电脑操作"}
          icon={state.status === "paused" ? <Play size={14} /> : <Pause size={14} />} isDisabled={busy}
          onClick={() => control(state.status === "paused" ? "resume" : "pause")} /> : null}
        {operational ? <VButton variant="secondary" icon={<Hand size={13} />} isDisabled={busy}
          onClick={() => control(state.status === "manual" ? "return" : "takeover")}>{state.status === "manual" ? "交回助理" : "交给我"}</VButton> : null}
        <VIconButton variant="ghost" label="收起电脑操作栏" icon={<PanelRightClose size={14} />} onClick={onCollapse} />
      </div>
    </header>
    <div className={styles.body}>
      {commandError ? <VStateSurface density="compact" tone="error" title="操作未成功">{commandError}</VStateSurface> : null}
      {computer.isError ? <VStateSurface density="compact" tone="error" title="电脑状态读取失败">{computer.error.message}
        <VButton variant="secondary" isPending={computer.isFetching} onClick={() => void computer.refetch()}>重试</VButton>
      </VStateSurface> : null}
      {computer.isPending ? <VStateSurface density="compact" tone="loading" busy title="正在读取电脑操作状态" /> : state ? <>
        {!state.available ? <VStateSurface density="compact" tone="unavailable" title="电脑操作暂不可用">{state.message}</VStateSurface> : null}
        {granted ? <>
          <VSurface className={styles.session} tone="inset" padding="normal">
            <strong>{state.window?.appName || "已授权窗口"}</strong><span className={styles.muted}>{state.window?.title}</span>
            <span className={styles.muted}>本次授权 · 仅此窗口</span>
            <VButton variant="ghost" isDisabled={busy} onClick={() => control("end")}>结束并重新选择</VButton>
          </VSurface>
          <p className={styles.status} role="status">{state.message || labels[state.status]}</p>
          {state.pending ? <VSurface className={styles.pending} tone="inset" padding="normal" ariaLabel="待确认的电脑操作">
            <strong>需要你确认</strong><p className={styles.muted}>确认后，助理将仅执行下面这项操作。</p>
            <dl className={styles.details}><div><dt>动作</dt><dd>{state.pending.action}</dd></div><div><dt>目标</dt><dd>{state.pending.targetLabel}</dd></div>
              {state.pending.text !== null ? <div><dt>输入内容</dt><dd><pre className={styles.input}>{state.pending.text || "（空文本）"}</pre></dd></div> : null}</dl>
            <div className={styles.buttons}><VButton variant="primary" isDisabled={busy || state.status !== "waiting_confirmation" || computer.isError}
              onClick={() => run({ kind: "confirm", grantId: state.grantId!, pendingId: state.pending!.id, approved: true })}>确认执行</VButton>
              <VButton variant="secondary" isDisabled={busy || state.status !== "waiting_confirmation"}
                onClick={() => run({ kind: "confirm", grantId: state.grantId!, pendingId: state.pending!.id, approved: false })}>取消操作</VButton></div>
          </VSurface> : null}
          <p className={styles.muted}>聊天保持可用。你可以随时暂停或接管；交回助理后会重新观察窗口。</p>
        </> : <>
          {state.message ? <p className={styles.status} role="status">{state.message}</p> : null}
          <p className={styles.muted}>选择一个窗口交给助理。切换到其他应用时，需要你重新选择。</p>
          <div className={styles.section}><div className={styles.sectionHeader}><h3>可选择的窗口</h3>
            <VIconButton variant="ghost" label="刷新可选窗口" icon={<RefreshCw size={14} />} isPending={windows.isFetching} isDisabled={busy}
              onClick={() => { setSelectionId(""); setAllowVision(false); void windows.refetch(); }} /></div>
            {windows.isPending ? <VStateSurface density="compact" tone="loading" busy title="正在读取可选窗口" />
              : windows.isError ? <VStateSurface density="compact" tone="error" title="窗口列表读取失败">{windows.error.message}</VStateSurface>
                : windows.data?.windows.length ? <div className={styles.windows} role="group" aria-label="选择授权窗口">{windows.data.windows.map(row =>
                  <VButton key={row.selectionId} className={styles.window} variant="secondary" contentLayout="plain" icon={<Monitor size={16} />}
                    data-selected={selectionId === row.selectionId} aria-pressed={selectionId === row.selectionId} isDisabled={busy || !state.available}
                    onClick={() => { setSelectionId(row.selectionId); setAllowVision(false); }}>
                    <span className={styles.windowCopy}><strong>{row.appName}</strong><span className={styles.muted}>{row.title}</span></span>
                  </VButton>)}</div> : <p className={styles.muted}>没有可授权的窗口。打开需要操作的应用后点击刷新。</p>}
          </div>
          <div className={styles.scope}><VCheckbox className={styles.checkbox} isSelected={allowVision} onChange={setAllowVision}
            isDisabled={busy || !state.available}>允许助理读取所选窗口的画面</VCheckbox>
            <p className={styles.muted}>画面将提供给当前助理模型，用于理解界面。</p>
            <VCheckbox className={styles.checkbox} isSelected isDisabled>提交、发送或删除前先让我确认</VCheckbox>
          </div>
          <VButton className={styles.full} variant="primary" isPending={busy} isDisabled={!state.available || !selected || !allowVision || windows.isFetching || windows.isError || computer.isError}
            onClick={() => { if (selected && allowVision) run({ kind: "grant", selectionId: selected.selectionId }); }}>授权这个窗口</VButton>
        </>}
      </> : null}
    </div>
    <footer className={styles.footer}><span>单个窗口授权</span><span>你始终可以接管</span></footer>
  </section>;
}
