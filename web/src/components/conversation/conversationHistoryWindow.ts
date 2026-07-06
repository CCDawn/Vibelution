export type ConversationHistoryLoadInput = {
  clientHeight: number;
  hiddenMessageCount: number;
  previousScrollTop: number;
  scrollHeight: number;
  scrollTop: number;
  thresholdPx: number;
};

export function shouldLoadEarlierConversationMessages({
  clientHeight,
  hiddenMessageCount,
  previousScrollTop,
  scrollHeight,
  scrollTop,
  thresholdPx,
}: ConversationHistoryLoadInput) {
  if (hiddenMessageCount <= 0) {
    return false;
  }
  if (scrollHeight <= clientHeight) {
    return true;
  }
  if (scrollTop <= 0) {
    return true;
  }
  return scrollTop <= thresholdPx && scrollTop < previousScrollTop;
}
