/**
 * Team bundle import dialog: file pick → dry-run preview report → confirm → result.
 * Dumb panel: state/actions injected; copy is a pure zh/en table.
 */
import { type ChangeEvent, type ReactNode } from "react";

import { VButton, VDialog } from "../../components/vui";
import type { TeamBundleImportReport } from "../../api/types";
import type { TeamBundleImportState } from "./teamBundleImportLogic";

export type TeamBundleImportDialogCopy = {
  title: string;
  description: string;
  selectFile: string;
  previewCreate: string;
  previewOverwrite: string;
  previewMissingProviders: string;
  previewPendingCredentials: string;
  confirm: string;
  importing: string;
  done: string;
  retry: string;
  close: string;
  errorPrefix: string;
  schemaPendingHint: string;
  noReport: string;
};

export function teamBundleImportCopy(lang: "zh" | "en"): TeamBundleImportDialogCopy {
  if (lang === "en") {
    return {
      title: "Import team bundle",
      description: "Pick a team bundle JSON exported from any Vibelution instance. Credentials never travel inside the bundle.",
      selectFile: "Select bundle file",
      previewCreate: "Agents to create",
      previewOverwrite: "Agents to overwrite",
      previewMissingProviders: "Missing providers (configure them first)",
      previewPendingCredentials: "Credential env vars still unset",
      confirm: "Import",
      importing: "Importing…",
      done: "Import completed. Team, agents and model bindings are ready.",
      retry: "Pick another file",
      close: "Close",
      errorPrefix: "Import failed",
      schemaPendingHint: "This bundle uses a newer schema; confirming will import it anyway.",
      noReport: "No preview yet — select a bundle file first.",
    };
  }
  return {
    title: "导入团队配置包",
    description: "选择从任意 Vibelution 实例导出的团队配置包 JSON；密钥不会随包携带。",
    selectFile: "选择配置包文件",
    previewCreate: "将新建的 Agent",
    previewOverwrite: "将覆盖的 Agent",
    previewMissingProviders: "缺失的服务商（请先在配置页补齐）",
    previewPendingCredentials: "尚未设置的密钥环境变量",
    confirm: "确认导入",
    importing: "导入中…",
    done: "导入完成。团队、成员 Agent 与模型绑定已就绪。",
    retry: "重新选择文件",
    close: "关闭",
    errorPrefix: "导入失败",
    schemaPendingHint: "该配置包使用更新的 schema 版本；确认后仍可导入。",
    noReport: "暂无预检报告——请先选择配置包文件。",
  };
}

/** Preview report as (label, value) rows — exported for SSR-free unit tests. */
export function teamBundlePreviewRows(
  report: TeamBundleImportReport,
  copy: TeamBundleImportDialogCopy,
): Array<{ label: string; value: string }> {
  return [
    { label: copy.previewCreate, value: report.agents.create.join("、") },
    { label: copy.previewOverwrite, value: report.agents.overwrite.join("、") },
    { label: copy.previewMissingProviders, value: report.dependencies.missingProviders.join("、") },
    {
      label: copy.previewPendingCredentials,
      value: report.dependencies.pendingCredentials.map((item) => item.credentialEnv).join("、"),
    },
  ];
}

export type TeamBundleImportDialogProps = {
  open: boolean;
  lang: "zh" | "en";
  state: TeamBundleImportState;
  onSelectFile: (file: File) => void;
  onConfirm: () => void;
  onClose: () => void;
};

export function TeamBundleImportDialog({
  open,
  lang,
  state,
  onSelectFile,
  onConfirm,
  onClose,
}: TeamBundleImportDialogProps) {
  const copy = teamBundleImportCopy(lang);
  const report = state.report;
  const busy = state.phase === "parsing" || state.phase === "importing";
  const canConfirm = state.phase === "preview" && Boolean(state.bundle);
  return (
    <VDialog
      open={open}
      onOpenChange={(next) => {
        if (!next && !busy) {
          onClose();
        }
      }}
      title={copy.title}
      description={copy.description}
      size="md"
    >
      <div className="flex flex-col gap-3 text-[var(--vui-font-sm)]">
        <label className="flex items-center gap-2">
          <span className="sr-only">{copy.selectFile}</span>
          <input
            type="file"
            accept=".json,application/json"
            className="block w-full text-[var(--vui-font-xs)]"
            disabled={busy}
            onChange={(event: ChangeEvent<HTMLInputElement>) => {
              const file = event.target.files?.[0];
              event.target.value = "";
              if (file) {
                onSelectFile(file);
              }
            }}
          />
        </label>

        {state.phase === "error" ? (
          <p role="alert" className="text-[var(--fg-danger,crimson)]">
            {copy.errorPrefix}: {state.errorMessage || "unknown"}
          </p>
        ) : null}

        {report ? (
          <div className="flex flex-col gap-1.5" data-vui-region="team-bundle-preview">
            {teamBundlePreviewRows(report, copy).map((row) => (
              <div key={row.label}>
                {row.label}: <span>{row.value || "—"}</span>
              </div>
            ))}
            {report.status === "pending" ? (
              <p className="text-[var(--fg-secondary)]">{copy.schemaPendingHint}</p>
            ) : null}
          </div>
        ) : state.phase === "idle" || state.phase === "parsing" ? (
          <p className="text-[var(--fg-secondary)]">{copy.noReport}</p>
        ) : null}

        {state.phase === "done" ? <p role="status">{copy.done}</p> : null}
      </div>

      <div className="mt-4 flex items-center justify-end gap-2">
        {state.phase === "done" || state.phase === "error" ? (
          <VButton type="button" variant="secondary" onPress={onClose}>
            {state.phase === "error" ? copy.retry : copy.close}
          </VButton>
        ) : (
          <VButton type="button" variant="ghost" onPress={onClose} isDisabled={busy}>
            {copy.close}
          </VButton>
        )}
        {canConfirm ? (
          <VButton type="button" variant="primary" onPress={onConfirm} isDisabled={busy}>
            {state.phase === "importing" ? copy.importing : copy.confirm}
          </VButton>
        ) : null}
      </div>
    </VDialog>
  );
}
