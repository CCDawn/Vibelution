import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Hand, Monitor, PanelRightClose, Pause, Play, RefreshCw } from "lucide-react";
import { confirmPersonalAssistantComputer, controlPersonalAssistantComputer, fetchPersonalAssistantComputer,
  fetchPersonalAssistantComputerWindows, grantPersonalAssistantComputer } from "../../api/personalAssistantComputer";
import { queryKeys } from "../../api/queryKeys";
import type { ComputerControlAction, ComputerState } from "../../api/types/personalAssistantComputer";
import { VButton, VCheckbox, VIconButton, VStateSurface, VSurface } from "../../components/vui";
import { useShellI18n } from "../../i18n/useShellI18n";
import COMPUTER_COPY from "./personalAssistantComputerCopy";
import styles from "./PersonalAssistantComputerPanel.styles";

type Command = { kind: "grant"; selectionId: string } | { kind: "control"; grantId: string; action: ComputerControlAction }
  | { kind: "confirm"; grantId: string; pendingId: string; approved: boolean };
type CommandError = { kind: "fallback" } | { kind: "backend"; message: string };

export function PersonalAssistantComputerPanel({ active = true, onCollapse }: { active?: boolean; onCollapse: () => void }) {
  const { lang } = useShellI18n();
  const copy = COMPUTER_COPY[lang];
  const client = useQueryClient();
  const [visible, setVisible] = useState(() => document.visibilityState !== "hidden");
  const [selectionId, setSelectionId] = useState("");
  const [allowVision, setAllowVision] = useState(false);
  const [commandError, setCommandError] = useState<CommandError | null>(null);
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
    onMutate: async () => { setCommandError(null); await client.cancelQueries({ queryKey: queryKeys.personalAssistantComputer(), exact: true }); },
    onSuccess: async (data, command) => {
      await client.cancelQueries({ queryKey: queryKeys.personalAssistantComputer(), exact: true });
      client.setQueryData(queryKeys.personalAssistantComputer(), data);
      if (command.kind === "grant" || !data.grantId) { setSelectionId(""); setAllowVision(false); }
      if (command.kind === "control" && command.action === "end") void windows.refetch();
      void client.invalidateQueries({ queryKey: queryKeys.personalAssistantComputer(), exact: true });
    },
    onError: error => setCommandError(error instanceof Error ? { kind: "backend", message: error.message } : { kind: "fallback" }),
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
  const statusLabels: Record<ComputerState["status"], string> = copy.statuses;
  return <section className={styles.root} aria-label={copy.section}>
    <header className={styles.header}>
      <h2 className={styles.heading}>{copy.section} <span className={styles.badge}>{state ? statusLabels[state.status] : copy.loading}</span></h2>
      <div className={styles.actions}>
        {operational && state.status !== "manual" ? <VIconButton variant="ghost" label={state.status === "paused" ? copy.resume : copy.pause}
          icon={state.status === "paused" ? <Play size={14} /> : <Pause size={14} />} isDisabled={busy}
          onClick={() => control(state.status === "paused" ? "resume" : "pause")} /> : null}
        {operational ? <VButton variant="secondary" icon={<Hand size={13} />} isDisabled={busy}
          onClick={() => control(state.status === "manual" ? "return" : "takeover")}>{state.status === "manual" ? copy.returnControl : copy.takeControl}</VButton> : null}
        <VIconButton variant="ghost" label={copy.collapse} icon={<PanelRightClose size={14} />} onClick={onCollapse} />
      </div>
    </header>
    <div className={styles.body}>
      {commandError ? <VStateSurface density="compact" tone="error" title={copy.commandErrorTitle}>
        {commandError.kind === "backend" ? commandError.message : copy.commandErrorFallback}</VStateSurface> : null}
      {computer.isError ? <VStateSurface density="compact" tone="error" title={copy.readFailed}>{computer.error.message}
        <VButton variant="secondary" isPending={computer.isFetching} onClick={() => void computer.refetch()}>{copy.retry}</VButton>
      </VStateSurface> : null}
      {computer.isPending ? <VStateSurface density="compact" tone="loading" busy title={copy.readState} /> : state ? <>
        {!state.available ? <VStateSurface density="compact" tone="unavailable" title={copy.unavailable}>{state.message}</VStateSurface> : null}
        {granted ? <>
          <VSurface className={styles.session} tone="inset" padding="normal">
            <strong>{state.window?.appName || copy.authorizedWindow}</strong><span className={styles.muted}>{state.window?.title}</span>
            <span className={styles.muted}>{copy.grantScope}</span>
            <VButton variant="ghost" isDisabled={busy} onClick={() => control("end")}>{copy.endAndSelect}</VButton>
          </VSurface>
          <p className={styles.status} role="status">{state.message || statusLabels[state.status]}</p>
          {state.pending ? <VSurface className={styles.pending} tone="inset" padding="normal" ariaLabel={copy.pendingConfirmation}>
            <strong>{copy.needsConfirmation}</strong><p className={styles.muted}>{copy.confirmationDescription}</p>
            <dl className={styles.details}><div><dt>{copy.action}</dt><dd>{copy.pendingActions[state.pending.action as keyof typeof copy.pendingActions] ?? state.pending.action}</dd></div><div><dt>{copy.target}</dt><dd>{state.pending.targetLabel}</dd></div>
              {state.pending.text !== null ? <div><dt>{copy.input}</dt><dd><pre className={styles.input}>{state.pending.text || copy.emptyText}</pre></dd></div> : null}</dl>
            <div className={styles.buttons}><VButton variant="primary" isDisabled={busy || state.status !== "waiting_confirmation" || computer.isError}
              onClick={() => run({ kind: "confirm", grantId: state.grantId!, pendingId: state.pending!.id, approved: true })}>{copy.confirm}</VButton>
              <VButton variant="secondary" isDisabled={busy || state.status !== "waiting_confirmation"}
                onClick={() => run({ kind: "confirm", grantId: state.grantId!, pendingId: state.pending!.id, approved: false })}>{copy.cancel}</VButton></div>
          </VSurface> : null}
          <p className={styles.muted}>{copy.sessionTip}</p>
        </> : <>
          {state.message ? <p className={styles.status} role="status">{state.message}</p> : null}
          <p className={styles.muted}>{copy.chooseWindow}</p>
          <div className={styles.section}><div className={styles.sectionHeader}><h3>{copy.availableWindows}</h3>
            <VIconButton variant="ghost" label={copy.refreshWindows} icon={<RefreshCw size={14} />} isPending={windows.isFetching} isDisabled={busy}
              onClick={() => { setSelectionId(""); setAllowVision(false); void windows.refetch(); }} /></div>
            {windows.isPending ? <VStateSurface density="compact" tone="loading" busy title={copy.readWindows} />
              : windows.isError ? <VStateSurface density="compact" tone="error" title={copy.windowsReadFailed}>{windows.error.message}</VStateSurface>
                : windows.data?.windows.length ? <div className={styles.windows} role="group" aria-label={copy.selectAuthorizedWindow}>{windows.data.windows.map(row =>
                  <VButton key={row.selectionId} className={styles.window} variant="secondary" contentLayout="plain" icon={<Monitor size={16} />}
                    data-selected={selectionId === row.selectionId} aria-pressed={selectionId === row.selectionId} isDisabled={busy || !state.available}
                    onClick={() => { setSelectionId(row.selectionId); setAllowVision(false); }}>
                    <span className={styles.windowCopy}><strong>{row.appName}</strong><span className={styles.muted}>{row.title}</span></span>
                  </VButton>)}</div> : <p className={styles.muted}>{copy.noWindows}</p>}
          </div>
          <div className={styles.scope}><VCheckbox className={styles.checkbox} isSelected={allowVision} onChange={setAllowVision}
            isDisabled={busy || !state.available}>{copy.allowVision}</VCheckbox>
            <p className={styles.muted}>{copy.visionDescription}</p>
            <VCheckbox className={styles.checkbox} isSelected isDisabled>{copy.confirmSensitiveActions}</VCheckbox>
          </div>
          <VButton className={styles.full} variant="primary" isPending={busy} isDisabled={!state.available || !selected || !allowVision || windows.isFetching || windows.isError || computer.isError}
            onClick={() => { if (selected && allowVision) run({ kind: "grant", selectionId: selected.selectionId }); }}>{copy.grantWindow}</VButton>
        </>}
      </> : null}
    </div>
    <footer className={styles.footer}><span>{copy.singleWindowGrant}</span><span>{copy.takeoverAvailable}</span></footer>
  </section>;
}
