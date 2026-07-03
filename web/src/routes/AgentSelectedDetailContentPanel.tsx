import { type ReactNode } from "react";

type AgentSelectedDetailPaneId = "overview" | "config" | "activity";

type AgentSelectedDetailContentPanelProps = {
  activePane: AgentSelectedDetailPaneId;
  header: ReactNode;
  brief: ReactNode;
  overview: ReactNode;
  configPrimary: ReactNode;
  configPolicies: ReactNode;
  configReferences: ReactNode;
  activity: ReactNode;
};

export function AgentSelectedDetailContentPanel({
  activePane,
  header,
  brief,
  overview,
  configPrimary,
  configPolicies,
  configReferences,
  activity,
}: AgentSelectedDetailContentPanelProps) {
  return (
    <>
      {header}
      {brief}
      {activePane === "overview" ? overview : null}
      {activePane === "config" ? (
        <>
          {configPrimary}
          {configPolicies}
          {configReferences}
        </>
      ) : null}
      {activePane === "activity" ? activity : null}
    </>
  );
}
