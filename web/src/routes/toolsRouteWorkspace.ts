export type ToolsWorkspaceView = "library" | "policy";

/** An explicit view is a manual navigation choice; deep links only choose the initial view. */
export function resolveToolsWorkspaceView(params: URLSearchParams): ToolsWorkspaceView {
  const view = params.get("view");
  if (view === "library" || view === "policy") return view;
  const focus = params.get("focus")?.trim().toLowerCase();
  if (focus === "detail" || focus === "test") return "library";
  if (focus === "policy" || focus === "bundle") return "policy";
  if (params.get("tool") || params.get("toolId")) return "library";
  if (params.get("bundle") || params.get("bundleId") || params.get("agent")) return "policy";
  return "library";
}

/** Keep each selected identifier in the URL so deep-link effects cannot snap a manual selection back. */
export function toolsWorkspaceParams(params: URLSearchParams, patch: Partial<Record<"view" | "agent" | "scope" | "tool" | "bundle", string>>): URLSearchParams {
  const next = new URLSearchParams(params);
  for (const [key, value] of Object.entries(patch)) next.set(key, value);
  if (patch.view) next.delete("focus");
  if (patch.tool) next.delete("toolId");
  if (patch.bundle) next.delete("bundleId");
  return next;
}
