/**
 * Isolated Challenge Cup team-canvas IA preview.
 * Open: /challenge-cup-team-canvas-preview.html
 * Design acceptance only — does not change TeamsRoute / TeamsCanvasComposer.
 */
import { StrictMode, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { Archive, Bot, Eye, Link2, Plus, Users } from "lucide-react";

import { VStatusChip } from "../components/vui/aesthetic/VStatusChip";
import { VSelect } from "../components/vui/forms/VSelect";
import { VActionGroup } from "../components/vui/layout/VActionGroup";
import { VCanvasWorkbenchPage } from "../components/vui/layout/VCanvasWorkbenchPage";
import { VStatusStrip } from "../components/vui/layout/VStatusStrip";
import { VToolbar } from "../components/vui/layout/VToolbar";
import { VButton } from "../components/vui/primitives/VButton";
import { VNativeButton } from "../components/vui/primitives/VNativeButton";
import { VSurface } from "../components/vui/primitives/VSurface";
import { VuiProvider } from "../components/vui/VuiProvider";
import "./base.css";
import "./tokens.css";
import "./tailwind.css";
import "./vui-provider-theme.css";
import "./vui-native-controls.css";
import "./challenge-cup-team-canvas-preview.css";
import { challengeCupTeamCanvasPreviewStyles as styles } from "./challenge-cup-team-canvas-preview.styles";
import {
  BLOCKED_ISSUE,
  DEFAULT_SELECTED_NODE,
  SCENE_LABEL,
  SCENE_ORDER,
  TEAMS,
  nodeById,
  teamById,
  type LayoutMode,
  type PreviewNode,
  type PreviewTeam,
  type RoleTone,
  type SceneId,
  type StageTone,
  type StatusTone,
  type TeamId,
} from "./challengeCupTeamCanvasPreviewModel";

function statusChipTone(tone: StatusTone | StageTone): "neutral" | "accent" | "success" | "warning" | "danger" {
  if (tone === "success" || tone === "done") return "success";
  if (tone === "warning" || tone === "active") return "warning";
  if (tone === "danger" || tone === "blocked") return "danger";
  return "neutral";
}

function roleBadgeClass(tone: RoleTone): string {
  if (tone === "lead") return "tcc-role-lead";
  if (tone === "research") return "tcc-role-research";
  if (tone === "advisor") return "tcc-role-advisor";
  return "tcc-role-open";
}

const NODE_WIDTH = 172;
const NODE_HEIGHT = 108;

function layoutNodes(nodes: PreviewNode[], size: { w: number; h: number }): Map<string, { x: number; y: number }> {
  const pad = 16;
  const gapX = 28;
  const gapY = 36;
  const positions = new Map<string, { x: number; y: number }>();
  const ids = new Set(nodes.map((node) => node.id));
  const colRight = Math.max(pad, size.w - pad - NODE_WIDTH);
  const rowBottom = Math.max(pad, size.h - pad - NODE_HEIGHT);
  const threeColWidth = pad * 2 + NODE_WIDTH * 3 + gapX * 2;
  if (ids.has("node-lead") && ids.has("node-graph")) {
    const col0 = pad;
    const col2 = colRight;
    const col1 = size.w >= threeColWidth
      ? (col0 + col2) / 2
      : col2;
    const row0 = pad;
    const row1 = Math.min(rowBottom, row0 + NODE_HEIGHT + gapY);
    const rowMid = (row0 + row1) / 2;
    positions.set("node-lead", { x: col0, y: row0 });
    positions.set("node-finder", { x: col1, y: size.w >= threeColWidth ? row0 : row1 });
    positions.set("node-extractor", { x: size.w >= threeColWidth ? col1 : col0, y: row1 });
    positions.set("node-graph", { x: col2, y: size.w >= threeColWidth ? rowMid : row1 });
    return positions;
  }
  if (nodes.length === 2) {
    positions.set(nodes[0].id, { x: pad, y: Math.max(pad, (size.h - NODE_HEIGHT) / 3) });
    positions.set(nodes[1].id, { x: colRight, y: Math.max(pad, (size.h - NODE_HEIGHT) / 3) });
    return positions;
  }
  nodes.forEach((node, index) => {
    positions.set(node.id, {
      x: pad + (index % 2) * Math.max(0, colRight - pad),
      y: pad + Math.floor(index / 2) * (NODE_HEIGHT + gapY),
    });
  });
  return positions;
}

function edgePath(
  team: PreviewTeam,
  fromId: string,
  toId: string,
  positions: Map<string, { x: number; y: number }>,
): string | null {
  const from = positions.get(fromId);
  const to = positions.get(toId);
  if (!from || !to) return null;
  const sameColumn = Math.abs(from.x - to.x) < 8;
  const sameRow = Math.abs(from.y - to.y) < 8;
  if (sameRow) {
    const left = from.x < to.x ? from : to;
    const right = from.x < to.x ? to : from;
    const y = left.y + NODE_HEIGHT / 2;
    return `M ${left.x + NODE_WIDTH} ${y} L ${right.x} ${y}`;
  }
  if (sameColumn) {
    const top = from.y < to.y ? from : to;
    const bottom = from.y < to.y ? to : from;
    const x = top.x + NODE_WIDTH / 2;
    return `M ${x} ${top.y + NODE_HEIGHT} L ${x} ${bottom.y}`;
  }
  const startX = from.x + NODE_WIDTH;
  const startY = from.y + NODE_HEIGHT / 2;
  const endX = to.x;
  const endY = to.y + NODE_HEIGHT / 2;
  const midX = (startX + endX) / 2;
  return `M ${startX} ${startY} L ${midX} ${startY} L ${midX} ${endY} L ${endX} ${endY}`;
}

function OrgCanvas(props: {
  team: PreviewTeam;
  selectedNodeId: string | null;
  onSelectNode: (nodeId: string) => void;
}) {
  const { team, selectedNodeId, onSelectNode } = props;
  const canvasRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 640, h: 420 });
  useLayoutEffect(() => {
    const el = canvasRef.current;
    if (!el) return;
    const update = () => setSize({ w: el.clientWidth, h: el.clientHeight });
    update();
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  const positions = layoutNodes(team.nodes, size);
  return (
    <div className={styles.canvasHost} data-testid="org-canvas">
      <div className={styles.canvas} ref={canvasRef}>
        <svg className={styles.edges} aria-hidden="true">
          {team.edges.map((edge) => {
            const d = edgePath(team, edge.from, edge.to, positions);
            return d ? <path key={edge.id} d={d} /> : null;
          })}
        </svg>
        {team.nodes.map((node) => {
          const selected = selectedNodeId === node.id;
          const point = positions.get(node.id) ?? { x: 16, y: 16 };
          return (
            <VNativeButton
              key={node.id}
              type="button"
              className={selected ? styles.nodeActive : styles.node}
              style={{ left: point.x, top: point.y, width: NODE_WIDTH, height: NODE_HEIGHT }}
              aria-pressed={selected}
              aria-label={`${node.label}, ${node.role}, ${node.agent}`}
              data-testid={`canvas-node-${node.id}`}
              onClick={() => onSelectNode(node.id)}
            >
              <span className={styles.nodeIcon}>
                {node.agent === "未绑定" ? <Users size={15} /> : <Bot size={15} />}
              </span>
              <strong>{node.label}</strong>
              <span className={`tcc-role ${roleBadgeClass(node.roleTone)}`}>{node.role}</span>
              <small>{node.agent}</small>
              <small>{node.purpose}</small>
            </VNativeButton>
          );
        })}
      </div>
    </div>
  );
}

function CurrentShell(props: {
  team: PreviewTeam;
  selectedNodeId: string | null;
  onSelectTeam: (teamId: TeamId) => void;
  onSelectNode: (nodeId: string) => void;
}) {
  const { team, selectedNodeId, onSelectTeam, onSelectNode } = props;
  return (
    <div className={styles.current} data-testid="layout-current">
      <aside className={styles.currentRail} data-testid="current-team-rail">
        {TEAMS.map((item) => (
          <VNativeButton
            key={item.id}
            type="button"
            className={item.id === team.id ? styles.currentTeamActive : styles.currentTeam}
            aria-pressed={item.id === team.id}
            onClick={() => onSelectTeam(item.id)}
          >
            <strong>{item.name}</strong>
            <span>{item.kind}</span>
          </VNativeButton>
        ))}
      </aside>
      <div className={styles.currentMain}>
        <div className={styles.currentToolbar}>
          <strong>{team.name}</strong>
          <span>{team.purpose}</span>
        </div>
        <div className={styles.currentFlow}>
          <div>
            <strong>下一步 · {team.nextTitle}</strong>
            <p>{team.nextBody}</p>
          </div>
          <VButton type="button" density="compact" variant="primary" className={styles.currentFlowCta}>
            {team.cta}
          </VButton>
          <div className={styles.currentStages}>
            {team.stages.map((stage) => (
              <div key={stage.id} className={styles.currentStage}>
                <strong>{stage.title}</strong>
                <div>{stage.status}</div>
              </div>
            ))}
          </div>
        </div>
        <p className={styles.currentCanvasHint}>检查器默认隐藏 · 画布被流程条压矮</p>
        <OrgCanvas team={team} selectedNodeId={selectedNodeId} onSelectNode={onSelectNode} />
      </div>
    </div>
  );
}

function StatusRail(props: {
  team: PreviewTeam;
  selectedNodeId: string | null;
  blocked: boolean;
  onSelectNode: (nodeId: string) => void;
}) {
  const { team, selectedNodeId, blocked, onSelectNode } = props;
  return (
    <div className={styles.rail} data-testid="status-rail">
      <VSurface tone="panel" padding="compact" className={styles.nextCard}>
        <span className={styles.nextKicker}>下一步</span>
        <p className={styles.nextTitle}>{team.nextTitle}</p>
        <p className={styles.nextBody}>{team.nextBody}</p>
        <VButton type="button" density="compact" variant="primary">
          {team.cta}
        </VButton>
        <VStatusStrip
          items={team.metrics.map((item) => ({
            label: item.label,
            value: blocked && item.label === "阻塞" ? "1" : item.value,
            tone: item.label === "阻塞" && blocked ? "danger" : "neutral",
          }))}
        />
      </VSurface>
      <div className={styles.stageList} aria-label="阶段">
        {team.stages.map((stage) => (
          <div
            key={stage.id}
            className={stage.tone === "active" ? styles.stageItemActive : styles.stageItem}
          >
            <strong>{stage.title}</strong>
            <VStatusChip tone={statusChipTone(stage.tone)}>{stage.status}</VStatusChip>
          </div>
        ))}
      </div>
      <div className={styles.nodeIndex} aria-label="节点状态">
        {team.nodes.map((node) => {
          const selected = selectedNodeId === node.id;
          return (
            <VNativeButton
              key={node.id}
              type="button"
              className={selected ? styles.nodeIndexItemActive : styles.nodeIndexItem}
              aria-pressed={selected}
              data-testid={`rail-node-${node.id}`}
              onClick={() => onSelectNode(node.id)}
            >
              <strong>{node.label}</strong>
              <VStatusChip tone={statusChipTone(node.statusTone)}>{node.status}</VStatusChip>
              <span>{node.agent}</span>
            </VNativeButton>
          );
        })}
      </div>
    </div>
  );
}

function NodeInspector(props: {
  team: PreviewTeam;
  node: PreviewNode | null;
  blocked: boolean;
}) {
  const { team, node, blocked } = props;
  return (
    <aside className={styles.inspector} data-testid="inspector">
      <div className={styles.inspectorHeader}>
        <strong>{node ? "节点详情" : "团队详情"}</strong>
        {node ? <Eye size={15} /> : <Users size={15} />}
      </div>
      {node ? (
        <div className={styles.inspectorGrid}>
          <div>
            <span>节点</span>
            <strong>{node.label}</strong>
          </div>
          <div>
            <span>职责</span>
            <strong>{node.role}</strong>
          </div>
          <div>
            <span>Agent</span>
            <strong>{node.agent}</strong>
          </div>
          <div>
            <span>状态</span>
            <strong>{node.status}</strong>
          </div>
          <div>
            <span>目的</span>
            <strong>{node.purpose}</strong>
          </div>
        </div>
      ) : (
        <p className={styles.inspectorEmpty} data-testid="inspector-empty">
          点选画布节点查看绑定与职责。未选中时这里只放当前团队摘要，不再跟左栏抢「选团队」。
        </p>
      )}
      {!node ? (
        <div className={styles.inspectorGrid}>
          <div>
            <span>团队</span>
            <strong>{team.name}</strong>
          </div>
          <div>
            <span>类型</span>
            <strong>{team.kind}</strong>
          </div>
          <div>
            <span>用途</span>
            <strong>{team.purpose}</strong>
          </div>
        </div>
      ) : null}
      {blocked && (!node || node.id === BLOCKED_ISSUE.nodeId) ? (
        <div className={styles.issue} data-testid="inspector-issue">
          <strong>{BLOCKED_ISSUE.code}</strong>
          <span>{BLOCKED_ISSUE.message}</span>
        </div>
      ) : (
        <span>{blocked ? "其余节点校验通过" : "画布校验通过"}</span>
      )}
    </aside>
  );
}

function ProposedShell(props: {
  team: PreviewTeam;
  selectedNodeId: string | null;
  blocked: boolean;
  onSelectTeam: (teamId: TeamId) => void;
  onSelectNode: (nodeId: string) => void;
}) {
  const { team, selectedNodeId, blocked, onSelectTeam, onSelectNode } = props;
  const selectedNode = nodeById(team, selectedNodeId);
  return (
    <VCanvasWorkbenchPage
      className={styles.proposed}
      hideHeader
      domainRecipe="teams-organization-workbench"
      shellTestId="team-shell-workspace"
      shellMode="canvas"
      ariaLabel="挑战杯团队画布建议布局"
      title={team.name}
      data-testid="layout-proposed"
      toolbar={(
        <VToolbar ariaLabel="团队画布" className={styles.toolbar}>
          <div className={styles.toolbarSwitch}>
            <VSelect
              density="compact"
              aria-label="切换团队"
              data-vui="team-select"
              selectedKey={team.id}
              options={TEAMS.map((item) => ({
                id: item.id,
                label: item.name,
                description: item.kind,
              }))}
              onSelectionChange={(key) => {
                if (key == null) return;
                onSelectTeam(String(key) as TeamId);
              }}
            />
          </div>
          <div className={styles.toolbarMeta}>
            <VStatusChip tone="accent">{team.kind}</VStatusChip>
          </div>
          <VActionGroup ariaLabel="画布操作" className={styles.toolbarActions}>
            <VButton type="button" density="compact" variant="ghost" icon={<Link2 size={14} />}>
              连线
            </VButton>
            <VButton type="button" density="compact" variant="ghost" icon={<Plus size={14} />}>
              节点
            </VButton>
            <VButton type="button" density="compact" variant="ghost" icon={<Archive size={14} />}>
              归档
            </VButton>
          </VActionGroup>
        </VToolbar>
      )}
      rail={(
        <StatusRail
          team={team}
          selectedNodeId={selectedNodeId}
          blocked={blocked}
          onSelectNode={onSelectNode}
        />
      )}
      canvas={(
        <OrgCanvas team={team} selectedNodeId={selectedNodeId} onSelectNode={onSelectNode} />
      )}
      inspector={(
        <NodeInspector team={team} node={selectedNode} blocked={blocked} />
      )}
    />
  );
}

export function ChallengeCupTeamCanvasPreviewApp() {
  const [layout, setLayout] = useState<LayoutMode>("proposed");
  const [scene, setScene] = useState<SceneId>("selected");
  const [teamId, setTeamId] = useState<TeamId>("challenge");
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(DEFAULT_SELECTED_NODE.selected);
  const team = teamById(teamId);
  const blocked = scene === "blocked";
  const narrow = scene === "narrow";

  const analogItems = useMemo(
    () => [
      { rank: "1", text: "Figma / n8n：组织图画布占主列，选中对象才出检查器。" },
      { rank: "2", text: "Linear / LangSmith：团队换到顶栏下拉，左栏不再当通讯录。" },
      { rank: "3", text: "Elicit：下一步和阶段当索引，不压在图上方。" },
    ],
    [],
  );

  const applyScene = (next: SceneId) => {
    setScene(next);
    setTeamId("challenge");
    const preset = DEFAULT_SELECTED_NODE[next];
    setSelectedNodeId(preset);
    if (next === "narrow") {
      setLayout("proposed");
    }
  };

  const selectTeam = (next: TeamId) => {
    setTeamId(next);
    const nextTeam = teamById(next);
    setSelectedNodeId((current) => (
      current && nextTeam.nodes.some((node) => node.id === current) ? current : null
    ));
  };

  return (
    <main className={styles.page} data-testid="preview-app">
      <header className={styles.header}>
        <p className={styles.eyebrow}>CHALLENGE CUP · TEAM CANVAS</p>
        <h1>挑战杯团队画布</h1>
        <p className={styles.subtitle}>
          这是组织关系图画布的隔离预览，不是科研流程步骤页。建议：顶栏切团队，左栏放状态，中间画布做事，右侧只出节点详情。
        </p>
        <div className={styles.analogs}>
          {analogItems.map((item) => (
            <div key={item.rank} className={styles.analog}>
              <span className={styles.analogRank}>{item.rank}</span>
              <span>{item.text}</span>
            </div>
          ))}
        </div>
        <div className={styles.scenes}>
          <VButton
            type="button"
            density="compact"
            variant={layout === "current" ? "secondary" : "ghost"}
            data-testid="compare-current"
            onClick={() => setLayout("current")}
          >
            现在
          </VButton>
          <VButton
            type="button"
            density="compact"
            variant={layout === "proposed" ? "secondary" : "ghost"}
            data-testid="compare-proposed"
            onClick={() => setLayout("proposed")}
          >
            建议
          </VButton>
          {SCENE_ORDER.map((id) => (
            <VButton
              key={id}
              type="button"
              density="compact"
              variant={scene === id ? "secondary" : "ghost"}
              data-testid={`scene-${id}`}
              onClick={() => applyScene(id)}
            >
              {SCENE_LABEL[id]}
            </VButton>
          ))}
        </div>
      </header>
      <div
        className={narrow ? styles.frameNarrow : styles.frame}
        data-testid="preview-frame"
        data-layout={layout}
        data-scene={scene}
      >
        {layout === "current" ? (
          <CurrentShell
            team={team}
            selectedNodeId={selectedNodeId}
            onSelectTeam={selectTeam}
            onSelectNode={setSelectedNodeId}
          />
        ) : (
          <ProposedShell
            team={team}
            selectedNodeId={selectedNodeId}
            blocked={blocked}
            onSelectTeam={selectTeam}
            onSelectNode={setSelectedNodeId}
          />
        )}
      </div>
      <p className={styles.note}>
        假数据，不写团队 API。批准前不会改 TeamsCanvasComposer / TeamShellRail。回复 APPROVED / REVISE / ABANDON。
      </p>
    </main>
  );
}

const previewRoot = document.getElementById("root");
if (previewRoot) {
  createRoot(previewRoot).render(
    <StrictMode>
      <VuiProvider>
        <ChallengeCupTeamCanvasPreviewApp />
      </VuiProvider>
    </StrictMode>,
  );
}
