"""Pass 4: promote const surfaceClass = '...' helpers onto recipes."""
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


def transform(body: str) -> tuple[str, set[str]]:
    symbols: set[str] = set()
    new = body
    # Panel-like
    if "vui-surface-panel" in new and "${vuiFlatPanelClass}" not in new:
        if re.search(r"rounded-\[[^\]]+\].*border.*(?:!)?bg-\[var\(--vui-surface-panel\)\]", new) or (
            "!bg-[var(--vui-surface-panel)]" in new and "border" in new
        ):
            new2 = re.sub(
                r"rounded-\[[^\]]+\]\s+border\s+border-[^\s]+\s+!bg-\[var\(--vui-surface-panel\)\]",
                "${vuiFlatPanelClass}",
                new,
                count=1,
            )
            if new2 == new:
                new2 = new.replace("!bg-[var(--vui-surface-panel)]", "${vuiFlatPanelClass}", 1)
            if new2 != new:
                new = new2
                symbols.add("vuiFlatPanelClass")
    # Row-like
    if "vui-surface-row" in new and "${vuiOpaqueRowClass}" not in new and "row-hover" not in new.split("vui-surface-row")[0][-20:]:
        if "!bg-[var(--vui-surface-row)]" in new or "bg-[var(--vui-surface-row)]" in new:
            # skip pure state mixes
            if "color-mix" in new and "accent" in new and "!bg-[var(--vui-surface-row)]" not in new:
                pass
            else:
                if "!bg-[var(--vui-surface-row)]" in new:
                    # try full triple first
                    new2 = re.sub(
                        r"rounded-\[[^\]]+\]\s+border\s+border-[^\s]+\s+!bg-\[var\(--vui-surface-row\)\]",
                        "${vuiOpaqueRowClass}",
                        new,
                        count=1,
                    )
                    if new2 == new:
                        new2 = new.replace("!bg-[var(--vui-surface-row)]", "${vuiOpaqueRowClass}", 1)
                    if new2 != new:
                        new = new2
                        symbols.add("vuiOpaqueRowClass")
    return new, symbols


def process_file(path: Path) -> bool:
    original = path.read_text(encoding="utf-8")
    if "vuiSurfaceRecipes" in original:
        return False
    if not any(t in original for t in ("--vui-surface-panel", "--vui-surface-row", "--vui-surface-glass")):
        return False
    text = original
    all_syms: set[str] = set()

    def sub_const(m: re.Match[str]) -> str:
        prefix, quote, body, endq = m.group(1), m.group(2), m.group(3), m.group(4)
        new_body, syms = transform(body)
        all_syms.update(syms)
        if new_body == body:
            return m.group(0)
        if "${" in new_body:
            return f"{prefix}`{new_body}`"
        return f"{prefix}{quote}{new_body}{endq}"

    # const foo = "...." or const foo = '....'
    text = re.sub(
        r"(const\s+[A-Za-z0-9_]+\s*=\s*)([\"'])((?:\\.|(?!\2).)*)(\2)",
        sub_const,
        text,
    )
    # also object props again for remaining
    def sub_prop(m: re.Match[str]) -> str:
        key, body = m.group(1), m.group(2)
        new_body, syms = transform(body)
        all_syms.update(syms)
        if new_body == body:
            return m.group(0)
        if "${" in new_body:
            return f"{key}: `{new_body}`,"
        return f'{key}: "{new_body}",'

    text = re.sub(r"([A-Za-z0-9_]+):\s*\"((?:\\.|[^\"\\])*)\",", sub_prop, text)

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
