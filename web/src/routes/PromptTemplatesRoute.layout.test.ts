import { describe, expect, it } from "vitest";

import routerSource from "../app/router.tsx?raw";
import routeSource from "./PromptTemplatesRoute.tsx?raw";

describe("PromptTemplatesRoute layout contract", () => {
  it("lives inside Agent management navigation with the shared nav row", () => {
    expect(routerSource).toContain('path: "agents/prompts"');
    expect(routerSource).toContain("<PromptTemplatesRoute />");
    expect(routeSource).toContain('<AgentManagementNav active="prompts" />');
    expect(routeSource.indexOf('<AgentManagementNav active="prompts" />')).toBeGreaterThan(routeSource.indexOf("</header>"));
    expect(routeSource.indexOf('<AgentManagementNav active="prompts" />')).toBeLessThan(routeSource.indexOf("styles.summaryGrid"));
  });

  it("loads prompt templates and linked Agents through the existing APIs", () => {
    expect(routeSource).toContain('queryKeys.promptTemplates()');
    expect(routeSource).toContain('fetchJson<PromptTemplateWorkspace>("/api/prompt-templates")');
    expect(routeSource).toContain('queryKeys.agents()');
    expect(routeSource).toContain('fetchJson<AgentInstance[]>("/api/agents")');
    expect(routeSource).toContain("agentsByTemplate");
  });

  it("keeps editing in the dedicated prompt center with save and reset actions", () => {
    expect(routeSource).toContain('method: "PATCH"');
    expect(routeSource).toContain('method: "POST"');
    expect(routeSource).toContain('body: JSON.stringify({');
    expect(routeSource).toContain('name: payload.name');
    expect(routeSource).toContain('content: payload.content');
    expect(routeSource).toContain('/reset`');
  });

  it("supports category deep links and the expected workbench panels", () => {
    expect(routeSource).toContain('searchParams.get("category")');
    expect(routeSource).toContain('categoryFilter === "all" ? {} : { category: categoryFilter }');
    expect(routeSource).toContain('"research"');
    expect(routeSource).toContain("styles.workspace");
    expect(routeSource).toContain("styles.listPanel");
    expect(routeSource).toContain("styles.editorPanel");
    expect(routeSource).toContain("styles.templateList");
    expect(routeSource).toContain("styles.agentList");
  });
});
