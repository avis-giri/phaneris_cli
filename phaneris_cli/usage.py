"""Your plan, limits and use, as the service reports it (/api/account/usage): the `phaneris usage` statement, the
USAGE pane in the window, and the one-line notice shown when free questions are nearly or fully used."""

import datetime
import textwrap

from .draw import sparkline


def _when(iso, now=None):
    """When a meter makes room again, said plainly in local time."""
    if not iso:
        return ""
    at = datetime.datetime.fromisoformat(iso).astimezone()
    now = now or datetime.datetime.now().astimezone()
    secs = (at - now).total_seconds()
    if secs <= 0:
        return "now"
    if secs < 3600:
        return f"in {max(1, round(secs / 60))} min"
    clock = at.strftime("%I:%M %p").lstrip("0")
    if at.date() == now.date():
        return f"at {clock}"
    if at.date() == (now + datetime.timedelta(days=1)).date():
        return f"tomorrow at {clock}"
    return at.strftime("%b %d at ") + clock


def meter_bar(s, m, width):
    """A meter as a bar of `width` cells: green while there is room, amber from 80%, red when used up."""
    if m["unlimited"]:
        return s.dim("no limit".ljust(width))
    share = m.get("share_used") or 0
    full = round(share * width)
    if not s.color:
        return ("#" * full).ljust(width, ".")
    paint = s.bad if m["state"] == "empty" else s.warn if m["state"] == "low" else s.good
    return paint("█" * full) + s.dim("░" * (width - full))


def meter_line(m):
    if m["unlimited"]:
        return "no limit"
    return f"{m['used']} of {m['limit']} used, {m['remaining']} left"


def meter_reset(m):
    when = _when(m.get("resets_at"))
    if m["unlimited"]:
        return "administrators have no limit"
    if m["key"] == "graph_questions":
        return "free ones do not renew; bought ones are used next" if m["state"] == "empty" else m["window"]
    return f"{m['window']}, next opens {when}" if when else m["window"]


def statement(s, u):
    """The full statement as lines, fitted to the terminal's width."""
    width = s.width
    bar_w = max(10, min(30, width - 50))

    def prose(text, style=None, indent="  "):
        return [(style or (lambda x: x))(indent + w) for w in textwrap.wrap(text, max(30, width - len(indent)))]

    lines = [s.rule("Usage and limits"), "", f"  Plan  {s.bold(u['plan'])}"]
    if not u["admin"]:
        b = u["bought"]
        lines += prose(f"Bought questions left: {b['balance']}  ({b['bought_total']} added in all, {b['used']} used)")
        if u.get("pack_request"):
            day = u["pack_request"]["requested_at"][:10]
            lines += prose(
                f"A pack of {b['pack']['questions']} (${b['pack']['price_usd']}) was requested on {day}; "
                "an administrator adds it until online payment opens.",
                s.dim,
            )
    lines.append("")
    for m in u["meters"]:
        lines.append(f"  {m['label']}")
        lines.append(f"    {meter_bar(s, m, bar_w)}  {meter_line(m)}")
        lines += prose(meter_reset(m), s.dim, "    ")
    days = u.get("history") or []
    totals = [d["disclosure"] + d["graph"] for d in days]
    spark_w = min(len(totals), max(10, width - 10))
    lines += ["", f"  Questions, last {u['history_days']} days   {sum(totals)} in all"]
    lines.append("    " + (sparkline(s, totals, spark_w) or s.dim("none")))
    if days:
        lines.append(s.dim(f"    {days[0]['date']}{'today'.rjust(max(5, spark_w - 10))}"))
    lines.append("")
    if not u["admin"]:
        lines += prose(f"More questions: phaneris buy  ({u['bought']['pack']['questions']} for ${u['bought']['pack']['price_usd']})", s.dim)
    lines += prose(
        f"A sign-in ends after {u['sign_in']['idle_minutes']} minutes without use; "
        f"terminal sign-ins last at most {u['sign_in']['terminal_sign_in_days']} days.",
        s.dim,
    )
    lines += prose("How limits work: phaneris guide usage, or Usage and limits in the console.", s.dim)
    return lines


def notice(u_or_quota, kind=None):
    """A one-line notice at 80% of the free questions and when they are used up, or None.

    Takes either the /api/account/usage object (uses the meter for `kind`) or an /api/explore quota."""
    if "meters" in u_or_quota:
        key = "graph_questions" if kind == "graph" else "disclosure_questions"
        m = next((x for x in u_or_quota["meters"] if x["key"] == key), None)
        balance = u_or_quota["bought"]["balance"]
        if not m or m["unlimited"]:
            return None
        state, remaining, limit = m["state"], m["remaining"], m["limit"]
    else:
        q = u_or_quota
        if q.get("unlimited"):
            return None
        key = "graph_questions" if q.get("kind") == "graph" else "disclosure_questions"
        limit, remaining, balance = q["limit"], q["free_left"], q.get("credits", 0)
        used = limit - remaining
        state = "empty" if remaining <= 0 else "low" if limit and used / limit >= 0.8 else "ok"
    what = "free whole-graph questions" if key == "graph_questions" else "free questions about your disclosures"
    if state == "empty":
        if balance > 0:
            return f"Your {what} are used; bought questions are used now ({balance} left)."
        if key == "graph_questions":
            return f"Your {what} are used and do not renew. More: phaneris buy (100 for $5)."
        return f"Your {what} are used. More: phaneris buy (100 for $5), or wait for free ones to open."
    if state == "low":
        return f"{remaining} of {limit} {what} left."
    return None
