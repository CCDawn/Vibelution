import {
  useEffect,
  type ComponentProps,
  type CSSProperties,
} from "react";

import { PaneResizeHandle } from "../components/layout/PaneResizeHandle";
import {
  readPaneLayout,
  writePaneLayout,
  type PaneSpec,
} from "../components/layout/paneLayoutPersistence";
import { usePersistedPaneResize } from "../components/layout/usePersistedPaneResize";
import { WORKBENCH_LAYOUT_IDS } from "../components/layout/workbenchLayoutIds";
import { AgentFilterRail } from "../components/vui/product/agent-management";
import { VNativeButton } from "../components/vui";
import { AgentDetailWorkspacePanel } from "./AgentDetailWorkspacePanel";
import { AgentInspectorRailPanel } from "./AgentInspectorRailPanel";
import { AgentListWorkspacePanel } from "./AgentListWorkspacePanel";
import styles from "./AgentWorkspaceLayoutPanel.styles";

const LAYOUT_ID = WORKBENCH_LAYOUT_IDS.agents;
const LEGACY_STORAGE_KEY = "vibelution.agent-workspace.column-widths.v1";

const LEFT_PANE: PaneSpec = {
  id: "left",
  defaultWidth: 340,
  minWidth: 280,
  maxWidth: 440,
};

const RIGHT_PANE: PaneSpec = {
  id: "right",
  defaultWidth: 360,
  minWidth: 300,
  maxWidth: 440,
};

const PANES_WITH_INSPECTOR: PaneSpec[] = [LEFT_PANE, RIGHT_PANE];
const PANES_WITHOUT_INSPECTOR: PaneSpec[] = [LEFT_PANE];

type AgentWorkspaceLayoutPanelProps = {
  detailWorkspace: ComponentProps<typeof AgentDetailWorkspacePanel>;
  filterRail: ComponentProps<typeof AgentFilterRail>;
  listWorkspace: ComponentProps<typeof AgentListWorkspacePanel>;
  inspectorRail?: ComponentProps<typeof AgentInspectorRailPanel> | null;
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
      left: Number(parsed.left) || LEFT_PANE.defaultWidth,
      right: Number(parsed.right) || RIGHT_PANE.defaultWidth,
    });
  } catch {
    // ignore
  }
}

export function AgentWorkspaceLayoutPanel({
  detailWorkspace,
  filterRail,
  listWorkspace,
  inspectorRail = null,
}: AgentWorkspaceLayoutPanelProps) {
  const hasInspector = Boolean(inspectorRail);
  const panes = hasInspector ? PANES_WITH_INSPECTOR : PANES_WITHOUT_INSPECTOR;

  useEffect(() => {
    migrateLegacyAgentWidths();
  }, []);

  const {
    layoutRef,
    widths,
    draggingPaneId,
    startResize,
    onResizeKeyDown,
  } = usePersistedPaneResize({
    layoutId: LAYOUT_ID,
    panes,
    preserveMainMinWidth: 560,
  });

  const leftWidth = widths.left ?? LEFT_PANE.defaultWidth;
  const rightWidth = widths.right ?? RIGHT_PANE.defaultWidth;

  const layoutStyle = {
    ["--agent-left-w" as string]: `${leftWidth}px`,
    ["--agent-right-w" as string]: `${rightWidth}px`,
  } as CSSProperties;

  return (
    <div
      ref={layoutRef}
      className={styles.workspace}
      style={layoutStyle}
      data-agent-workspace="resizable"
      data-vui-recipe="agents-workspace-shell"
      data-vui-layout-id={LAYOUT_ID}
      data-has-inspector={hasInspector ? "true" : "false"}
    >
      <div
        className={styles.directory}
        style={{ width: leftWidth, flexBasis: leftWidth }}
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

      <PaneResizeHandle
        label="调整目录栏宽度"
        valueNow={leftWidth}
        valueMin={LEFT_PANE.minWidth}
        valueMax={LEFT_PANE.maxWidth}
        active={draggingPaneId === "left"}
        onPointerDown={(event) => startResize("left", event, { direction: 1 })}
        onKeyDown={(event) => onResizeKeyDown("left", event, { direction: 1 })}
      />

      <div className={styles.main} data-agent-pane="main" data-vui-region="agents-detail">
        <AgentDetailWorkspacePanel {...detailWorkspace} />
      </div>

      {hasInspector && inspectorRail ? (
        <>
          <VNativeButton
            type="button"
            className={styles.inspectorBackdrop}
            aria-label={inspectorRail.closeLabel || inspectorRail.title}
            onClick={inspectorRail.onClose}
          />
          <PaneResizeHandle
            label="调整侧栏宽度"
            valueNow={rightWidth}
            valueMin={RIGHT_PANE.minWidth}
            valueMax={RIGHT_PANE.maxWidth}
            active={draggingPaneId === "right"}
            className={styles.inspectorResizeHandle}
            onPointerDown={(event) => startResize("right", event, { direction: -1 })}
            onKeyDown={(event) => onResizeKeyDown("right", event, { direction: -1 })}
          />
          <div
            className={styles.inspector}
            style={{ width: rightWidth, flexBasis: rightWidth }}
            data-agent-pane="inspector"
            data-vui-region="agents-inspector"
          >
            <AgentInspectorRailPanel {...inspectorRail} />
          </div>
        </>
      ) : null}
    </div>
  );
}
