import { describe, expect, it } from "vitest";

import routerSource from "../app/router.tsx?raw";
import routeSource from "./PromptTemplatesRoute.tsx?raw";
import styles from "./PromptTemplatesRoute.styles";
import stylesSource from "./PromptTemplatesRoute.styles.ts?raw";

describe("PromptTemplatesRoute layout contract", () => {
  it("lives inside Agent management navigation with the shared nav row", () => {
    expect(routerSource).toContain('path: "agents/prompts"');
    expect(routerSource).toContain("<PromptTemplatesRoute />");
    expect(routeSource).toContain('<AgentManagementNav active="prompts" className={styles.managementNavClass} />');
    expect(stylesSource).toContain("const managementNavClass");
    expect(routeSource.indexOf('<AgentManagementNav active="prompts" className={styles.managementNavClass} />')).toBeGreaterThan(
      routeSource.indexOf("</VRouteHeader>"),
    );
    expect(routeSource.indexOf('<AgentManagementNav active="prompts" className={styles.managementNavClass} />')).toBeLessThan(
      routeSource.indexOf("className={styles.summaryStripClass}"),
    );
  });

  it("uses shell language state without loading the full app dictionary", () => {
    expect(routeSource).toContain("useShellI18n");
    expect(routeSource).toContain("const { lang } = useShellI18n()");
    expect(routeSource).not.toContain("useAppI18n");
  });

  it("keeps route and header chrome light enough for AppShell/VUI backgrounds", () => {
    const routeClass = stylesSource.match(/const routeClass = "([^"]+)"/)?.[1] ?? "";
    const headerClass = stylesSource.match(/const headerClass = "([^"]+)"/)?.[1] ?? "";

    expect(routeClass).not.toContain("surface-page");
    expect(routeClass).not.toMatch(/\bbg-\[/);
    expect(headerClass).not.toContain("gradient");
    expect(headerClass).not.toContain("shadow-[");
    expect(headerClass).not.toContain("vui-shadow");
    expect(headerClass).toContain("!bg-transparent");
    expect(headerClass).toContain("!shadow-none");
    expect(headerClass).toContain("!backdrop-blur-none");
  });

  it("loads prompt templates and linked Agents through the existing APIs", () => {
    expect(routeSource).toContain('queryKeys.promptTemplates()');
    expect(routeSource).toContain('fetchJson<PromptTemplateWorkspace>("/api/prompt-templates?includeInactive=true")');
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

  it("keeps prompt edits coherent with Agent workspace cache and frozen session snapshots", () => {
    expect(routeSource).toContain("queryKeys.agentConfigWorkspace()");
    expect(routeSource).toContain("copy.snapshotNotice");
    expect(routeSource).toContain("tooltip={copy.snapshotNotice}");
    expect(routeSource).not.toContain('<p className={styles.helperTextClass}>{copy.snapshotNotice}</p>');
    expect(routeSource).toContain("editableTemplate?.hasDefault");
    expect(routeSource).toContain("if (!template.hasDefault)");
    expect(routeSource).not.toContain("if (!template.defaultContent?.trim())");
    expect(routeSource).toContain("sourceAuthority");
    expect(routeSource).toContain("sourceDriftStatus");
  });

  it("supports category deep links and the expected workbench panels", () => {
    expect(routeSource).toContain('searchParams.get("category")');
    expect(routeSource).toContain('next.delete("category")');
    expect(routeSource).toContain('next.set("category", categoryFilter)');
    expect(routeSource).toContain('"research"');
    expect(routeSource).toContain("workspaceClass");
    expect(routeSource).toContain("listPanelClass");
    expect(routeSource).toContain("editorPanelClass");
    expect(routeSource).toContain("templateListClass");
    expect(routeSource).toContain("agentListClass");
  });

  it("supports Agent config deep links and preserves return navigation", () => {
    expect(routeSource).toContain('searchParams.get("agent")');
    expect(routeSource).toContain('searchParams.get("template")');
    expect(routeSource).toContain('searchParams.get("focus")');
    expect(routeSource).toContain("safeAgentCenterReturnToPath(searchParams.get(\"returnTo\"))");
    expect(routeSource).toContain("returnButtonClass");
    expect(routeSource).toContain("selectableRowLinkedClass");
    expect(routeSource).toContain("agentItemLinkedClass");
    expect(routeSource).toContain("editorPanelFocusedClass");
    expect(routeSource).toContain("linkedBorderClass");
  });

  it("keeps the prompt content editor as the primary visible area", () => {
    expect(routeSource).toContain("nameFieldClass");
    expect(routeSource).toContain("contentFieldClass");
    expect(routeSource.indexOf("contentFieldClass")).toBeLessThan(routeSource.indexOf("bottomGridClass"));
  });

  it("supports bulk prompt selection with safe existing mutations", () => {
    expect(routeSource).toContain("selectedTemplateIds");
    expect(routeSource).toContain("<VNativeInput");
    expect(routeSource).toContain("<VNativeSelect");
    expect(routeSource).toContain("<VNativeTextarea");
    expect(routeSource).not.toMatch(/<input\b/);
    expect(routeSource).not.toMatch(/<select\b/);
    expect(routeSource).not.toMatch(/<textarea\b/);
    expect(routeSource).toContain("bulkPatchTemplates({ category: bulkCategory }, copy.bulkCategoryResult)");
    expect(routeSource).toContain("bulkPatchTemplates({ status: \"inactive\" }, copy.bulkDeactivateResult)");
    expect(routeSource).toContain("bulkResetTemplates");
    expect(routeSource).toContain("copy.bulkDeactivateConfirm");
    expect(routeSource).toContain("copy.bulkResetConfirm");
    expect(routeSource).toContain("window.confirm(copy.bulkDeactivateConfirm)");
    expect(routeSource).toContain("window.confirm(copy.bulkResetConfirm)");
    expect(routeSource).toContain("bulkActionBarClass");
    expect(routeSource).toContain("selectableRowClass");
    expect(routeSource).toContain("<VTooltip content={`${copy.bulkSelected}:");
    expect(routeSource).toContain("disabledReason={bulkPromptPending ? copy.bulkWorking : copy.bulkNoSelection}");
    expect(routeSource).toContain('method: "PATCH"');
    expect(routeSource).toContain('method: "POST"');
    expect(routeSource).toContain("/reset`");
  });

  it("keeps bulk prompt controls in their own compact row above the list", () => {
    expect(routeSource).toContain("listPanelClass");
    expect(stylesSource).toContain("grid-rows-[auto_auto_auto_auto_minmax(0,1fr)]");
    expect(routeSource).toContain("bulkActionBarClass");
    expect(stylesSource).toContain("max-w-full flex-wrap items-center");
    expect(stylesSource).toContain("flex-[1_1_118px]");
    expect(stylesSource).not.toContain("grid-cols-[auto_auto_minmax(118px,1fr)]");
    expect(stylesSource).toContain("min-h-[26px]");
  });

  it("keeps the narrow prompt workspace scrollable without oversized editor panels", () => {
    expect(routeSource).toContain("workspaceClass");
    expect(stylesSource).toContain("clamp(260px,26vw,380px)");
    expect(stylesSource).toContain("minmax(0,1fr)");
    expect(stylesSource).toContain("max-[980px]:grid-cols-1");
    expect(stylesSource).toContain("max-[980px]:content-start");
    expect(stylesSource).toContain("max-[980px]:overflow-auto");
    expect(stylesSource).toContain("max-[980px]:grid-rows-[auto_auto_auto_minmax(180px,0.8fr)_auto_auto]");
  });

  it("keeps prompt controls content-sized and detail metadata row-like", () => {
    expect(styles.primaryButtonClass).toContain("w-fit");
    expect(styles.primaryButtonClass).toContain("max-w-full");
    expect(styles.secondaryButtonClass).toContain("w-fit");
    expect(styles.filterButtonClass).toContain("w-fit");
    expect(styles.panelBaseClass).not.toContain("bg-[var(--surface-panel)]");
    expect(styles.detailRowClass).toContain("grid-cols-[auto_minmax(0,1fr)]");
    expect(styles.detailRowClass).toContain("border-b");
    expect(styles.detailRowClass).not.toContain("bg-[var(--surface-card)]");
    expect(styles.detailCardClass).not.toContain("bg-[var(--surface-panel)]");
    expect(styles.agentListClass).not.toContain("bg-[var(--surface-panel)]");
  });

  it("lets multiline prompt template rows define their own height", () => {
    expect(routeSource).toMatch(/contentLayout="plain"[\s\S]{0,180}styles\.templateButtonBaseClass/);
    expect(styles.templateButtonBaseClass).toContain("!h-auto");
    expect(styles.templateButtonBaseClass).toContain("!grid");
    expect(styles.templateButtonBaseClass).toContain("w-full");
    expect(styles.templateMetaClass).toContain("min-w-0");
    expect(styles.templateMetaClass).toContain("[&_span]:truncate");
    expect(styles.templateMetaClass).toContain("[&_span]:whitespace-nowrap");
  });

  it("uses VUI composition for summary, panels, bulk controls, and default status", () => {
    expect(routeSource).toContain("VStatusStrip");
    expect(routeSource).toContain("VSurface");
    expect(routeSource).toContain("VDenseToolbar");
    expect(routeSource).toContain("VPanelHeader");
    expect(routeSource).toContain("VStatusChip");
    expect(routeSource).toContain("className={styles.summaryStripClass}");
    expect(routeSource).toContain("<VSurface");
    expect(routeSource).toContain("as=\"aside\"");
    expect(routeSource).toContain("as=\"section\"");
    expect(routeSource).toContain("<VDenseToolbar");
    expect(routeSource).toContain("tone={hasDefault ? \"success\" : \"neutral\"}");
    expect(routeSource).not.toContain("hasDefault ? styles.statePillClass : styles.templateMetaClass");
    expect(stylesSource).not.toContain("const summaryCardClass");
    expect(stylesSource).not.toContain("const statePillClass");
  });
});
