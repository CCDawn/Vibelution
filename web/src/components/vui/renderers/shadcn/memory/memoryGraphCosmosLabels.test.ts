// @vitest-environment happy-dom
import { describe, expect, it } from "vitest";
import { PerspectiveCamera, Vector3 } from "three";
import { layoutMemoryKnowledgeGraph } from "../../../product/memory/memoryGraphModel";
import type { MemoryKnowledgeGraphNode } from "../../../../../api/types";
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
