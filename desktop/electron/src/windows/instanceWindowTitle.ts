export type InstanceWindowRole = "workbench" | "launcher";

export function instanceWindowTitle(
  role: InstanceWindowRole,
  shortName = process.env.VIBELUTION_INSTANCE_SHORT_NAME || "main"
): string {
  const name = String(shortName || "main").trim() || "main";
  return role === "workbench" ? `${name} 台` : `${name} 控`;
}
