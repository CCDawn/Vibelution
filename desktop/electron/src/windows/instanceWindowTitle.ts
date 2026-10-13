export type InstanceWindowRole = "workbench" | "launcher";

export function instanceWindowTitle(
  role: InstanceWindowRole,
  shortName = process.env.VIBELUTION_INSTANCE_SHORT_NAME || "main"
): string {
  const name = String(shortName || "main").trim() || "main";
  if (role === "launcher") return "Vibelution 启动管理";
  const label = name.replace(/^(branch\+|retired\+)/, "");
  return name === "main" ? "Vibelution 工作台 · main" : `Vibelution 测试工作台 · ${label}`;
}
