import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const vuiRoot = resolve(import.meta.dirname);

describe("VDropdownMenu contract", () => {
  it("exports Radix dropdown renderer and product facade", () => {
    const indexSource = readFileSync(resolve(vuiRoot, "index.ts"), "utf8");
    const facade = readFileSync(resolve(vuiRoot, "primitives/VDropdownMenu.tsx"), "utf8");
    const renderer = readFileSync(resolve(vuiRoot, "renderers/shadcn/ShadcnDropdownMenu.tsx"), "utf8");
    const catalog = readFileSync(resolve(vuiRoot, "designs/INDEX.md"), "utf8");
    const feedback = readFileSync(resolve(vuiRoot, "designs/primitives/feedback.md"), "utf8");

    expect(indexSource).toContain("VDropdownMenu");
    expect(facade).toContain("ShadcnDropdownMenu");
    expect(renderer).toContain("@radix-ui/react-dropdown-menu");
    expect(renderer).toContain("DropdownMenuPrimitive");
    expect(renderer).toContain("position");
    expect(renderer).toContain("data-renderer=\"radix\"");
    expect(catalog).toContain("`VDropdownMenu`");
    expect(feedback).toContain("## VDropdownMenu");
  });

  it("Agent and Session context menus consume VDropdownMenu", () => {
    const agent = readFileSync(resolve(vuiRoot, "../../routes/AgentContextMenu.tsx"), "utf8");
    const session = readFileSync(resolve(vuiRoot, "../../routes/SessionContextMenu.tsx"), "utf8");
    expect(agent).toContain("VDropdownMenu");
    expect(agent).toContain("position={{ x: state.x, y: state.y }}");
    expect(session).toContain("VDropdownMenu");
    expect(session).toContain("position={position}");
    expect(agent).not.toContain('role="menuitem"');
    expect(session).not.toContain('role="menuitem"');
  });

  it("keeps lifecycle management in Launcher and removes the duplicate AppShell power menu", () => {
    const shell = readFileSync(resolve(vuiRoot, "../../app/AppShell.tsx"), "utf8");
    const launcher = readFileSync(resolve(vuiRoot, "../../routes/LauncherRoute.tsx"), "utf8");
    const powerMenu = readFileSync(
      resolve(vuiRoot, "product/workbench-shell/VWorkbenchPowerMenu.tsx"),
      "utf8",
    );
    const lifecycleActions = readFileSync(
      resolve(vuiRoot, "../../app/workbenchLifecycleActions.ts"),
      "utf8",
    );
    expect(powerMenu).toContain("VDropdownMenu");
    expect(powerMenu).toContain('id: "restart"');
    expect(powerMenu).toContain('id: "stop"');
    expect(powerMenu).toContain('id: "force-stop"');
    expect(shell).not.toContain("VWorkbenchPowerMenu");
    expect(shell).not.toContain("lifecycleMenuRef");
    expect(shell).not.toContain('role="menuitem"');
    expect(launcher).toContain("VWorkbenchPowerMenu");
    expect(launcher).toContain('variant="labeled"');
    // No parallel status-bar restart/stop/force buttons outside the unified menu.
    expect(launcher).not.toContain('onPress={() => controlMutation.mutate("restart")}');
    expect(launcher).not.toContain('onPress={() => controlMutation.mutate("stop")}');
    expect(launcher).not.toContain('onPress={() => controlMutation.mutate("force-stop")}');
    // Launcher remains the lifecycle management owner.
    expect(launcher).toContain('useWorkbenchLifecycleActions("launcher_route")');
    expect(lifecycleActions).toContain("requestWorkbenchLifecycleOperation");
    expect(lifecycleActions).toContain("app_shell_shutdown_button");
    expect(lifecycleActions).toContain("launcher_route_stop_button");
  });
});
