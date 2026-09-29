/**
 * 对话内查找条（Find in transcript）—— 只负责展示与输入。
 *
 * 状态全部由 ConversationView 内部持有（本组件不做任何会话状态管理）；文案
 * 键在 web/src/i18n/domains/dictionaryChat.ts（find* 前缀），由调用方经
 * useAppI18n 解析后以 labels 传入。控件一律走 VUI 原语（VInput/VIconButton）。
 *
 * 键盘：Enter 下一个命中、Shift+Enter 上一个、Escape 关闭（关闭在捕获层
 * preventDefault + stopPropagation，绝不触发轮次停止语义）。
 */
import type { KeyboardEvent, RefObject } from "react";

import { ChevronDown, ChevronUp, X } from "lucide-react";

import { VIconButton, VInput } from "../vui";
import styles from "./ConversationFindBar.styles";

export type ConversationFindBarLabels = {
  title: string;
  placeholder: string;
  matchCountAria: (current: number, total: number) => string;
  previous: string;
  next: string;
  close: string;
};

export type ConversationFindBarProps = {
  labels: ConversationFindBarLabels;
  inputRef?: RefObject<HTMLInputElement | null>;
  value: string;
  onValueChange: (value: string) => void;
  /** 总命中数（0 显示 0/0，不禁用输入）。 */
  matchCount: number;
  /** 当前命中序号（0 起；无命中为 -1）。 */
  activeIndex: number;
  onPrevious: () => void;
  onNext: () => void;
  onClose: () => void;
};

function handleFindBarInputKeyDown(
  event: KeyboardEvent<HTMLInputElement>,
  actions: { onPrevious: () => void; onNext: () => void; onClose: () => void },
) {
  if (event.nativeEvent.isComposing) {
    return;
  }
  if (event.key === "Escape") {
    event.preventDefault();
    event.stopPropagation();
    actions.onClose();
    return;
  }
  if (event.key === "Enter") {
    event.preventDefault();
    if (event.shiftKey) {
      actions.onPrevious();
    } else {
      actions.onNext();
    }
  }
}

export function ConversationFindBar({
  labels,
  inputRef,
  value,
  onValueChange,
  matchCount,
  activeIndex,
  onPrevious,
  onNext,
  onClose,
}: ConversationFindBarProps) {
  const hasMatches = matchCount > 0;
  const currentDisplay = hasMatches ? activeIndex + 1 : 0;
  const countText = `${currentDisplay}/${matchCount}`;
  return (
    <div className={styles.host} data-conversation-find-bar="true">
      <div
        className={styles.bar}
        role="search"
        aria-label={labels.title}
      >
        <VInput
          ref={inputRef}
          className={styles.input}
          type="text"
          value={value}
          placeholder={labels.placeholder}
          aria-label={labels.title}
          data-conversation-find-input="true"
          autoComplete="off"
          spellCheck={false}
          onChange={(event) => onValueChange(event.target.value)}
          onKeyDown={(event) => handleFindBarInputKeyDown(event, { onPrevious, onNext, onClose })}
        />
        <span
          className={styles.count}
          aria-live="polite"
          aria-label={labels.matchCountAria(currentDisplay, matchCount)}
          data-conversation-find-count="true"
        >
          {countText}
        </span>
        <VIconButton
          label={labels.previous}
          title={labels.previous}
          variant="ghost"
          type="button"
          isDisabled={!hasMatches}
          data-conversation-find-previous="true"
          onClick={onPrevious}
          icon={<ChevronUp size={14} aria-hidden="true" />}
        />
        <VIconButton
          label={labels.next}
          title={labels.next}
          variant="ghost"
          type="button"
          isDisabled={!hasMatches}
          data-conversation-find-next="true"
          onClick={onNext}
          icon={<ChevronDown size={14} aria-hidden="true" />}
        />
        <span className={styles.divider} aria-hidden="true" />
        <VIconButton
          label={labels.close}
          title={labels.close}
          variant="ghost"
          type="button"
          data-conversation-find-close="true"
          onClick={onClose}
          icon={<X size={14} aria-hidden="true" />}
        />
      </div>
    </div>
  );
}
