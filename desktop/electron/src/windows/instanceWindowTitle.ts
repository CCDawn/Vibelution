export type InstanceWindowRole = "workbench" | "launcher";

export function instanceWindowTitle(
  role: InstanceWindowRole,
  shortName = process.env.VIBELUTION_INSTANCE_SHORT_NAME || "主"
): string {
  const name = String(shortName || "主").trim() || "主";
  return role === "workbench" ? `${name} 台` : `${name} 控`;
}
