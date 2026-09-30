import { useEffect, useMemo, useRef, useState } from "react";
import { ShadcnButton } from "../ShadcnButton";

import type { VMemoryGraphCanvasProps } from "../../../product/memory/VMemoryGraphCanvas";
import { layoutMemoryKnowledgeGraph } from "../../../product/memory/memoryGraphModel";
import { createMemoryGraphEngine, type MemoryGraphEngine } from "./MemoryGraphEngine";
import { memoryGraphRendererStyles as styles } from "./memoryGraphRenderer.styles";

const EMPTY_HIGHLIGHTS: string[] = [];

type WebGlState = "pending" | "ready" | "failed";

export function ShadcnMemoryGraphCanvas(props: VMemoryGraphCanvasProps) {
  const {
    nodes,
    edges,
    selectedNodeId,
    fallbackText,
    flat = false,
    focusToken,
    onSelectNode,
    onSelectEdge,
  } = props;
  const highlightIds = props.highlightIds ?? EMPTY_HIGHLIGHTS;
  const layout = useMemo(() => layoutMemoryKnowledgeGraph(nodes, edges), [nodes, edges]);
  const rendererLayout = useMemo(() => {
    if (!flat) return layout;
    return {
      nodes: layout.nodes.map((node) => ({ ...node, z: 0 })),
      clusters: layout.clusters.map((cluster) => ({
        ...cluster,
        center: { ...cluster.center, z: 0 },
      })),
    };
  }, [flat, layout]);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const canvasHostRef = useRef<HTMLDivElement | null>(null);
  const labelLayerRef = useRef<HTMLDivElement | null>(null);
  const engineRef = useRef<MemoryGraphEngine | null>(null);
  const onSelectNodeRef = useRef(onSelectNode);
  const onSelectEdgeRef = useRef(onSelectEdge);
  const currentPropsRef = useRef({ selectedNodeId, flat, highlightIds });
  const focusStateRef = useRef({
    token: focusToken,
    primed: false,
    pending: false,
  });
  const [webglState, setWebglState] = useState<WebGlState>("pending");

  onSelectNodeRef.current = onSelectNode;
  onSelectEdgeRef.current = onSelectEdge;
  currentPropsRef.current = { selectedNodeId, flat, highlightIds };

  useEffect(() => {
    const host = canvasHostRef.current;
    const labelLayer = labelLayerRef.current;
    if (!host || !labelLayer) return;
    const canvasHost = host;
    const graphLabelLayer = labelLayer;

    let abandoned = false;
    let themeObserver: MutationObserver | null = null;
    engineRef.current = null;
    setWebglState("pending");

    const fail = () => {
      if (!abandoned) setWebglState("failed");
    };

    const observeTheme = (engine: MemoryGraphEngine) => {
      if (typeof MutationObserver === "undefined") return;
      themeObserver = new MutationObserver(() => engine.refreshTheme());
      let target: Element | null = rootRef.current;
      while (target) {
        themeObserver.observe(target, {
          attributes: true,
          attributeFilter: ["class", "data-theme", "style"],
        });
        target = target.parentElement;
      }
    };

    const initialize = async () => {
      try {
        const [THREE, controlsModule] = await Promise.all([
          import("three"),
          import("three/addons/controls/OrbitControls.js"),
        ]);
        if (abandoned) return;

        const initial = currentPropsRef.current;
        const engine = createMemoryGraphEngine({
          THREE,
          OrbitControls: controlsModule.OrbitControls,
          host: canvasHost,
          labelLayer: graphLabelLayer,
          nodes: rendererLayout.nodes,
          clusters: rendererLayout.clusters,
          edges,
          selectedNodeId: initial.selectedNodeId,
          flat: initial.flat,
          highlightIds: initial.highlightIds,
          showLabels: true,
          onSelectNode: (id) => onSelectNodeRef.current(id),
          onSelectEdge: (id) => onSelectEdgeRef.current?.(id),
          canSelectEdge: () => Boolean(onSelectEdgeRef.current),
          onFailure: (reason) => {
            if (reason) {
              console.warn("[VMemoryGraphCanvas] WebGL canvas unavailable; using list fallback", reason);
            }
            fail();
          },
        });
        if (abandoned) {
          engine?.dispose();
          return;
        }
        if (!engine) {
          fail();
          return;
        }

        engineRef.current = engine;
        observeTheme(engine);
        setWebglState("ready");
      } catch (error) {
        console.warn("[VMemoryGraphCanvas] renderer initialization failed; using list fallback", error);
        fail();
      }
    };

    void initialize();
    return () => {
      abandoned = true;
      themeObserver?.disconnect();
      engineRef.current?.dispose();
      engineRef.current = null;
    };
  }, [rendererLayout, edges]);

  useEffect(() => {
    const engine = engineRef.current;
    engine?.updateSelection(selectedNodeId);
    engine?.updateHighlights(highlightIds);
    engine?.updateFlat(flat);
  }, [selectedNodeId, highlightIds, flat]);

  useEffect(() => {
    const focusState = focusStateRef.current;
    if (!focusState.primed) {
      focusState.token = focusToken;
      focusState.primed = true;
      return;
    }
    if (focusState.token !== focusToken) {
      focusState.token = focusToken;
      if (engineRef.current) engineRef.current.focus(selectedNodeId);
      else focusState.pending = true;
      return;
    }
    if (webglState === "ready" && focusState.pending) {
      engineRef.current?.focus(selectedNodeId);
      focusState.pending = false;
    }
  }, [focusToken, selectedNodeId, webglState]);

  return (
    <div
      ref={rootRef}
      className={styles.rendererRoot}
      data-webgl={webglState}
      data-flat={flat ? "true" : "false"}
      data-zoom-level="overview"
      role="region"
      aria-label="交互式记忆知识图谱"
      aria-busy={webglState === "pending"}
    >
      <div
        ref={canvasHostRef}
        className="absolute inset-0"
        aria-hidden="true"
        hidden={webglState === "failed"}
      />
      <div
        ref={labelLayerRef}
        className={styles.labels}
        role="group"
        aria-label="图谱节点与关系"
        hidden={webglState === "failed"}
      />
      {webglState === "pending" ? (
        <div className={styles.loading} role="status">正在渲染记忆图谱…</div>
      ) : null}
      {webglState === "failed" ? (
        <div className={styles.fallback} role="region" aria-label="记忆图谱节点列表">
          <p className={styles.fallbackIntro} role="status">{fallbackText}</p>
          <ul className={styles.fallbackList}>
            {nodes.map((node) => (
              <li key={node.id} className={styles.fallbackItem}>
                <ShadcnButton
                  type="button"
                  className={styles.fallbackButton}
                  aria-pressed={selectedNodeId === node.id}
                  onClick={() => onSelectNode(node.id)}
                >
                  <span>{node.label}</span>
                  <span className={styles.fallbackSummary}>
                    {node.type}{node.summary ? " · " + node.summary : ""}
                  </span>
                </ShadcnButton>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
