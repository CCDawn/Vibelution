"""Pass 3: promote remaining opaque !bg / bg surface tokens into recipes."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"


def import_path_for(file: Path) -> str:
    rel = file.relative_to(ROOT)
    depth = len(rel.parts) - 1
    return ("../" * depth) + "design/vuiSurfaceRecipes"


def ensure_import(text: str, file: Path, symbols: set[str]) -> str:
    if not symbols:
        return text
    if "vuiSurfaceRecipes" not in text:
        imp = (
            "import {\n  "
            + ",\n  ".join(sorted(symbols))
            + f',\n}} from "{import_path_for(file)}";\n\n'
        )
        lines = text.splitlines(keepends=True)
        i = 0
        while i < len(lines):
            s = lines[i].lstrip()
            if s.startswith("//") or s.startswith("/*") or s.startswith("*") or s.strip() == "":
                i += 1
                continue
            break
        return "".join(lines[:i]) + imp + "".join(lines[i:])
    m = re.search(
        r"import\s*\{([^}]+)\}\s*from\s*[\"'][^\"']*vuiSurfaceRecipes[\"']\s*;",
        text,
    )
    if not m:
        return text
    existing = {s.strip() for s in m.group(1).split(",") if s.strip()}
    missing = symbols - existing
    if not missing:
        return text
    new_block = (
        "import {\n  "
        + ",\n  ".join(sorted(existing | missing))
        + f',\n}} from "{import_path_for(file)}";'
    )
    return text[: m.start()] + new_block + text[m.end() :]


def transform_body(body: str) -> tuple[str, set[str]]:
    if "${vui" in body and "vuiOpaqueRowClass" in body and "vuiFlatPanelClass" in body:
        return body, set()
    symbols: set[str] = set()
    new = body
    # Promote opaque bg tokens that are not already recipe interpolations.
    if "${vuiOpaqueRowClass}" not in new:
        if "!bg-[var(--vui-surface-row)]" in new or "bg-[var(--vui-surface-row)]" in new:
            # Prefer replacing bang form first
            if "!bg-[var(--vui-surface-row)]" in new:
                new = new.replace("!bg-[var(--vui-surface-row)]", "${vuiOpaqueRowClass}", 1)
                # drop redundant border/radius if immediately preceding common patterns already covered
                symbols.add("vuiOpaqueRowClass")
            elif re.search(r"(^|\s)bg-\[var\(--vui-surface-row\)\]", new):
                new = re.sub(
                    r"(^|\s)bg-\[var\(--vui-surface-row\)\]",
                    r"\1${vuiOpaqueRowClass}",
                    new,
                    count=1,
                )
                symbols.add("vuiOpaqueRowClass")
    if "${vuiFlatPanelClass}" not in new:
        if "!bg-[var(--vui-surface-panel)]" in new:
            new = new.replace("!bg-[var(--vui-surface-panel)]", "${vuiFlatPanelClass}", 1)
            symbols.add("vuiFlatPanelClass")
        elif re.search(r"(^|\s)bg-\[var\(--vui-surface-panel\)\]", new):
            new = re.sub(
                r"(^|\s)bg-\[var\(--vui-surface-panel\)\]",
                r"\1${vuiFlatPanelClass}",
                new,
                count=1,
            )
            symbols.add("vuiFlatPanelClass")
    if "${vuiGlassPanelClass}" not in new and "bg-[var(--vui-surface-glass)]" in new:
        # only when paired with rounded panel-ish
        if "rounded-[var(--radius-panel)]" in new or "rounded-[var(--radius-overlay)]" in new:
            new = new.replace("bg-[var(--vui-surface-glass)]", "${vuiGlassPanelClass}", 1)
            # remove duplicate rounded/border/shadow if full triple still present - best effort
            new = new.replace(
                "rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] ${vuiGlassPanelClass}",
                "${vuiGlassPanelClass}",
            )
            new = new.replace(
                "${vuiGlassPanelClass} shadow-[var(--vui-shadow-hairline)]",
                "${vuiGlassPanelClass}",
            )
            symbols.add("vuiGlassPanelClass")
    return new, symbols


def process_file(path: Path) -> bool:
    original = path.read_text(encoding="utf-8")
    # Only STRUCT-ish remaining files without recipe
    if "vuiSurfaceRecipes" in original:
        return False
    if not any(
        t in original
        for t in (
            "--vui-surface-panel",
            "--vui-surface-row",
            "--vui-surface-glass",
        )
    ):
        return False

    text = original
    all_syms: set[str] = set()

    def sub_dq(m: re.Match[str]) -> str:
        key, body = m.group(1), m.group(2)
        new_body, syms = transform_body(body)
        all_syms.update(syms)
        if new_body == body:
            return m.group(0)
        if "${" in new_body:
            return f"{key}: `{new_body.replace('`', '\\`')}`,"
        return f'{key}: "{new_body}",'

    def sub_bt(m: re.Match[str]) -> str:
        key, body = m.group(1), m.group(2)
        new_body, syms = transform_body(body)
        all_syms.update(syms)
        if new_body == body:
            return m.group(0)
        return f"{key}: `{new_body}`,"

    text = re.sub(r"([A-Za-z0-9_]+):\s*\"((?:\\.|[^\"\\])*)\",", sub_dq, text)
    text = re.sub(r"([A-Za-z0-9_]+):\s*`((?:\\.|[^`\\])*)`,", sub_bt, text)
    if all_syms:
        text = ensure_import(text, path, all_syms)
    if text != original:
        path.write_text(text, encoding="utf-8", newline="\n")
        return True
    return False


def main() -> None:
    n = 0
    for path in sorted(ROOT.rglob("*.styles.ts")):
        if "test" in path.name.lower():
            continue
        if process_file(path):
            n += 1
            print("OK", path.relative_to(ROOT.parent))
    print("changed", n)


if __name__ == "__main__":
    main()
