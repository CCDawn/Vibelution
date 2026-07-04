export function addComparableConversationImageUrl(target: Set<string>, url: string) {
  const normalized = comparableConversationImageUrl(url);
  if (normalized) {
    target.add(normalized);
  }
}

export function comparableConversationImageUrl(url: string) {
  return conversationImagePreviewUrl(url).trim();
}

export function isLikelyConversationImageUrl(url: string) {
  const normalized = String(url ?? "").toLowerCase();
  return /\.(png|jpe?g|webp|gif)(?:[?#].*)?$/.test(normalized) || normalized.includes("/artifacts/image");
}

export function conversationImagePreviewUrl(url: string) {
  const trimmed = String(url ?? "").trim();
  const [withoutHash, hash = ""] = trimmed.split("#", 2);
  const [path, query = ""] = withoutHash.split("?", 2);
  if (!query) {
    return trimmed;
  }
  const kept = query
    .split("&")
    .filter((param) => !/^download=(1|true)$/i.test(param));
  return `${path}${kept.length ? `?${kept.join("&")}` : ""}${hash ? `#${hash}` : ""}`;
}

export function conversationImageDownloadName(url: string) {
  const path = String(url ?? "").split(/[?#]/, 1)[0] ?? "";
  return path.split("/").filter(Boolean).pop() ?? "";
}
