import { describe, expect, it } from "vitest";

// @ts-expect-error Vitest runs this contract in Node; the web project intentionally omits global Node types.
import { readFileSync } from "node:fs";
import routerSource from "../app/router.tsx?raw";
import routeSource from "./PromptTemplatesRoute.tsx?raw";

const stylesSource = readFileSync(new URL("./PromptTemplatesRoute.module.css", import.meta.url), "utf-8");

describe("PromptTemplatesRoute layout contract", () => {
  it("lives inside Agent management navigation with the shared nav row", () => {
    expect(routerSource).toContain('path: "agents/prompts"');
    expect(routerSource).toContain("<PromptTemplatesRoute />");
    expect(routeSource).toContain('<AgentManagementNav active="prompts" className={styles.managementNav} />');
    expect(routeSource.indexOf('<AgentManagementNav active="prompts" className={styles.managementNav} />')).toBeGreaterThan(
      routeSource.indexOf("</header>"),
    );
    expect(routeSource.indexOf('<AgentManagementNav active="prompts" className={styles.managementNav} />')).toBeLessThan(
      routeSource.indexOf("styles.summaryGrid"),
    );
  });

  it("uses shell language state without loading the full app dictionary", () => {
    expect(routeSource).toContain("useShellI18n");
    expect(routeSource).toContain("const { lang } = useShellI18n()");
    expect(routeSource).not.toContain("useAppI18n");
  });

  it("loads prompt templates and linked Agents through the existing APIs", () => {
    expect(routeSource).toContain('queryKeys.promptTemplates()');
    expect(routeSource).toContain('fetchJson<PromptTemplateWorkspace>("/api/prompt-templates")');
    expect(routeSource).toContain('queryKeys.agents()');
    expect(routeSource).toContain('fetchJson<AgentInstance[]>("/api/agents?detail=summary")');
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

  it("keeps save and reset pending state scoped to the active template", () => {
    expect(routeSource).toContain("if (activeTemplateId === template.promptTemplateId)");
    expect(routeSource).toContain("saveMutation.variables?.templateId === activeTemplateId");
    expect(routeSource).toContain("resetMutation.variables === activeTemplateId");
    expect(routeSource).not.toContain("const busy = saveMutation.isPending || resetMutation.isPending || detailQuery.isFetching");
  });

  it("supports category deep links and the expected workbench panels", () => {
    expect(routeSource).toContain('searchParams.get("category")');
    expect(routeSource).toContain('next.delete("category")');
    expect(routeSource).toContain('next.set("category", categoryFilter)');
    expect(routeSource).toContain('"research"');
    expect(routeSource).toContain("styles.workspace");
    expect(routeSource).toContain("styles.listPanel");
    expect(routeSource).toContain("styles.editorPanel");
    expect(routeSource).toContain("styles.templateList");
    expect(routeSource).toContain("styles.agentList");
  });

  it("supports Agent config deep links and preserves return navigation", () => {
    expect(routeSource).toContain('searchParams.get("agent")');
    expect(routeSource).toContain('searchParams.get("template")');
    expect(routeSource).toContain('searchParams.get("focus")');
    expect(routeSource).toContain("safeAgentCenterReturnToPath(searchParams.get(\"returnTo\"))");
    expect(routeSource).toContain("styles.returnButton");
    expect(routeSource).toContain("styles.selectableRowLinked");
    expect(routeSource).toContain("styles.agentItemLinked");
    expect(routeSource).toContain("styles.editorPanelFocused");
    expect(stylesSource).toContain(".returnButton");
    expect(stylesSource).toContain(".selectableRowLinked");
    expect(stylesSource).toContain(".agentItemLinked");
    expect(stylesSource).toContain(".editorPanelFocused");
  });

  it("keeps the prompt content editor as the primary visible area", () => {
    expect(routeSource).toContain("styles.nameField");
    expect(routeSource).toContain("styles.contentField");
    expect(routeSource.indexOf("styles.contentField")).toBeLessThan(routeSource.indexOf("styles.bottomGrid"));
  });

  it("supports bulk prompt selection with safe existing mutations", () => {
    expect(routeSource).toContain("selectedTemplateIds");
    expect(routeSource).toContain("bulkPatchTemplates({ category: bulkCategory }, copy.bulkCategoryResult)");
    expect(routeSource).toContain("bulkPatchTemplates({ status: \"inactive\" }, copy.bulkDeactivateResult)");
    expect(routeSource).toContain("bulkResetTemplates");
    expect(routeSource).toContain("copy.bulkDeactivateConfirm");
    expect(routeSource).toContain("copy.bulkResetConfirm");
    expect(routeSource).toContain("window.confirm(copy.bulkDeactivateConfirm)");
    expect(routeSource).toContain("window.confirm(copy.bulkResetConfirm)");
    expect(routeSource).toContain("styles.bulkActionBar");
    expect(routeSource).toContain("styles.selectableRow");
    expect(routeSource).toContain('method: "PATCH"');
    expect(routeSource).toContain('method: "POST"');
    expect(routeSource).toContain("/reset`");
  });

  it("keeps bulk prompt controls in their own compact row above the list", () => {
    expect(stylesSource).toContain("grid-template-rows: auto auto auto auto minmax(0, 1fr)");
    expect(stylesSource).toContain(".bulkActionBar");
    expect(stylesSource).toContain("display: grid");
    expect(stylesSource).toContain("grid-template-columns: auto auto minmax(118px, 1fr)");
    expect(stylesSource).toContain("min-height: 26px");
  });

  it("keeps the narrow prompt workspace scrollable without oversized editor panels", () => {
    const breakpoint = stylesSource.slice(stylesSource.indexOf("@media (max-width: 980px)"));

    expect(breakpoint).toContain(".workspace {\n    overflow: auto;\n    align-content: start;");
    expect(breakpoint).toContain(".listPanel,\n  .editorPanel {\n    min-height: 0;");
    expect(breakpoint).toContain("grid-template-rows: auto auto minmax(180px, 0.8fr) auto auto");
  });
});
