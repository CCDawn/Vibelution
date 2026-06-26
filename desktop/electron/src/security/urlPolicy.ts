export function assertLocalHttpUrl(rawUrl: string, expectedOrigin: string): string {
  const url = new URL(rawUrl);
  if (url.protocol !== "http:" || !["127.0.0.1", "localhost"].includes(url.hostname)) {
    throw new Error(`blocked non-local URL: ${rawUrl}`);
  }
  if (url.origin !== expectedOrigin) {
    throw new Error(`blocked unexpected origin: ${url.origin}`);
  }
  return url.toString();
}
