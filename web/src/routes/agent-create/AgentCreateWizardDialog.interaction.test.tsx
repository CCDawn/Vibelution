/** @vitest-environment happy-dom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { clearControlToken, seedControlTokenForTests } from "../../api/client";
import { queryKeys } from "../../api/queryKeys";
import { type AgentModelChoice } from "../../api/types";
import { AgentCreateWizardDialog } from "./AgentCreateWizardDialog";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const jsonResponse = (payload: unknown) =>
  new Response(JSON.stringify(payload), { status: 200, headers: { "Content-Type": "application/json" } });

function modelChoice(
  overrides: Partial<AgentModelChoice> & Pick<AgentModelChoice, "modelId" | "label">,
): AgentModelChoice {
  return {
    modelRef: overrides.modelId,
    modelKey: overrides.modelId,
    upstreamId: "",
    model: overrides.label,
    providerId: "provider-a",
    providerLabel: "Provider A",
    providerKind: "vllm",
    providerBaseUrl: "https://example.invalid/v1",
    transport: "openai",
    source: "pinned",
    runtimeSelectable: true,
    availability: "available",
    verificationStatus: "verified",
    catalogStale: false,
    slotCompatibility: {},
    capabilities: {},
    apiKeyEnv: "TEST_KEY",
    apiKeyConfigured: true,
    apiKeyState: "configured",
    requiresApiKey: true,
    missingApiKey: false,
    capabilityStatus: "ready",
    capabilitySource: "catalog",
    ...overrides,
  } as AgentModelChoice;
}

const promptTemplates = [
  { promptTemplateId: "prompt-chat-default", templateId: "prompt-chat-default", name: "默认会话", category: "chat" },
];

function workspacePayload(models: AgentModelChoice[]) {
  return { agentModelChoices: models, promptTemplates };
}

const bundleLabels: Record<string, string> = {
  core: "核心工具包",
  research: "研究工具包",
  coding: "编码工具包",
};

function toolsPayload(bundleIds: string[]) {
  return {
    toolBundles: bundleIds.map((bundleId) => ({
      bundleId,
      label: bundleLabels[bundleId] ?? bundleId,
      description: `${bundleId} bundle`,
      category: "general",
      toolNames: ["grep_search_tool"],
      preferredToolNames: [],
      toolCount: 1,
      preferredToolCount: 0,
      highRiskToolCount: 0,
      explicitAllowToolCount: 0,
      riskTags: [],
    })),
  };
}

type DeferredRoute = "workspace" | "tools";

/**
 * Fetch router whose workspace/tools payloads start withheld, so test bodies
 * control exactly when the async catalog reaches the wizard — the timing the
 * normalize-defaults defect lives in.
 */
function createRouter() {
  const payloads: Record<DeferredRoute, unknown> = { workspace: undefined, tools: undefined };
  const resolvers: Record<DeferredRoute, Array<(response: Response) => void>> = { workspace: [], tools: [] };
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(typeof input === "string" ? input : input instanceof URL ? input.href : input.url);
    if (url.includes("/api/agents/config-workspace")) {
      if (payloads.workspace === undefined) {
        return new Promise<Response>((resolve) => { resolvers.workspace.push(resolve); });
      }
      return jsonResponse(payloads.workspace);
    }
    if (url.includes("/api/tools")) {
      if (payloads.tools === undefined) {
        return new Promise<Response>((resolve) => { resolvers.tools.push(resolve); });
      }
      return jsonResponse(payloads.tools);
    }
    if (url.includes("/api/config/test-llm")) return jsonResponse({ ok: true, message: "" });
    if (url.includes("/api/config/public")) return jsonResponse({ language: "zh" });
    if (url.includes("/api/agents/avatar-options")) {
      return jsonResponse({ directory: "", options: [], count: 0, modelDefault: null });
    }
    return jsonResponse({});
  });
  return {
    fetchMock,
    /** Respond to any held request with `payload`, and serve it to future requests. */
    setResponse(route: DeferredRoute, payload: unknown) {
      payloads[route] = payload;
      const pending = resolvers[route];
      resolvers[route] = [];
      for (const resolve of pending) resolve(jsonResponse(payload));
    },
  };
}

function buttonByText(text: string): HTMLButtonElement | null {
  const buttons = Array.from(document.querySelectorAll("button"));
  return buttons.find((button) => (button.textContent ?? "").includes(text)) ?? null;
}

function modelTriggerText(): string {
  const trigger = document.querySelector<HTMLButtonElement>('button[aria-haspopup="listbox"][aria-label="模型"]');
  return trigger ? (trigger.textContent ?? "") : "";
}

function bundleCheckbox(label: string): HTMLInputElement | null {
  const checkboxes = Array.from(document.querySelectorAll<HTMLInputElement>('input[type="checkbox"]'));
  return checkboxes.find((box) => (box.closest("label")?.textContent ?? "").includes(label)) ?? null;
}

describe("AgentCreateWizardDialog async defaults interaction", () => {
  let root: Root | null = null;
  let queryClient: QueryClient | null = null;

  afterEach(async () => {
    if (root) {
      await act(async () => {
        root?.unmount();
      });
    }
    document.body.innerHTML = "";
    root = null;
    queryClient = null;
    clearControlToken();
    vi.unstubAllGlobals();
  });

  async function flush() {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  }

  async function waitFor(predicate: () => boolean, message: string) {
    for (let attempt = 0; attempt < 200 && !predicate(); attempt += 1) {
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 10));
      });
    }
    expect(predicate(), message).toBe(true);
  }

  async function mountWizard(router: ReturnType<typeof createRouter>) {
    vi.stubGlobal("fetch", router.fetchMock);
    seedControlTokenForTests();
    queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const activeClient = queryClient;
    await act(async () => {
      activeClient.setQueryData(queryKeys.configPublic(), { language: "zh" });
      root = createRoot(document.body);
      root.render(
        <QueryClientProvider client={activeClient}>
          <AgentCreateWizardDialog open onClose={() => undefined} />
        </QueryClientProvider>,
      );
    });
    await flush();
  }

  async function refetchWorkspace() {
    await act(async () => {
      await queryClient?.refetchQueries({ queryKey: queryKeys.agentConfigWorkspace() });
    });
    await flush();
  }

  async function refetchTools() {
    await act(async () => {
      await queryClient?.refetchQueries({ queryKey: queryKeys.tools() });
    });
    await flush();
  }

  async function typeName(value: string) {
    const input = document.querySelector<HTMLInputElement>('input[placeholder="例如：项目开发 Agent"]');
    expect(input, "display name input should render on step 1").toBeTruthy();
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
      setter?.call(input!, value);
      input!.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await flush();
  }

  async function clickButton(text: string) {
    const button = buttonByText(text);
    expect(button, `button "${text}" should render`).toBeTruthy();
    await act(async () => {
      button!.click();
    });
    await flush();
  }

  async function pickModelOption(labelPart: string) {
    const trigger = document.querySelector<HTMLButtonElement>('button[aria-haspopup="listbox"][aria-label="模型"]');
    expect(trigger, "model select trigger should render").toBeTruthy();
    await act(async () => {
      trigger!.click();
    });
    await flush();
    const option = Array.from(document.querySelectorAll<HTMLButtonElement>('button[role="option"]'))
      .find((candidate) => (candidate.textContent ?? "").includes(labelPart));
    expect(option, `model option "${labelPart}" should render`).toBeTruthy();
    await act(async () => {
      option!.click();
    });
    await flush();
  }

  async function toggleBundle(label: string) {
    const box = bundleCheckbox(label);
    expect(box, `bundle checkbox "${label}" should render`).toBeTruthy();
    await act(async () => {
      box!.click();
    });
    await flush();
  }

  const catalogBase = [
    modelChoice({ modelId: "provider-a/model-a", label: "Model Alpha" }),
    modelChoice({ modelId: "provider-a/model-b", label: "Model Beta" }),
  ];

  async function reachBundleStep(router: ReturnType<typeof createRouter>) {
    await clickButton("下一步");
    await waitFor(() => modelTriggerText().includes("Model Alpha"), "default model should be selected before probing");
    await clickButton("探测当前模型");
    await waitFor(() => modelTriggerText().includes("探测通过"), "probe should pass for the default model");
    await clickButton("下一步");
    await waitFor(() => Boolean(bundleCheckbox("核心工具包")), "tool bundle grid should render");
  }

  it("keeps backfilling untouched fields after the user types before the catalog arrives (defect ⑥)", async () => {
    const router = createRouter();
    await mountWizard(router);

    // Keystrokes land while the async catalog is still in flight.
    await typeName("我的研究助手");

    // Catalog and tool registry arrive late; defaults must still apply.
    router.setResponse("workspace", workspacePayload(catalogBase));
    router.setResponse("tools", toolsPayload(["core", "research"]));
    const nameInput = document.querySelector<HTMLInputElement>('input[placeholder="例如：项目开发 Agent"]');
    expect(nameInput?.value).toBe("我的研究助手");

    await clickButton("下一步");
    await waitFor(() => modelTriggerText().includes("Model Alpha"), "default model should auto-fill despite the earlier keystroke");
    await clickButton("探测当前模型");
    await waitFor(() => modelTriggerText().includes("探测通过"), "probe should pass for the default model");
    await clickButton("下一步");
    await waitFor(() => Boolean(bundleCheckbox("核心工具包")), "tool bundle grid should render");
    expect(bundleCheckbox("核心工具包")?.checked).toBe(true);
    expect(bundleCheckbox("研究工具包")?.checked).toBe(false);
  });

  it("keeps a user-selected valid model when refreshed defaults arrive later", async () => {
    const router = createRouter();
    await mountWizard(router);
    router.setResponse("workspace", workspacePayload(catalogBase));
    router.setResponse("tools", toolsPayload(["core"]));
    await clickButton("下一步");
    await waitFor(() => modelTriggerText().includes("Model Alpha"), "default model should arrive first");

    await pickModelOption("Model Beta");
    expect(modelTriggerText()).toContain("Model Beta");

    // Late catalog refresh: the default would still be Model Alpha, and the
    // user-picked Model Beta must survive it. Gamma keeps the payload distinct
    // so the query actually produces new data.
    router.setResponse("workspace", workspacePayload([
      ...catalogBase,
      modelChoice({ modelId: "provider-a/model-c", label: "Model Gamma" }),
    ]));
    await refetchWorkspace();
    await waitFor(() => modelTriggerText().includes("Model Beta"), "user-picked model should survive the late refresh");
    expect(modelTriggerText()).not.toContain("Model Gamma");
  });

  it("keeps the user's tool-bundle selection when the registry refreshes later", async () => {
    const router = createRouter();
    await mountWizard(router);
    router.setResponse("workspace", workspacePayload(catalogBase));
    router.setResponse("tools", toolsPayload(["core", "research"]));
    await reachBundleStep(router);

    expect(bundleCheckbox("核心工具包")?.checked).toBe(true);
    await toggleBundle("研究工具包");
    expect(bundleCheckbox("研究工具包")?.checked).toBe(true);

    // Registry refresh adds a bundle; the empty-selection default fill must
    // not clobber the user's picks.
    router.setResponse("tools", toolsPayload(["core", "research", "coding"]));
    await refetchTools();
    await waitFor(() => Boolean(bundleCheckbox("编码工具包")), "newly published bundle should appear");
    expect(bundleCheckbox("核心工具包")?.checked).toBe(true);
    expect(bundleCheckbox("研究工具包")?.checked).toBe(true);
    expect(bundleCheckbox("编码工具包")?.checked).toBe(false);
  });

  it("replaces a user-picked model that later turns out unavailable with the default", async () => {
    const router = createRouter();
    await mountWizard(router);
    router.setResponse("workspace", workspacePayload(catalogBase));
    router.setResponse("tools", toolsPayload(["core"]));
    await clickButton("下一步");
    await waitFor(() => modelTriggerText().includes("Model Alpha"), "default model should arrive first");

    await pickModelOption("Model Beta");
    expect(modelTriggerText()).toContain("Model Beta");

    // Spec-expected behavior (archive plan 2026-07-19:81): a field-level
    // default may replace the user's model when the late catalog proves it
    // unusable, so creation stays possible instead of stuck disabled.
    router.setResponse("workspace", workspacePayload([
      modelChoice({ modelId: "provider-a/model-a", label: "Model Alpha" }),
      modelChoice({
        modelId: "provider-a/model-b",
        label: "Model Beta",
        missingApiKey: true,
        apiKeyConfigured: false,
        apiKeyState: "missing",
      }),
    ]));
    await refetchWorkspace();
    await waitFor(() => modelTriggerText().includes("Model Alpha"), "unavailable pick should be replaced by the default");
    expect(modelTriggerText()).not.toContain("Model Beta");
    expect(document.body.textContent).not.toContain("当前模型不可用");
  });
});
