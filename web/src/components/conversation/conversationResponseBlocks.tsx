import type { ReactNode } from "react";

import type { SkillLibraryItem } from "../../api/types";
import type { TranslationKey } from "../../i18n/dictionaryTypes";
import { assistantTurnIsStreaming } from "../../routes/chatTurnProtocol";
import type { ConversationMessage } from "../../api/types";
import { LazyConversationMarkdownRenderer } from "./LazyConversationMarkdownRenderer";
import { ConversationStreamingResponseContent } from "./ConversationStreamingResponseContent";
import { ConversationFileReferenceChips } from "./ConversationFileReferenceChips";
import {
  ConversationSlashCommandChip,
  parseUserSlashCommandEcho,
  resolveUserSlashCommandTone,
} from "./ConversationSlashCommandChip";
import {
  isResponseSegmentCodeLike,
  responseSegmentLabel as resolveResponseSegmentLabel,
} from "./conversationResponseSegmentPresentation";
import { formattedCodeBlockContent } from "./conversationFormattedCodeBlock";
import type { ResponseSegment } from "./messageResponseSegments";
import styles from "./ConversationView.styles";

export type ConversationResponseBlocksDeps = {
  lang: "zh" | "en";
  t: (key: TranslationKey) => string;
  sessionWorkspacePath?: string;
  onOpenRailFile?: (path: string) => void;
  /** Component-memoized image renderer: identity stability keeps the content-memoized markdown subtree from re-parsing. */
  renderMarkdownImage: (alt: string, url: string, duplicateImageUrls?: Set<string>) => ReactNode;
  slashCommandSuggestions: SkillLibraryItem[];
};

/**
 * Response text/segment renderers (markdown body, slash-command echo, file
 * reference chips). Extracted from ConversationView with identical output.
 */
export function createConversationResponseBlocks({
  lang,
  t,
  sessionWorkspacePath,
  onOpenRailFile,
  renderMarkdownImage,
  slashCommandSuggestions,
}: ConversationResponseBlocksDeps) {
  function responseSegmentLabel(segment: ResponseSegment) {
    return resolveResponseSegmentLabel(segment, (key) => t(key));
  }

  function renderResponseText(content: string, duplicateImageUrls?: Set<string>) {
    return (
      <LazyConversationMarkdownRenderer
        content={content}
        duplicateImageUrls={duplicateImageUrls}
        renderImage={renderMarkdownImage}
        workspaceRoot={sessionWorkspacePath}
        language={lang}
        onOpenRailFile={onOpenRailFile}
      />
    );
  }

  function renderResponseSegment(segment: ResponseSegment, duplicateImageUrls?: Set<string>) {
    const label = responseSegmentLabel(segment);
    return (
      <section
        key={segment.id}
        className={`${styles.responseSegment} ${styles[`responseSegment_${segment.kind}`]}`}
      >
        <div className={styles.responseSegmentHeader}>
          <span className={styles.responseSegmentLabel}>{label}</span>
          {segment.language && segment.kind !== "code" ? (
            <span className={styles.responseSegmentMeta}>{segment.language}</span>
          ) : null}
        </div>
        {isResponseSegmentCodeLike(segment) ? (
          <pre className={styles.responseSegmentPre}>
            <code>{formattedCodeBlockContent(segment.content, segment.language)}</code>
          </pre>
        ) : (
          renderResponseText(segment.content, duplicateImageUrls)
        )}
      </section>
    );
  }

  /**
   * User message bodies echo a leading slash command as a chip (ZCode
   * ConversationUserInputContent parity). The text prefix is the parse basis:
   * optimistic rows and unknown commands carry no `slashSkillCommand`
   * metadata, and the chip must render for both — tone comes from the same
   * skill library the composer suggestion list ranks. Everything after the
   * command token keeps the ordinary markdown body; non-user rows and
   * slash-less text are untouched.
   */
  function renderUserContentWithSlashEcho(content: string, isUserAuthored: boolean) {
    if (!isUserAuthored) {
      return renderResponseText(content);
    }
    const echo = parseUserSlashCommandEcho(content);
    if (!echo) {
      return renderResponseText(content);
    }
    return (
      <>
        <ConversationSlashCommandChip
          command={echo.command}
          tone={resolveUserSlashCommandTone(echo.command, slashCommandSuggestions)}
        />
        {echo.rest.trim() ? renderResponseText(echo.rest) : null}
      </>
    );
  }

  function renderAssistantTranscriptResponseText(
    content: string,
    isStreaming: boolean,
    duplicateImageUrls?: Set<string>,
  ) {
    if (!content) {
      return null;
    }
    // One component type across streaming and settled: the Codex transcript
    // cell keeps its markdown subtree mounted on the streaming→settled flip
    // (settled text re-routes through the shared stable renderer instead of
    // swapping to a different renderer component).
    return (
      <ConversationStreamingResponseContent
        content={content}
        isStreaming={isStreaming}
        duplicateImageUrls={duplicateImageUrls}
        renderImage={renderMarkdownImage}
        workspaceRoot={sessionWorkspacePath}
        language={lang}
        onOpenRailFile={onOpenRailFile}
      />
    );
  }

  /**
   * ZCode AssistantPreviewCards parity: a settled assistant answer surfaces
   * the whitelisted local file references found in its final markdown as a
   * clickable chip row (same open/reveal/copy semantics as the inline
   * workspace-file links). Streaming turns stay chip-free; markdown-linked
   * workspace files are already clickable inline, so the extractor suppresses
   * them from the row instead of double-presenting.
   */
  function renderAssistantFileReferenceChips(message: ConversationMessage, text: string) {
    if (assistantTurnIsStreaming(message)) {
      return null;
    }
    return (
      <ConversationFileReferenceChips
        text={text}
        workspaceRoot={sessionWorkspacePath}
        language={lang}
        onOpenInRail={onOpenRailFile}
      />
    );
  }

  return {
    responseSegmentLabel,
    renderResponseSegment,
    renderResponseText,
    renderUserContentWithSlashEcho,
    renderAssistantTranscriptResponseText,
    renderAssistantFileReferenceChips,
  };
}
