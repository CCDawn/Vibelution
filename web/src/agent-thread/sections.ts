import type {
  AgentMessage,
  AgentMessagePart,
  AgentMessageSection,
  AgentMessageSectionKind,
} from "./types";

export function agentMessageToSections(message: AgentMessage): AgentMessageSection[] {
  return message.parts.reduce<AgentMessageSection[]>((sections, part) => {
    const kind = sectionKindForPart(part);
    const lastSection = sections[sections.length - 1];
    if (lastSection?.kind === kind) {
      lastSection.parts.push(part);
      return sections;
    }

    sections.push({
      id: `${message.id}-section-${kind}-${sections.length}`,
      kind,
      parts: [part],
    });
    return sections;
  }, []);
}

function sectionKindForPart(part: AgentMessagePart): AgentMessageSectionKind {
  if (part.type === "attachment" || part.type === "reference") {
    return "context";
  }
  if (part.type === "text") {
    return "content";
  }
  return "process";
}
