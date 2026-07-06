import { describe, expect, it } from "vitest";

import styles from "./CliAgentRunTerminalPanel.styles";
import terminalPanelSource from "./CliAgentRunTerminalPanel.tsx?raw";

describe("CliAgentRunTerminalPanel layout contract", () => {
  it("keeps long command previews inside the terminal header", () => {
    expect(terminalPanelSource).toContain("className={styles.cliAgentTerminalCommandText}");
    expect(styles.cliAgentTerminalCommand).toContain("grid-cols-[auto_minmax(0,1fr)_auto]");
    expect(styles.cliAgentTerminalCommand).toContain("overflow-hidden");
    expect(styles.cliAgentTerminalCommandText).toContain("min-w-0");
    expect(styles.cliAgentTerminalCommandText).toContain("max-w-full");
    expect(styles.cliAgentTerminalCommandText).toContain("break-words");
    expect(styles.cliAgentTerminalCommandText).toContain("[overflow-wrap:anywhere]");
    expect(styles.cliAgentTerminalCommandText).not.toContain("whitespace-nowrap");
  });
});
