"""
Codemod: VButton children icons → icon=/trailingIcon=/isIconOnly props.

Handles:
1. Leading self-closing icon + simple label
2. Simple label + trailing arrow/chevron
3. Conditional leading icon {a ? <A/> : <B/>} + simple label
4. Icon-only body (single self-closing icon or conditional icons) → isIconOnly + icon=
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"

# Any PascalCase component used as icon (self-closing with optional attrs)
ICON_NAME = (
    r"[A-Z][A-Za-z0-9]*"
)

TRAIL_ICONS = (
    "ArrowRight|ArrowUpRight|ChevronRight|ExternalLink|ArrowLeft|ChevronLeft|"
    "ChevronDown|ChevronUp"
)


def find_open_end(text: str, start: int) -> int:
    """start points at '<VButton'."""
    i = start + len("<VButton")
    depth_brace = 0
    in_s = in_d = False
    while i < len(text):
        ch = text[i]
        if in_s:
            if ch == "\\" and i + 1 < len(text):
                i += 2
                continue
            if ch == "'":
                in_s = False
            i += 1
            continue
        if in_d:
            if ch == "\\" and i + 1 < len(text):
                i += 2
                continue
            if ch == '"':
                in_d = False
            i += 1
            continue
        if ch == "'":
            in_s = True
            i += 1
            continue
        if ch == '"':
            in_d = True
            i += 1
            continue
        if ch == "{":
            depth_brace += 1
            i += 1
            continue
        if ch == "}":
            depth_brace = max(0, depth_brace - 1)
            i += 1
            continue
        if ch == ">" and depth_brace == 0:
            return i
        i += 1
    return -1


def find_close(text: str, body_start: int) -> int:
    depth = 1
    pos = body_start
    while pos < len(text) and depth > 0:
        o = text.find("<VButton", pos)
        c = text.find("</VButton>", pos)
        if c < 0:
            return -1
        # skip VButtonFoo
        while o >= 0:
            ao = o + len("<VButton")
            if ao < len(text) and (text[ao].isalnum() or text[ao] == "_"):
                o = text.find("<VButton", ao)
                continue
            break
        if o >= 0 and o < c:
            depth += 1
            pos = o + 8
        else:
            depth -= 1
            if depth == 0:
                return c
            pos = c + len("</VButton>")
    return -1


SKIP_RE = re.compile(
    r'contentLayout\s*=\s*["\']plain["\']|isIconOnly|\bicon\s*=|\btrailingIcon\s*='
)

# Self-closing icon tag
SELF_ICON = re.compile(
    rf"<(?P<name>{ICON_NAME})\b(?P<iattrs>(?:[^>{{\"'/]|\"[^\"]*\"|'[^']*'|\{{[^{{}}]*\}})*?)\s*/>"
)

# Leading icon: optional whitespace, self-closing icon, rest
LEAD_ICON = re.compile(
    rf"^\s*{SELF_ICON.pattern}\s*(?P<rest>[\s\S]*)$"
)

# Conditional icon: { expr ? <A .../> : <B .../> } or { expr ? <A .../> : null }
COND_ICON = re.compile(
    rf"^\s*\{{(?P<expr>[\s\S]*?)\?\s*"
    rf"(?P<a><{ICON_NAME}\b(?:[^>{{\"'/]|\"[^\"]*\"|'[^']*'|\{{[^{{}}]*\}})*?/>)\s*:\s*"
    rf"(?P<b><{ICON_NAME}\b(?:[^>{{\"'/]|\"[^\"]*\"|'[^']*'|\{{[^{{}}]*\}})*?/>|null)\s*\}}\s*"
    rf"(?P<rest>[\s\S]*)$"
)

# Trailing trail icon
TRAIL_SELF = re.compile(
    rf"^(?P<head>[\s\S]*?)\s*<(?P<name>{TRAIL_ICONS})\b(?P<iattrs>(?:[^>{{\"'/]|\"[^\"]*\"|'[^']*'|\{{[^{{}}]*\}})*?)\s*/>\s*$"
)

# Icon-only conditional (no rest label)
COND_ICON_ONLY = re.compile(
    rf"^\s*\{{(?P<expr>[\s\S]*?)\?\s*"
    rf"(?P<a><{ICON_NAME}\b(?:[^>{{\"'/]|\"[^\"]*\"|'[^']*'|\{{[^{{}}]*\}})*?/>)\s*:\s*"
    rf"(?P<b><{ICON_NAME}\b(?:[^>{{\"'/]|\"[^\"]*\"|'[^']*'|\{{[^{{}}]*\}})*?/>|null)\s*\}}\s*$"
)

# Triple conditional for rating etc — leave alone (complex)

# Icon-only single
ICON_ONLY = re.compile(
    rf"^\s*<(?P<name>{ICON_NAME})\b(?P<iattrs>(?:[^>{{\"'/]|\"[^\"]*\"|'[^']*'|\{{[^{{}}]*\}})*?)\s*/>\s*$"
)

# Known non-icon PascalCase tags that must NOT be treated as icons
NOT_ICON = {
    "VButton",
    "VSurface",
    "VTooltip",
    "VChip",
    "VBadge",
    "VSelect",
    "VInput",
    "VTextarea",
    "VDialog",
    "VTabs",
    "VSkeleton",
    "VStateSurface",
    "Suspense",
    "Fragment",
    "Provider",
    "Router",
    "Link",
    "NavLink",
    "Outlet",
    "Portal",
    "Transition",
}


def is_simple_label(fragment: str) -> bool:
    fragment = fragment.strip()
    if not fragment:
        return False
    # {expr} simple
    if re.fullmatch(r"\{[^{}]+\}", fragment):
        return True
    # nested ternary in braces for labels like {a ? b : c}
    if fragment.startswith("{") and fragment.endswith("}"):
        inner = fragment[1:-1]
        # allow nested braces one level for ternary strings
        if "<" not in inner:
            return True
    if re.fullmatch(r"<span\b[^>]*>[\s\S]*?</span>", fragment):
        # span without nested component icons (allow em/strong)
        if re.search(r"<[A-Z]", fragment):
            return False
        return True
    # plain text / jsx text without component tags
    if re.search(r"<[A-Z]", fragment):
        return False
    if re.search(r"</?[a-z]", fragment) and not re.fullmatch(
        r"(?:[\s\S]*?)", fragment
    ):
        # lowercase tags like <em> inside plain is ok if no capital
        pass
    if re.search(r"<[A-Z]", fragment):
        return False
    # disallow multi-root structural divs
    if "<div" in fragment:
        return False
    return True


def with_prop(attrs: str, prop: str, icon_jsx: str) -> str:
    attrs = attrs.rstrip()
    # already has prop?
    if re.search(rf"\b{prop}\s*=", attrs):
        return attrs
    if "\n" in attrs:
        last = attrs.split("\n")[-1]
        m = re.match(r"^(\s*)", last)
        indent = m.group(1) if m and last.strip() else "  "
        if not attrs.endswith("\n"):
            attrs += "\n"
        return f"{attrs}{indent}{prop}={{{icon_jsx}}}"
    if attrs and not attrs.endswith(" "):
        attrs += " "
    return f"{attrs}{prop}={{{icon_jsx}}}"


def with_flag(attrs: str, flag: str) -> str:
    if re.search(rf"\b{flag}\b", attrs):
        return attrs
    attrs = attrs.rstrip()
    if "\n" in attrs:
        last = attrs.split("\n")[-1]
        m = re.match(r"^(\s*)", last)
        indent = m.group(1) if m and last.strip() else "  "
        if not attrs.endswith("\n"):
            attrs += "\n"
        return f"{attrs}{indent}{flag}"
    if attrs and not attrs.endswith(" "):
        attrs += " "
    return f"{attrs}{flag}"


def looks_like_icon_name(name: str) -> bool:
    if name in NOT_ICON:
        return False
    # StageIcon / ActionIcon dynamic components are icons
    if name.endswith("Icon"):
        return True
    # Heuristic: lucide-style names are PascalCase without "Panel"/"Route" suffixes of app components
    if name.startswith("V") and len(name) > 1 and name[1].isupper():
        return False  # VSomething product components
    return True


def process_file(text: str) -> tuple[str, int]:
    count = 0
    out: list[str] = []
    pos = 0
    while True:
        idx = text.find("<VButton", pos)
        if idx < 0:
            out.append(text[pos:])
            break
        after = idx + len("<VButton")
        if after < len(text) and (text[after].isalnum() or text[after] == "_"):
            out.append(text[pos:after])
            pos = after
            continue
        out.append(text[pos:idx])
        open_end = find_open_end(text, idx)
        if open_end < 0:
            out.append(text[idx:])
            break
        open_tag = text[idx : open_end + 1]
        if open_tag.rstrip().endswith("/>"):
            out.append(open_tag)
            pos = open_end + 1
            continue
        close = find_close(text, open_end + 1)
        if close < 0:
            out.append(text[idx:])
            break
        attrs = open_tag[len("<VButton") : -1]
        body = text[open_end + 1 : close]
        full = text[idx : close + len("</VButton>")]

        if SKIP_RE.search(attrs):
            out.append(full)
            pos = close + len("</VButton>")
            continue

        # 1) Icon-only single self-close
        m = ICON_ONLY.match(body)
        if m and looks_like_icon_name(m.group("name")):
            icon = f"<{m.group('name')}{m.group('iattrs')}/>"
            new_attrs = with_prop(with_flag(attrs, "isIconOnly"), "icon", icon)
            out.append(f"<VButton{new_attrs} />")
            count += 1
            pos = close + len("</VButton>")
            continue

        # 2) Icon-only conditional
        m = COND_ICON_ONLY.match(body)
        if m:
            a_name = re.match(rf"<({ICON_NAME})\b", m.group("a"))
            if a_name and looks_like_icon_name(a_name.group(1)):
                expr = m.group("expr").strip()
                icon_jsx = f"{expr} ? {m.group('a')} : {m.group('b')}"
                new_attrs = with_prop(with_flag(attrs, "isIconOnly"), "icon", icon_jsx)
                out.append(f"<VButton{new_attrs} />")
                count += 1
                pos = close + len("</VButton>")
                continue

        # 3) Conditional leading icon + simple label
        m = COND_ICON.match(body)
        if m:
            rest = m.group("rest").strip()
            a_name = re.match(rf"<({ICON_NAME})\b", m.group("a"))
            if a_name and looks_like_icon_name(a_name.group(1)) and is_simple_label(rest):
                expr = m.group("expr").strip()
                icon_jsx = f"{expr} ? {m.group('a')} : {m.group('b')}"
                new_attrs = with_prop(attrs, "icon", icon_jsx)
                out.append(f"<VButton{new_attrs}>{rest}</VButton>")
                count += 1
                pos = close + len("</VButton>")
                continue

        # 4) Leading icon + simple label
        m = LEAD_ICON.match(body)
        if m and looks_like_icon_name(m.group("name")):
            label = m.group("rest").strip()
            if is_simple_label(label):
                icon = f"<{m.group('name')}{m.group('iattrs')}/>"
                # trailing chevron cases with lead icon → leave for multi-child
                if re.search(rf"<({TRAIL_ICONS})\b", label):
                    out.append(full)
                    pos = close + len("</VButton>")
                    continue
                out.append(f"<VButton{with_prop(attrs, 'icon', icon)}>{label}</VButton>")
                count += 1
                pos = close + len("</VButton>")
                continue

        # 5) label + trailing arrow (no other capital tags in head)
        m = TRAIL_SELF.match(body)
        if m:
            head = m.group("head").strip()
            if is_simple_label(head) and not re.search(r"<[A-Z]", head):
                icon = f"<{m.group('name')}{m.group('iattrs')}/>"
                out.append(f"<VButton{with_prop(attrs, 'trailingIcon', icon)}>{head}</VButton>")
                count += 1
                pos = close + len("</VButton>")
                continue

        out.append(full)
        pos = close + len("</VButton>")
    return "".join(out), count


def main() -> None:
    total = 0
    files = 0
    for path in sorted(ROOT.rglob("*.tsx")):
        original = path.read_text(encoding="utf-8")
        updated, n = process_file(original)
        if n and updated != original:
            # preserve original line endings style if pure LF
            path.write_text(updated, encoding="utf-8", newline="\n")
            files += 1
            total += n
            print(f"{n:3d} {path.relative_to(ROOT)}")
    print(f"FIXED {total} in {files} files")


if __name__ == "__main__":
    main()
