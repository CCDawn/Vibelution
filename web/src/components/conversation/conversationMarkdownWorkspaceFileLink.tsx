import { useEffect, useRef, useState, type KeyboardEvent, type MouseEvent, type ReactNode } from "react";
import { Copy, ExternalLink, FolderOpen } from "lucide-react";

import { VDropdownMenu, type VDropdownMenuItem } from "../vui";
import {
  copyWorkspaceFilePath,
  openWorkspaceFile,
  revealWorkspaceFile,
} from "./conversationMarkdownWorkspaceFileActions";
import styles from "./conversationMarkdownWorkspaceFileLink.styles";

export type ConversationMarkdownWorkspaceFileLinkProps = {
  /** Normalized absolute workspace path produced by the link-target classifier. */
  path: string;
  /** Host-provided inline link style (same map as ordinary markdown anchors). */
  className: string;
  language: "zh" | "en";
  children: ReactNode;
};

const FALLBACK_HINT_VISIBLE_MS = 2400;

/**
 * Clickable workspace-file link inside settled conversation markdown: primary
 * click opens the file with the system default program via the desktop bridge;
 * when the bridge is unavailable or the shell call fails the path is copied to
 * the clipboard with a light inline hint. Right-click (or the anchor's context
 * surface) offers 打开 / 在文件夹中显示 / 复制路径 — copy remains the graceful
 * web fallback for every action.
 */
export function ConversationMarkdownWorkspaceFileLink({
  path,
  className,
  language,
  children,
}: ConversationMarkdownWorkspaceFileLinkProps) {
  const zh = language === "zh";
  const [menuPosition, setMenuPosition] = useState<{ x: number; y: number } | null>(null);
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

  const runWithClipboardFallback = (action: () => Promise<"done" | "unavailable">) => {
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

  const handleOpen = () => runWithClipboardFallback(() => openWorkspaceFile(path));
  const handleReveal = () => runWithClipboardFallback(() => revealWorkspaceFile(path));
  const handleCopyPath = () => {
    void copyWorkspaceFilePath(path).then((copied) => {
      if (copied) {
        showCopiedHint();
      }
    });
  };

  const handleContextMenu = (event: MouseEvent<HTMLAnchorElement>) => {
    event.preventDefault();
    setMenuPosition({ x: event.clientX, y: event.clientY });
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLAnchorElement>) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      handleOpen();
    }
  };

  const menuItems: VDropdownMenuItem[] = [
    {
      id: "open",
      icon: <ExternalLink size={14} aria-hidden="true" />,
      label: zh ? "打开（系统默认）" : "Open (system default)",
      onSelect: handleOpen,
    },
    {
      id: "reveal",
      icon: <FolderOpen size={14} aria-hidden="true" />,
      label: zh ? "在文件夹中显示" : "Show in folder",
      onSelect: handleReveal,
    },
    {
      id: "copy",
      icon: <Copy size={14} aria-hidden="true" />,
      label: zh ? "复制路径" : "Copy path",
      onSelect: handleCopyPath,
    },
  ];

  return (
    <>
      <a
        className={`${className} ${styles.link}`.trim()}
        data-markdown-workspace-file-link="true"
        title={path}
        role="link"
        tabIndex={0}
        onClick={(event) => {
          event.preventDefault();
          handleOpen();
        }}
        onContextMenu={handleContextMenu}
        onKeyDown={handleKeyDown}
      >
        {children}
      </a>
      {hint ? (
        <span className={styles.hint} role="status">
          {hint}
        </span>
      ) : null}
      {menuPosition ? (
        <VDropdownMenu
          items={menuItems}
          position={menuPosition}
          aria-label={zh ? "打开方式" : "Open with"}
          data-vui="markdown-workspace-file-menu"
          onOpenChange={(open) => {
            if (!open) {
              setMenuPosition(null);
            }
          }}
        />
      ) : null}
    </>
  );
}
