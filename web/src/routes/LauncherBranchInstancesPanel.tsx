import { VTooltip } from "../components/vui";
import type { LauncherBranchInstance } from "../api/launcher";
import styles from "./LauncherBranchInstancesPanel.styles";

type LauncherBranchInstancesCopy = {
  branchInstances: string;
  branchInstancesHint: string;
  branchColumn: string;
  instanceState: string;
  instanceKind: string;
  instancePath: string;
  currentInstance: string;
  legacyCheckout: string;
  retiredCheckout: string;
  notCheckedOut: string;
};

type LauncherBranchInstancesPanelProps = {
  copy: LauncherBranchInstancesCopy;
  items: LauncherBranchInstance[];
  selectedId: string;
  onSelect: (id: string) => void;
};

function kindLabel(item: LauncherBranchInstance, copy: LauncherBranchInstancesCopy): string {
  if (item.kind === "main") {
    return copy.currentInstance;
  }
  if (item.kind === "retired") {
    return copy.retiredCheckout;
  }
  if (item.kind === "local_branch") {
    return copy.notCheckedOut;
  }
  return item.legacy ? copy.legacyCheckout : item.kind;
}

function stateLabel(item: LauncherBranchInstance): string {
  if (item.kind === "local_branch") {
    return "not_checked_out";
  }
  if (item.alive) {
    return item.observedState || "alive";
  }
  if (item.dirty) {
    return "dirty";
  }
  return item.observedState || "idle";
}

export function LauncherBranchInstancesPanel({
  copy,
  items,
  selectedId,
  onSelect,
}: LauncherBranchInstancesPanelProps) {
  return (
    <section className={styles.panel} data-vui-region="launcher-branch-instances" aria-label={copy.branchInstances}>
      <div className={styles.panelHeader}>
        <p className={styles.panelEyebrow}>{copy.branchInstances}</p>
        <strong>{copy.branchInstancesHint}</strong>
      </div>
      <div className={styles.statusTable} role="table" aria-label={copy.branchInstances}>
        <div className={styles.statusHead} role="row">
          <span role="columnheader">{copy.branchColumn}</span>
          <span role="columnheader">{copy.instanceState}</span>
          <span role="columnheader">{copy.instanceKind}</span>
          <span role="columnheader">HEAD</span>
          <span role="columnheader">Port</span>
          <span role="columnheader">{copy.instancePath}</span>
        </div>
        {items.map((item) => {
          const selected = item.id === selectedId;
          return (
            <VTooltip
              key={item.id}
              content={`${item.branch || item.id} · ${item.path || item.displayPath || item.id}`}
              width="wide"
            >
              <div
                className={styles.statusRow}
                role="row"
                tabIndex={0}
                data-tone={item.alive ? "success" : item.kind === "retired" ? "warning" : "neutral"}
                data-selected={selected ? "true" : "false"}
                aria-selected={selected}
                onClick={() => onSelect(item.id)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    onSelect(item.id);
                  }
                }}
              >
                <span role="cell"><strong>{item.branch || item.id}</strong></span>
                <span role="cell">{stateLabel(item)}</span>
                <span role="cell">{kindLabel(item, copy)}</span>
                <span role="cell">{item.head || "-"}</span>
                <span role="cell">{item.port > 0 ? String(item.port) : "-"}</span>
                <span role="cell">{item.displayPath || "-"}</span>
              </div>
            </VTooltip>
          );
        })}
      </div>
    </section>
  );
}
