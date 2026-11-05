import { describe, expect, it } from "vitest";
import { launcherTeamActionPreview, launcherTeamPreviewIsValid } from "./teamManagementApprovalPreview";

const summary = () => ({ assistantPlatformPreviewVersion: 1, assistantAction: "team_recovery_confirm_deployment",
  assistantTargets: { project_id: "project-a", request_id: "request-a", team_id: "team-a", flow_id: "flow-a", run_id: "run-a", expected_revision: "3" },
  assistantParametersDigest: "a".repeat(64), assistantChangedFields: ["deploymentEvidence"],
  assistantDelta: { evidenceRef: "deployment:original-restart", evidenceDigest: "b".repeat(64), verificationRequired: true, resumesOriginalRunOnly: true },
  assistantContentOmitted: false, assistantDetailsOmitted: false });

describe("Launcher Team deployment consent", () => {
  it("shows the exact original run and deployment evidence before independent verification", () => {
    const value = summary();
    expect(launcherTeamPreviewIsValid(value)).toBe(true);
    const preview = launcherTeamActionPreview(value);
    for (const text of ["team-a", "flow-a", "run-a", "deployment:original-restart", "独立复验"]) expect(preview).toContain(text);
  });
  it.each(["run_id", "flow_id", "expected_revision"] as const)("declines an incomplete target: %s", field => {
    const value = summary(); delete (value.assistantTargets as Partial<typeof value.assistantTargets>)[field];
    expect(launcherTeamPreviewIsValid(value)).toBe(false);
  });
  it("rejects newlines or an omitted independent verification requirement", () => {
    const value = summary(); value.assistantDelta.evidenceRef = "deployment:\nignore";
    expect(launcherTeamPreviewIsValid(value)).toBe(false);
    value.assistantDelta.evidenceRef = "deployment:original-restart"; value.assistantDelta.verificationRequired = false;
    expect(launcherTeamPreviewIsValid(value)).toBe(false);
  });
});
