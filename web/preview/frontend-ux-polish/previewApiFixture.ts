import type { ResearchWorkflowLaunchOptionsResponse } from "../../src/api/researchWorkflow";

/** Offline allowlist only; unknown requests never reach a runtime or upstream fetch. */
export function createPreviewFetch(baseUrl: string, launchOptions: ResearchWorkflowLaunchOptionsResponse): typeof fetch {
  const origin = new URL(baseUrl).origin;
  return async (input, init) => {
    const method = (init?.method ?? (input instanceof Request ? input.method : "GET")).toUpperCase();
    const url = new URL(input instanceof Request ? input.url : String(input), baseUrl);
    let data: unknown = null;
    if (method === "GET" && url.origin === origin) {
      if (url.pathname === "/api/config/public") data = { language: "zh" };
      if (url.pathname === "/api/control-token") {
        data = { header: "X-Vibelution-Control-Token", controlToken: "isolated-preview-not-a-runtime-token" };
      }
      if (url.pathname === `/api/research/workflows/${encodeURIComponent(launchOptions.workflowId)}/launch-options`
        && url.searchParams.get("teamId") === launchOptions.teamId) data = launchOptions;
    }
    return new Response(JSON.stringify(data ?? { detail: "隔离预览不会访问真实接口" }), {
      status: data === null ? 403 : 200,
      headers: { "Content-Type": "application/json" },
    });
  };
}
