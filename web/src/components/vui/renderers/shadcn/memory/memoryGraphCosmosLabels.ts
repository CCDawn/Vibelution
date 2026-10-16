import { createMemoryGraphLabelElements as createOriginalLabels, positionMemoryGraphLabels as positionOriginalLabels } from "./memoryGraphLabels";
import { memoryGraphRendererStyles as styles } from "./memoryGraphRenderer.styles";
export { buildMemoryGraphAdjacency } from "./memoryGraphLabels";
export type { MemoryGraphLabelElements, MemoryGraphEdgePath } from "./memoryGraphLabels";

type Placement = { offsetY: number; width: number; height: number };
type Labels = Parameters<typeof positionOriginalLabels>[0]["elements"];
const layouts = new WeakMap<Labels, {
  key: string; mode: "overview" | "detail"; placements: Map<string, Placement>; edgePlacements: Map<string, Placement>;
}>();

export const createMemoryGraphCosmosLabelElements: typeof createOriginalLabels = (...args) => {
  const elements = createOriginalLabels(...args);
  for (const node of args[1]) {
    const button = elements.nodeButtons.get(node.id)!;
    // Keep summaries in the inspector; hover must not resize projected labels.
    if (button.children.length > 1) button.children[1].remove();
    if (node.source.type === "topic") {
      button.className = styles.cosmosTopicLabel;
      button.querySelector("span")!.textContent = node.clusterLabel;
      const count = document.createElement("span");
      count.className = styles.cosmosCount;
      count.textContent = String(node.source.metadata.memberCount ?? 0) + " 条知识";
      button.append(count);
    } else button.className = styles.cosmosRecordLabel;
  }
  for (const edge of args[2]) {
    const button = elements.edgeButtons.get(edge.id)!;
    button.className = styles.cosmosEdgeLabel;
    button.textContent = (edge.metadata.status === "candidate" ? "待确认 · " : "") + (edge.label || edge.type);
    button.dataset.relationLayer = String(edge.metadata.layer);
    button.title = edge.label || edge.type;
  }
  return elements;
};

export const positionMemoryGraphCosmosLabels = (options: Parameters<typeof positionOriginalLabels>[0] & { moving: boolean }) => {
  // Read geometry before writing any label styles. A display:none -> layout
  // read -> display:grid cycle destroyed generated captions every render.
  const width = options.host.clientWidth, height = options.host.clientHeight;
  const moving = options.moving;
  const roots = options.nodes.filter(node => node.source.type === "topic");
  const selected = options.nodes.find(node => node.id === options.selectedNodeId);
  const distance = options.camera.position.distanceTo(options.cameraTarget);
  const proposedMode = selected || options.highlightIds.size || distance < 25 ? "detail" : "overview";
  const key = [options.selectedNodeId,[...options.highlightIds].sort().join(","),width,height,options.labelsVisible].join(":");
  let state = layouts.get(options.elements);
  const mode = moving && state?.key === key ? state.mode : proposedMode;
  options.labelLayer.parentElement!.dataset.zoomLevel = mode;
  const project = (node: typeof options.nodes[number]) => {
    const point = options.scratch.set(node.x,node.y,node.z).project(options.camera);
    return { x: (point.x * 0.5 + 0.5) * width, y: (-point.y * 0.5 + 0.5) * height, visible: point.z >= -1 && point.z <= 1 };
  };
  // Keep the same captions and anchor offsets throughout drag, inertia, zoom,
  // auto-orbit and focus animation. Resolve collisions once the camera settles.
  if (!moving || !state || state.key !== key) {
    const previous = state?.key === key ? state.placements : new Map<string, Placement>();
    const focusCluster = selected?.source.type === "topic" ? selected.clusterKey : undefined;
    const candidates = options.highlightIds.size ? options.nodes.filter(node => options.highlightIds.has(node.id)) : roots.length && !selected && mode === "overview" ? roots
      : [...(selected ? [selected] : []), ...options.nodes.filter(node => node.id !== selected?.id && (focusCluster ? node.clusterKey === focusCluster : selected ? options.adjacent.get(selected.id)?.has(node.id) : node.source.type !== "topic"))];
    const placements = new Map<string, Placement>();
    const occupied: Array<{x:number;y:number;w:number;h:number}> = [];
    const budget = selected ? 12 : roots.length && mode === "overview" ? 10 : 14;
    for (const node of candidates) {
      if (placements.size >= budget || !options.labelsVisible) break;
      const anchor = project(node);
      if (!anchor.visible || anchor.x < 12 || anchor.x > width-12 || anchor.y < 12 || anchor.y > height-16) continue;
      const topic = node.source.type === "topic";
      const text = topic ? node.clusterLabel : node.source.label;
      const w = Math.min(248, width-28, Math.max(104,text.length * (topic ? 15 : 13) + 38)), h = topic ? 46 : 30;
      const x = Math.max(w/2+12,Math.min(width-w/2-12,anchor.x));
      const members = topic ? options.nodes.filter(member => member.clusterKey === node.clusterKey) : [];
      const top = members.length ? Math.min(...members.map(member => project(member).y))-22 : anchor.y-23;
      const old = previous.get(node.id);
      const candidatesY = [...(old ? [anchor.y+old.offsetY] : []), ...(topic ? [top,anchor.y+38,anchor.y-38,anchor.y+65] : [anchor.y-23,anchor.y+24,anchor.y-48])];
      const y = candidatesY.find(candidate => candidate > 32 && candidate < height-42 && !occupied.some(rect => Math.abs(rect.x-x)<(rect.w+w)/2+5 && Math.abs(rect.y-candidate)<(rect.h+h)/2+3));
      if (y === undefined) continue;
      placements.set(node.id,{offsetY:y-anchor.y,width:w,height:h});
      occupied.push({x,y,w,h});
    }
    const edgePlacements = new Map<string,Placement>();
    if (options.labelsVisible && options.canSelectEdge()) for (const path of options.edgePaths) {
      if (edgePlacements.size >= 5) break;
      const connected = selected && selected.source.type !== "topic" && (path.edge.source===selected.id || path.edge.target===selected.id);
      const highlighted = options.highlightIds.has(path.edge.source) && options.highlightIds.has(path.edge.target);
      if (!connected && !highlighted) continue;
      const point = path.curve.getPoint(0.5).project(options.camera);
      const anchor = {x:(point.x*0.5+0.5)*width,y:(-point.y*0.5+0.5)*height};
      if (point.z < -1 || point.z > 1 || anchor.x < 16 || anchor.x > width-16 || anchor.y < 24 || anchor.y > height-24) continue;
      const w = Math.min(width-28,Math.max(64,(path.edge.label||path.edge.type).length*14+28)), h = 28;
      const x = Math.max(w/2+12,Math.min(width-w/2-12,anchor.x));
      const old = state?.key === key ? state.edgePlacements.get(path.edge.id) : undefined;
      const y = [...(old ? [anchor.y+old.offsetY] : []),anchor.y,anchor.y-28,anchor.y+28,anchor.y+52].find(candidate => candidate > 32 && candidate < height-42 && !occupied.some(rect=>Math.abs(rect.x-x)<(rect.w+w)/2+4 && Math.abs(rect.y-candidate)<(rect.h+h)/2+3));
      if (y===undefined) continue;
      edgePlacements.set(path.edge.id,{offsetY:y-anchor.y,width:w,height:h});
      occupied.push({x,y,w,h});
    }
    state = {key,mode,placements,edgePlacements};
    layouts.set(options.elements,state);
  }
  for (const node of options.nodes) {
    const button = options.elements.nodeButtons.get(node.id)!;
    const placement = state.placements.get(node.id);
    if (!placement || !options.labelsVisible) {
      if (button.style.display !== "none") button.style.display = "none";
      continue;
    }
    const anchor = project(node);
    const x = Math.max(placement.width/2+12,Math.min(width-placement.width/2-12,anchor.x));
    button.style.left = x + "px"; button.style.top = anchor.y + placement.offsetY + "px";
    button.style.width = placement.width + "px";
    button.style.visibility = anchor.visible ? "visible" : "hidden";
    if (button.style.display !== "grid") button.style.display = "grid";
    const pressed = String(node.id === options.selectedNodeId);
    if (button.getAttribute("aria-pressed") !== pressed) button.setAttribute("aria-pressed",pressed);
  }
  for (const path of options.edgePaths) {
    const button = options.elements.edgeButtons.get(path.edge.id)!;
    button.disabled = !options.canSelectEdge();
    const placement = state.edgePlacements.get(path.edge.id);
    if (!placement || !options.labelsVisible) { if (button.style.display!=="none") button.style.display="none"; continue; }
    const point = path.curve.getPoint(0.5).project(options.camera);
    const x = Math.max(placement.width/2+12,Math.min(width-placement.width/2-12,(point.x*0.5+0.5)*width));
    button.style.left = x+"px"; button.style.top = (-point.y*0.5+0.5)*height+placement.offsetY+"px";
    button.style.width = placement.width+"px"; button.style.visibility = point.z>=-1 && point.z<=1 ? "visible" : "hidden";
    if (button.style.display!=="grid") button.style.display="grid";
  }
  return state.mode;
};
