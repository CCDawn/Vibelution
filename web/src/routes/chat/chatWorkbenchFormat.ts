/**
 * Pure presentation formatters for Chat workbench (kept out of the route orchestrator).
 */

export function formatChatClockTime(value: string, formatter: Intl.DateTimeFormat): string {
  if (!value) {
    return "";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return formatter.format(parsed);
}

export function formatChatConversationIndexTime(value: string, formatter: Intl.DateTimeFormat): string {
  return formatChatClockTime(value, formatter).replace(/:\d{2}$/, "");
}
