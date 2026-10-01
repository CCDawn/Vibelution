// @vitest-environment happy-dom
/**
 * ui.language dedicated endpoint flow: toggling the interface-language row goes
 * straight to PUT /api/config/language (updateConfigLanguage) — never through
 * previewConfigDraft / applyConfigWorkspace — then invalidates the configPublic
 * and configWorkspace queries and refetches the workspace so the settings page
 * copy flips without a reload. Endpoint failures surface a failed row badge
 * without touching any query.
 */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { queryKeys } from "../api/queryKeys";
import { seedControlTokenForTests } from "../api/client";
import { ConfigRoute } from "./ConfigRoute";

function publicConfigFixture(language: "zh" | "en") {
  return {
    language,
    evolution: { intake_mode: "manual" },
    ui: {
      language,
      show_welcome: true,
    },
  };
}

const EDITOR_META = {
  ui: { path: "ui", label: "界面外观", hint: "", kind: "object", badge: "", options: [] },
  "ui.language": {
    path: "ui.language",
    label: "界面语言",
    hint: "切换工作台界面使用的语言。",
    kind: "select",
    badge: "",
    options: [{ value: "zh", label: "中文" }, { value: "en", label: "English" }],
  },
  "ui.show_welcome": { path: "ui.show_welcome", label: "显示欢迎面板", hint: "", kind: "boolean", badge: "", options: [] },
};

const EDITOR_SECTION = { id: "ui", path: "ui", title: "界面外观", summary: "结构化编辑", fieldCount: 2 };

function workspaceFixture(language: "zh" | "en", overrides: Record<string, unknown> = {}) {
  return {
    hash: `draft-hash-${language}`,
    language,
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
    sections: [{ id: "ui", title: "界面外观", summary: "" }],
    message: "",
    baseHash: `base-hash-${language}`,
    configPath: "C:/config/operator-config.toml",
    publicConfig: publicConfigFixture(language),
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

function installFetchMock(options: { languageEndpointStatus?: number } = {}) {
  let workspaceLanguage: "zh" | "en" = "zh";
  const languageCalls: FetchCall[] = [];
  const previewCalls: FetchCall[] = [];
  const applyCalls: FetchCall[] = [];
  const workspaceCalls: FetchCall[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : {};
    if (url.includes("/api/config/workspace")) {
      workspaceCalls.push({ url, body });
      return jsonResponse(workspaceFixture(workspaceLanguage));
    }
    if (url.includes("/api/config/language")) {
      languageCalls.push({ url, body });
      if (options.languageEndpointStatus && options.languageEndpointStatus !== 200) {
        return jsonResponse({ detail: "语言写入失败" }, options.languageEndpointStatus);
      }
      workspaceLanguage = body.language === "en" ? "en" : "zh";
      return jsonResponse({ language: workspaceLanguage });
    }
    if (url.includes("/api/config/draft/preview")) {
      previewCalls.push({ url, body });
      return jsonResponse(workspaceFixture(workspaceLanguage));
    }
    if (url.includes("/api/config/apply")) {
      applyCalls.push({ url, body });
      return jsonResponse(workspaceFixture(workspaceLanguage));
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
  return { languageCalls, previewCalls, applyCalls, workspaceCalls };
}

describe("ConfigRoute ui.language dedicated endpoint flow", () => {
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
    queryClient.setQueryData(queryKeys.configPublic(), publicConfigFixture("zh"));
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
        initialEntries: ["/config?section=workbench-interface&page=workbench-interface&focus=ui&field=ui.language"],
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

  async function pickEnglishOption() {
    const row = container.querySelector('[data-testid="row-ui.language"]');
    expect(row, "ui.language row renders").not.toBeNull();
    const trigger = row?.querySelector<HTMLButtonElement>("[data-vui-select-trigger]");
    expect(trigger, "language toggle hosts a VStringSelect trigger").not.toBeNull();
    await act(async () => {
      trigger?.click();
    });
    const option = [...document.querySelectorAll<HTMLElement>('[role="option"]')]
      .find((item) => item.textContent?.includes("English"));
    expect(option, "English option renders in the portal").toBeTruthy();
    await act(async () => {
      option?.click();
    });
  }

  it("switches language through the dedicated endpoint, skips preview/apply, invalidates configPublic, and flips page copy", async () => {
    const mock = installFetchMock();

    await renderRoute();
    await waitFor(() => Boolean(container.querySelector('[data-testid="row-ui.language"]')), "ui.language row renders");
    expect(container.querySelector('[data-testid="row-ui.language"]')?.textContent).toContain("界面语言");

    await pickEnglishOption();
    await waitFor(() => mock.languageCalls.length === 1, "language endpoint called");

    // 专用端点载荷：PUT /api/config/language { language: "en" }
    expect(String(mock.languageCalls[0]?.url)).toContain("/api/config/language");
    expect(mock.languageCalls[0]?.body).toEqual({ language: "en" });
    // 单一写入方：语言切换绝不走通用 preview + 整份配置 apply 管线。
    expect(mock.previewCalls.length).toBe(0);
    expect(mock.applyCalls.length).toBe(0);

    // 成功后失效 configPublic（AppShell 顶栏 i18n）；configWorkspace 以显式
    // refetch 刷新（失效后重取成功会清掉 isInvalidated，用取数次数断言）。
    await waitFor(() => Boolean(container.querySelector('[data-vui-row-status="applied"]')), "applied badge shows");
    expect(queryClient.getQueryState(queryKeys.configPublic())?.isInvalidated).toBe(true);

    // 工作区回读后设置页自身文案不重载完成切换。
    await waitFor(
      () => Boolean(container.querySelector('[data-testid="row-ui.language"]')?.textContent?.includes("Interface language")),
      "row copy flips to English",
    );
    expect(mock.workspaceCalls.length).toBeGreaterThanOrEqual(2);
  });

  it("surfaces a failed badge and leaves queries untouched when the language endpoint rejects", async () => {
    const mock = installFetchMock({ languageEndpointStatus: 500 });

    await renderRoute();
    await waitFor(() => Boolean(container.querySelector('[data-testid="row-ui.language"]')), "ui.language row renders");

    await pickEnglishOption();
    await waitFor(() => Boolean(container.querySelector('[data-vui-row-status="failed"]')), "failed badge shows");

    expect(mock.languageCalls.length).toBe(1);
    expect(mock.previewCalls.length).toBe(0);
    expect(mock.applyCalls.length).toBe(0);
    // 失败不静默：notice 出现错误文案；查询保持未失效。
    expect(container.querySelector('[role="alert"], [class*="noticeError"]')).not.toBeNull();
    expect(queryClient.getQueryState(queryKeys.configPublic())?.isInvalidated).toBe(false);
  });
});
