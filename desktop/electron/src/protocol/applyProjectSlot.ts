import {
  matchBranchInstanceByProjectRoot,
  type BranchInstanceRecord
} from "./launcherControlClient.js";

export const PROJECT_SLOT_LIFECYCLE_COMMANDS = new Set([
  "start",
  "stop",
  "force-stop",
  "restart",
  "rebuild-and-start"
]);

export type ProjectSlotPlan = {
  instanceId: string;
  url: string;
  kind: string;
  current: boolean;
  alive: boolean;
  isMain: boolean;
  operation: "" | "start" | "stop" | "force-stop" | "restart" | "rebuild-and-start";
};

export function instanceWorkbenchUrl(item: Pick<BranchInstanceRecord, "url" | "port">): string {
  const url = String(item.url || "").trim();
  if (url) {
    return url.endsWith("/") ? url : `${url}/`;
  }
  const port = Number(item.port || 0);
  if (Number.isFinite(port) && port > 0) {
    return `http://127.0.0.1:${port}/`;
  }
  return "";
}

export function isMainProjectSlot(item: Pick<BranchInstanceRecord, "id" | "current" | "kind">): boolean {
  return item.id === "main" || item.current === true || item.kind === "main";
}

export function planProjectSlot(input: {
  items: BranchInstanceRecord[];
  projectRoot: string;
  lifecycleCommand?: string;
}): ProjectSlotPlan {
  const projectRoot = String(input.projectRoot || "").trim();
  if (!projectRoot) {
    throw new Error("未指定要应用的工作区路径。");
  }
  const matched = matchBranchInstanceByProjectRoot(input.items, projectRoot);
  if (matched === null) {
    throw new Error(`找不到对应工作区：${projectRoot}`);
  }
  if (!matched.checkedOut) {
    throw new Error("该工作区未打开，无法应用。");
  }
  const requested = String(input.lifecycleCommand || "").trim().toLowerCase();
  let operation: ProjectSlotPlan["operation"] = "";
  if (PROJECT_SLOT_LIFECYCLE_COMMANDS.has(requested)) {
    operation = requested as ProjectSlotPlan["operation"];
  } else if (requested !== "status" && requested !== "toggle" && !matched.alive) {
    operation = "start";
  }
  const url = instanceWorkbenchUrl(matched);
  if (!url && operation !== "start" && operation !== "restart" && operation !== "rebuild-and-start") {
    throw new Error(`工作区已匹配但没有可打开的地址：${matched.id}`);
  }
  return {
    instanceId: matched.id,
    url,
    kind: matched.kind,
    current: matched.current,
    alive: matched.alive,
    isMain: isMainProjectSlot(matched),
    operation
  };
}
