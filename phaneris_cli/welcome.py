"""The welcome `phaneris` shows on a terminal before anything else, and the greeting at the top of the window.

Signed in: "Welcome back, NAME", the office, the role and how many disclosures the office has, a one-line question
meter with a warning when it is low or used up, then the first option, Enter to open the Phaneris window (or, without
its extra, the one command that adds it), and three next steps. Signed out: one line on what Phaneris is and how to
sign in. Never shown with --json or without a terminal; PHANERIS_NO_WELCOME=1 or "don't show this again" skips it.
"""

import os

from . import store
from . import usage as usage_view
from .api import ApiError

ROLE = {"client": "Office user", "staff": "Developer", "admin": "Administrator"}
ABOUT = "Phaneris scores inventions and shows the evidence behind every score."


def wanted(args):
    """Whether to show the welcome: on a terminal, not for scripts, and not when the person turned it off."""
    if getattr(args, "json", False) or os.environ.get("PHANERIS_NO_WELCOME") == "1":
        return False
    return store.read_config().get("welcome", True) is not False


def turn_off():
    cfg = store.read_config()
    cfg["welcome"] = False
    store.write_config(cfg)


def facts(api):
    """Who, which office, how many disclosures, and the question allowances; each part is left out if it cannot be read."""
    from .main import disclosure_rows

    out = {}
    try:
        out["me"] = api.get("/auth/me")["user"]
    except ApiError as e:
        out["error"] = e
        return out
    try:
        offices = {w["id"]: w["name"] for w in api.get("/workspaces").get("workspaces") or []}
        out["office"] = offices.get(out["me"].get("workspace"), out["me"].get("workspace"))
    except ApiError:
        out["office"] = out["me"].get("workspace")
    try:
        out["disclosures"] = len(disclosure_rows(api.get("/console")))
    except (ApiError, KeyError):
        out["disclosures"] = None
    try:
        out["usage"] = api.get("/account/usage")
    except ApiError:
        out["usage"] = None
    return out


def greeting(f):
    """'Welcome back, Pat' and 'Aldermoor University · Office user · 3 disclosures'."""
    me = f.get("me") or {}
    first = (me.get("display_name") or me.get("username") or "").split(" ")[0]
    parts = [f.get("office"), ROLE.get(me.get("role"), me.get("role"))]
    if f.get("disclosures") is not None:
        n = f["disclosures"]
        parts.append(f"{n} disclosure{'s' if n != 1 else ''}")
    return f"Welcome back, {first}." if first else "Welcome back.", " · ".join(p for p in parts if p)


def meter(s, f, width=16):
    """One line for the questions, and the warnings (low or used up) under it."""
    u = f.get("usage")
    if not u:
        return [], []
    meters = {m["key"]: m for m in u.get("meters") or []}
    d, g = meters.get("disclosure_questions"), meters.get("graph_questions")
    if not d or not g:
        return [], []
    if d["unlimited"]:
        return [f"{s.dim('Questions')}  {s.dim('no limit (administrator)')}"], []
    balance = (u.get("bought") or {}).get("balance", 0)
    first = f"{s.dim('Questions')}  {usage_view.meter_bar(s, d, width)}  {d['remaining']} of {d['limit']} free about your disclosures"
    second = f"{' ' * (11 + width)}{g['remaining']} of {g['limit']} across the whole graph · {balance} bought"
    warnings = [w for w in (usage_view.notice(u, "disclosure"), usage_view.notice(u, "graph")) if w]
    return [first, second], warnings


def lines(s, f, window_available):
    """The welcome, as lines for a terminal."""
    if f.get("error") is not None or not f.get("me"):
        return []
    hello, about = greeting(f)
    out = [s.bold(hello) + "  " + s.dim(about)]
    bar, warnings = meter(s, f)
    out += ["  " + x for x in bar]
    out += ["  " + s.warn(w) for w in warnings]
    out.append("")
    if window_available:
        out.append("  " + s.accent("Press Enter") + " to open the Phaneris window (full screen)")
    else:
        out.append("  " + s.accent("Press Enter") + " to see how to add the Phaneris window (one command)")
    out.append(s.dim("  b line-mode bar   n don't show this again   q quit"))
    out.append("")
    out.append("  " + s.bold("Next"))
    out.append(f"  {s.accent('T-000003 SCR'.ljust(16))}open a disclosure (or type any name)")
    out.append(f"  {s.accent('/kg QUESTION'.ljust(16))}ask across the whole knowledge graph")
    out.append(f"  {s.accent('phaneris guide'.ljust(16))}everything else, in the terminal")
    return out


def signed_out_lines(s, server):
    return [s.bold("Welcome to Phaneris."), "  " + ABOUT, "", "  Sign in to get started:  " + s.accent("phaneris login"),
            s.dim(f"  ({server})")]  # fmt: skip


def one_line(f):
    """The window's greeting: 'Welcome back, Pat.  Aldermoor University · Office user · 3 disclosures'."""
    if f.get("error") is not None or not f.get("me"):
        return ""
    hello, about = greeting(f)
    return f"{hello}  {about}"
