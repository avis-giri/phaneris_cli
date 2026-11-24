"""The command bar's history and suggestions.

What the person ran in the command bar is kept in ~/.config/phaneris/history (readable only by them, at most 500 lines,
newest last) so Tab can suggest from it. Only command bar lines are kept: never the questions typed into a
conversation, and never anything that looks like a password or a sign-in token. `phaneris history --clear` empties it.

Suggestions for what has been typed so far, best first:
1. whole lines run before, most used and most recent first;
2. function codes for the word being typed;
3. subjects run before;
4. subjects seen in this session (disclosure ids, names, record ids from earlier screens).
"""

import os
import re
import stat
from collections import Counter

from . import store

MAX_LINES = 500
SECRET = re.compile(r"phc_|phr_|passw|token|secret|bearer|\b[A-Za-z0-9_\-]{32,}\b", re.I)


def path():
    return os.path.join(store.CONFIG_DIR, "history")


def keepable(line):
    """A command bar line worth keeping: not empty, not help, nothing that looks like a secret."""
    line = line.strip()
    return bool(line) and line not in ("?", "help", "HELP", "quit", "exit") and not SECRET.search(line) and len(line) <= 200


def load():
    try:
        with open(path(), encoding="utf-8") as fh:
            return [x.rstrip("\n") for x in fh if x.strip()][-MAX_LINES:]
    except OSError:
        return []


def add(line):
    if not keepable(line):
        return
    lines = (load() + [line.strip()])[-MAX_LINES:]
    os.makedirs(store.CONFIG_DIR, mode=0o700, exist_ok=True)
    fd = os.open(path(), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    os.chmod(path(), stat.S_IRUSR | stat.S_IWUSR)


def clear():
    try:
        os.remove(path())
        return True
    except FileNotFoundError:
        return False


def ranked(lines):
    """Distinct lines, most used and most recent first: each use counts, and newer uses count more."""
    score = Counter()
    n = len(lines)
    for i, line in enumerate(lines):
        score[line] += 1 + (i + 1) / max(n, 1)
    return [line for line, _ in sorted(score.items(), key=lambda kv: -kv[1])]


def suggestions(typed, lines, codes, session_subjects, limit=12):
    """What Tab offers for the text typed so far, best first, each a whole replacement for the line."""
    typed_l = typed.lower()
    out = []

    def push(x):
        if x and x.lower().startswith(typed_l) and x != typed and x not in out:
            out.append(x)

    history = ranked(lines)
    if not typed.strip():
        return history[:5]  # an empty line offers the last few commands
    for line in history:
        push(line)
    head, _, word = typed.rpartition(" ")
    for c in codes:
        if c.lower().startswith(word.lower()):
            push(f"{head} {c}".strip() if head else c)
    subjects = []
    for line in history:
        words = line.split()
        if len(words) > 1 and words[-1].upper() in codes:
            subjects.append(" ".join(words[:-1]))
    for subj in subjects + list(session_subjects):
        push(subj)
    return out[:limit]
