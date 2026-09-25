// @vitest-environment happy-dom
/**
 * Settings-align wave 3 phase 1 — main component save-flow safety net.
 *
 * Covers the route-level flows ConfigRoute.settingsRows.test.tsx does not:
 * - a section draft surfaces the global pending-save badge;
 * - the global save folds section drafts into one apply (invalid drafts block);
 * - the leave guard offers save-and-leave / discard / cancel with the right
 *   apply and navigation side effects.
 *
 * Immediate-field apply is already covered by ConfigRoute.immediateFlow.test.tsx.
 * Phase 2 moves helpers out of ConfigRoute.tsx; this file must not change.
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

type ApplyCall = { url: string; body: Record<string, unknown> };

function installFetchMock(handlers: {
  workspace: unknown;
  previewResponse?: unknown;
  previewError?: boolean;
  applyResponse?: unknown;
}) {
  const applyCalls: ApplyCall[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : {};
    if (url.includes("/api/config/workspace")) {
      return jsonResponse(handlers.workspace);
    }
    if (url.includes("/api/config/draft/preview")) {
      if (handlers.previewError) {
        return jsonResponse({ detail: "配置基线已过期，请刷新后重试" }, 409);
      }
      return jsonResponse(handlers.previewResponse ?? handlers.workspace);
    }
    if (url.includes("/api/config/apply")) {
      applyCalls.push({ url, body });
      return jsonResponse(handlers.applyResponse ?? handlers.workspace);
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
  return { applyCalls };
}

describe("ConfigRoute main save flow (wave 3 safety net)", () => {
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

  async function renderRoute(initialUrl = "/config?section=runtime-context&page=runtime-context&focus=context-compression") {
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
        {
          path: "/agents",
          element: <div data-testid="agents-destination">agents</div>,
        },
      ],
      { initialEntries: [initialUrl] },
    );
    await act(async () => {
      root = createRoot(container);
      root.render(<RouterProvider router={router} />);
    });
    return router;
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

  function findButtonByText(text: string): HTMLButtonElement | null {
    const buttons = Array.from(container.querySelectorAll("button"));
    return buttons.find((button) => (button.textContent ?? "").includes(text)) ?? null;
  }

  /** VDialog 经 Radix portal 渲染在 document.body，不在 route container 内。 */
  function dialogButtons(): HTMLButtonElement[] {
    return Array.from(document.querySelectorAll('[role="dialog"] button'));
  }

  function setInputValue(element: HTMLInputElement | HTMLTextAreaElement, nextValue: string) {
    const proto = element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
    setter?.call(element, nextValue);
    element.dispatchEvent(new Event("input", { bubbles: true }));
  }

  /** 进入分区编辑态并把 number 草稿改成 24000（走 number 步进器输入框）。 */
  async function editNumberDraft() {
    const editButton = findButtonByText("编辑分区");
    expect(editButton, "edit section button renders").not.toBeNull();
    await act(async () => {
      editButton?.click();
    });
    const numberInput = container.querySelector(
      '[data-testid="number-editor-context_compression.max_token_limit"] input',
    ) as HTMLInputElement | null;
    expect(numberInput, "number editor input renders").not.toBeNull();
    await act(async () => {
      setInputValue(numberInput as HTMLInputElement, "24000");
    });
  }

  it("surfaces the global pending-save badge from a section draft and clears it after a folded global save", async () => {
    const mock = installFetchMock({ workspace: workspaceFixture() });
    await renderRoute();
    await waitFor(() => Boolean(container.querySelector('[data-testid="row-context_compression.enabled"]')), "view row renders");
    expect(container.querySelector('[data-testid="config-pending-save-count"]')).toBeNull();

    await editNumberDraft();
    await waitFor(() => Boolean(container.querySelector('[data-testid="config-pending-save-count"]')), "pending badge shows");
    const badge = container.querySelector('[data-testid="config-pending-save-count"]');
    expect(badge?.textContent).toContain("1");

    await act(async () => {
      findButtonByText("保存到外部配置")?.click();
    });
    await waitFor(() => mock.applyCalls.length === 1, "apply called once");
    const applyBody = mock.applyCalls[0]?.body as {
      publicConfig: { context_compression: { max_token_limit: number } };
      baseHash: string;
    };
    // 全局保存折叠分区草稿：number 文本按 schema 解析成数字
    expect(applyBody.publicConfig.context_compression.max_token_limit).toBe(24000);
    expect(applyBody.baseHash).toBe("base-hash-1");
    // 保存成功后徽标清除、编辑态收起
    await waitFor(() => !container.querySelector('[data-testid="config-pending-save-count"]'), "badge clears");
    expect(findButtonByText("编辑分区")).not.toBeNull();
  });

  it("blocks the global save while a section draft is invalid", async () => {
    const mock = installFetchMock({ workspace: workspaceFixture() });
    await renderRoute();
    await waitFor(() => Boolean(container.querySelector('[data-testid="row-context_compression.enabled"]')), "view row renders");

    await editNumberDraft();
    // 把同一 number 草稿改成越界值（0 不满足 exclusiveMinimum 0）：整树解析失败 → 全局保存禁用。
    // （非法 json 阻塞由组件级测试覆盖；json 编辑器仅在草稿为原始串时出现，路由交互不产生该形态。）
    await act(async () => {
      const numberInput = container.querySelector(
        '[data-testid="number-editor-context_compression.max_token_limit"] input',
      ) as HTMLInputElement | null;
      setInputValue(numberInput as HTMLInputElement, "0");
    });
    await waitFor(
      () => Boolean(container.querySelector('[data-testid="number-error-context_compression.max_token_limit"]')),
      "number inline error shows",
    );
    await waitFor(() => {
      const saveButton = findButtonByText("保存到外部配置");
      return Boolean(saveButton?.disabled);
    }, "global save disabled");
    const saveButton = findButtonByText("保存到外部配置");
    expect(saveButton?.getAttribute("title")).toBe("有格式不正确的修改，修正后才能保存");
    await act(async () => {
      saveButton?.click();
    });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 50));
    });
    expect(mock.applyCalls.length).toBe(0);
  });

  it("offers the leave guard three choices with correct apply and navigation effects", async () => {
    const mock = installFetchMock({ workspace: workspaceFixture() });
    const router = await renderRoute();
    await waitFor(() => Boolean(container.querySelector('[data-testid="row-context_compression.enabled"]')), "view row renders");

    await editNumberDraft();

    // 取消：留在当前页，不触发 apply
    await act(async () => {
      void router.navigate("/agents");
    });
    await waitFor(() => Boolean(document.querySelector('[role="dialog"]')), "leave guard dialog shows");
    await act(async () => {
      dialogButtons()
        .find((button) => (button.textContent ?? "").includes("取消"))
        ?.click();
    });
    await waitFor(() => !document.querySelector('[role="dialog"]'), "dialog closes on cancel");
    expect(router.state.location.pathname).toBe("/config");
    expect(mock.applyCalls.length).toBe(0);

    // 不保存离开：直接放行，不触发 apply
    await act(async () => {
      void router.navigate("/agents");
    });
    await waitFor(() => Boolean(document.querySelector('[role="dialog"]')), "leave guard dialog shows again");
    await act(async () => {
      dialogButtons()
        .find((button) => (button.textContent ?? "").includes("不保存离开"))
        ?.click();
    });
    await waitFor(() => router.state.location.pathname === "/agents", "navigated away");
    expect(mock.applyCalls.length).toBe(0);
  });

  it("saves pending drafts and leaves when save-and-leave is chosen", async () => {
    const appliedWorkspace = workspaceFixture(({
      publicConfig: {
        ...BASE_PUBLIC_CONFIG,
        context_compression: { ...BASE_PUBLIC_CONFIG.context_compression, max_token_limit: 24000 },
      },
      baseHash: "base-hash-2",
      hash: "draft-hash-2",
    }) as unknown);
    const mock = installFetchMock({ workspace: workspaceFixture(), applyResponse: appliedWorkspace });
    const router = await renderRoute();
    await waitFor(() => Boolean(container.querySelector('[data-testid="row-context_compression.enabled"]')), "view row renders");

    await editNumberDraft();
    await act(async () => {
      void router.navigate("/agents");
    });
    await waitFor(() => Boolean(document.querySelector('[role="dialog"]')), "leave guard dialog shows");
    await act(async () => {
      dialogButtons()
        .find((button) => (button.textContent ?? "").includes("保存并离开"))
        ?.click();
    });
    await waitFor(() => mock.applyCalls.length === 1, "apply called on save-and-leave");
    await waitFor(() => router.state.location.pathname === "/agents", "navigated after save");
    const applyBody = mock.applyCalls[0]?.body as {
      publicConfig: { context_compression: { max_token_limit: number } };
    };
    expect(applyBody.publicConfig.context_compression.max_token_limit).toBe(24000);
  });
});
