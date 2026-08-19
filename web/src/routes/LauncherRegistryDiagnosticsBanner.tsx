import { Copy, RefreshCw } from "lucide-react";

import type { LauncherRegistryReconciliationItem, LauncherStateSnapshotV1 } from "../api/launcher";
import { VButton, VStateSurface } from "../components/vui";
import {
  buildLauncherRegistryDiagnosticText,
  copyLauncherRegistryDiagnostics,
} from "./launcherRegistryDiagnostics";

function compactDate(value: string | undefined, locale: string) {
  const text = String(value || "").trim();
  if (!text) {
    return "";
  }
  const date = new Date(text);
  if (Number.isNaN(date.getTime())) {
    return text;
  }
  return new Intl.DateTimeFormat(locale, {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(date);
}

type LauncherRegistryDiagnosticsBannerProps = {
  className?: string;
  uiLang: "zh" | "en";
  locale: string;
  snapshot: LauncherStateSnapshotV1;
  classifications: LauncherRegistryReconciliationItem[];
  canRecheck: boolean;
  rechecking: boolean;
  onRecheck: () => void;
  onNotice: (notice: { tone: "success" | "error"; text: string }) => void;
};

export function LauncherRegistryDiagnosticsBanner({
  className,
  uiLang,
  locale,
  snapshot,
  classifications,
  canRecheck,
  rechecking,
  onRecheck,
  onNotice,
}: LauncherRegistryDiagnosticsBannerProps) {
  const copyDiagnosticsLabel = uiLang === "zh" ? "复制诊断" : "Copy diagnostics";
  const recheckLabel = uiLang === "zh" ? "再核对" : "Recheck";
  const tone = snapshot.freshness === "stale" ? "unavailable" : snapshot.freshness === "refreshing" ? "loading" : "info";

  const copyDiagnostics = () => {
    const text = buildLauncherRegistryDiagnosticText({
      snapshot,
      items: classifications,
      uiLang,
    });
    void copyLauncherRegistryDiagnostics(text)
      .then(() => {
        onNotice({
          tone: "success",
          text: uiLang === "zh" ? "诊断已复制。" : "Diagnostics copied.",
        });
      })
      .catch((error: unknown) => {
        onNotice({
          tone: "error",
          text: error instanceof Error ? error.message : String(error),
        });
      });
  };

  return (
    <VStateSurface
      className={className}
      density="compact"
      tone={tone}
      title={[
        uiLang === "zh" ? "Launcher 状态快照" : "Launcher state snapshot",
        compactDate(snapshot.observedAt, locale),
        snapshot.freshness,
        snapshot.cleanup.reconciliation.active
          ? `${uiLang === "zh" ? "协调中" : "reconciling"}: ${snapshot.cleanup.reconciliation.reason || "-"}`
          : "",
        snapshot.staleReason || "",
      ].filter(Boolean).join(" · ")}
      actions={(
        <>
          <VButton
            type="button"
            density="compact"
            variant="secondary"
            disabledReason={uiLang === "zh" ? "没有可复制的快照" : "No snapshot to copy"}
            icon={<Copy size={13} />}
            onPress={copyDiagnostics}
          >
            <span>{copyDiagnosticsLabel}</span>
          </VButton>
          <VButton
            type="button"
            density="compact"
            variant="secondary"
            isDisabled={!canRecheck || rechecking}
            isPending={rechecking}
            disabledReason={canRecheck ? recheckLabel : (uiLang === "zh" ? "需要换新壳后才能再核对" : "Recheck needs a new desktop shell")}
            icon={<RefreshCw size={13} />}
            onPress={onRecheck}
          >
            <span>{recheckLabel}</span>
          </VButton>
        </>
      )}
    />
  );
}
