import type { ConversationMarkdownClassNames } from "./ConversationMarkdownRenderer";
import conversationViewStyles from "./ConversationView.styles";

export const conversationMarkdownRendererStyles: ConversationMarkdownClassNames = {
  inlineCode: conversationViewStyles.inlineCode,
  inlineLink: conversationViewStyles.inlineLink,
  inlineStrong: conversationViewStyles.inlineStrong,
  markdownBlockquote: conversationViewStyles.markdownBlockquote,
  markdownBody: conversationViewStyles.markdownBody,
  markdownBodyWithTable: conversationViewStyles.markdownBodyWithTable,
  markdownDivider: conversationViewStyles.markdownDivider,
  markdownHeading: conversationViewStyles.markdownHeading,
  markdownHeading1: conversationViewStyles.markdownHeading1,
  markdownHeading2: conversationViewStyles.markdownHeading2,
  markdownHeading3: conversationViewStyles.markdownHeading3,
  markdownHeading4: conversationViewStyles.markdownHeading4,
  markdownTable: conversationViewStyles.markdownTable,
  markdownTableWrap: conversationViewStyles.markdownTableWrap,
  messageBody: conversationViewStyles.messageBody,
  responseSegmentList: conversationViewStyles.responseSegmentList,
  responseSegmentPre: conversationViewStyles.responseSegmentPre,
};
