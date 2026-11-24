"""Small text pictures for the screens: score bars with the 0.5 middle line, a value with its range, a percentile strip
over the history's distribution, a diverging bar for model contributions, a heat cell, and a sparkline. Unicode block
characters with color on a terminal; plain ASCII stand-ins without color, so output stays readable when piped."""

BLOCKS = " ▏▎▍▌▋▊▉█"
SPARK = "▁▂▃▄▅▆▇█"


def _fill(s, n_full, frac, width, real=True):
    """A bar of `width` cells, `n_full` whole cells plus a fraction; Real solid, Inferred shaded."""
    if not s.color:
        ch = "#" if real else "+"
        return (ch * (n_full + (1 if frac >= 0.5 else 0))).ljust(width, ".")[:width]
    body = ("█" if real else "▓") * n_full
    if n_full < width and frac > 0 and real:
        body += BLOCKS[min(8, max(1, round(frac * 8)))]
    elif n_full < width and frac >= 0.5:
        body += "▒"
    return body + " " * (width - len(body))


def score_bar(s, score, width, kind="real"):
    """A 0 to 1 score as a bar, with the middle (0.5) marked."""
    width = max(10, width)
    score = 0.0 if score is None else max(0.0, min(1.0, score))
    cells = score * width
    raw = _fill(s, int(cells), cells - int(cells), width, real=(kind == "real"))
    mid = width // 2
    mark = "│" if s.color else "|"
    chars = list(raw)
    if chars[mid] in (" ", "."):
        chars[mid] = mark
    raw = "".join(chars)
    if not s.color:
        return "[" + raw + "]"
    color = s.good if kind == "real" else s.warn
    left, right = raw[:mid], raw[mid + 1 :]
    middle = s.dim(raw[mid]) if raw[mid] == mark else color(raw[mid])
    return s.dim("▕") + color(left) + middle + color(right) + s.dim("▏")


def range_bar(s, value, low, high, top, width):
    """A value on a 0 to `top` scale with its range drawn around it: ───[──●──]───."""
    width = max(12, width)

    def at(v):
        return max(0, min(width - 1, round((v or 0) / top * (width - 1)))) if top else 0

    cells = [("─" if s.color else "-")] * width
    lo, hi, v = at(low if low is not None else value), at(high if high is not None else value), at(value)
    for i in range(lo, hi + 1):
        cells[i] = "━" if s.color else "="
    cells[lo] = "├" if s.color else "["
    cells[hi] = "┤" if s.color else "]"
    cells[v] = "●" if s.color else "o"
    text = "".join(cells)
    if not s.color:
        return text
    return s.dim(text[:lo]) + s.accent(text[lo : hi + 1]) + s.dim(text[hi + 1 :])


def sparkline(s, counts, width):
    """Counts as a row of rising blocks, squeezed or stretched to `width`."""
    if not counts:
        return ""
    width = max(4, width)
    n = len(counts)
    vals = [counts[min(n - 1, int(i * n / width))] for i in range(width)]
    top = max(vals) or 1
    if not s.color:
        return "".join(" .:-=+*#"[min(7, int(v / top * 7))] for v in vals)
    return "".join(SPARK[min(7, int(v / top * 7))] if v else " " for v in vals)


def percentile_strip(s, distribution, value, percentile, width):
    """The history's deal chances as a sparkline, with this disclosure's place marked underneath."""
    width = max(20, width)
    line = sparkline(s, distribution["counts"], width) if distribution else ""
    top = (distribution or {}).get("max") or 1
    pos = max(0, min(width - 1, round((value or 0) / top * (width - 1))))
    marker = " " * pos + ("▲" if s.color else "^")
    label = f" {percentile:.0f}th percentile" if percentile is not None else ""
    if pos + len(label) + 1 > width:
        marker = " " * max(0, pos - len(label)) + label.strip() + " " + ("▲" if s.color else "^")
    else:
        marker += label
    return (s.dim(line) if s.color else line), s.accent(marker) if s.color else marker


def diverging(s, value, scale, width):
    """A contribution as a bar left (down) or right (up) of a centre line."""
    half = max(4, width // 2)
    n = min(half, round(abs(value) / scale * half)) if scale else 0
    if not s.color:
        left = ("<" * n).rjust(half) if value < 0 else " " * half
        right = (">" * n).ljust(half) if value > 0 else " " * half
        return left + "|" + right
    left = (" " * (half - n) + "█" * n) if value < 0 else " " * half
    right = ("█" * n + " " * (half - n)) if value > 0 else " " * half
    return s.bad(left) + s.dim("│") + s.good(right)


def heat(s, score, kind):
    """One metric as a single shaded cell: darker is higher; Inferred hatched."""
    if score is None:
        return s.dim("·") if s.color else "."
    level = min(4, int(score * 5))
    if not s.color:
        return "0123456789"[min(9, int(score * 10))]
    ch = " ░▒▓█"[level] if kind == "real" else "·░▒▒▒"[level]
    return (s.good if kind == "real" else s.warn)(ch if ch != " " else "▁")
