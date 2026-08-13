import {
  fetchLauncherBranchInstanceRecords,
  matchBranchInstanceByProjectRoot,
  postLauncherControl,
  type BranchInstanceRecord
} from "./launcherControlClient.js";

export type ApplyProjectSlotInput = {
  projectRoot: string;
  launcherOrigin: string;
  controlToken: string;
  fetchImpl?: typeof fetch;
  requestTimeoutMs?: number;
};

export type ApplyProjectSlotResult = {
  instanceId: string;
  url: string;
  started: boolean;
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

export async function applyProjectSlot(input: ApplyProjectSlotInput): Promise<ApplyProjectSlotResult> {
  const projectRoot = String(input.projectRoot || "").trim();
  if (!projectRoot) {
    throw new Error("未指定要应用的工作区路径。");
  }
  const listed = await fetchLauncherBranchInstanceRecords(input);
  let matched = matchBranchInstanceByProjectRoot(listed, projectRoot);
  if (matched === null) {
    throw new Error(`找不到对应工作区：${projectRoot}`);
  }
  if (!matched.checkedOut) {
    throw new Error("该工作区未打开，无法应用。");
  }
  let started = false;
  if (!matched.alive) {
    await postLauncherControl({
      launcherOrigin: input.launcherOrigin,
      controlToken: input.controlToken,
      path: "/api/launcher/branch-instances/start",
      trigger: "electron_project_apply",
      body: { instanceId: matched.id },
      fetchImpl: input.fetchImpl,
      requestTimeoutMs: input.requestTimeoutMs
    });
    started = true;
    const refreshed = await fetchLauncherBranchInstanceRecords(input);
    matched = matchBranchInstanceByProjectRoot(refreshed, projectRoot) ?? matched;
  }
  const url = instanceWorkbenchUrl(matched);
  if (!url) {
    throw new Error(`工作区已匹配但没有可打开的地址：${matched.id}`);
  }
  return {
    instanceId: matched.id,
    url,
    started
  };
}
