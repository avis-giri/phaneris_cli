"""Terminal output: color and symbols only on a real terminal, aligned tables that fit its width, section rules, and
the signed-in wordmark. Plain ANSI, no dependencies.

Color is off when output is not a terminal, when NO_COLOR is set (https://no-color.org), with --no-color or --json,
and when TERM is dumb. The animation is also off with PHANERIS_NO_ANIMATION=1.
"""

import os
import shutil
import sys
import textwrap
import time

ACCENT = (109, 74, 224)  # the site's accent, #6D4AE0
ACCENT_DARK = (167, 139, 250)  # its dark-theme form, #A78BFA, easier to read on dark terminals


class Style:
    def __init__(self, color=None, stream=None):
        self.stream = stream or sys.stdout
        self.tty = bool(getattr(self.stream, "isatty", lambda: False)())
        if color is None:
            color = self.tty and not os.environ.get("NO_COLOR") and os.environ.get("TERM") != "dumb"
        self.color = bool(color)
        self.truecolor = os.environ.get("COLORTERM", "").lower() in ("truecolor", "24bit")

    # ------------------------------------------------------------ colors

    def _sgr(self, code, text):
        return f"\033[{code}m{text}\033[0m" if self.color else text

    def rgb(self, rgb, text):
        if not self.color:
            return text
        if self.truecolor:
            return f"\033[38;2;{rgb[0]};{rgb[1]};{rgb[2]}m{text}\033[0m"
        return f"\033[38;5;{_to_256(rgb)}m{text}\033[0m"

    def accent(self, text):
        return self.rgb(ACCENT_DARK, text)

    def bold(self, text):
        return self._sgr("1", text)

    def dim(self, text):
        return self._sgr("2", text)

    def good(self, text):
        return self._sgr("32", text)

    def warn(self, text):
        return self._sgr("33", text)

    def bad(self, text):
        return self._sgr("31", text)

    def kind(self, kind):
        """Real or Inferred, colored the same way every time."""
        if kind == "real":
            return self.good("Real")
        if kind == "inferred":
            return self.warn("Inferred")
        return kind or ""

    def mark(self, ok):
        if ok:
            return self.good("✓" if self.color else "ok")
        return self.bad("✗" if self.color else "FAIL")

    # ------------------------------------------------------------ layout

    @property
    def width(self):
        return max(60, min(shutil.get_terminal_size((100, 24)).columns, 120))

    def rule(self, title=""):
        line = "─" if self.color else "-"
        if title:
            head = f"{line * 2} {title} "
            return self.dim(head[:2]) + " " + self.bold(title) + " " + self.dim(line * max(3, self.width - len(head) - 1))
        return self.dim(line * self.width)

    def wrap(self, text, indent=""):
        return textwrap.fill(str(text), width=self.width, initial_indent=indent, subsequent_indent=indent)

    def table(self, rows, headers, color_cols=None, shrink=None):
        """Aligned columns. When the table is wider than the terminal, column `shrink` (default: the widest) is cut with
        an ellipsis, so identifiers needed for the next command stay whole. `color_cols` maps a column index to a
        function applied after padding (so colors do not break alignment)."""
        if not rows:
            return ""
        color_cols = color_cols or {}
        cells = [[str(c) for c in r] for r in rows]
        widths = [max(len(h), *(len(r[i]) for r in cells)) for i, h in enumerate(headers)]
        gap = 2
        over = sum(widths) + gap * (len(widths) - 1) - self.width
        if over > 0:
            widest = shrink if shrink is not None else max(range(len(widths)), key=lambda i: widths[i])
            widths[widest] = max(len(headers[widest]), widths[widest] - over, 8)
        out = ["  ".join(self.dim(h.ljust(w)) for h, w in zip(headers, widths, strict=True)).rstrip()]
        for r in cells:
            parts = []
            for i, (c, w) in enumerate(zip(r, widths, strict=True)):
                if len(c) > w:
                    c = c[: w - 1] + "…"
                padded = c.ljust(w)
                parts.append(color_cols[i](padded) if i in color_cols else padded)
            out.append("  ".join(parts).rstrip())
        return "\n".join(out)

    # ------------------------------------------------------------ the wordmark

    def wordmark(self, animate=True):
        """The lower-case "phaneris." wordmark in the accent color, revealed with a brief shimmer (under a second) on a
        real terminal; otherwise printed plainly, or not at all when there is no color."""
        word = "phaneris."
        if not self.color:
            return
        if not animate or os.environ.get("PHANERIS_NO_ANIMATION") or not self.tty:
            print(self.bold(self.accent(word)), file=self.stream)
            return
        w = self.stream
        try:
            w.write("\033[?25l")  # hide the cursor while drawing
            for n in range(1, len(word) + 1):  # reveal, about 0.45 s
                w.write("\r" + self.bold(self.accent(word[:n])))
                w.flush()
                time.sleep(0.05)
            for pos in range(len(word) + 2):  # a light passes across, about 0.4 s
                line = ""
                for i, ch in enumerate(word):
                    near = abs(i - pos)
                    rgb = (255, 255, 255) if near == 0 else _mix(ACCENT_DARK, (255, 255, 255), 0.5) if near == 1 else ACCENT_DARK
                    line += self.rgb(rgb, ch)
                w.write("\r" + self._sgr("1", line))
                w.flush()
                time.sleep(0.035)
            w.write("\r" + self.bold(self.accent(word)) + "\n")
        finally:
            w.write("\033[?25h")
            w.flush()


def _mix(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b, strict=True))


def _to_256(rgb):
    r, g, b = (round(c / 255 * 5) for c in rgb)
    return 16 + 36 * r + 6 * g + b


def pct(v, digits=1):
    return "" if v is None else f"{v * 100:.{digits}f}%"
