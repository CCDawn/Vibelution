// The block fallback intentionally reuses the message-level degradation
// chrome verbatim (same fallback box / pre / note tokens) so a degraded block
// reads like the established degraded state — one visual language, no
// duplicated class strings. Re-exported through this sibling module so the
// boundary component owns its styles surface like every other conversation
// subcomponent.
import shared from "./LazyConversationMarkdownRenderer.errorBoundary.styles";

export default shared;
