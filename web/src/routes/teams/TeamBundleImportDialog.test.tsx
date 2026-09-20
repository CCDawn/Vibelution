import { describe, expect, it } from "vitest";

import {
  TeamBundleImportDialog,
  teamBundleImportCopy,
  teamBundlePreviewRows,
} from "./TeamBundleImportDialog";
import { initialTeamBundleImportState } from "./teamBundleImportLogic";
import type { TeamBundleImportReport } from "../../api/types";
import source from "./TeamBundleImportDialog.tsx?raw";

const sampleReport: TeamBundleImportReport = {
  schemaVersion: 1,
  bundleSchemaVersion: 1,
  status: "ready",
  dryRun: true,
  team: { name: "挑战杯团队", action: "create" },
  agents: { create: ["搜索", "评估"], overwrite: [] },
  dependencies: {
    missingProviders: ["dashscope_main"],
    missingModels: [],
    pendingCredentials: [{ providerId: "dashscope_main", credentialEnv: "DASHSCOPE_API_KEY" }],
  },
  warnings: [],
};

describe("TeamBundleImportDialog", () => {
  it("assembles zh preview rows from a dry-run report", () => {
    const rows = teamBundlePreviewRows(sampleReport, teamBundleImportCopy("zh"));
    expect(rows).toEqual([
      { label: "将新建的 Agent", value: "搜索、评估" },
      { label: "将覆盖的 Agent", value: "" },
      { label: "缺失的服务商（请先在配置页补齐）", value: "dashscope_main" },
      { label: "尚未设置的密钥环境变量", value: "DASHSCOPE_API_KEY" },
    ]);
  });

  it("uses VUI dialog and buttons only (no raw button element)", () => {
    expect(source).toContain("VDialog");
    expect(source).toContain("VButton");
    expect(source).not.toMatch(/<button[\s>]/);
  });

  it("provides a pure zh/en copy table", () => {
    expect(teamBundleImportCopy("zh").title).toBe("导入团队配置包");
    expect(teamBundleImportCopy("en").title).toBe("Import team bundle");
  });

  it("renders without crashing in the idle state", () => {
    expect(() =>
      TeamBundleImportDialog({
        open: true,
        lang: "zh",
        state: initialTeamBundleImportState(),
        onSelectFile: () => {},
        onConfirm: () => {},
        onClose: () => {},
      }),
    ).not.toThrow();
  });
});
