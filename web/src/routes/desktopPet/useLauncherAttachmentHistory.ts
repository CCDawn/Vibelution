import { useEffect, useRef, useState } from "react";
import type { ConversationMessage } from "../../api/types";
import { readLauncherAttachment } from "../../api/launcherAssistant";

const MAX_CACHE_CHARS = 96 * 1024 * 1024;
const MAX_CACHE_ENTRIES = 32;
type Cache = { sessionId: string; values: Map<string, string> };

/** Read only mounted rows, one at a time; cache is local, bounded and disposable. */
export function useLauncherAttachmentHistory(messages: ConversationMessage[], sessionId: string, enabled: boolean, visibleIds: readonly string[]) {
  const visible = new Set(visibleIds);
  const generatedImageId = (message: ConversationMessage) => message.role === "assistant"
    && message.metadata?.kind === "image2_generation" && message.metadata?.status === "succeeded"
    && typeof message.metadata.artifactId === "string" ? message.metadata.artifactId : "";
  const desired = Array.from(new Set(messages.flatMap(message => {
    if (!visible.has(message.id)) return [];
    if (message.role === "user") return (message.attachments || []).map(attachment => attachment.artifactId).filter(Boolean);
    const id = generatedImageId(message);
    return id ? [id] : [];
  })));
  const missingGenerated = enabled && messages.some(message => visible.has(message.id) && message.role === "assistant"
    && message.metadata?.kind === "image2_generation" && message.metadata?.status === "succeeded" && !generatedImageId(message));
  const desiredKey = JSON.stringify(desired);
  const cache = useRef<Cache>({ sessionId, values: new Map() });
  const attempted = useRef(new Set<string>());
  const failed = useRef(new Set<string>());
  const current = useRef({ sessionId, enabled, desired: new Set(desired) });
  current.current = { sessionId, enabled, desired: new Set(desired) };
  const flight = useRef<{ sessionId: string; id: string } | null>(null);
  const mounted = useRef(false);
  const [version, setVersion] = useState(0);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);

  useEffect(() => {
    if (cache.current.sessionId !== sessionId || !enabled) {
      cache.current = { sessionId, values: new Map() };
      attempted.current.clear(); failed.current.clear();
      return;
    }
    const wanted = new Set(JSON.parse(desiredKey) as string[]);
    for (const id of attempted.current) if (!wanted.has(id)) attempted.current.delete(id);
    for (const id of failed.current) if (!wanted.has(id)) failed.current.delete(id);
    // Recently visible entries win eviction, including on returning to a row.
    for (const id of wanted) {
      const value = cache.current.values.get(id);
      if (value) { cache.current.values.delete(id); cache.current.values.set(id, value); }
    }
    if (flight.current) return;
    const id = [...wanted].find(item => !cache.current.values.has(item) && !attempted.current.has(item));
    if (!id) return;
    attempted.current.add(id);
    const request = { sessionId, id };
    flight.current = request;
    void readLauncherAttachment(id).then(url => {
      if (!mounted.current || current.current.sessionId !== sessionId || !current.current.enabled || !current.current.desired.has(id)) return;
      const values = cache.current.values;
      values.set(id, url);
      let size = [...values.values()].reduce((total, value) => total + value.length, 0);
      while (values.size > MAX_CACHE_ENTRIES || size > MAX_CACHE_CHARS) {
        const oldest = values.keys().next().value as string | undefined;
        if (!oldest) break;
        size -= values.get(oldest)?.length || 0;
        values.delete(oldest);
      }
    }).catch(() => {
      if (mounted.current && current.current.sessionId === sessionId && current.current.enabled && current.current.desired.has(id)) failed.current.add(id);
    }).finally(() => {
      if (flight.current === request) flight.current = null;
      if (mounted.current) setVersion(value => value + 1);
    });
  }, [desiredKey, enabled, sessionId, version]);

  const values = enabled && cache.current.sessionId === sessionId ? cache.current.values : new Map<string, string>();
  const safeMessages = messages.map(message => {
    // Never trust URLs or paths in history; only this session's artifact ID may resolve.
    if (message.role === "assistant" && message.metadata?.kind === "image2_generation") {
      const url = values.get(generatedImageId(message)) || "";
      return { ...message, metadata: { ...message.metadata, artifactPath: "", imageUrl: url, url, downloadUrl: url } };
    }
    if (message.role !== "user" || !message.attachments) return message;
    return { ...message, attachments: message.attachments.map(attachment => {
      const url = values.get(attachment.artifactId) || "";
      return { ...attachment, url, imageUrl: attachment.kind === "user_image" ? url : "", downloadUrl: url };
    }) };
  });
  return { messages: safeMessages, missingGenerated, failed: enabled && desired.some(id => failed.current.has(id)), retry: () => {
    for (const id of failed.current) attempted.current.delete(id);
    failed.current.clear(); setVersion(value => value + 1);
  } };
}
