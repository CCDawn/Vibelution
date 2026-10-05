import { useEffect, useRef, useState, type MouseEvent } from "react";
import {
  Copy,
  ExternalLink,
  FileAudio,
  FileText,
  Film,
  FolderOpen,
  Image as ImageIcon,
} from "lucide-react";

import { VButton, VDropdownMenu, type VDropdownMenuItem } from "../vui";
import {
  copyWorkspaceFilePath,
  openWorkspaceFile,
  revealWorkspaceFile,
} from "./conversationMarkdownWorkspaceFileActions";
import {
  conversationFileReferenceName,
  extractConversationFileReferences,
  type ConversationFileReference,
} from "./conversationFileReferences";
import styles from "./ConversationFileReferenceChips.styles";

const FALLBACK_HINT_VISIBLE_MS = 2400;

function ReferenceIcon({ family }: { family: ConversationFileReference["family"] }) {
  if (family === "image") {
    return <ImageIcon size={14} aria-hidden="true" />;
  }
  if (family === "audio") {
    return <FileAudio size={14} aria-hidden="true" />;
  }
  if (family === "video") {
    return <Film size={14} aria-hidden="true" />;
  }
  return <FileText size={14} aria-hidden="true" />;
}

export type ConversationFileReferenceChipsProps = {
  /** Settled assistant markdown text to scan for file references. */
  text: string;
  /** Session workspace root; relative references resolve against it. */
  workspaceRoot?: string;
  language: "zh" | "en";
};

/**
 * Clickable file-reference chip row under a settled assistant message (ZCode
 * AssistantPreviewCards parity, tightened to path shapes): the extractor pulls
 * whitelisted local file references out of the final markdown and each chip
 * opens the file with the system default program. When the desktop bridge is
 * unavailable or the shell call fails the path is copied with a light hint.
 * Right-click offers 打开 / 在文件夹中显示 / 复制路径 — the same semantics as
 * inline markdown workspace-file links. No references → renders nothing.
 */
export function ConversationFileReferenceChips({
  text,
  workspaceRoot,
  language,
}: ConversationFileReferenceChipsProps) {
  const zh = language === "zh";
  const references = extractConversationFileReferences(text, workspaceRoot);
  const [menu, setMenu] = useState<{ path: string; x: number; y: number } | null>(null);
  const [hint, setHint] = useState<string | null>(null);
  const hintTimerRef = useRef<number | null>(null);
  useEffect(
    () => () => {
      if (hintTimerRef.current !== null) {
        window.clearTimeout(hintTimerRef.current);
      }
    },
    [],
  );
  if (references.length === 0) {
    return null;
  }

  const showCopiedHint = () => {
    setHint(zh ? "路径已复制" : "Path copied");
    if (hintTimerRef.current !== null) {
      window.clearTimeout(hintTimerRef.current);
    }
    hintTimerRef.current = window.setTimeout(() => {
      hintTimerRef.current = null;
      setHint(null);
    }, FALLBACK_HINT_VISIBLE_MS);
  };

  const runWithClipboardFallback = (path: string, action: () => Promise<"done" | "unavailable">) => {
    void action().then((result) => {
      if (result === "done") {
        return;
      }
      void copyWorkspaceFilePath(path).then((copied) => {
        if (copied) {
          showCopiedHint();
        }
      });
    });
  };

  const handleOpen = (path: string) => runWithClipboardFallback(path, () => openWorkspaceFile(path));
  const handleReveal = (path: string) => runWithClipboardFallback(path, () => revealWorkspaceFile(path));
  const handleCopyPath = (path: string) => {
    void copyWorkspaceFilePath(path).then((copied) => {
      if (copied) {
        showCopiedHint();
      }
    });
  };

  const menuItems: VDropdownMenuItem[] = menu
    ? [
      {
        id: "open",
        icon: <ExternalLink size={14} aria-hidden="true" />,
        label: zh ? "打开（系统默认）" : "Open (system default)",
        onSelect: () => handleOpen(menu.path),
      },
      {
        id: "reveal",
        icon: <FolderOpen size={14} aria-hidden="true" />,
        label: zh ? "在文件夹中显示" : "Show in folder",
        onSelect: () => handleReveal(menu.path),
      },
      {
        id: "copy",
        icon: <Copy size={14} aria-hidden="true" />,
        label: zh ? "复制路径" : "Copy path",
        onSelect: () => handleCopyPath(menu.path),
      },
    ]
    : [];

  return (
    <>
      <div
        className={styles.row}
        role="list"
        aria-label={zh ? "引用的本地文件" : "Referenced local files"}
        data-conversation-file-references="true"
      >
        {references.map((reference) => {
          const name = conversationFileReferenceName(reference.absolutePath);
          const open = () => handleOpen(reference.absolutePath);
          return (
            <VButton
              key={reference.absolutePath}
              role="listitem"
              variant="ghost"
              density="compact"
              contentLayout="plain"
              className={styles.chip}
              data-conversation-file-reference-chip="true"
              data-file-extension={reference.extension}
              title={reference.absolutePath}
              onPress={open}
              onContextMenu={(event: MouseEvent<HTMLButtonElement>) => {
                event.preventDefault();
                setMenu({ path: reference.absolutePath, x: event.clientX, y: event.clientY });
              }}
            >
              <ReferenceIcon family={reference.family} />
              <span className={styles.name}>{name}</span>
              <span className={styles.badge}>{reference.extension}</span>
            </VButton>
          );
        })}
        {hint ? (
          <span className={styles.hint} role="status">
            {hint}
          </span>
        ) : null}
      </div>
      {menu ? (
        <VDropdownMenu
          items={menuItems}
          position={{ x: menu.x, y: menu.y }}
          aria-label={zh ? "打开方式" : "Open with"}
          data-vui="conversation-file-reference-menu"
          onOpenChange={(open) => {
            if (!open) {
              setMenu(null);
            }
          }}
        />
      ) : null}
    </>
  );
}
