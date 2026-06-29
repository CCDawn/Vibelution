export const STREAMING_RESPONSE_REVEAL_MIN_CHARS = 2;
export const STREAMING_RESPONSE_REVEAL_MAX_CHARS = 36;
export const STREAMING_RESPONSE_REVEAL_BACKLOG_RATIO = 0.18;
export const STREAMING_RESPONSE_CATCH_UP_BACKLOG_CHARS = 420;
export const STREAMING_RESPONSE_CATCH_UP_MAX_CHARS = 180;
export const STREAMING_RESPONSE_STABLE_TAIL_CHARS = 240;

export type StreamingRevealState = {
  stableText: string;
  revealTail: string;
};

export const EMPTY_STREAMING_REVEAL_STATE: StreamingRevealState = {
  stableText: "",
  revealTail: "",
};

export function streamingRevealText(state: StreamingRevealState) {
  return `${state.stableText}${state.revealTail}`;
}

export function appendStableText(_previous: StreamingRevealState, nextVisibleText: string): StreamingRevealState {
  const stableLength = Math.max(0, nextVisibleText.length - STREAMING_RESPONSE_STABLE_TAIL_CHARS);
  return {
    stableText: nextVisibleText.slice(0, stableLength),
    revealTail: nextVisibleText.slice(stableLength),
  };
}

export function nextStreamingRevealLength(currentLength: number, targetLength: number) {
  const backlog = Math.max(0, targetLength - currentLength);
  if (backlog === 0) {
    return currentLength;
  }
  const catchUpActive = backlog >= STREAMING_RESPONSE_CATCH_UP_BACKLOG_CHARS;
  const maxStep = catchUpActive ? STREAMING_RESPONSE_CATCH_UP_MAX_CHARS : STREAMING_RESPONSE_REVEAL_MAX_CHARS;
  const ratio = catchUpActive ? 0.42 : STREAMING_RESPONSE_REVEAL_BACKLOG_RATIO;
  const step = Math.min(
    maxStep,
    Math.max(STREAMING_RESPONSE_REVEAL_MIN_CHARS, Math.ceil(backlog * ratio)),
  );
  return Math.min(targetLength, currentLength + step);
}
