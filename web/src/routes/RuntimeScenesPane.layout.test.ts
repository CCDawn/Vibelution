import { describe, expect, it } from "vitest";

import paneSource from "./RuntimeScenesPane.tsx?raw";

describe("RuntimeScenesPane layout contract", () => {
  it("renders package diagnosis before evidence metrics and raw log sections", () => {
    const diagnosisIndex = paneSource.indexOf("{renderPackageDiagnosisPanel(scene, lang, handleOpenRawLog)}");
    const evidenceIndex = paneSource.indexOf('<div className={styles.sceneEvidenceStrip}>');
    const rawHeaderIndex = paneSource.indexOf('{t("runtimeSceneRawLogs")}');

    expect(diagnosisIndex).toBeGreaterThan(0);
    expect(evidenceIndex).toBeGreaterThan(diagnosisIndex);
    expect(rawHeaderIndex).toBeGreaterThan(evidenceIndex);
  });

  it("keeps package diagnosis compact by folding low-frequency details", () => {
    expect(paneSource).toContain("<details className={styles.packageDiagnosisDetails}>");
    expect(paneSource).toContain("{lang === \"zh\" ? \"阅读顺序与关键入口\" : \"Reading order and key entries\"}");
    expect(paneSource).toContain("packageDiagnosisFoldout");
    expect(paneSource).toContain("packageDiagnosisInlineMetrics");
    expect(paneSource).toContain("handleOpenRawLog(scene.runtimeSceneId, entry.path)");
  });
});
