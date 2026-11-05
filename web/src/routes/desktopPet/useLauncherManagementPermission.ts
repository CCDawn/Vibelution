import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  getLauncherAssistantStatus, setLauncherManagementPermissionPreset,
  type LauncherAssistantStatus, type LauncherManagementPermission,
} from "../../api/launcherAssistant";
import type { AgentPermissionPreset } from "../../api/types";

const statusKey = ["launcher-assistant", "status"] as const;
const identity = (status?: LauncherAssistantStatus) => status
  ? JSON.stringify([status.assistant.agentId, status.assistant.directSessionId]) : "";

/** Status is a read projection. An older in-flight poll cannot roll back a verified receipt. */
export function reconcileLauncherManagementPermission(incoming: LauncherAssistantStatus, current?: LauncherAssistantStatus): LauncherAssistantStatus {
  const previous = current?.settings?.managementPermission;
  const observed = incoming.settings?.managementPermission;
  if (identity(incoming) !== identity(current) || !previous || !observed || previous.revision < observed.revision) return incoming;
  return { ...incoming, settings: { ...incoming.settings!, managementPermission: previous } };
}

export async function readLauncherManagementStatus(current: () => LauncherAssistantStatus | undefined): Promise<LauncherAssistantStatus> {
  const incoming = await getLauncherAssistantStatus();
  return reconcileLauncherManagementPermission(incoming, current());
}

function failureMessage(error: unknown, lang: "zh" | "en"): string {
  const message = error instanceof Error ? error.message : "";
  if (message.includes("ASSISTANT_PERMISSION_CONFLICT")) return lang === "zh"
    ? "权限已在别处更新，正在核对当前档位；请重新选择。" : "Permissions changed elsewhere. Refreshing the current level; choose again.";
  if (message.includes("ASSISTANT_REQUEST_INVALID")) return lang === "zh"
    ? "当前版本暂不支持切换权限，请更新 Launcher。" : "This version cannot change permissions. Update Launcher.";
  if (message.includes("ASSISTANT_IDENTITY_INVALID")) return lang === "zh"
    ? "助理会话身份已失效，本次未保存；请刷新或重建助理会话后重选。" : "The assistant session identity is no longer valid. Nothing was saved; refresh or rebuild the assistant session and choose again.";
  if (message.includes("ASSISTANT_PERMISSION_UNAVAILABLE")) return lang === "zh"
    ? "权限设置暂不可用，请稍后重试。" : "Permission settings are temporarily unavailable. Try again shortly.";
  if (message.includes("ASSISTANT_PERMISSION_INVALID")) return lang === "zh"
    ? "权限设置无效，请刷新后重新选择。" : "Invalid permission setting. Refresh and choose again.";
  return lang === "zh" ? "权限保存尚未确认，当前显示保持不变；请刷新核对。" : "Permission change is unconfirmed. The displayed level is unchanged; refresh to verify.";
}

export function useLauncherManagementPermission(status: LauncherAssistantStatus | undefined, lang: "zh" | "en") {
  const client = useQueryClient();
  const owner = identity(status);
  const permission = status?.settings?.managementPermission;
  const ownerRef = useRef(owner);
  ownerRef.current = owner;
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const flight = useRef<object | null>(null);
  const [pendingOwner, setPendingOwner] = useState("");
  const [failure, setFailure] = useState<{ owner: string; message: string } | null>(null);
  const [unsupportedOwner, setUnsupportedOwner] = useState("");
  const [confirmation, setConfirmation] = useState<{ owner: string; revision: number } | null>(null);
  const pending = pendingOwner === owner && Boolean(owner);

  async function save(preset: AgentPermissionPreset, expected: LauncherManagementPermission) {
    if (!owner || flight.current) return;
    const token = {};
    flight.current = token;
    setPendingOwner(owner);
    setFailure(null);
    try {
      if (preset !== expected.preset && expected.revision === Number.MAX_SAFE_INTEGER) throw new Error("ASSISTANT_PERMISSION_INVALID");
      const receipt = await setLauncherManagementPermissionPreset(preset, expected.revision);
      if (receipt.revision !== expected.revision + (preset === expected.preset ? 0 : 1)) throw new Error("ASSISTANT_RESPONSE_INVALID");
      if (!mounted.current || ownerRef.current !== owner) return;
      client.setQueryData<LauncherAssistantStatus>(statusKey, current => {
        if (!current?.settings || identity(current) !== owner) return current;
        return reconcileLauncherManagementPermission({ ...current, settings: { ...current.settings, managementPermission: receipt } }, current);
      });
      void client.invalidateQueries({ queryKey: statusKey, exact: true });
    } catch (error) {
      if (!mounted.current || ownerRef.current !== owner) return;
      setFailure({ owner, message: failureMessage(error, lang) });
      if (error instanceof Error && error.message.includes("ASSISTANT_REQUEST_INVALID"))
        setUnsupportedOwner(owner);
      // Read the new revision, but never replay the rejected choice.
      if (error instanceof Error && error.message.includes("ASSISTANT_PERMISSION_CONFLICT"))
        void client.invalidateQueries({ queryKey: statusKey, exact: true });
    } finally {
      if (flight.current === token) {
        flight.current = null;
        if (mounted.current) setPendingOwner("");
      }
    }
  }

  function choose(preset: AgentPermissionPreset) {
    if (!permission || unsupportedOwner === owner || flight.current || preset === permission.preset) return;
    setFailure(null);
    if (preset === "full_access") setConfirmation({ owner, revision: permission.revision });
    else void save(preset, permission);
  }

  function confirmFullAccess() {
    const current = client.getQueryData<LauncherAssistantStatus>(statusKey);
    setConfirmation(null);
    if (!confirmation || identity(current) !== confirmation.owner
      || !current?.settings?.managementPermission || current.settings.managementPermission.revision !== confirmation.revision) {
      setFailure({ owner, message: lang === "zh" ? "权限已更新，请核对当前档位后重新选择。" : "Permissions changed. Review the current level and choose again." });
      return;
    }
    void save("full_access", current.settings.managementPermission);
  }

  return {
    value: permission?.preset ?? null,
    disabled: !permission || !owner || unsupportedOwner === owner,
    pending,
    error: failure?.owner === owner ? failure.message : "",
    choose,
    confirmationOpen: confirmation?.owner === owner && Boolean(owner),
    closeConfirmation: () => setConfirmation(null),
    confirmFullAccess,
  };
}

export type LauncherManagementPermissionControlState = ReturnType<typeof useLauncherManagementPermission>;
