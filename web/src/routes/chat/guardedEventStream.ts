import { fetchWithControl } from "../../api/chat";

export type GuardedSseFrame = {
  event: string;
  data: string;
  /** Journal sequence from the frame's `id:` line, when the server sent one. */
  id?: string;
};

export function parseGuardedSseFrame(rawFrame: string): GuardedSseFrame | null {
  let event = "message";
  let id = "";
  const data: string[] = [];
  for (const line of rawFrame.split(/\r?\n/)) {
    if (!line || line.startsWith(":")) continue;
    const separator = line.indexOf(":");
    const field = separator >= 0 ? line.slice(0, separator) : line;
    let value = separator >= 0 ? line.slice(separator + 1) : "";
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") event = value || "message";
    else if (field === "id") id = value.trim();
    else if (field === "data") data.push(value);
  }
  if (!data.length) return null;
  return id ? { event, data: data.join("\n"), id } : { event, data: data.join("\n") };
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
  /** Extra request headers (e.g. Last-Event-ID on a resume reconnect). */
  headers?: Record<string, string>;
  onOpen?: () => void;
  onActivity?: () => void;
  onFrame: (frame: GuardedSseFrame) => void;
}): Promise<void> {
  const requestController = new AbortController();
  let response: Response | null = null;
  let reader: ReadableStreamDefaultReader<Uint8Array> | null = null;
  let bodyCancellation: Promise<void> | null = null;
  const cancelBody = (): void => {
    if (bodyCancellation !== null) return;
    let cancellation: Promise<unknown> | null = null;
    try {
      cancellation = reader ? reader.cancel() : response?.body?.cancel() ?? null;
    } catch {
      return;
    }
    if (cancellation !== null) {
      bodyCancellation = cancellation.then(() => undefined, () => undefined);
    }
  };
  const abortRequest = (): void => {
    if (!requestController.signal.aborted) {
      requestController.abort(options.signal.reason);
    }
    cancelBody();
  };
  options.signal.addEventListener("abort", abortRequest, { once: true });
  if (options.signal.aborted) abortRequest();

  try {
    response = await fetchWithControl(options.url, {
      headers: { Accept: "text/event-stream", ...(options.headers ?? {}) },
      signal: requestController.signal,
    });
    if (options.signal.aborted) {
      throw options.signal.reason ?? new DOMException("The operation was aborted.", "AbortError");
    }
    if (!response.body) throw new Error("事件流没有返回响应体");

    reader = response.body.getReader();
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
    options.onOpen?.();

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      buffer = consumeFrames(buffer);
    }
    buffer += decoder.decode();
    consumeFrames(buffer);
  } finally {
    options.signal.removeEventListener("abort", abortRequest);
    abortRequest();
    if (reader) {
      try {
        reader.releaseLock();
      } catch {
        // Cleanup must not replace a fetch, read, or callback failure.
      }
    }
  }
}
