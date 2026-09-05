import { fetchWithControl } from "../../api/chat";

export type GuardedSseFrame = {
  event: string;
  data: string;
};

export function parseGuardedSseFrame(rawFrame: string): GuardedSseFrame | null {
  let event = "message";
  const data: string[] = [];
  for (const line of rawFrame.split(/\r?\n/)) {
    if (!line || line.startsWith(":")) continue;
    const separator = line.indexOf(":");
    const field = separator >= 0 ? line.slice(0, separator) : line;
    let value = separator >= 0 ? line.slice(separator + 1) : "";
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") event = value || "message";
    else if (field === "data") data.push(value);
  }
  return data.length ? { event, data: data.join("\n") } : null;
}

function splitCompleteSseFrames(buffer: string): { frames: string[]; rest: string } {
  const frames: string[] = [];
  let rest = buffer;
  while (true) {
    const boundary = /\r?\n\r?\n/.exec(rest);
    if (!boundary || boundary.index == null) break;
    frames.push(rest.slice(0, boundary.index));
    rest = rest.slice(boundary.index + boundary[0].length);
  }
  return { frames, rest };
}

export async function consumeGuardedEventStream(options: {
  url: string;
  signal: AbortSignal;
  onOpen?: () => void;
  onActivity?: () => void;
  onFrame: (frame: GuardedSseFrame) => void;
}): Promise<void> {
  const response = await fetchWithControl(options.url, {
    headers: { Accept: "text/event-stream" },
    signal: options.signal,
  });
  if (!response.body) throw new Error("事件流没有返回响应体");
  options.onOpen?.();

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const consumeFrames = (rawBuffer: string) => {
    const parsed = splitCompleteSseFrames(rawBuffer);
    for (const rawFrame of parsed.frames) {
      options.onActivity?.();
      const frame = parseGuardedSseFrame(rawFrame);
      if (frame) options.onFrame(frame);
    }
    return parsed.rest;
  };
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      buffer = consumeFrames(buffer);
    }
    buffer += decoder.decode();
    consumeFrames(buffer);
  } finally {
    reader.releaseLock();
  }
}
