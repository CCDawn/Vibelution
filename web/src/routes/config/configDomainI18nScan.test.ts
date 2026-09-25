import { describe, expect, it } from "vitest";

/**
 * Settings-align wave 4 i18n gate: the settings domain must not carry bare
 * (single-language) Chinese string literals in component/hook source. All
 * user-facing copy lives in the bilingual table configCopy.ts (zh + en).
 *
 * Exemptions
 * - configCopy.ts itself: it IS the bilingual table (zh strings are its payload).
 * - Comments: stripped before scanning.
 * - Regex literals that match server-side bilingual error messages
 *   (configApplyModel / configDiagnosisPresentation): not string literals,
 *   therefore not scanned.
 * - Files holding `zh/en` data pairs by design (bilingual-at-the-source, no
 *   hole): ConfigShortcutsPanel, ConfigFeatureDecisionPanel,
 *   ConfigSettingsNavigation, ConfigDesktopPetSettings, ConfigSettingsIndex.
 */
import routeSource from "../ConfigRoute.tsx?raw";
import providerRegistryPanelSource from "../ConfigProviderRegistryPanel.tsx?raw";
import providerWizardSource from "../ConfigProviderWizard.tsx?raw";
import quickSetupPanelSource from "../ConfigQuickSetupPanel.tsx?raw";
import migrationPanelSource from "../ConfigModelMigrationPanel.tsx?raw";
import placeholderPanelSource from "../ConfigWorkspacePlaceholderPanel.tsx?raw";
import providerLogicSource from "../configProviderLogic.ts?raw";
import configCopySource from "./configCopy.ts?raw";
import sectionEditorSource from "./ConfigSectionEditor.tsx?raw";
import configApplyModelSource from "./configApplyModel.ts?raw";
import configEditorModelSource from "./configEditorModel.ts?raw";
import configFieldEditorsModelSource from "./configFieldEditorsModel.ts?raw";
import configProviderActionModelSource from "./configProviderActionModel.ts?raw";
import useConfigMigrationActionsSource from "./useConfigMigrationActions.ts?raw";
import useConfigProviderDraftActionsSource from "./useConfigProviderDraftActions.ts?raw";
import useConfigProviderModelDomainSource from "./useConfigProviderModelDomain.ts?raw";
import useConfigProviderQuickSetupActionsSource from "./useConfigProviderQuickSetupActions.ts?raw";

/** Files scanned by this gate: route shell + config/* modules + models panels. */
const SCANNED_SOURCES: Array<[string, string]> = [
  ["ConfigRoute.tsx", routeSource],
  ["ConfigProviderRegistryPanel.tsx", providerRegistryPanelSource],
  ["ConfigProviderWizard.tsx", providerWizardSource],
  ["ConfigQuickSetupPanel.tsx", quickSetupPanelSource],
  ["ConfigModelMigrationPanel.tsx", migrationPanelSource],
  ["ConfigWorkspacePlaceholderPanel.tsx", placeholderPanelSource],
  ["configProviderLogic.ts", providerLogicSource],
  ["config/ConfigSectionEditor.tsx", sectionEditorSource],
  ["config/configApplyModel.ts", configApplyModelSource],
  ["config/configEditorModel.ts", configEditorModelSource],
  ["config/configFieldEditorsModel.ts", configFieldEditorsModelSource],
  ["config/configProviderActionModel.ts", configProviderActionModelSource],
  ["config/useConfigMigrationActions.ts", useConfigMigrationActionsSource],
  ["config/useConfigProviderDraftActions.ts", useConfigProviderDraftActionsSource],
  ["config/useConfigProviderModelDomain.ts", useConfigProviderModelDomainSource],
  ["config/useConfigProviderQuickSetupActions.ts", useConfigProviderQuickSetupActionsSource],
];

const CJK = /[\u4e00-\u9fff]/;

/** Remove block comments, then line comments (guarded against `https://`). */
function stripComments(source: string): string {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, (match) => match.replace(/[^\n]/g, ""))
    .replace(/(^|[^:])\/\/[^\n]*/g, (match, prefix: string) => `${prefix}${""}`);
}

/** String literals ('…' / "…" / `…`) containing CJK characters. */
function findCjkStringLiterals(source: string): string[] {
  const cleaned = stripComments(source);
  const literal = /'[^'\n]*'|"[^"\n]*"|`[^`]*`/g;
  const hits: string[] = [];
  for (const match of cleaned.match(literal) ?? []) {
    if (CJK.test(match)) {
      hits.push(match.length > 80 ? `${match.slice(0, 77)}…` : match);
    }
  }
  return hits;
}

describe("settings domain i18n gate", () => {
  it("keeps bare Chinese string literals out of settings domain sources (copy lives in configCopy)", () => {
    const offenders = SCANNED_SOURCES
      .flatMap(([name, source]) => findCjkStringLiterals(source).map((literal) => `${name}: ${literal}`));
    expect(offenders, offenders.join("\n")).toEqual([]);
  });

  it("keeps the scan honest: configCopy stays the single bilingual table", () => {
    // The table itself carries the zh payload; both tables must stay key-aligned.
    expect(configCopySource).toContain("zh: {");
    expect(configCopySource).toContain("en: {");
    expect(configCopySource).toContain("as const");
  });
});
