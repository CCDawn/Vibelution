/**
 * Teams toolbar actions: import a team bundle (dialog) and export the
 * selected team as a bundle JSON download. Self-contained mount — the
 * toolbar only renders <TeamBundleToolbarActions />.
 */
import { useCallback, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Download, Upload } from "lucide-react";

import { fetchTeamBundle } from "../../api/teamBundles";
import { VButton } from "../../components/vui";
import { startUserAction } from "../../app/userActionTelemetry";
import { TeamBundleImportDialog } from "./TeamBundleImportDialog";
import { useTeamBundleImportActions } from "./useTeamBundleImportActions";
import styles from "./TeamBundleToolbarActions.styles";

export type TeamBundleToolbarActionsProps = {
  lang: "zh" | "en";
  selectedTeamId?: string;
};

function downloadBundleJson(teamName: string, payload: unknown) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${teamName || "team"}-bundle.json`;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function TeamBundleToolbarActions({ lang, selectedTeamId }: TeamBundleToolbarActionsProps) {
  const [open, setOpen] = useState(false);
  const [exportPending, setExportPending] = useState(false);
  const queryClient = useQueryClient();
  const { state, prepareBundleFile, confirmImport, reset } = useTeamBundleImportActions({ queryClient });

  const handleExport = useCallback(async () => {
    const teamId = selectedTeamId?.trim();
    if (!teamId || exportPending) {
      return;
    }
    setExportPending(true);
    try {
      const bundle = await fetchTeamBundle(teamId);
      downloadBundleJson(bundle.team?.name ?? teamId, bundle);
    } finally {
      setExportPending(false);
    }
  }, [exportPending, selectedTeamId]);

  const exportLabel = lang === "zh" ? "导出团队配置包" : "Export team bundle";
  const importLabel = lang === "zh" ? "导入团队配置包" : "Import team bundle";

  return (
    <>
      <div className={styles.actions} data-vui-region="team-bundle-actions">
        <VButton
          type="button"
          variant="ghost"
          density="compact"
          icon={<Upload size={14} aria-hidden="true" />}
          aria-label={importLabel}
          title={importLabel}
          onClick={() => {
            reset();
            setOpen(true);
          }}
        >
          {importLabel}
        </VButton>
        {selectedTeamId ? (
          <VButton
            type="button"
            variant="ghost"
            density="compact"
            icon={<Download size={14} aria-hidden="true" />}
            aria-label={exportLabel}
            title={exportLabel}
            isDisabled={exportPending}
            onClick={() => {
              startUserAction("teams.teamBundle.export");
              void handleExport();
            }}
          >
            {exportLabel}
          </VButton>
        ) : null}
      </div>
      <TeamBundleImportDialog
        open={open}
        lang={lang}
        state={state}
        onSelectFile={(file) => {
          startUserAction("teams.teamBundle.import");
          void prepareBundleFile(file);
        }}
        onConfirm={() => {
          void confirmImport();
        }}
        onClose={() => {
          setOpen(false);
          reset();
        }}
      />
    </>
  );
}
