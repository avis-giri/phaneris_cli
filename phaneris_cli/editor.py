"""A small line editor for the command bar, with suggestions as you type. Standard library only.

The best suggestion for what is typed shows after the cursor in dim text (ghost text); Right arrow or Tab accepts it.
When several suggestions match, Tab first completes as far as they agree and lists them, best first; Tab again takes
the best one. Up and Down walk earlier commands; Ctrl-A and Ctrl-E go to the start and end; Ctrl-U clears; Ctrl-C
drops the line; Ctrl-D on an empty line leaves.

Used only on a real terminal with color (ghost text needs dim text). Elsewhere the command bar uses readline, or plain
input when readline is missing.
"""

import os
import sys

KEYS = {
    "\x1b[A": "up",
    "\x1b[B": "down",
    "\x1b[C": "right",
    "\x1b[D": "left",
    "\x1b[H": "home",
    "\x1b[F": "end",
    "\x1bOH": "home",
    "\x1bOF": "end",
    "\x1b[3~": "delete",
    "\x01": "home",
    "\x05": "end",
    "\x15": "clear",
    "\x17": "word",
    "\t": "tab",
    "\r": "enter",
    "\n": "enter",
    "\x7f": "backspace",
    "\x08": "backspace",
    "\x03": "interrupt",
    "\x04": "eof",
}


def available():
    try:
        import termios  # noqa: F401
        import tty  # noqa: F401
    except ImportError:
        return False
    return sys.stdin.isatty() and sys.stdout.isatty() and os.environ.get("TERM") != "dumb"


def common_prefix(words):
    if not words:
        return ""
    first = words[0]
    n = len(first)
    for w in words[1:]:
        n = min(n, len(w))
        for i in range(n):
            if w[i].lower() != first[i].lower():
                n = i
                break
    return first[:n]


class Editor:
    """The editing state, separate from the terminal so it can be driven by tests."""

    def __init__(self, prompt, suggest, history, dim, write):
        self.prompt, self.suggest, self.history, self.dim, self.write = prompt, suggest, list(history), dim, write
        self.buf, self.pos, self.hist_at, self.last_tab = "", 0, len(self.history), False

    # ------------------------------------------------------------ what is shown

    def ghost(self):
        if self.pos != len(self.buf):
            return ""
        for s in self.suggest(self.buf):
            if s.lower().startswith(self.buf.lower()) and len(s) > len(self.buf):
                return s[len(self.buf) :]
        return ""

    def render(self):
        g = self.ghost()
        after = self.buf[self.pos :]
        line = "\r" + self.prompt + self.buf + (self.dim(g) if g else "") + "\x1b[K"
        back = len(after) + len(g)
        self.write(line + (f"\x1b[{back}D" if back else ""))

    # ------------------------------------------------------------ keys

    def key(self, k):
        """Handle one key. Returns the finished line on Enter, None otherwise; raises EOFError to leave."""
        name = KEYS.get(k)
        tab = name == "tab"
        if name == "enter":
            self.write("\r\n")
            return self.buf
        if name == "eof":
            if not self.buf:
                self.write("\r\n")
                raise EOFError
            name = "delete"
        if name == "interrupt":
            self.write("^C\r\n")
            self.buf, self.pos = "", 0
            return ""
        if name == "tab":
            self._tab()
        elif name == "right":
            g = self.ghost()
            if g:
                self.buf += g
                self.pos = len(self.buf)
            else:
                self.pos = min(len(self.buf), self.pos + 1)
        elif name == "left":
            self.pos = max(0, self.pos - 1)
        elif name == "home":
            self.pos = 0
        elif name == "end":
            self.pos = len(self.buf)
        elif name == "backspace":
            if self.pos:
                self.buf = self.buf[: self.pos - 1] + self.buf[self.pos :]
                self.pos -= 1
        elif name == "delete":
            self.buf = self.buf[: self.pos] + self.buf[self.pos + 1 :]
        elif name == "clear":
            self.buf, self.pos = "", 0
        elif name == "word":
            head = self.buf[: self.pos].rstrip()
            cut = head.rfind(" ") + 1
            self.buf, self.pos = self.buf[:cut] + self.buf[self.pos :], cut
        elif name in ("up", "down"):
            if self.history:
                self.hist_at = max(0, self.hist_at - 1) if name == "up" else min(len(self.history), self.hist_at + 1)
                self.buf = self.history[self.hist_at] if self.hist_at < len(self.history) else ""
                self.pos = len(self.buf)
        elif name is None and k.isprintable():
            self.buf = self.buf[: self.pos] + k + self.buf[self.pos :]
            self.pos += len(k)
        self.last_tab = tab
        self.render()
        return None

    def _tab(self):
        options = [s for s in self.suggest(self.buf) if s.lower().startswith(self.buf.lower())]
        if not options:
            return
        if len(options) == 1 or self.last_tab:
            self.buf = options[0]
        else:
            grown = common_prefix(options)
            if len(grown) > len(self.buf):
                self.buf = grown
            self.write("\r\n" + "\r\n".join("  " + o for o in options) + "\r\n")
        self.pos = len(self.buf)


def read_line(prompt, suggest, history, dim):
    """One line from the terminal in raw mode, with suggestions."""
    import termios
    import tty

    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    out = sys.stdout

    def write(text):
        out.write(text)
        out.flush()

    ed = Editor(prompt, suggest, history, dim, write)
    try:
        tty.setraw(fd)
        ed.render()
        while True:
            k = os.read(fd, 1).decode(errors="ignore")
            if k == "\x1b":  # an escape sequence: read the rest of it
                k += os.read(fd, 1).decode(errors="ignore")
                if k[-1] in "[O":
                    k += os.read(fd, 1).decode(errors="ignore")
                    while k[-1].isdigit():
                        k += os.read(fd, 1).decode(errors="ignore")
            done = ed.key(k)
            if done is not None:
                return done
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
