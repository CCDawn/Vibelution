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

  it("keeps package diagnosis actionable with key entry buttons", () => {
    expect(paneSource).toContain("diagnosis.agentNextStep");
    expect(paneSource).toContain("diagnosis.recommendedOrder");
    expect(paneSource).toContain("diagnosis.keyEntries");
    expect(paneSource).toContain("handleOpenRawLog(scene.runtimeSceneId, entry.path)");
  });
});
