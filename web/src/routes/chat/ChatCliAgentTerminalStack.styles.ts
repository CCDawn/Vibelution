import {
  vuiGlassPanelClass,
  vuiStateCoolInfoClass,
} from "../../design/vuiSurfaceRecipes";

const styles = {
  cliAgentRunPanel: `vui-routes-chatcodingroute cliAgentRunPanel min-w-0 ${vuiGlassPanelClass} p-2 ${vuiStateCoolInfoClass}`,
  cliAgentRunPanelHidden: `vui-routes-chatcodingroute cliAgentRunPanelHidden min-w-0 ${vuiGlassPanelClass} p-2 hidden ${vuiStateCoolInfoClass} hidden`,
  cliAgentTerminalCommand:
    `vui-routes-chatcodingroute cliAgentTerminalCommand min-w-0 ${vuiStateCoolInfoClass} !grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-2`,
  cliAgentTerminalFrame:
    `vui-routes-chatcodingroute cliAgentTerminalFrame min-w-0 ${vuiStateCoolInfoClass}`,
  cliAgentTerminalStatus:
    `vui-routes-chatcodingroute cliAgentTerminalStatus min-w-0 ${vuiStateCoolInfoClass}`,
} as const;

export default styles;
