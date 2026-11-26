"""Signing out after a stretch without use, as the console does.

The server decides: a sign-in not used for its idle limit (GET /api/health says how many minutes) is ended there,
and the next request is refused with code idle_signed_out. The command bar and full-screen mode also watch the
keyboard: after the limit with no key pressed they clear the screen, end the sign-in on the server, forget it here
and say why, so an unattended terminal shows nothing.
"""

import signal
import sys

from . import store
from .api import ApiError

DEFAULT_MINUTES = 2


class IdleTimeout(Exception):
    """Nothing was typed for the idle limit."""


def minutes(api):
    try:
        return max(1, int(api.get("/health").get("idle_minutes") or DEFAULT_MINUTES))
    except (ApiError, ValueError, TypeError):
        return DEFAULT_MINUTES


def timed(read, seconds):
    """Run read() but raise IdleTimeout if it waits longer than `seconds`. Uses the alarm signal where there is one
    (macOS and Linux); elsewhere it reads without a limit and the server's own idle rule still applies."""
    if not hasattr(signal, "SIGALRM"):
        return read()

    def ring(signum, frame):
        raise IdleTimeout()

    old = signal.signal(signal.SIGALRM, ring)
    signal.alarm(max(1, int(seconds)))
    try:
        return read()
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


def lock_out(api, mins, color=True):
    """Clear the screen, end the sign-in on the server and forget it here."""
    try:
        api.post("/cli/logout", {"why": "idle"})
    except ApiError:
        pass  # already ended on the server
    store.delete_token(api.server)
    if sys.stdout.isatty():
        sys.stdout.write("\x1b[2J\x1b[H")
    print(f"Signed out after {mins} minute{'' if mins == 1 else 's'} without use. Run phaneris login to carry on.")
