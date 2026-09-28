// @vitest-environment happy-dom
/**
 * Settings-align wave 1 — view-mode immediate field save flow against a mocked
 * fetch: toggling a boolean row goes through previewConfigDraft + apply with
 * the frozen baseline hash, the row badge transitions waiting → applied, and a
 * preview failure surfaces a failed badge + error notice instead of saving
 * silently.
 */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { seedControlTokenForTests } from "../api/client";
import { ConfigRoute } from "./ConfigRoute";

const BASE_PUBLIC_CONFIG = {
  language: "zh",
  evolution: { intake_mode: "manual" },
  context_compression: {
    enabled: true,
    compression_model: "qwen-turbo",
    max_token_limit: 16000,
    summary_chars: { light: 500 },
    micro_compact_tool_whitelist: ["read_file_tool"],
  },
};

const EDITOR_META = {
  context_compression: { path: "context_compression", label: "上下文压缩", hint: "", kind: "object", badge: "", options: [] },
  "context_compression.enabled": { path: "context_compression.enabled", label: "启用上下文压缩", hint: "启用后生效", kind: "boolean", badge: "", options: [] },
  "context_compression.compression_model": { path: "context_compression.compression_model", label: "压缩用模型", hint: "", kind: "select", badge: "", options: [{ value: "qwen-turbo", label: "qwen-turbo" }] },
  "context_compression.max_token_limit": { path: "context_compression.max_token_limit", label: "压缩触发阈值", hint: "", kind: "number", badge: "", options: [], unit: "令牌", exclusiveMinimum: 0 },
  "context_compression.summary_chars": { path: "context_compression.summary_chars", label: "各级摘要字数", hint: "", kind: "json", badge: "", options: [] },
  "context_compression.micro_compact_tool_whitelist": { path: "context_compression.micro_compact_tool_whitelist", label: "微压缩白名单", hint: "", kind: "string_list", badge: "", options: [] },
};

const EDITOR_SECTION = { id: "context-compression", path: "context_compression", title: "上下文压缩", summary: "结构化编辑", fieldCount: 6 };

function workspaceFixture(overrides: Record<string, unknown> = {}) {
  return {
    hash: "draft-hash-1",
    language: "zh",
    runtimeProfile: "balanced",
    defaultMode: "supervised",
    defaultRoute: "",
    intakeMode: "manual",
    modeAvailability: {},
    domainAvailability: {},
    modelLibraryCount: 0,
    modelLabels: {},
    modelImageInputSupport: {},
    blockingCount: 0,
    warningCount: 0,
    sections: [{ id: "context-compression", title: "上下文压缩", summary: "" }],
    message: "",
    baseHash: "base-hash-1",
    configPath: "C:/config/operator-config.toml",
    publicConfig: BASE_PUBLIC_CONFIG,
    featureDecisions: { configRevision: "", source: "", features: {} },
    rawToml: "",
    draftMeta: { pending_api_keys: {}, pending_cleared_api_keys: [] },
    diagnosis: { blocking_issues: [], warnings: [], suggested_actions: [] },
    summary: {},
    editorSections: [EDITOR_SECTION],
    editorMeta: EDITOR_META,
    modelPresetOptions: [],
    providerPresetOptions: [],
    modelOptions: [],
    schemaVersion: 1,
    providerOptions: [],
    modelCatalog: { schemaVersion: 2, providerCount: 0, modelCount: 0, providers: {} },
    modelAliasUsage: { aliases: [] },
    ...overrides,
  };
}

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

type FetchCall = { url: string; body: Record<string, unknown> };

function installFetchMock(handlers: {
  workspace: unknown;
  previewResponse: unknown;
  previewError?: boolean;
  applyResponse: unknown;
}) {
  const previewCalls: FetchCall[] = [];
  const applyCalls: FetchCall[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : {};
    if (url.includes("/api/config/workspace")) {
      return jsonResponse(handlers.workspace);
    }
    if (url.includes("/api/config/draft/preview")) {
      previewCalls.push({ url, body });
      if (handlers.previewError) {
        return jsonResponse({ detail: "配置基线已过期，请刷新后重试" }, 409);
      }
      return jsonResponse(handlers.previewResponse);
    }
    if (url.includes("/api/config/apply")) {
      applyCalls.push({ url, body });
      return jsonResponse(handlers.applyResponse);
    }
    if (url.includes("/api/diagnostics")) {
      return jsonResponse({ blocking_issues: [], warnings: [], suggested_actions: [] });
    }
    if (url.includes("/api/control-token")) {
      return jsonResponse({ controlToken: "test-control-token" });
    }
    return jsonResponse({}, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
  return { previewCalls, applyCalls };
}

describe("ConfigRoute view-mode immediate field save flow", () => {
  let container: HTMLElement;
  let root: Root | null = null;
  let queryClient: QueryClient;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    seedControlTokenForTests();
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
  });

  afterEach(async () => {
    if (root) {
      await act(async () => root?.unmount());
      root = null;
    }
    container.remove();
    queryClient.clear();
    vi.unstubAllGlobals();
    window.localStorage.clear();
  });

  async function renderRoute() {
    const router = createMemoryRouter(
      [
        {
          path: "/config",
          element: (
            <QueryClientProvider client={queryClient}>
              <ConfigRoute />
            </QueryClientProvider>
          ),
        },
      ],
      {
        initialEntries: ["/config?section=runtime-context&page=runtime-context&focus=context-compression"],
      },
    );
    await act(async () => {
      root = createRoot(container);
      root.render(<RouterProvider router={router} />);
    });
  }

  async function waitFor(predicate: () => boolean, label: string, timeoutMs = 4000) {
    const deadline = Date.now() + timeoutMs;
    while (!predicate()) {
      if (Date.now() > deadline) {
        throw new Error(`waitFor timeout: ${label}`);
      }
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 25));
      });
    }
  }

  async function toggleEnableCheckbox() {
    const checkbox = container.querySelector(
      '[data-testid="row-context_compression.enabled"] input[type="checkbox"]',
    ) as HTMLInputElement | null;
    expect(checkbox, "view row hosts a live boolean control").not.toBeNull();
    await act(async () => {
      checkbox?.click();
    });
  }

  it("applies an immediate toggle through preview + apply and shows the applied badge", async () => {
    const appliedWorkspace = workspaceFixture(({
      publicConfig: {
        ...BASE_PUBLIC_CONFIG,
        context_compression: { ...BASE_PUBLIC_CONFIG.context_compression, enabled: false },
      },
      baseHash: "base-hash-2",
      hash: "draft-hash-2",
    }) as unknown);
    const mock = installFetchMock({
      workspace: workspaceFixture(),
      // previewConfigDraft echoes the draft workspace; baseHash stays frozen.
      previewResponse: workspaceFixture(({
        publicConfig: {
          ...BASE_PUBLIC_CONFIG,
          context_compression: { ...BASE_PUBLIC_CONFIG.context_compression, enabled: false },
        },
        hash: "draft-hash-preview",
      }) as unknown),
      applyResponse: appliedWorkspace,
    });

    await renderRoute();
    await waitFor(() => Boolean(container.querySelector('[data-testid="row-context_compression.enabled"]')), "view row renders");
    await waitFor(() => Boolean(container.querySelector('[data-testid="row-status-context_compression.enabled"]')) === false, "initially clean");

    await toggleEnableCheckbox();
    await waitFor(() => Boolean(container.querySelector('[data-vui-row-status="applied"]')), "applied badge shows");

    expect(mock.previewCalls.length).toBe(1);
    const previewBody = mock.previewCalls[0]?.body as {
      publicConfig: { context_compression: { enabled: boolean } };
      baseHash: string;
    };
    expect(previewBody.publicConfig.context_compression.enabled).toBe(false);
    expect(previewBody.baseHash).toBe("base-hash-1");

    expect(mock.applyCalls.length).toBe(1);
    const applyBody = mock.applyCalls[0]?.body as {
      publicConfig: { context_compression: { enabled: boolean } };
      baseHash: string;
    };
    expect(applyBody.publicConfig.context_compression.enabled).toBe(false);
    // 复用冻结基线的乐观并发口径
    expect(applyBody.baseHash).toBe("base-hash-1");
  });

  it("surfaces a failed badge and skips apply when the preview is rejected", async () => {
    const mock = installFetchMock({
      workspace: workspaceFixture(),
      previewResponse: null,
      previewError: true,
      applyResponse: workspaceFixture(),
    });

    await renderRoute();
    await waitFor(() => Boolean(container.querySelector('[data-testid="row-context_compression.enabled"]')), "view row renders");

    await toggleEnableCheckbox();
    await waitFor(() => Boolean(container.querySelector('[data-vui-row-status="failed"]')), "failed badge shows");

    expect(mock.previewCalls.length).toBe(1);
    expect(mock.applyCalls.length).toBe(0);
    // 失败不静默：notice 出现错误文案
    expect(container.querySelector('[role="alert"], [data-notice="error"], [class*="noticeError"]')).not.toBeNull();
  });
});
