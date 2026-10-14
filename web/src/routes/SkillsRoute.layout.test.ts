import { describe, expect, it } from "vitest";

import appShellSource from "../app/AppShell.tsx?raw";
import routerSource from "../app/router.tsx?raw";
import routeSource from "./SkillsRoute.tsx?raw";
import skillsApiSource from "../api/skills.ts?raw";
import styles from "./SkillsRoute.styles";
import stylesSource from "./SkillsRoute.styles.ts?raw";

function extractConstClass(name: string) {
  return stylesSource.match(new RegExp(`const ${name} = "([^"]+)"`))?.[1] ?? "";
}

describe("SkillsRoute layout contract", () => {
  it("is mounted as an Agent management section with the shared module bar", () => {
    expect(routerSource).toContain('path: "agents/skills"');
    expect(routerSource).toContain("<SkillsRoute />");
    expect(routerSource).not.toContain('path: "skills"');
    expect(routerSource).not.toContain('to="/agents/skills" replace');
    expect(routeSource).toContain("<AgentManagementModuleBar");
    expect(routeSource).toContain('active="skills"');
    expect(routeSource).toContain("VListDetailPage");
    expect(routeSource).toContain("toolbar={(");
    expect(routeSource.indexOf("<AgentManagementModuleBar")).toBeGreaterThan(
      routeSource.indexOf("toolbar={("),
    );
    expect(routeSource).not.toContain("VStatusStrip");
    expect(routeSource).not.toContain("summaryStripClass");
    expect(routeSource).toContain("workspaceClassName={styles.workspaceClass}");
    expect(routeSource).toContain("list={(");
    expect(routeSource).toContain("detail={(");
    expect(appShellSource).not.toContain('to="/skills"');
  });

  it("uses shell language state without loading the full app dictionary", () => {
    expect(routeSource).toContain("useShellI18n");
    expect(routeSource).toContain("const { lang } = useShellI18n()");
    expect(routeSource).not.toContain("useAppI18n");
  });

  it("uses read-only skill library APIs", () => {
    expect(routeSource).toContain("fetchSkillLibrary(");
    expect(routeSource).toContain("fetchSkillLibraryDetail(");
    expect(skillsApiSource).toContain('"/api/skills"');
    expect(skillsApiSource).toContain("/api/skills/${encodeURIComponent(command)}");
    expect(routeSource).not.toContain('method: "POST"');
    expect(routeSource).not.toContain('method: "PUT"');
    expect(routeSource).not.toContain('method: "PATCH"');
    expect(routeSource).not.toContain('method: "DELETE"');
  });

  it("surfaces slash command and SKILL.md preview", () => {
    expect(routeSource).toContain("copyCommand(activeSkill.command)");
    expect(routeSource).toContain("SKILL.md");
    expect(routeSource).toContain("activeSkill.preview");
    expect(routeSource).toContain("activeSkill.aliases.join");
  });

  it("adds bulk selection without breaking the read-only skill contract", () => {
    expect(routeSource).toContain("selectedSkillCommands");
    expect(routeSource).toContain("copySelectedSkillCommands");
    expect(routeSource).toContain("copy.bulkReadOnlyReason");
    expect(routeSource).toContain("<VNativeInput");
    expect(routeSource).not.toMatch(/<input\b/);
    expect(routeSource).not.toMatch(/<select\b/);
    expect(routeSource).not.toMatch(/<textarea\b/);
    expect(routeSource).not.toContain("{copy.bulkEdit}");
    expect(routeSource).not.toContain("{copy.bulkDelete}");
    expect(routeSource).toContain("<VTooltip content={`${copy.bulkSelected}: ${skill.name}`}");
    expect(routeSource).toContain("bulkReadOnlyNoteClass");
    expect(routeSource).not.toContain("title={copy.bulkReadOnlyReason}");
    expect(routeSource).toContain("<VDenseToolbar");
    expect(routeSource).toContain("useState(false)");
    expect(routeSource).toContain("{bulkSelectionMode ? <VDenseToolbar");
    expect(routeSource).toContain("{bulkSelectionMode ? <VTooltip");
    expect(routeSource).toContain("{selectedSkills.length ? <VButton");
    expect(routeSource).toContain("copy.bulkSelect}");
    expect(styles.listPanelClass).toContain("flex-col");
    expect(styles.skillListClass).toContain("flex-1");
    expect(routeSource).toContain("selectableRowClass");
    expect(routeSource).not.toContain('method: "POST"');
    expect(routeSource).not.toContain('method: "PUT"');
    expect(routeSource).not.toContain('method: "PATCH"');
    expect(routeSource).not.toContain('method: "DELETE"');
  });

  it("keeps the narrow skill workspace in normal document flow with compact empty details", () => {
    expect(routeSource).toContain("workspaceClass");
    expect(routeSource).toContain("layoutId={WORKBENCH_LAYOUT_IDS.skills}");
    expect(routeSource).toContain("defaultWidth: 304, minWidth: 300, maxWidth: 520");
    expect(styles.workspaceClass).toContain("max-[920px]:!flex-col");
    expect(styles.workspaceClass).toContain("[&>[data-vui=split-sidebar]]:!w-full");
    expect(styles.workspaceClass).toContain("[&>[data-vui=split-main]]:!shrink-0");
    expect(styles.workspaceClass).toContain("[&>[role=separator]]:!hidden");
    expect(stylesSource).toContain("max-[920px]:overflow-auto");
    expect(routeSource).toContain("listPanelClass");
    expect(routeSource).toContain("detailPanelClass");
    expect(routeSource).toContain("emptyDetailClass");
    expect(stylesSource).toContain("min-h-24");
    expect(stylesSource).toContain("p-3");
  });

  it("removes the redundant route header while keeping the route background-aware", () => {
    const routeClass = extractConstClass("routeClass");

    expect(routeClass).not.toContain("surface-page");
    expect(routeClass).not.toMatch(/\bbg-\[(?:var\(--surface-page\)|color-mix\(in_srgb,var\(--surface-page\))/);
    expect(routeSource).toContain("hideHeader");
    expect(routeSource).not.toContain("headerClassName=");
  });

  it("keeps Skills surfaces lightweight instead of building nested opaque card walls", () => {
    const surfaceClasses = [
      extractConstClass("panelClass"),
      extractConstClass("commandPanelClass"),
      extractConstClass("metaGridClass"),
      extractConstClass("surfacePanelClass"),
      extractConstClass("emptyDetailClass"),
    ];

    expect(surfaceClasses).toHaveLength(5);
    surfaceClasses.forEach((className) => {
      expect(className).not.toContain("bg-[var(--surface-panel)]");
      expect(className).not.toContain("bg-[var(--surface-card)]");
      expect(className).not.toContain("shadow-[");
    });
    expect(routeSource).toContain("<VSurface");
    expect(routeSource).toContain("tone=\"panel\"");
  });

  it("keeps toolbar buttons sized to their content while full-row skill buttons remain explicit", () => {
    const compactButtonClasses = [
      styles.filterButtonClass,
      styles.primaryButtonClass,
    ];
    const skillButtonBaseClass = styles.skillButtonBaseClass;

    compactButtonClasses.forEach((className) => {
      expect(className).toContain("inline-flex");
      expect(className).toContain("w-fit");
      expect(className).toContain("max-w-full");
      expect(className.split(/\s+/)).not.toContain("w-full");
    });
    expect(skillButtonBaseClass).toContain("w-full");
    expect(skillButtonBaseClass).toContain("!h-auto");
    expect(skillButtonBaseClass).toContain("!grid");
    expect(skillButtonBaseClass).toContain("grid-cols-[auto_minmax(0,1fr)]");
    expect(routeSource).toMatch(/contentLayout="plain"[\s\S]{0,180}styles\.skillButtonBaseClass/);
  });

  it("uses shared rail and pane boundaries with flat neutral list rows", () => {
    expect(styles.listPanelClass).toContain("vui-workbench-rail");
    expect(styles.detailPanelClass).toContain("!border-0");
    expect(styles.detailPanelClass).toContain("!bg-transparent");
    expect(styles.skillButtonBaseClass).toContain("!bg-transparent");
    expect(styles.skillButtonBaseClass).toContain("!border-0");
    expect(styles.skillButtonBaseClass).toContain("!shadow-none");
    expect(styles.skillButtonActiveClass).toBe("!bg-[var(--vui-selection-bg)]");
    expect(routeSource).toContain("<small className={styles.sourceCaptionClass}>");
    expect(routeSource).not.toContain("sourcePillClass");
    expect(styles.contentPreClass).toContain("border-0 bg-transparent");
    expect(styles.contentPreClass).toContain("leading-[1.7]");
    [styles.primaryButtonClass, styles.filterTabsTriggerClass, styles.searchInputClass, styles.metadataSummaryClass]
      .forEach((className) => expect(className).toContain("min-h-11"));
    expect(styles.rowSelectClass).toContain("max-[920px]:w-11");
  });

  it("keeps detail chrome and command rows responsive on narrow viewports", () => {
    expect(extractConstClass("detailHeaderClass")).toContain("max-[720px]:flex-wrap");
    expect(extractConstClass("contentHeaderClass")).toContain("max-[720px]:flex-wrap");
    expect(styles.commandPanelClass).toContain("max-[720px]:grid-cols-[auto_minmax(0,1fr)]");
    expect(extractConstClass("rootRowClass")).toContain("max-[720px]:grid-cols-1");
  });

  it("uses VUI composition for panels and bulk/list surfaces", () => {
    expect(routeSource).not.toContain("VStatusStrip");
    expect(routeSource).toContain("VSurface");
    expect(routeSource).toContain("VDenseToolbar");
    expect(routeSource).toContain("VPanelHeader");
    expect(routeSource).toContain("VStatusChip");
    expect(routeSource).not.toContain("summaryStripClass");
    expect(routeSource).toContain("<VSurface");
    expect(routeSource).toContain('as="section"');
    expect(routeSource).toContain("VListDetailPage");
    expect(routeSource).toContain("as=\"section\"");
    expect(routeSource).toContain("<VDenseToolbar");
    expect(routeSource).toContain("<VStatusChip");
    expect(stylesSource).not.toContain("const summaryCardClass");
    expect(stylesSource).not.toContain("const bulkActionBarClass");
  });
});
