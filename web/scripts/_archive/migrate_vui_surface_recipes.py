"""
Bulk-migrate product style maps onto VUI surface recipes and collapse
structural surface+transparent color-mix washes into opaque surfaces.

Does NOT rewrite intentional state tints (accent/state mixed into a surface).
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"

PANEL_TRIPLE = (
    "rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] "
    "bg-[var(--vui-surface-panel)]"
)
ROW_TRIPLE = (
    "rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] "
    "bg-[var(--vui-surface-row)]"
)
# Arbitrary-property form used by Agents converted maps
PANEL_ARB = (
    "[border:1px_solid_color-mix(in_srgb,_var(--vui-border-subtle)_76%,_transparent)] "
    "[border-radius:var(--radius-panel)] [background:var(--vui-surface-panel)]"
)
ROW_ARB = (
    "[border:1px_solid_color-mix(in_srgb,_var(--vui-border-subtle)_76%,_transparent)] "
    "[border-radius:var(--radius-control)] [background:var(--vui-surface-row)]"
)
ROW_ARB_SOLID = (
    "[border:1px_solid_var(--vui-border-subtle)] "
    "[border-radius:var(--radius-control)] [background:var(--vui-surface-row)]"
)
PANEL_ARB_SOLID = (
    "[border:1px_solid_var(--vui-border-subtle)] "
    "[border-radius:var(--radius-panel)] [background:var(--vui-surface-panel)]"
)

# Structural washes: surface mixed only with transparent → opaque token.
STRUCTURAL_RESUBS: list[tuple[re.Pattern[str], str]] = [
    # Tailwind bg-[color-mix(...surface...transparent)]
    (
        re.compile(
            r"bg-\[color-mix\(in_srgb,var\(--vui-surface-row-hover\)_\d+%,transparent\)\]"
        ),
        "!bg-[var(--vui-surface-row-hover)]",
    ),
    (
        re.compile(
            r"bg-\[color-mix\(in_srgb,var\(--vui-surface-row\)_\d+%,transparent\)\]"
        ),
        "!bg-[var(--vui-surface-row)]",
    ),
    (
        re.compile(
            r"bg-\[color-mix\(in_srgb,var\(--vui-surface-panel\)_\d+%,transparent\)\]"
        ),
        "!bg-[var(--vui-surface-panel)]",
    ),
    (
        re.compile(
            r"bg-\[color-mix\(in_srgb,var\(--vui-surface-workspace\)_\d+%,transparent\)\]"
        ),
        "!bg-[var(--vui-surface-workspace)]",
    ),
    (
        re.compile(
            r"bg-\[color-mix\(in_srgb,var\(--vui-surface-card\)_\d+%,transparent\)\]"
        ),
        "!bg-[var(--vui-surface-card)]",
    ),
    (
        re.compile(
            r"bg-\[color-mix\(in_srgb,var\(--vui-surface-base\)_\d+%,transparent\)\]"
        ),
        "!bg-[var(--vui-surface-base)]",
    ),
    (
        re.compile(
            r"bg-\[color-mix\(in_srgb,var\(--vui-surface-toolbar\)_\d+%,transparent\)\]"
        ),
        "!bg-[var(--vui-surface-toolbar)]",
    ),
    (
        re.compile(
            r"bg-\[color-mix\(in_srgb,var\(--vui-surface-row\)_\d+%,var\(--vui-surface-base\)\)\]"
        ),
        "!bg-[var(--vui-surface-row)]",
    ),
    # Arbitrary [background:color-mix(...)] with underscore separators
    (
        re.compile(
            r"\[background:color-mix\(in_srgb,_var\(--vui-surface-row-hover\)_\d+%,_transparent\)\]"
        ),
        "!bg-[var(--vui-surface-row-hover)]",
    ),
    (
        re.compile(
            r"\[background:color-mix\(in_srgb,_var\(--vui-surface-row\)_\d+%,_transparent\)\]"
        ),
        "!bg-[var(--vui-surface-row)]",
    ),
    (
        re.compile(
            r"\[background:color-mix\(in_srgb,_var\(--vui-surface-panel\)_\d+%,_transparent\)\]"
        ),
        "!bg-[var(--vui-surface-panel)]",
    ),
    (
        re.compile(
            r"\[background:color-mix\(in_srgb,_var\(--vui-surface-workspace\)_\d+%,_transparent\)\]"
        ),
        "!bg-[var(--vui-surface-workspace)]",
    ),
    (
        re.compile(
            r"\[background:color-mix\(in_srgb,var\(--vui-surface-toolbar\)_\d+%,transparent\)\]"
        ),
        "!bg-[var(--vui-surface-toolbar)]",
    ),
    (
        re.compile(
            r"\[background:color-mix\(in_srgb,var\(--vui-surface-row-hover\)_\d+%,transparent\)\]"
        ),
        "!bg-[var(--vui-surface-row-hover)]",
    ),
    (
        re.compile(
            r"\[background:color-mix\(in_srgb,var\(--vui-surface-row\)_\d+%,transparent\)\]"
        ),
        "!bg-[var(--vui-surface-row)]",
    ),
    (
        re.compile(
            r"\[background:color-mix\(in_srgb,var\(--vui-surface-panel\)_\d+%,transparent\)\]"
        ),
        "!bg-[var(--vui-surface-panel)]",
    ),
    # hover: structural wash
    (
        re.compile(
            r"hover:bg-\[color-mix\(in_srgb,var\(--vui-surface-row-hover\)_\d+%,transparent\)\]"
        ),
        "hover:bg-[var(--vui-surface-row-hover)]",
    ),
    (
        re.compile(
            r"hover:\[background:color-mix\(in_srgb,_var\(--vui-surface-row-hover\)_\d+%,_transparent\)\]"
        ),
        "hover:bg-[var(--vui-surface-row-hover)]",
    ),
]


def import_path_for(file: Path) -> str:
    rel = file.relative_to(ROOT)
    depth = len(rel.parts) - 1
    return ("../" * depth) + "design/vuiSurfaceRecipes"


def collapse_structural(text: str) -> tuple[str, int]:
    hits = 0
    for pat, repl in STRUCTURAL_RESUBS:
        text, n = pat.subn(repl, text)
        hits += n
    return text, hits


def splice_recipes(text: str, file: Path) -> tuple[str, int]:
    spliced = 0

    def maybe_replace(body: str) -> str:
        nonlocal spliced
        # Prefer triple replacements even when multiple bgs exist if exact triple present
        # once and not already a recipe.
        new = body
        if "${vuiFlatPanelClass}" not in new and PANEL_TRIPLE in new:
            # only if that panel bg is the structural one (may still have state later)
            new = new.replace(PANEL_TRIPLE, "${vuiFlatPanelClass}", 1)
            spliced += 1
        if "${vuiOpaqueRowClass}" not in new and ROW_TRIPLE in new:
            new = new.replace(ROW_TRIPLE, "${vuiOpaqueRowClass}", 1)
            spliced += 1
        if "${vuiFlatPanelClass}" not in new and PANEL_ARB in new:
            new = new.replace(PANEL_ARB, "${vuiFlatPanelClass}", 1)
            spliced += 1
        if "${vuiOpaqueRowClass}" not in new and ROW_ARB in new:
            new = new.replace(ROW_ARB, "${vuiOpaqueRowClass}", 1)
            spliced += 1
        if "${vuiOpaqueRowClass}" not in new and ROW_ARB_SOLID in new:
            new = new.replace(ROW_ARB_SOLID, "${vuiOpaqueRowClass}", 1)
            spliced += 1
        if "${vuiFlatPanelClass}" not in new and PANEL_ARB_SOLID in new:
            new = new.replace(PANEL_ARB_SOLID, "${vuiFlatPanelClass}", 1)
            spliced += 1
        # After structural collapse, pure !bg + border + radius forms
        pure_panel = (
            "rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] "
            "!bg-[var(--vui-surface-panel)]"
        )
        pure_row = (
            "rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] "
            "!bg-[var(--vui-surface-row)]"
        )
        if "${vuiFlatPanelClass}" not in new and pure_panel in new:
            new = new.replace(pure_panel, "${vuiFlatPanelClass}", 1)
            spliced += 1
        if "${vuiOpaqueRowClass}" not in new and pure_row in new:
            new = new.replace(pure_row, "${vuiOpaqueRowClass}", 1)
            spliced += 1
        return new

    # Double-quoted single-line values
    def sub_dq(m: re.Match[str]) -> str:
        key, body = m.group(1), m.group(2)
        new_body = maybe_replace(body)
        if new_body == body:
            return m.group(0)
        if "${" in new_body:
            new_body = new_body.replace("`", "\\`")
            return f"{key}: `{new_body}`,"
        return f'{key}: "{new_body}",'

    text2 = re.sub(r"([A-Za-z0-9_]+):\s*\"((?:\\.|[^\"\\])*)\",", sub_dq, text)

    # Backtick values already templates
    def sub_bt(m: re.Match[str]) -> str:
        key, body = m.group(1), m.group(2)
        new_body = maybe_replace(body)
        if new_body == body:
            return m.group(0)
        return f"{key}: `{new_body}`,"

    text2 = re.sub(r"([A-Za-z0-9_]+):\s*`((?:\\.|[^`\\])*)`,", sub_bt, text2)

    needs_flat = "${vuiFlatPanelClass}" in text2
    needs_row = "${vuiOpaqueRowClass}" in text2
    if not (needs_flat or needs_row):
        return text2, spliced

    if "vuiSurfaceRecipes" not in text2:
        symbols = []
        if needs_flat:
            symbols.append("vuiFlatPanelClass")
        if needs_row:
            symbols.append("vuiOpaqueRowClass")
        # Keep existing dense imports if present
        if "vuiDenseRowClass" in text2 and "vuiDenseRowClass" not in symbols:
            # already imported elsewhere
            pass
        imp = (
            "import {\n  "
            + ",\n  ".join(symbols)
            + f',\n}} from "{import_path_for(file)}";\n\n'
        )
        # Insert after leading comment block if any, else top
        if text2.lstrip().startswith("//") or text2.lstrip().startswith("/*"):
            # find first non-comment line
            lines = text2.splitlines(keepends=True)
            i = 0
            while i < len(lines):
                s = lines[i].lstrip()
                if s.startswith("//") or s.startswith("/*") or s.startswith("*") or s.strip() == "":
                    i += 1
                    continue
                break
            text2 = "".join(lines[:i]) + imp + "".join(lines[i:])
        else:
            text2 = imp + text2
    else:
        # Ensure symbols present in existing import
        def add_symbols(m: re.Match[str]) -> str:
            block = m.group(0)
            for sym in ("vuiFlatPanelClass", "vuiOpaqueRowClass"):
                if sym in text2 and f"  {sym}" not in block and f" {sym}" not in block:
                    # insert before closing
                    if needs_flat and sym == "vuiFlatPanelClass" and "vuiFlatPanelClass" not in block:
                        block = block.replace("} from", f"  {sym},\n}} from").replace(
                            "}} from", "} from"
                        )
                        # fix double
                        block = re.sub(r"\n\}\n\} from", "\n} from", block)
                    if needs_row and sym == "vuiOpaqueRowClass" and "vuiOpaqueRowClass" not in block:
                        if "vuiFlatPanelClass" in block and "vuiOpaqueRowClass" not in block:
                            block = block.replace(
                                "vuiFlatPanelClass",
                                "vuiFlatPanelClass,\n  vuiOpaqueRowClass",
                            )
                        elif "vuiDenseRowClass" in block and "vuiOpaqueRowClass" not in block:
                            block = block.replace(
                                "vuiDenseRowClass",
                                "vuiDenseRowClass,\n  vuiOpaqueRowClass",
                            )
            return block

        text2 = re.sub(
            r"import\s*\{[^}]+\}\s*from\s*[\"'][^\"']*vuiSurfaceRecipes[\"']\s*;",
            add_symbols,
            text2,
            count=1,
        )

    return text2, spliced


def should_process(path: Path) -> bool:
    name = path.name
    if "test" in name.lower():
        return False
    if path.suffix not in {".ts", ".tsx"}:
        return False
    # style maps and a few known class string modules
    if name.endswith(".styles.ts") or name.endswith(".styles.tsx"):
        return True
    if name in {"codeMirrorTheme.ts"}:
        return True
    return False


def main() -> None:
    total_struct = 0
    total_splice = 0
    changed_files = 0
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or not should_process(path):
            continue
        original = path.read_text(encoding="utf-8")
        text, struct_hits = collapse_structural(original)
        text, splice_hits = splice_recipes(text, path)
        if text != original:
            path.write_text(text, encoding="utf-8", newline="\n")
            changed_files += 1
            total_struct += struct_hits
            total_splice += splice_hits
            print(f"OK {path.relative_to(ROOT.parent)} struct={struct_hits} splice={splice_hits}")
    print(
        f"\nDONE files={changed_files} structural_replacements={total_struct} recipe_splices={total_splice}"
    )


if __name__ == "__main__":
    main()
