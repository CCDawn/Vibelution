import { VConfirmDialog } from "../../components/vui";
import { AgentPermissionPresetControl } from "../../components/vui/product/agent-management";
import type { LauncherManagementPermissionControlState } from "./useLauncherManagementPermission";
import styles from "./LauncherManagementPermissionControl.styles";

/** Launcher-only composition of the shared permission selector and native-state hook. */
export function LauncherManagementPermissionControl({ state, lang }: {
  state: LauncherManagementPermissionControlState;
  lang: "zh" | "en";
}) {
  const unavailable = lang === "zh" ? "当前版本暂不支持切换权限，请更新 Launcher。" : "This version cannot change permissions. Update Launcher.";
  return <div className={styles.footer} data-launcher-management-permission>
    <div className={styles.row}>
      <AgentPermissionPresetControl value={state.value} context="launcher" lang={lang} surface="composer"
        side="top" align="start" disabled={state.disabled} pending={state.pending} onChange={state.choose} />
      <span className={styles.scope} title={lang === "zh"
        ? "新档位仅用于之后的操作，已有待确认操作仍需单独处理；不会增加项目或私人资料的访问权限。"
        : "The new level applies to future actions. Existing approvals still need a separate decision. Access to projects and private data will not expand."}>
        {lang === "zh" ? "仅 Launcher 助理" : "Launcher assistant only"}
      </span>
    </div>
    {state.disabled || state.error ? <p className={styles.notice} role={state.error ? "alert" : "status"}>
      {state.error || unavailable}
    </p> : null}
    <VConfirmDialog open={state.confirmationOpen} onOpenChange={open => { if (!open) state.closeConfirmation(); }}
      title={lang === "zh" ? "启用完全访问权限？" : "Enable full access?"} size="sm" tone="danger"
      description={lang === "zh"
        ? "开启后，助理可在已授权项目内直接执行重启、永久删除等管理操作。不会增加项目或私人资料的访问权限。已有待确认操作仍需单独处理。"
        : "The assistant may directly execute management actions in authorized projects, including restarts and permanent deletion. Access to projects and private data will not expand. Existing approvals still need a separate decision."}
      confirmLabel={lang === "zh" ? "启用完全访问" : "Enable full access"} cancelLabel={lang === "zh" ? "取消" : "Cancel"}
      confirmPending={state.pending} onConfirm={state.confirmFullAccess} onCancel={state.closeConfirmation} />
  </div>;
}
