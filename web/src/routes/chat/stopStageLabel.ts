/**
 * Stop-chain progress copy.
 *
 * The backend already stamps every stop stage (requested / provider_aborted /
 * tools_cancelled / snapshot_persisted / stop_observed / forced). Until now the
 * composer showed the same static "stopping" copy for the whole window, so a
 * stop that waited on a long tool looked identical to one that was stuck. The
 * label names the hop the stop is currently on.
 */
import type { SessionStopStage } from "../../api/types/chat";

const STOP_STAGE_COPY: Record<string, { zh: string; en: string }> = {
  requested: { zh: "已受理", en: "request received" },
  provider_aborted: { zh: "已中断模型", en: "model aborted" },
  stop_observed: { zh: "已观察到停止", en: "stop observed" },
  tools_cancelled: { zh: "已取消工具", en: "tools cancelled" },
  snapshot_persisted: { zh: "正在保存现场", en: "saving snapshot" },
  forced: { zh: "强制收尾", en: "forcing settle" },
};

export function resolveStopStageLabel(
  stages: readonly SessionStopStage[] | null | undefined,
  lang: "zh" | "en",
): string {
  if (!Array.isArray(stages) || stages.length === 0) {
    return "";
  }
  const stage = String(stages[stages.length - 1]?.stage ?? "").trim();
  const copy = STOP_STAGE_COPY[stage];
  if (!copy) {
    return "";
  }
  return lang === "zh" ? `正在停止 · ${copy.zh}` : `Stopping · ${copy.en}`;
}
