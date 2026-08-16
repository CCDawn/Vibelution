import { fetchJson } from "./client";
import type {
  GeneratedToolDeleteResponse,
  ToolDependencyHealth,
  ToolImage2ModelConfig,
  ToolRegistryItem,
  ToolRegistryPayload,
  ToolTestResponse,
} from "./types";

export type ToolBulkMutationResponse = {
  action: string;
  enabled?: boolean;
  successCount: number;
  skippedCount: number;
  failedCount: number;
  results: Array<{
    toolId: string;
    status: string;
    reason?: string;
  }>;
};

function sendJson<T>(url: string, method: string, body?: unknown): Promise<T> {
  return fetchJson<T>(url, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

export function fetchToolRegistry(): Promise<ToolRegistryPayload> {
  return fetchJson<ToolRegistryPayload>("/api/tools");
}

export function fetchToolImage2Models(): Promise<ToolImage2ModelConfig> {
  return fetchJson<ToolImage2ModelConfig>("/api/tools/image2/models");
}

export function setGeneratedToolEnabled(
  toolId: string,
  enabled: boolean,
): Promise<ToolRegistryItem> {
  return sendJson<ToolRegistryItem>(
    `/api/tools/generated/${encodeURIComponent(toolId)}/enabled`,
    "PUT",
    { enabled },
  );
}

export function deleteTool(toolId: string): Promise<GeneratedToolDeleteResponse> {
  return fetchJson<GeneratedToolDeleteResponse>(`/api/tools/${encodeURIComponent(toolId)}`, {
    method: "DELETE",
  });
}

export function testTool(payload: {
  toolId: string;
  agentScopeId: string;
  agentId: string;
}): Promise<ToolTestResponse> {
  return sendJson<ToolTestResponse>(
    `/api/tools/${encodeURIComponent(payload.toolId)}/test`,
    "POST",
    {
      args: {},
      agentScope: payload.agentScopeId,
      agentId: payload.agentId,
    },
  );
}

export function setToolImage2DefaultModel(modelRef: string): Promise<ToolImage2ModelConfig> {
  return sendJson<ToolImage2ModelConfig>("/api/tools/image2/default-model", "PUT", { modelRef });
}

export function fetchWebSearchToolHealth(): Promise<ToolDependencyHealth> {
  return fetchJson<ToolDependencyHealth>("/api/tools/web-search/health");
}

export function bulkSetGeneratedToolsEnabled(payload: {
  toolIds: string[];
  enabled: boolean;
}): Promise<ToolBulkMutationResponse> {
  return sendJson<ToolBulkMutationResponse>("/api/tools/generated/bulk-enabled", "PUT", payload);
}

export function bulkDeleteToolRegistry(toolIds: string[]): Promise<ToolBulkMutationResponse> {
  return sendJson<ToolBulkMutationResponse>("/api/tools/bulk-delete", "POST", { toolIds });
}
