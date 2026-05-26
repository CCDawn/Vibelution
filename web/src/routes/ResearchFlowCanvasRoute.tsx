import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  CirclePlus,
  GitBranchPlus,
  Link2,
  MousePointer2,
  Save,
  Trash2,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { PointerEvent } from "react";
import { Link } from "react-router-dom";

import { fetchJson } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import {
  ResearchAgentConfig,
  ResearchFlowCanvas,
  ResearchFlowEdge,
  ResearchFlowNode,
  ResearchPromptWorkspace,
} from "../api/types";
import styles from "./ResearchFlowCanvasRoute.module.css";

type Selection =
  | { kind: "node"; id: string }
  | { kind: "edge"; id: string }
  | null;

type ConnectState = {
  active: boolean;
  sourceId: string | null;
};

type DragState = {
  nodeId: string;
  originX: number;
  originY: number;
  startX: number;
  startY: number;
};

const NODE_WIDTH = 220;
const NODE_HEIGHT = 112;

const STATUS_OPTIONS = [
  { value: "idle", label: "未开始" },
  { value: "ready", label: "就绪" },
  { value: "running", label: "运行中" },
  { value: "done", label: "已完成" },
  { value: "failed", label: "失败" },
  { value: "stale", label: "需复核" },
  { value: "needs_review", label: "待审查" },
  { value: "needs_input", label: "待输入" },
  { value: "needs_evidence", label: "缺证据" },
  { value: "blocked", label: "阻塞" },
  { value: "skipped", label: "跳过" },
] as const;

const NODE_TYPE_OPTIONS = [
  { value: "agent", label: "Agent" },
  { value: "decision", label: "判断" },
  { value: "artifact", label: "产物" },
  { value: "human", label: "人工" },
  { value: "tool", label: "工具" },
  { value: "evaluation", label: "评估" },
] as const;

function cloneCanvas(canvas: ResearchFlowCanvas): ResearchFlowCanvas {
  return {
    ...canvas,
    viewport: { ...canvas.viewport },
    nodes: canvas.nodes.map((node) => ({ ...node })),
    edges: canvas.edges.map((edge) => ({ ...edge })),
  };
}

function canvasSignature(canvas: ResearchFlowCanvas | null) {
  if (!canvas) {
    return "";
  }
  return JSON.stringify({
    viewport: canvas.viewport,
    nodes: canvas.nodes,
    edges: canvas.edges,
  });
}

function nodeCenter(node: ResearchFlowNode) {
  return {
    x: node.x + NODE_WIDTH / 2,
    y: node.y + NODE_HEIGHT / 2,
  };
}

function statusLabel(status: string) {
  return STATUS_OPTIONS.find((option) => option.value === status)?.label ?? status;
}

function statusClass(status: string) {
  return styles[`status_${status}` as keyof typeof styles] ?? styles.status_idle;
}

function nextNodeId(nodes: ResearchFlowNode[]) {
  let index = nodes.length + 1;
  let id = `custom_node_${index}`;
  const known = new Set(nodes.map((node) => node.id));
  while (known.has(id)) {
    index += 1;
    id = `custom_node_${index}`;
  }
  return id;
}

function nextEdgeId(edges: ResearchFlowEdge[]) {
  let index = edges.length + 1;
  let id = `custom_edge_${index}`;
  const known = new Set(edges.map((edge) => edge.id));
  while (known.has(id)) {
    index += 1;
    id = `custom_edge_${index}`;
  }
  return id;
}

export function ResearchFlowCanvasRoute() {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<ResearchFlowCanvas | null>(null);
  const [savedSignature, setSavedSignature] = useState("");
  const [selection, setSelection] = useState<Selection>(null);
  const [connect, setConnect] = useState<ConnectState>({ active: false, sourceId: null });
  const [drag, setDrag] = useState<DragState | null>(null);

  const canvasQuery = useQuery({
    queryKey: queryKeys.researchFlowCanvas(),
    queryFn: () => fetchJson<ResearchFlowCanvas>("/api/research/flow-canvas"),
  });

  const promptsQuery = useQuery({
    queryKey: queryKeys.researchThemeDiscoveryPrompts(),
    queryFn: () => fetchJson<ResearchPromptWorkspace>("/api/research/theme-discovery/prompts"),
  });

  useEffect(() => {
    if (canvasQuery.data) {
      const next = cloneCanvas(canvasQuery.data);
      setDraft(next);
      setSavedSignature(canvasSignature(next));
      setSelection((current) => {
        if (!current) {
          return { kind: "node", id: next.nodes[0]?.id ?? "" };
        }
        if (current.kind === "node" && next.nodes.some((node) => node.id === current.id)) {
          return current;
        }
        if (current.kind === "edge" && next.edges.some((edge) => edge.id === current.id)) {
          return current;
        }
        return { kind: "node", id: next.nodes[0]?.id ?? "" };
      });
    }
  }, [canvasQuery.data]);

  useEffect(() => {
    if (!drag) {
      return undefined;
    }
    const handleMove = (event: PointerEvent | globalThis.PointerEvent) => {
      setDraft((current) => {
        if (!current) {
          return current;
        }
        return {
          ...current,
          nodes: current.nodes.map((node) =>
            node.id === drag.nodeId
              ? {
                  ...node,
                  x: Math.max(0, drag.startX + event.clientX - drag.originX),
                  y: Math.max(0, drag.startY + event.clientY - drag.originY),
                }
              : node,
          ),
        };
      });
    };
    const handleUp = () => setDrag(null);
    window.addEventListener("pointermove", handleMove);
    window.addEventListener("pointerup", handleUp, { once: true });
    return () => {
      window.removeEventListener("pointermove", handleMove);
      window.removeEventListener("pointerup", handleUp);
    };
  }, [drag]);

  const dirty = useMemo(() => canvasSignature(draft) !== savedSignature, [draft, savedSignature]);
  const selectedNode = draft && selection?.kind === "node" ? draft.nodes.find((node) => node.id === selection.id) ?? null : null;
  const selectedEdge = draft && selection?.kind === "edge" ? draft.edges.find((edge) => edge.id === selection.id) ?? null : null;
  const agentOptions = promptsQuery.data?.agents ?? [];
  const llmOptions = promptsQuery.data?.llmConfigs ?? [];

  const saveMutation = useMutation({
    mutationFn: async (payload: ResearchFlowCanvas) =>
      fetchJson<ResearchFlowCanvas>("/api/research/flow-canvas", {
        method: "PUT",
        body: JSON.stringify({
          schemaVersion: payload.schemaVersion,
          viewport: payload.viewport,
          nodes: payload.nodes,
          edges: payload.edges,
        }),
      }),
    onSuccess: async (saved) => {
      const next = cloneCanvas(saved);
      setDraft(next);
      setSavedSignature(canvasSignature(next));
      await queryClient.invalidateQueries({ queryKey: queryKeys.researchFlowCanvas() });
    },
  });

  const updateNode = (nodeId: string, patch: Partial<ResearchFlowNode>) => {
    setDraft((current) =>
      current
        ? {
            ...current,
            nodes: current.nodes.map((node) => (node.id === nodeId ? { ...node, ...patch } : node)),
          }
        : current,
    );
  };

  const updateEdge = (edgeId: string, patch: Partial<ResearchFlowEdge>) => {
    setDraft((current) =>
      current
        ? {
            ...current,
            edges: current.edges.map((edge) => (edge.id === edgeId ? { ...edge, ...patch } : edge)),
          }
        : current,
    );
  };

  const addNode = () => {
    setDraft((current) => {
      if (!current) {
        return current;
      }
      const id = nextNodeId(current.nodes);
      const node: ResearchFlowNode = {
        id,
        label: "新科研模块",
        type: "agent",
        status: "idle",
        x: 120 + (current.nodes.length % 4) * 260,
        y: 180 + Math.floor(current.nodes.length / 4) * 170,
        agentKey: "",
        promptKey: "",
        llmConfigId: "",
        description: "描述这个模块要完成的科研动作、工具使用和可观察结果。",
        routeCondition: "填写进入这个模块的条件。",
      };
      setSelection({ kind: "node", id });
      return { ...current, nodes: [...current.nodes, node] };
    });
  };

  const deleteSelected = () => {
    if (!draft || !selection) {
      return;
    }
    if (selection.kind === "node") {
      setDraft({
        ...draft,
        nodes: draft.nodes.filter((node) => node.id !== selection.id),
        edges: draft.edges.filter((edge) => edge.source !== selection.id && edge.target !== selection.id),
      });
    } else {
      setDraft({ ...draft, edges: draft.edges.filter((edge) => edge.id !== selection.id) });
    }
    setSelection(null);
  };

  const handleNodePointerDown = (event: PointerEvent<HTMLButtonElement>, node: ResearchFlowNode) => {
    if (connect.active) {
      return;
    }
    event.currentTarget.setPointerCapture(event.pointerId);
    setSelection({ kind: "node", id: node.id });
    setDrag({
      nodeId: node.id,
      originX: event.clientX,
      originY: event.clientY,
      startX: node.x,
      startY: node.y,
    });
  };

  const handleNodeClick = (node: ResearchFlowNode) => {
    if (!connect.active) {
      setSelection({ kind: "node", id: node.id });
      return;
    }
    if (!connect.sourceId) {
      setConnect({ active: true, sourceId: node.id });
      setSelection({ kind: "node", id: node.id });
      return;
    }
    if (connect.sourceId === node.id || !draft) {
      return;
    }
    const edge: ResearchFlowEdge = {
      id: nextEdgeId(draft.edges),
      source: connect.sourceId,
      target: node.id,
      label: "新路由",
      condition: "填写触发条件",
    };
    setDraft({ ...draft, edges: [...draft.edges, edge] });
    setSelection({ kind: "edge", id: edge.id });
    setConnect({ active: false, sourceId: null });
  };

  const fitView = () => {
    if (!draft) {
      return;
    }
    setDraft({ ...draft, viewport: { x: 0, y: 0, zoom: 1 } });
  };

  const applyAgentBinding = (agent: ResearchAgentConfig | undefined) => {
    if (!selectedNode || !agent) {
      return;
    }
    updateNode(selectedNode.id, {
      agentKey: agent.key,
      promptKey: agent.key,
      llmConfigId: agent.llmConfigId,
    });
  };

  const canvasWidth = Math.max(1480, ...(draft?.nodes.map((node) => node.x + NODE_WIDTH + 120) ?? [1480]));
  const canvasHeight = Math.max(760, ...(draft?.nodes.map((node) => node.y + NODE_HEIGHT + 120) ?? [760]));

  return (
    <section className={styles.route}>
      <header className={styles.header}>
        <div className={styles.heading}>
          <p>Research Flow Canvas</p>
          <h1>科研流程画布</h1>
          <span>把科研流程改成可配置的动态路线图：模块、状态、路由、Agent 和 LLM 都在这里统一编排。</span>
        </div>
        <div className={styles.headerActions}>
          <Link className={styles.secondaryButton} to="/research">
            <ArrowLeft size={16} />
            返回科研页
          </Link>
          <button className={styles.secondaryButton} type="button" onClick={fitView} disabled={!draft}>
            <MousePointer2 size={16} />
            复位视图
          </button>
          <button
            className={connect.active ? styles.primaryButton : styles.secondaryButton}
            type="button"
            onClick={() => setConnect((current) => ({ active: !current.active, sourceId: null }))}
          >
            <Link2 size={16} />
            {connect.active ? (connect.sourceId ? "选择目标" : "选择起点") : "连线"}
          </button>
          <button className={styles.secondaryButton} type="button" onClick={addNode} disabled={!draft}>
            <CirclePlus size={16} />
            新增模块
          </button>
          <button className={styles.dangerButton} type="button" onClick={deleteSelected} disabled={!selection}>
            <Trash2 size={16} />
            删除
          </button>
          <button
            className={styles.primaryButton}
            type="button"
            onClick={() => draft && saveMutation.mutate(draft)}
            disabled={!draft || !dirty || saveMutation.isPending}
          >
            <Save size={16} />
            {saveMutation.isPending ? "保存中" : dirty ? "保存画布" : "已保存"}
          </button>
        </div>
      </header>

      <div className={styles.body}>
        <main className={styles.canvasShell} aria-label="科研流程图画布">
          {canvasQuery.isLoading || !draft ? (
            <div className={styles.emptyState}>正在读取 workspace 科研流程画布...</div>
          ) : canvasQuery.isError ? (
            <div className={styles.emptyState}>画布读取失败，请检查后端科研配置接口。</div>
          ) : (
            <div className={styles.canvasScroller}>
              <div
                className={styles.canvas}
                style={{ width: canvasWidth, height: canvasHeight }}
                onClick={() => {
                  if (!connect.active) {
                    setSelection(null);
                  }
                }}
              >
                <svg className={styles.edges} width={canvasWidth} height={canvasHeight} aria-hidden="true">
                  <defs>
                    <marker id="research-flow-arrow" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto">
                      <path d="M0,0 L0,6 L8,3 z" className={styles.arrowMarker} />
                    </marker>
                  </defs>
                  {draft.edges.map((edge) => {
                    const source = draft.nodes.find((node) => node.id === edge.source);
                    const target = draft.nodes.find((node) => node.id === edge.target);
                    if (!source || !target) {
                      return null;
                    }
                    const start = nodeCenter(source);
                    const end = nodeCenter(target);
                    const midX = (start.x + end.x) / 2;
                    const active = selection?.kind === "edge" && selection.id === edge.id;
                    return (
                      <g key={edge.id} className={active ? styles.edgeActive : styles.edge}>
                        <path
                          d={`M ${start.x} ${start.y} C ${midX} ${start.y}, ${midX} ${end.y}, ${end.x} ${end.y}`}
                          markerEnd="url(#research-flow-arrow)"
                        />
                      </g>
                    );
                  })}
                </svg>
                {draft.edges.map((edge) => {
                  const source = draft.nodes.find((node) => node.id === edge.source);
                  const target = draft.nodes.find((node) => node.id === edge.target);
                  if (!source || !target) {
                    return null;
                  }
                  const start = nodeCenter(source);
                  const end = nodeCenter(target);
                  const midX = (start.x + end.x) / 2;
                  const midY = (start.y + end.y) / 2;
                  return (
                    <button
                      key={`${edge.id}-hotspot`}
                      type="button"
                      className={[
                        styles.edgeHotspot,
                        selection?.kind === "edge" && selection.id === edge.id ? styles.edgeHotspotActive : "",
                      ].join(" ")}
                      style={{ left: midX - 58, top: midY - 16 }}
                      onClick={(event) => {
                        event.stopPropagation();
                        setSelection({ kind: "edge", id: edge.id });
                      }}
                    >
                      {edge.label || "路由"}
                    </button>
                  );
                })}
                {draft.nodes.map((node) => {
                  const active = selection?.kind === "node" && selection.id === node.id;
                  const pendingSource = connect.sourceId === node.id;
                  return (
                    <button
                      key={node.id}
                      type="button"
                      className={[
                        styles.node,
                        active ? styles.nodeActive : "",
                        pendingSource ? styles.nodeConnectSource : "",
                      ].join(" ")}
                      style={{ left: node.x, top: node.y }}
                      onPointerDown={(event) => handleNodePointerDown(event, node)}
                      onClick={(event) => {
                        event.stopPropagation();
                        handleNodeClick(node);
                      }}
                    >
                      <span className={styles.nodeTopline}>
                        <span className={`${styles.statusPill} ${statusClass(node.status)}`}>{statusLabel(node.status)}</span>
                        <span>{node.type}</span>
                      </span>
                      <strong>{node.label}</strong>
                      <span className={styles.nodeMeta}>
                        <GitBranchPlus size={14} />
                        {node.agentKey || "未绑定 agent"}
                      </span>
                      <small>{node.routeCondition || "未设置路由条件"}</small>
                    </button>
                  );
                })}
              </div>
            </div>
          )}
        </main>

        <aside className={styles.inspector} aria-label="流程模块配置">
          <div className={styles.inspectorHeader}>
            <p>唯一事实来源</p>
            <strong>{draft?.path || "workspace/prompts/research/flow_canvas.json"}</strong>
            <span>{dirty ? "有未保存修改" : `已同步 ${draft?.updatedAt ?? ""}`}</span>
          </div>

          {selectedNode ? (
            <div className={styles.editorStack}>
              <label>
                模块名称
                <input value={selectedNode.label} onChange={(event) => updateNode(selectedNode.id, { label: event.target.value })} />
              </label>
              <div className={styles.twoColumns}>
                <label>
                  类型
                  <select
                    value={selectedNode.type}
                    onChange={(event) => updateNode(selectedNode.id, { type: event.target.value })}
                  >
                    {NODE_TYPE_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  状态
                  <select
                    value={selectedNode.status}
                    onChange={(event) => updateNode(selectedNode.id, { status: event.target.value })}
                  >
                    {STATUS_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <label>
                Agent 模板
                <select value={selectedNode.agentKey} onChange={(event) => applyAgentBinding(agentOptions.find((agent) => agent.key === event.target.value))}>
                  <option value="">不绑定</option>
                  {agentOptions.map((agent) => (
                    <option key={agent.key} value={agent.key}>
                      {agent.label}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                LLM 配置
                <select
                  value={selectedNode.llmConfigId}
                  onChange={(event) => updateNode(selectedNode.id, { llmConfigId: event.target.value })}
                >
                  <option value="">不绑定</option>
                  {llmOptions.map((option) => (
                    <option key={option.configId} value={option.configId}>
                      {option.label} / {option.model}
                    </option>
                  ))}
                </select>
              </label>
              <div className={styles.twoColumns}>
                <label>
                  Prompt Key
                  <input
                    value={selectedNode.promptKey}
                    onChange={(event) => updateNode(selectedNode.id, { promptKey: event.target.value })}
                  />
                </label>
                <label>
                  Agent Key
                  <input
                    value={selectedNode.agentKey}
                    onChange={(event) => updateNode(selectedNode.id, { agentKey: event.target.value })}
                  />
                </label>
              </div>
              <label>
                进入条件
                <textarea
                  value={selectedNode.routeCondition}
                  onChange={(event) => updateNode(selectedNode.id, { routeCondition: event.target.value })}
                />
              </label>
              <label>
                模块说明
                <textarea
                  value={selectedNode.description}
                  onChange={(event) => updateNode(selectedNode.id, { description: event.target.value })}
                />
              </label>
            </div>
          ) : selectedEdge ? (
            <div className={styles.editorStack}>
              <label>
                路由名称
                <input value={selectedEdge.label} onChange={(event) => updateEdge(selectedEdge.id, { label: event.target.value })} />
              </label>
              <label>
                触发条件
                <textarea
                  value={selectedEdge.condition}
                  onChange={(event) => updateEdge(selectedEdge.id, { condition: event.target.value })}
                />
              </label>
              <div className={styles.edgePair}>
                <span>{draft?.nodes.find((node) => node.id === selectedEdge.source)?.label ?? selectedEdge.source}</span>
                <strong>→</strong>
                <span>{draft?.nodes.find((node) => node.id === selectedEdge.target)?.label ?? selectedEdge.target}</span>
              </div>
            </div>
          ) : (
            <div className={styles.emptyInspector}>
              <strong>选择一个模块或路由</strong>
              <span>点击画布节点可编辑状态、提示词、LLM 和进入条件；开启连线后先点起点再点目标。</span>
            </div>
          )}
        </aside>
      </div>
    </section>
  );
}
