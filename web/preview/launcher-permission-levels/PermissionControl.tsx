/** The approved preview now reuses the formal shared control. */
import type { AgentPermissionPreset } from "../../src/api/types";
import { AgentPermissionPresetControl } from "../../src/components/vui/product/agent-management/AgentPermissionPresetControl";

export function PermissionControl(props: {
  value: AgentPermissionPreset;
  disabled: boolean;
  pending: boolean;
  onChange: (value: AgentPermissionPreset) => void;
}) {
  return <AgentPermissionPresetControl {...props} lang="zh" surface="composer" context="launcher" side="top" align="start" />;
}
