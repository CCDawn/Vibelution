import { Suspense, type ComponentType, type LazyExoticComponent } from "react";

import { VStateSurface } from "../../components/vui";
import styles from "./ChatCliAgentTerminalStack.styles";
import type { CliAgentRunView, CliAgentTerminalSession } from "./cliAgentRunModel";

type CliAgentRunTerminalPanelProps = {
  run: CliAgentRunView;
  sourceSessionId: string;
  active: boolean;
  lang: "zh" | "en";
  onTerminalSessionChange: (runId: string, session: CliAgentTerminalSession) => void;
};

export type ChatCliAgentTerminalStackProps = {
  runs: CliAgentRunView[];
  activeCliAgentRunId: string | null | undefined;
  activeSessionId: string | null | undefined;
  groupPanelActive: boolean;
  lang: "zh" | "en";
  TerminalPanel: LazyExoticComponent<ComponentType<CliAgentRunTerminalPanelProps>> | ComponentType<CliAgentRunTerminalPanelProps>;
  onTerminalSessionChange: (runId: string, session: CliAgentTerminalSession) => void;
};

/**
 * Mounted CLI agent terminal panels for the chat center surface.
 */
export function ChatCliAgentTerminalStack({
  runs,
  activeCliAgentRunId,
  activeSessionId,
  groupPanelActive,
  lang,
  TerminalPanel,
  onTerminalSessionChange,
}: ChatCliAgentTerminalStackProps) {
  return (
    <>
      {runs.map((run) => {
        const active = !groupPanelActive && activeCliAgentRunId === run.id;
        return (
          <Suspense
            key={run.id}
            fallback={(
              <section
                className={
                  active
                    ? styles.cliAgentRunPanel
                    : `${styles.cliAgentRunPanel} ${styles.cliAgentRunPanelHidden}`
                }
                aria-hidden={!active}
                aria-label={`${run.title} ${lang === "zh" ? "终端加载中" : "terminal loading"}`}
                data-active={active ? "true" : "false"}
                data-cli-agent-run-id={run.id}
              >
                <div className={styles.cliAgentTerminalFrame}>
                  <VStateSurface
                    tone="loading"
                    title={lang === "zh" ? "加载终端" : "Loading terminal"}
                    skeletonLines={2}
                  >
                    <code className={styles.cliAgentTerminalCommand}>{run.commandLine}</code>
                  </VStateSurface>
                </div>
              </section>
            )}
          >
            <TerminalPanel
              run={run}
              sourceSessionId={activeSessionId || ""}
              active={active}
              lang={lang}
              onTerminalSessionChange={onTerminalSessionChange}
            />
          </Suspense>
        );
      })}
    </>
  );
}
