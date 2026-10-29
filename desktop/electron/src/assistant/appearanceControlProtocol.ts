/** Closed appearance data only; no file paths, script, URLs or image bytes. */
export type AppearanceMainControlRequest = { deliveryId: string } & (
  | { action: "launcher_theme_get"; operation: "read" }
  | { action: "launcher_theme_set"; operation: "set"; theme: "dark" | "light" }
  | { action: "operator_image_upload"; operation: "import"; kind: "avatar" | "background"; timeoutMs: number }
);
export function isAppearanceAction(value: unknown): boolean {
  return typeof value === "string" && ["launcher_theme_get", "launcher_theme_set", "operator_image_upload"].includes(value);
}
function closed(value: unknown, required: string[], optional: string[] = []): value is Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value) || ![Object.prototype,null].includes(Object.getPrototypeOf(value))) return false;
  const descriptors = Object.getOwnPropertyDescriptors(value);
  return Reflect.ownKeys(value).length === Object.keys(descriptors).length && required.every(key => Object.hasOwn(descriptors,key))
    && Object.entries(descriptors).every(([key,d]) => [...required,...optional].includes(key) && Object.hasOwn(d,"value") && d.enumerable);
}
export function parseAppearanceClaim(value: unknown): AppearanceMainControlRequest {
  const fail = (): never => { throw new Error("ASSISTANT_MAIN_CONTROL_INVALID"); };
  if (!closed(value,["deliveryId","action","operation"],["theme","kind","timeoutMs"]) || typeof value.deliveryId !== "string" || !/^[0-9a-f]{32}$/.test(value.deliveryId)) return fail();
  const base = {deliveryId:value.deliveryId};
  if (value.action === "launcher_theme_get" && value.operation === "read" && Object.keys(value).length === 3) return {...base,action:value.action,operation:value.operation};
  if (value.action === "launcher_theme_set" && value.operation === "set" && Object.keys(value).length === 4 && ["dark","light"].includes(value.theme as string)) return {...base,action:value.action,operation:value.operation,theme:value.theme as "dark"|"light"};
  if (value.action === "operator_image_upload" && value.operation === "import" && Object.keys(value).length === 5 && ["avatar","background"].includes(value.kind as string) && typeof value.timeoutMs === "number" && Number.isSafeInteger(value.timeoutMs) && value.timeoutMs >= 1 && value.timeoutMs <= 120000) return {...base,action:value.action,operation:value.operation,kind:value.kind as "avatar"|"background",timeoutMs:value.timeoutMs};
  return fail();
}
export function appearanceUnavailable(request: AppearanceMainControlRequest): Record<string,unknown> {
  return request.action === "operator_image_upload" ? {schemaVersion:1,operation:"import",kind:request.kind,code:"unavailable",verified:false}
    : {schemaVersion:1,operation:request.operation,code:"unavailable"};
}
export function appearanceControlResult(request: AppearanceMainControlRequest,value: unknown): Record<string,unknown> {
  const fail = () => appearanceUnavailable(request);
  if (request.action === "operator_image_upload") {
    if (!closed(value,["schemaVersion","operation","kind","code","verified"],["selection"]) || value.schemaVersion !== 1 || value.operation !== "import" || value.kind !== request.kind || typeof value.verified !== "boolean"
      || typeof value.code !== "string" || !["applied","cancelled","unavailable","invalid_image","not_applied","unknown","busy"].includes(value.code)) return fail();
    if (value.code === "applied") {
      const prefix = request.kind === "avatar" ? "workspace/user_avatars" : "theme_backgrounds";
      if (value.verified !== true || typeof value.selection !== "string" || !new RegExp("^"+prefix+"/[A-Za-z0-9_-][A-Za-z0-9_.-]{0,239}\\.(?:png|jpe?g|webp)$","i").test(value.selection)) return fail();
    } else if (value.verified !== false || Object.hasOwn(value,"selection")) return fail();
    return {...value};
  }
  if (!closed(value,["schemaVersion","operation","code"],["theme","workbenchSync","assistantSync","authorityStatus"]) || value.schemaVersion !== 1 || value.operation !== request.operation || typeof value.code !== "string" || !["read","applied","conflict","unknown","unavailable","persistence_failed"].includes(value.code)) return fail();
  if (["conflict","unknown"].includes(value.code) && request.action !== "launcher_theme_set") return fail();
  if (Object.hasOwn(value,"authorityStatus") && (request.action !== "launcher_theme_set" || !["committed","unknown"].includes(value.authorityStatus as string))) return fail();
  if (Object.hasOwn(value,"assistantSync") && (request.action !== "launcher_theme_set" || !["applied","conflict","unavailable","unknown"].includes(value.assistantSync as string))) return fail();
  if (Object.hasOwn(value,"workbenchSync") && (request.action !== "launcher_theme_set" || !["applied","conflict","unknown","unavailable"].includes(value.code)
      || !["applied","conflict","unavailable","unknown"].includes(value.workbenchSync as string))) return fail();
  if (["read","applied"].includes(value.code)) {
    if (!["dark","light"].includes(value.theme as string) || value.code !== (request.action === "launcher_theme_get" ? "read" : "applied") || request.action === "launcher_theme_set" && value.theme !== request.theme) return fail();
  } else if (Object.hasOwn(value,"theme")) return fail();
  return {...value};
}
