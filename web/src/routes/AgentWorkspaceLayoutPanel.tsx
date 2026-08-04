import {
  useEffect,
  type ComponentProps,
  type ReactNode,
} from "react";

import {
  readPaneLayout,
  writePaneLayout,
} from "../components/layout/paneLayoutPersistence";
import { WORKBENCH_LAYOUT_IDS } from "../components/layout/workbenchLayoutIds";
import { AgentFilterRail } from "../components/vui/product/agent-management";
import { VListDetailPage, VNativeButton } from "../components/vui";
import { AgentDetailWorkspacePanel } from "./AgentDetailWorkspacePanel";
import { AgentInspectorRailPanel } from "./AgentInspectorRailPanel";
import { AgentListWorkspacePanel } from "./AgentListWorkspacePanel";
import styles from "./AgentWorkspaceLayoutPanel.styles";

const LAYOUT_ID = WORKBENCH_LAYOUT_IDS.agents;
const LEGACY_STORAGE_KEY = "vibelution.agent-workspace.column-widths.v1";

const LEFT_SIDEBAR = {
  id: "left",
  defaultWidth: 340,
  minWidth: 280,
  maxWidth: 440,
} as const;

const RIGHT_ASIDE = {
  id: "right",
  defaultWidth: 360,
  minWidth: 300,
  maxWidth: 440,
} as const;

type AgentWorkspaceLayoutPanelProps = {
  /** Module bar / chrome above the list-detail split. */
  toolbar: ReactNode;
  detailWorkspace: ComponentProps<typeof AgentDetailWorkspacePanel>;
  filterRail: ComponentProps<typeof AgentFilterRail>;
  listWorkspace: ComponentProps<typeof AgentListWorkspacePanel>;
  inspectorRail?: ComponentProps<typeof AgentInspectorRailPanel> | null;
  className?: string;
  ariaLabel?: string;
  title?: string;
};

/** One-time migrate legacy agent-workspace key into shared pane-layouts store. */
function migrateLegacyAgentWidths(): void {
  if (typeof window === "undefined") {
    return;
  }
  try {
    const existing = readPaneLayout(LAYOUT_ID);
    if (existing.left || existing.right) {
      return;
    }
    const raw = window.localStorage.getItem(LEGACY_STORAGE_KEY);
    if (!raw) {
      return;
    }
    const parsed = JSON.parse(raw) as { left?: number; right?: number };
    writePaneLayout(LAYOUT_ID, {
      left: Number(parsed.left) || LEFT_SIDEBAR.defaultWidth,
      right: Number(parsed.right) || RIGHT_ASIDE.defaultWidth,
    });
  } catch {
    // ignore
  }
}

export function AgentWorkspaceLayoutPanel({
  toolbar,
  detailWorkspace,
  filterRail,
  listWorkspace,
  inspectorRail = null,
  className,
  ariaLabel = "Agents",
  title = "Agents",
}: AgentWorkspaceLayoutPanelProps) {
  const hasInspector = Boolean(inspectorRail);

  useEffect(() => {
    migrateLegacyAgentWidths();
  }, []);

  return (
    <div
      className={styles.shellHost}
      data-agent-workspace="resizable"
      data-vui-recipe="agents-workspace-shell"
      data-vui-layout-id={LAYOUT_ID}
      data-has-inspector={hasInspector ? "true" : "false"}
    >
      <VListDetailPage
        className={className}
        headerClassName={styles.hiddenHeader}
        ariaLabel={ariaLabel}
        title={title}
        data-vui-domain-recipe="agents-management-workbench"
        layoutId={LAYOUT_ID}
        resize={{
          sidebar: LEFT_SIDEBAR,
          ...(hasInspector ? { aside: RIGHT_ASIDE } : {}),
        }}
        workspaceClassName={styles.workspace}
        columnsClassName=""
        toolbar={toolbar}
        list={(
          <div
            className={styles.directory}
            data-agent-pane="directory"
            data-vui-region="agents-directory"
          >
            <div className={styles.directoryFilter}>
              <AgentFilterRail {...filterRail} />
            </div>
            <div className={styles.directoryList}>
              <AgentListWorkspacePanel {...listWorkspace} />
            </div>
          </div>
        )}
        detail={(
          <div className={styles.main} data-agent-pane="main" data-vui-region="agents-detail">
            <AgentDetailWorkspacePanel {...detailWorkspace} />
          </div>
        )}
        aside={
          hasInspector && inspectorRail
            ? (
              <div
                className={styles.inspector}
                data-agent-pane="inspector"
                data-vui-region="agents-inspector"
              >
                <AgentInspectorRailPanel {...inspectorRail} />
              </div>
            )
            : undefined
        }
      />
      {hasInspector && inspectorRail ? (
        <VNativeButton
          type="button"
          className={styles.inspectorBackdrop}
          aria-label={inspectorRail.closeLabel || inspectorRail.title}
          onClick={inspectorRail.onClose}
        />
      ) : null}
    </div>
  );
}
