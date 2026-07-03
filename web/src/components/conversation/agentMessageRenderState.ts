import type { AgentMessage, AgentTextPart } from "../../agent-thread/types";
import {
  agentMessageContentSections,
  agentMessageContextSections,
  agentMessageProcessSections,
  buildAgentMessageSectionState,
  type AgentMessageContentSection,
  type AgentMessageContextSection,
  type AgentMessageProcessSection,
  type AgentMessageSectionState,
} from "./messageSections";

export type AgentMessageRenderState = {
  sectionState: AgentMessageSectionState;
  contentSections: AgentMessageContentSection[];
  contextSections: AgentMessageContextSection[];
  processSections: AgentMessageProcessSection[];
  sectionKinds: string;
  userContentSectionIds: string | undefined;
  answerContentSectionIds: string | undefined;
  processSectionIds: string | undefined;
};

export function buildAgentMessageRenderState(message: AgentMessage): AgentMessageRenderState {
  const sectionState = buildAgentMessageSectionState(message);
  const contentSections = agentMessageContentSections(message);
  const contextSections = agentMessageContextSections(message);
  const processSections = agentMessageProcessSections(message);
  return {
    sectionState,
    contentSections,
    contextSections,
    processSections,
    sectionKinds: sectionState.sectionKinds.join(" "),
    userContentSectionIds: contentSectionIdsForChannel(contentSections, "user"),
    answerContentSectionIds: contentSectionIdsForChannel(contentSections, "answer"),
    processSectionIds: processSectionIdsForSections(processSections),
  };
}

function contentSectionIdsForChannel(
  sections: AgentMessageContentSection[],
  channel: AgentTextPart["channel"],
) {
  return sections
    .filter((section) => section.parts.some((part) => part.channel === channel))
    .map((section) => section.id)
    .join(" ") || undefined;
}

function processSectionIdsForSections(sections: AgentMessageProcessSection[]) {
  return sections.map((section) => section.id).join(" ") || undefined;
}
