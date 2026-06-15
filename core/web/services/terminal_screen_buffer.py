"""Small VT-style screen buffer for replaying TUI terminal snapshots."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


CSI_RE = re.compile(r"\x1b\[([0-9;?]*)([@-~])")


@dataclass(frozen=True)
class TerminalScreenSnapshot:
    rows: int
    cols: int
    text: str
    replay: str
    quality: str


class TerminalScreenBuffer:
    """Track the current visible terminal screen from a bounded ANSI stream."""

    def __init__(self, *, rows: int, cols: int, initial_text: str = "") -> None:
        self.rows = _clamp(rows, 28, 4, 120)
        self.cols = _clamp(cols, 100, 20, 240)
        self.cursor_row = 0
        self.cursor_col = 0
        self._cells = [[" " for _ in range(self.cols)] for _ in range(self.rows)]
        if initial_text:
            self.feed_text(initial_text)

    def resize(self, *, rows: int, cols: int) -> None:
        next_rows = _clamp(rows, self.rows, 4, 120)
        next_cols = _clamp(cols, self.cols, 20, 240)
        next_cells = [[" " for _ in range(next_cols)] for _ in range(next_rows)]
        copy_rows = min(self.rows, next_rows)
        copy_cols = min(self.cols, next_cols)
        for row in range(copy_rows):
            for col in range(copy_cols):
                next_cells[row][col] = self._cells[row][col]
        self.rows = next_rows
        self.cols = next_cols
        self._cells = next_cells
        self.cursor_row = min(self.cursor_row, self.rows - 1)
        self.cursor_col = min(self.cursor_col, self.cols - 1)

    def feed(self, chunk: str) -> TerminalScreenSnapshot:
        text = str(chunk or "")
        index = 0
        while index < len(text):
            char = text[index]
            if char == "\x1b":
                consumed = self._consume_escape(text, index)
                index = consumed if consumed > index else index + 1
                continue
            self._put_control_or_text(char)
            index += 1
        return self.snapshot()

    def feed_text(self, text: str) -> TerminalScreenSnapshot:
        for char in str(text or ""):
            self._put_control_or_text(char)
        return self.snapshot()

    def snapshot(self) -> TerminalScreenSnapshot:
        lines = ["".join(row).rstrip() for row in self._cells]
        while lines and not lines[-1].strip():
            lines.pop()
        text = "\n".join(lines)
        replay = "\x1b[2J\x1b[H" + "\r\n".join(lines)
        return TerminalScreenSnapshot(
            rows=self.rows,
            cols=self.cols,
            text=text,
            replay=replay,
            quality="screen_buffer",
        )

    def _consume_escape(self, text: str, index: int) -> int:
        if index + 1 >= len(text):
            return index + 1
        if text[index + 1] == "[":
            match = CSI_RE.match(text, index)
            if not match:
                return index + 2
            self._apply_csi(match.group(1), match.group(2))
            return match.end()
        if text[index + 1] == "]":
            end = text.find("\x07", index + 2)
            if end == -1:
                end = text.find("\x1b\\", index + 2)
                return len(text) if end == -1 else end + 2
            return end + 1
        return index + 2

    def _apply_csi(self, raw_params: str, final: str) -> None:
        params = _parse_params(raw_params)
        if final in {"H", "f"}:
            row = (params[0] if len(params) >= 1 and params[0] else 1) - 1
            col = (params[1] if len(params) >= 2 and params[1] else 1) - 1
            self.cursor_row = _clamp(row, 0, 0, self.rows - 1)
            self.cursor_col = _clamp(col, 0, 0, self.cols - 1)
            return
        if final == "A":
            self.cursor_row = max(0, self.cursor_row - (params[0] or 1))
            return
        if final == "B":
            self.cursor_row = min(self.rows - 1, self.cursor_row + (params[0] or 1))
            return
        if final == "C":
            self.cursor_col = min(self.cols - 1, self.cursor_col + (params[0] or 1))
            return
        if final == "D":
            self.cursor_col = max(0, self.cursor_col - (params[0] or 1))
            return
        if final == "G":
            self.cursor_col = _clamp((params[0] or 1) - 1, 0, 0, self.cols - 1)
            return
        if final == "d":
            self.cursor_row = _clamp((params[0] or 1) - 1, 0, 0, self.rows - 1)
            return
        if final == "J":
            self._erase_display(params[0] if params else 0)
            return
        if final == "K":
            self._erase_line(params[0] if params else 0)
            return
        if final == "m":
            return

    def _erase_display(self, mode: int) -> None:
        if mode == 2:
            self._cells = [[" " for _ in range(self.cols)] for _ in range(self.rows)]
            self.cursor_row = 0
            self.cursor_col = 0
            return
        if mode == 1:
            for row in range(0, self.cursor_row + 1):
                end = self.cursor_col if row == self.cursor_row else self.cols - 1
                for col in range(0, end + 1):
                    self._cells[row][col] = " "
            return
        for row in range(self.cursor_row, self.rows):
            start = self.cursor_col if row == self.cursor_row else 0
            for col in range(start, self.cols):
                self._cells[row][col] = " "

    def _erase_line(self, mode: int) -> None:
        if mode == 2:
            start, end = 0, self.cols
        elif mode == 1:
            start, end = 0, self.cursor_col + 1
        else:
            start, end = self.cursor_col, self.cols
        for col in range(start, end):
            self._cells[self.cursor_row][col] = " "

    def _put_control_or_text(self, char: str) -> None:
        if char == "\r":
            self.cursor_col = 0
            return
        if char == "\n":
            self._newline()
            return
        if char == "\b":
            self.cursor_col = max(0, self.cursor_col - 1)
            return
        if char == "\t":
            next_tab = min(self.cols - 1, self.cursor_col + (4 - (self.cursor_col % 4)))
            while self.cursor_col < next_tab:
                self._put_printable(" ")
            return
        if not char.isprintable():
            return
        self._put_printable(char)

    def _put_printable(self, char: str) -> None:
        width = _char_width(char)
        if self.cursor_col >= self.cols:
            self._newline()
        self._cells[self.cursor_row][self.cursor_col] = char
        if width == 2 and self.cursor_col + 1 < self.cols:
            self._cells[self.cursor_row][self.cursor_col + 1] = ""
        self.cursor_col += width
        if self.cursor_col >= self.cols:
            self._newline()

    def _newline(self) -> None:
        self.cursor_col = 0
        self.cursor_row += 1
        if self.cursor_row < self.rows:
            return
        self._cells.pop(0)
        self._cells.append([" " for _ in range(self.cols)])
        self.cursor_row = self.rows - 1


def _parse_params(raw: str) -> list[int]:
    text = str(raw or "").replace("?", "")
    if not text:
        return []
    result: list[int] = []
    for part in text.split(";"):
        try:
            result.append(int(part) if part else 0)
        except ValueError:
            result.append(0)
    return result


def _char_width(char: str) -> int:
    if not char:
        return 0
    if unicodedata.combining(char):
        return 0
    return 2 if unicodedata.east_asian_width(char) in {"F", "W"} else 1


def _clamp(value: int, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))
