import { describe, expect, it } from "vitest";

import routeSource from "./GitRoute.tsx?raw";
import diffViewSource from "./GitDiffView.tsx?raw";
import logicSource from "./gitRouteLogic.ts?raw";
import shellDictionarySource from "../i18n/shellDictionary.ts?raw";

describe("GitRoute layout contract", () => {
  it("uses shell language state without loading the full app dictionary", () => {
    expect(routeSource).toContain("useShellI18n");
    expect(routeSource).toContain("const { lang, t } = useShellI18n()");
    expect(routeSource).not.toContain("useAppI18n");
    expect(diffViewSource).toContain("useShellI18n");
    expect(diffViewSource).not.toContain("useAppI18n");
    expect(logicSource).toContain("ShellTranslationKey");
    expect(logicSource).not.toContain("../i18n/dictionary");
  });

  it("keeps Git shell copy available for the route and diff preview", () => {
    expect(shellDictionarySource).toContain("gitCommitBlockedStagedOutsideSelection");
    expect(shellDictionarySource).toContain("gitAiPromptPlaceholder");
    expect(shellDictionarySource).toContain("readonlyPreview");
    expect(shellDictionarySource).toContain("previewTruncated");
  });

  it("keeps commit actions scoped to selected files", () => {
    expect(routeSource).toContain("selectedPaths");
    expect(routeSource).toContain("stagedOutsideSelection");
    expect(routeSource).toContain("gitCommitSelected");
  });
});
