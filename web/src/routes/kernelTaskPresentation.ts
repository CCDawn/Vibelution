/** Use the actual goal as the title; strip only the producer's known prefix. */
export function kernelTaskTitle(goal: string, fallback: string, lang: "zh" | "en") {
  const text = goal.trim();
  const chatRound = text.startsWith("Chat room round:");
  const content = chatRound ? text.slice("Chat room round:".length).trim() : text;
  const firstLine = content.split(/\r?\n/).find((line) => line.trim())?.replace(/^#{1,6}\s+/, "").trim();
  return firstLine || (chatRound ? (lang === "zh" ? "群聊讨论" : "Group discussion") : fallback);
}
