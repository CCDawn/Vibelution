// @vitest-environment happy-dom
import { describe, expect, it } from "vitest";
import { PerspectiveCamera, QuadraticBezierCurve3, Vector3 } from "three";
import { layoutMemoryKnowledgeGraph } from "../../../product/memory/memoryGraphModel";
import type { MemoryKnowledgeGraphEdge, MemoryKnowledgeGraphNode } from "../../../../../api/types";
import { createMemoryGraphCosmosLabelElements as createMemoryGraphLabelElements, positionMemoryGraphCosmosLabels as positionMemoryGraphLabels } from "./memoryGraphCosmosLabels";

describe("spatial captions while orbiting", () => {
  it("keeps visible captions rendered and their offsets stable throughout camera motion", () => {
    const root = document.createElement("div");
    root.dataset.previewRenderer = "three-original";
    const host = document.createElement("div"), layer = document.createElement("div");
    root.append(host,layer); document.body.append(root);
    Object.defineProperties(host,{clientWidth:{value:1000},clientHeight:{value:600}});
    const roots: MemoryKnowledgeGraphNode[] = ["one", "two"].map(id => ({ id, type: "topic", label: id, summary: "summary", status: "active", createdAt: "", updatedAt: "", metadata: { topicId: id, topicLabel: id, memberCount: 3 }, visual: {}, responsibilityQuestion: "", childNodeIds: [], contentItems: [] })); const layout = layoutMemoryKnowledgeGraph(roots,[],{groupByTopic:true});
    const nodes = layout.nodes.map((node,i) => ({...node,x:i*20-10,y:0,z:i*3-2}));
    const elements = createMemoryGraphLabelElements(layer,nodes,[],layout.clusters,()=>{},()=>{},()=>false);
    const camera = new PerspectiveCamera(46,1000/600,0.1,220);
    camera.position.set(0,0,40); camera.lookAt(0,0,0); camera.updateMatrixWorld();
    const options = {host,labelLayer:layer,camera,fieldOfView:46,nodes,clusters:layout.clusters,edgePaths:[],elements,
      adjacent:new Map<string,Set<string>>(),degree:new Map<string,number>(),selectedNodeId:"",highlightIds:new Set<string>(),labelsVisible:true,
      overviewDistance:40,cameraTarget:new Vector3(),canSelectEdge:()=>false,scratch:new Vector3(),moving:false};
    positionMemoryGraphLabels(options);
    const buttons = [...elements.nodeButtons.values()];
    expect(buttons.every(button=>button.style.display === "grid")).toBe(true);
    const observers = buttons.map(button => {
      const observer = new MutationObserver(()=>{});
      observer.observe(button,{attributes:true,attributeFilter:["style"],attributeOldValue:true});
      return observer;
    });
    const initialOffsets = nodes.map((node,i)=>Number.parseFloat(buttons[i].style.top)-(-new Vector3(node.x,node.y,node.z).project(camera).y*0.5+0.5)*600);
    options.moving = true;
    for (let frame=1;frame<=20;frame++) {
      camera.position.set(frame*0.12,frame*0.03,40); camera.lookAt(0,0,0); camera.updateMatrixWorld();
      positionMemoryGraphLabels(options);
      nodes.forEach((node,i) => {
        expect(buttons[i].style.display).toBe("grid");
        expect(Number.parseFloat(buttons[i].style.top)-(-new Vector3(node.x,node.y,node.z).project(camera).y*0.5+0.5)*600).toBeCloseTo(initialOffsets[i],4);
      });
    }
    // A transient display:none also recreates CSS-generated count captions.
    for (const observer of observers) {
      expect(observer.takeRecords().some(record=>record.oldValue?.includes("display: none"))).toBe(false);
      observer.disconnect();
    }
    root.remove();
  });
});

function record(id: string, type = "knowledge_item"): MemoryKnowledgeGraphNode {
  return { id, type, label: "Long knowledge title " + id, summary: "Inspector summary", status: "active", createdAt: "", updatedAt: "", metadata: {}, visual: {}, responsibilityQuestion: "", childNodeIds: [], contentItems: [] };
}

function labelsFixture(sourceNodes: MemoryKnowledgeGraphNode[], edges: MemoryKnowledgeGraphEdge[] = [], width = 1000, height = 600) {
  const root = document.createElement("div");
  const host = document.createElement("div");
  const layer = document.createElement("div");
  root.append(host, layer);
  Object.defineProperties(host, { clientWidth: { value: width }, clientHeight: { value: height } });
  const layout = layoutMemoryKnowledgeGraph(sourceNodes, edges, { groupByTopic: true });
  const nodes = layout.nodes.map((node, index) => ({ ...node, x: (index % 2 ? 1 : -1) * 4, y: 0, z: 0 }));
  const elements = createMemoryGraphLabelElements(layer, nodes, edges, layout.clusters, () => {}, () => {}, () => true);
  const camera = new PerspectiveCamera(46, width / height, 0.1, 220);
  camera.position.set(0, 0, 15);
  camera.lookAt(0, 0, 0);
  camera.updateMatrixWorld();
  const positions = new Map(nodes.map(node => [node.id, new Vector3(node.x, node.y, node.z)]));
  return {
    host, labelLayer: layer, camera, fieldOfView: 46, nodes, clusters: layout.clusters,
    edgePaths: edges.map(edge => ({ edge, curve: new QuadraticBezierCurve3(positions.get(edge.source)!, new Vector3(), positions.get(edge.target)!) })),
    elements, adjacent: new Map<string, Set<string>>(), degree: new Map<string, number>(), selectedNodeId: "",
    highlightIds: new Set(nodes.map(node => node.id)), labelsVisible: true, overviewDistance: 40,
    cameraTarget: new Vector3(), canSelectEdge: () => true, scratch: new Vector3(), moving: false,
  };
}

function visibleRects(options: ReturnType<typeof labelsFixture>) {
  return [...options.elements.nodeButtons.values(), ...options.elements.edgeButtons.values()]
    .filter(button => button.style.display !== "none" && button.style.visibility !== "hidden")
    .map(button => ({
      x: Number.parseFloat(button.style.left), y: Number.parseFloat(button.style.top),
      width: Number.parseFloat(button.style.width), height: button.dataset.nodeType === "topic" ? 46 : 32,
    }));
}

describe("cosmos caption collision regression", () => {
  it.each([[1000, 600], [390, 520]])("reflows moving captions and relation labels before they overlap at %s by %s", (width, height) => {
    const edge: MemoryKnowledgeGraphEdge = { id: "relation", source: "left", target: "right", type: "related_to", label: "真实关联", weight: 1, metadata: {} };
    const options = labelsFixture([record("left"), record("right")].map(node => ({ ...node, label: node.id })), [edge], width, height);
    positionMemoryGraphLabels(options);
    expect(visibleRects(options).length).toBeGreaterThanOrEqual(2);
    options.moving = true;
    let relocated = false;
    const initialOffsets = options.nodes.map(node => Number.parseFloat(options.elements.nodeButtons.get(node.id)!.style.top) - height / 2);
    for (let frame = 0; frame <= 120; frame++) {
      const angle = frame / 120 * Math.PI / 2;
      options.camera.position.set(Math.sin(angle) * 15, 0, Math.cos(angle) * 15);
      options.camera.lookAt(0, 0, 0);
      options.camera.updateMatrixWorld();
      positionMemoryGraphLabels(options);
      const rects = visibleRects(options);
      expect(rects.length).toBeGreaterThanOrEqual(2);
      for (let left = 0; left < rects.length; left++) {
        expect(rects[left].x - rects[left].width / 2).toBeGreaterThanOrEqual(12);
        expect(rects[left].x + rects[left].width / 2).toBeLessThanOrEqual(width - 12);
        for (const right of rects.slice(left + 1)) {
          const overlaps = Math.abs(rects[left].x - right.x) < (rects[left].width + right.width) / 2 &&
            Math.abs(rects[left].y - right.y) < (rects[left].height + right.height) / 2;
          expect(overlaps).toBe(false);
        }
      }
      relocated ||= options.nodes.some((node, index) => Number.parseFloat(options.elements.nodeButtons.get(node.id)!.style.top) - height / 2 !== initialOffsets[index]);
    }
    expect(relocated).toBe(true);
  });

  it("retains selection before a crowded highlight set even when selection is outside the search", () => {
    const options = labelsFixture(Array.from({ length: 20 }, (_, index) => record("record-" + index)));
    options.nodes.forEach(node => { node.x = 0; });
    options.selectedNodeId = options.nodes.at(-1)!.id;
    options.highlightIds.delete(options.selectedNodeId);
    options.moving = true;
    positionMemoryGraphLabels(options);
    const selected = options.elements.nodeButtons.get(options.selectedNodeId)!;
    expect(selected.style.display).toBe("grid");
    expect(selected.getAttribute("aria-pressed")).toBe("true");
    expect(visibleRects(options).length).toBeLessThan(12);
  });

  it("keeps full titles and a separate topic count while captions use fixed-height styles", () => {
    const longTitle = "中文知识标题与 English knowledge title ".repeat(6);
    const topic = { ...record("topic", "topic"), metadata: { topicId: "science", topicLabel: "科学主题", memberCount: 123 } };
    const edge: MemoryKnowledgeGraphEdge = { id: "candidate", source: "topic", target: "record", type: "related_to", label: longTitle, weight: 1, metadata: { status: "candidate" } };
    const options = labelsFixture([topic, { ...record("record"), label: longTitle }], [edge]);
    const recordButton = options.elements.nodeButtons.get("record")!;
    const topicButton = options.elements.nodeButtons.get("topic")!;
    const edgeButton = options.elements.edgeButtons.get("candidate")!;
    expect(recordButton.title).toBe(longTitle);
    expect(recordButton.firstElementChild!.textContent).toBe(longTitle);
    expect(recordButton.children).toHaveLength(1);
    expect(recordButton.className).toContain("max-h-[32px]");
    expect(topicButton.className).toContain("h-[46px]");
    expect(topicButton.lastElementChild!.textContent).toBe("123 条知识");
    expect(edgeButton.title).toBe(longTitle);
    expect(edgeButton.firstElementChild!.textContent).toBe("待确认 · " + longTitle);
    expect(edgeButton.className).toContain("max-h-[32px]");
  });

  it("keeps a topic-only overview caption at the approved close camera distance", () => {
    const topic = { ...record("topic", "topic"), metadata: { topicId: "science", topicLabel: "科学主题", memberCount: 123 } };
    const options = labelsFixture([topic]);
    options.highlightIds.clear();
    options.nodes[0].x = 0;
    options.camera.position.set(0, 0, 10.08);
    options.camera.lookAt(0, 0, 0);
    options.camera.updateMatrixWorld();
    positionMemoryGraphLabels(options);
    const button = options.elements.nodeButtons.get("topic")!;
    expect(button.style.display).toBe("grid");
    expect(button.lastElementChild!.textContent).toBe("123 条知识");
  });
});
