"""Subjects and function codes: `phaneris <SUBJECT> <CODE>`, `phaneris go "<SUBJECT> <CODE>"`, and the command bar.

A subject is one of your disclosures (by id, name or patent number), a patent number ("US 9415020" or 9415020), a
person or owner name in quotes, a patent class (A61K), or a record id from another screen (inventor:5718883-2). Codes
are case-insensitive. Every screen reads the same server routes as the console, under the same bounds and limits;
nothing here widens what an account can see.
"""

import json
import re
import shlex
import sys
import textwrap

from . import draw
from .api import ApiError
from .style import pct, visible_len

CODES = {
    "DES": ("What it is: the record brief", ("disclosure", "record")),
    "SCR": ("Scores: deal chance and range, percentile, deal stages, nine metrics Real or Inferred", ("disclosure",)),
    "WHY": ("What moves the score: the fitted model's terms, and the facts not found", ("disclosure",)),
    "CMP": ("Comparables: the closest earlier records and how far they got, and look-alike patents", ("disclosure",)),
    "GRF": ("The neighbourhood in Phaneron, one and two links out", ("disclosure", "record")),
    "ASK": ("Ask about it (a conversation)", ("disclosure", "record", "none")),
    "PORT": ("My office's board, ranked by deal chance", ("none",)),
    "HELP": ("What applies here", ("disclosure", "record", "none")),
}
CPC_RX = re.compile(r"^[A-HY]\d{2}[A-Z](\s?\d{1,4}/\d{1,6})?$", re.I)
PATENT_RX = re.compile(r"^(?:US)?\s*([\d,]{6,13})$", re.I)
STAGE_LABEL = {"out": "Going out", "licensed": "Licensed", "spinout": "Spin-out", "maintained": "Maintained", "inactive": "Inactive"}


class Ctx:
    """What one run of commands shares: the signed-in API, output, options, and what was looked at (in memory only)."""

    def __init__(self, api, out, args):
        self.api, self.out, self.args = api, out, args
        self.s = out.s
        self._console = None
        self.recent = []
        cfg = __import__("phaneris_cli.store", fromlist=["read_config"]).read_config()
        self.role = cfg.get("role")
        self.context = cfg.get("last_disclosure")

    def console(self):
        if self._console is None:
            self._console = self.api.get("/console")
        return self._console

    def p(self, text=""):
        """One screen line; a line wider than the terminal is wrapped (as plain text) instead of running past it."""
        if visible_len(text) > self.s.width:
            plain = re.sub(r"\033\[[0-9;?]*[A-Za-z]", "", text)
            indent = " " * (len(plain) - len(plain.lstrip(" ")))
            for part in textwrap.wrap(plain.strip(), width=self.s.width, initial_indent=indent, subsequent_indent=indent + "  ") or [""]:
                print(self.s.line(part))
            return
        print(self.s.line(text))


# ------------------------------------------------------------------ grammar and subjects


def parse(tokens):
    """(subject text, code, options) from the words after `phaneris`."""
    opts, words = {}, []
    it = iter(tokens)
    for t in it:
        if t.startswith("--"):
            key = t[2:]
            if key in ("sort", "disclosure"):
                opts[key] = next(it, "")
            else:
                opts[key] = True
        else:
            words.append(t)
    code = None
    if words and words[-1].upper() not in CODES and " " in words[-1].strip():
        head, _, tail = words[-1].strip().rpartition(" ")
        if tail.upper() in CODES:  # the whole "SUBJECT CODE" given as one quoted word
            words[-1:] = [head, tail]
    if words and words[-1].upper() in CODES:
        code = words.pop().upper()
    subject = " ".join(words).strip().strip("\"'")
    if not code:
        code = "DES" if subject else "HELP"
    return subject, code, opts


def resolve(ctx, text):
    """The subject a text names: one of your disclosures, or a knowledge graph record within reach."""
    from .main import disclosure_rows, fail, find_row, remember

    if not text:
        return {"kind": "none"}
    row = find_row(ctx.console(), text)
    if not row and re.match(r"^(US)?[\d ,]+$", text.strip(), re.I):
        number = re.sub(r"\D", "", text)
        row = next((r for r in disclosure_rows(ctx.console()) if str(r["patent"]) == number), None)
        if not row and PATENT_RX.match(number):
            return _record(ctx, f"pat:{number}", text)
    if row:
        remember(last_disclosure=row["id"])
        ctx.context = row["id"]
        subject = {"kind": "disclosure", "id": row["id"], "name": row["name"], "row": row}
        _recent(ctx, row["name"])
        _recent(ctx, row["id"])
        return subject
    if ":" in text and " " not in text:
        return _record(ctx, text, text)
    hits = _search(ctx, text)
    exact = [h for h in hits if (h.get("name") or "").lower() == text.lower() or h.get("id", "").lower() == text.lower()]
    pool = exact or hits
    if not pool:
        where = f" around {ctx.context}" if ctx.context and ctx.role != "admin" else ""
        fail(f'nothing named "{text}" within reach{where}.', "Try part of the name, or open a disclosure first: phaneris T-ID DES")
    if len(pool) == 1:
        h = pool[0]
    else:
        h = _pick(ctx, pool, text)
    _recent(ctx, h["id"])
    return {"kind": "record", "node": h["id"], "name": h.get("name") or h["id"], "type": h.get("type", "")}


def _recent(ctx, subject):
    if subject in ctx.recent:
        ctx.recent.remove(subject)
    ctx.recent.insert(0, subject)
    del ctx.recent[20:]


def _context_query(ctx, **params):
    from .main import fail

    if ctx.args and getattr(ctx.args, "disclosure", None):
        ctx.context = ctx.args.disclosure
    if ctx.role != "admin":
        if not ctx.context:
            fail("records are looked up around one of your disclosures.", "Open one first, for example: phaneris T-000003 DES")
        params["disclosure"] = ctx.context
    elif ctx.context and params.pop("_bounded", False):
        params["disclosure"] = ctx.context
    from urllib.parse import quote

    return "&".join(f"{k}={quote(str(v), safe='')}" for k, v in params.items() if not k.startswith("_"))


def _search(ctx, text):
    if CPC_RX.match(text):
        text = text.upper()
    return ctx.api.get("/graph/search?" + _context_query(ctx, q=text)).get("records") or []


def _record(ctx, node, label):
    from .main import fail

    try:
        rec = ctx.api.get("/graph/record?" + _context_query(ctx, node=node))
    except ApiError as e:
        if e.code == "out_of_reach" or e.status == 404:
            where = f" around {ctx.context}" if ctx.context and ctx.role != "admin" else ""
            fail(f"{label} is not within reach{where}.", "Lookups reach what your disclosure connects to. Ask across the graph: phaneris ask --graph")
        raise
    r = rec.get("record") or {}
    _recent(ctx, node)
    return {"kind": "record", "node": node, "name": r.get("name") or node, "type": r.get("type", ""), "data": rec}


def _pick(ctx, hits, text):
    from .main import fail

    hits = hits[:12]
    if ctx.out.as_json or not sys.stdin.isatty():
        names = "; ".join(f"{h['id']} ({h.get('name') or ''})" for h in hits[:6])
        fail(f'"{text}" matches {len(hits)} records: {names}.', "Use the record id, for example: phaneris inventor:123 DES")
    ctx.p(ctx.s.bold(f'"{text}" matches {len(hits)} records:'))
    for i, h in enumerate(hits, 1):
        ctx.p(f"  {i:>2}. {h.get('name') or h['id']}  {ctx.s.dim(h.get('type', ''))}  {ctx.s.dim(h['id'])}")
    pick = input("Number: ").strip()
    if not (pick.isdigit() and 1 <= int(pick) <= len(hits)):
        fail("nothing chosen.")
    return hits[int(pick) - 1]


# ------------------------------------------------------------------ running a code


def run(ctx, tokens):
    from .main import fail

    subject_text, code, opts = parse(tokens)
    ctx.opts = opts
    if opts.get("disclosure"):
        ctx.context = opts["disclosure"]
    if code in ("PORT",) and subject_text:
        fail(f"{code} is for your whole office; leave out the subject.", f"phaneris {code}")
    subject = resolve(ctx, subject_text) if code != "PORT" else {"kind": "none"}
    allowed = CODES[code][1]
    if subject["kind"] not in allowed:
        what = {"disclosure": "a disclosure", "record": "a knowledge graph record", "none": "no subject"}[subject["kind"]]
        fail(f"{code} does not apply to {what}.", f"See what does: phaneris {subject_text + ' ' if subject_text else ''}HELP")
    SCREENS[code](ctx, subject)


def heading(ctx, subject, code, extra=""):
    s = ctx.s
    name = subject.get("name") or ""
    ident = subject.get("id") or subject.get("node") or ""
    left = f"{s.accent(code)}  {s.bold(name)}  {s.dim(ident)}"
    if extra:
        left += "  " + s.dim(extra)
    ctx.p(left)
    ctx.p(s.rule())


# ------------------------------------------------------------------ screens


def screen_help(ctx, subject):
    s = ctx.s
    kind = subject["kind"]
    if ctx.out.as_json:
        return ctx.out.data({"subject": subject.get("id") or subject.get("node"), "codes": {c: d for c, (d, k) in CODES.items() if kind in k}})
    title = {"disclosure": f"Functions for {subject.get('name')}", "record": f"Functions for {subject.get('name')}", "none": "Functions"}[kind]
    ctx.p(s.bold(title))
    ctx.p(s.rule())
    applies = {"disclosure": "a disclosure", "record": "a record", "none": "no subject"}
    for c, (d, kinds) in CODES.items():
        if kind in kinds or kind == "none":
            code = s.accent(c.ljust(5)) if s.color else c.ljust(5)
            where = "" if kind != "none" else s.dim("   for " + ", ".join(applies[k] for k in kinds))
            ctx.p(f"  {code} {d}{where}")
    ctx.p()
    if kind == "none":
        ctx.p(s.dim('Give a subject first:  phaneris T-000003 SCR   phaneris "Carl H. June" GRF   phaneris US 8916381 DES   phaneris PORT'))
        ctx.p(s.dim('Or: phaneris go "T-000003 WHY". With no words on a terminal, phaneris opens the command bar.'))
    else:
        ident = subject.get("id") or subject.get("node")
        ctx.p(s.dim(f"For example: phaneris {ident} {'SCR' if kind == 'disclosure' else 'GRF'}"))


def screen_des(ctx, subject):
    s = ctx.s
    if subject["kind"] == "disclosure":
        summary = _summary(ctx, subject)
        if ctx.out.as_json:
            return ctx.out.data(summary)
        heading(ctx, subject, "DES", summary.get("scored") and f"scored {summary['scored']}")
        if summary.get("title"):
            for line in s.wrap(summary["title"]).splitlines():
                ctx.p(line)
        facts = [("Institution", summary.get("institution")), ("Patent", summary.get("patent") or "none recorded"), ("As of", summary.get("as_of")),
                 ("Deal chance", pct(summary["deal_chance"].get("real_data"))), ("Recommendation", summary.get("recommendation")),
                 ("Facts measured", f"{summary['facts']['measured']} of {summary['facts']['total']}")]  # fmt: skip
        for k, v in facts:
            ctx.p(f"  {s.dim(k.ljust(16))}{v or ''}")
        ctx.p()
        ctx.p(s.dim(f"Next: {subject['id']} SCR · WHY · CMP · GRF · ASK" if s.color else f"Next: {subject['id']} SCR, WHY, CMP, GRF, ASK"))
        return
    rec = subject.get("data") or ctx.api.get("/graph/record?" + _context_query(ctx, node=subject["node"]))
    if ctx.out.as_json:
        return ctx.out.data(rec)
    r = rec.get("record") or {}
    heading(ctx, subject, "DES", f"{r.get('type', '')} in {rec.get('graph', '')}")
    shown = 0
    for k, v in (r.get("fields") or {}).items():
        if k in ("type", "label") or shown >= 16:
            continue
        val = _value(v)
        if val is None:
            continue
        ctx.p(_fit(s, f"  {s.dim(k.replace('_', ' ')[:22].ljust(22))} {val}"))
        shown += 1
    if rec.get("claim_excerpt"):
        ctx.p()
        ctx.p(s.dim("First claim (excerpt):"))
        for line in s.wrap(rec["claim_excerpt"], indent="  ").splitlines():
            ctx.p(line)
    ctx.p()
    ctx.p(s.dim(f"Links: {r.get('links_out', 0)} out, {r.get('links_in', 0)} in.  Next: {subject['node']} GRF"))


def _value(v):
    """A graph field as text: {value, status} records show their value, or say they are not available."""
    if isinstance(v, dict) and "status" in v:
        if v.get("value") in (None, "", [], {}):
            return "not available" if v.get("status") == "UNAVAILABLE" else None
        v = v["value"]
    if v in (None, "", [], {}):
        return None
    if isinstance(v, list):
        return ", ".join(str(x) for x in v[:8]) + (f", and {len(v) - 8} more" if len(v) > 8 else "")
    return v if isinstance(v, str) else json.dumps(v, default=str)


def _summary(ctx, subject):
    from urllib.parse import quote

    return ctx.api.get(f"/disclosures/{quote(subject['id'], safe='')}/summary")["summary"]


def screen_scr(ctx, subject):
    s = ctx.s
    summary = _summary(ctx, subject)
    if ctx.out.as_json:
        return ctx.out.data(summary)
    heading(ctx, subject, "SCR", f"as of {summary.get('as_of')}")
    w = s.width
    d, full = summary["deal_chance"], summary["full_estimate"]
    rng = d.get("range") or [d.get("real_data"), d.get("real_data")]
    dist = summary.get("distribution")
    top = (dist or {}).get("max") or max(0.1, (rng[1] or 0) * 2)
    bar_w = max(16, min(60, w - 50))
    ctx.p(s.bold("Deal chance, real data"))
    ctx.p(
        f"  {s.bold(pct(d.get('real_data'))):<8} {draw.range_bar(s, d.get('real_data'), rng[0], rng[1], top, bar_w)}  {s.dim(f'0 to {pct(top, 0)}')}"
    )
    ctx.p(
        s.dim(
            f"  range {pct(rng[0])} to {pct(rng[1])}" + (f", {d['times_average']}× the average record" if d.get("times_average") is not None else "")
        )
    )
    if dist:
        spark, marker = draw.percentile_strip(s, dist, d.get("real_data"), d.get("percentile"), bar_w)
        records = f"{dist['records']:,} earlier records"
        if dist.get("above"):
            records += f", {dist['above']} above {pct(top, 0)}"
        ctx.p(f"  {'':8} {spark}  {s.dim(records)}")
        ctx.p(f"  {'':8} {marker}")
    ctx.p(f"  Full estimate {s.bold(pct(full.get('p_out')))}  {s.dim('adds the metrics with no history at an assumed weight')}")
    ctx.p(f"  Recommendation {s.bold(summary.get('recommendation') or 'not set')}")
    leaves = (summary.get("stages") or {}).get("leaves")
    if leaves:
        ctx.p()
        ctx.p(s.bold("Deal stages"))
        tee, last, pipe = ("├─", "└─", "│ ") if s.color else ("|-", "`-", "| ")
        not_out = 1 - (leaves.get("out") or 0)
        rows = [(tee, "Going out", leaves.get("out")), (pipe + " " + tee, "Licensed", leaves.get("licensed")),
                (pipe + " " + last, "Spin-out", leaves.get("spinout")), (last, "Not going out", not_out),
                ("   " + tee, "Maintained", leaves.get("maintained")), ("   " + last, "Inactive", leaves.get("inactive"))]  # fmt: skip
        for prefix, label, v in rows:
            dots = "." * max(2, 22 - len(prefix) - len(label))
            ctx.p(f"  {s.dim(prefix)} {label} {s.dim(dots)} {s.bold(pct(v)):>6}")
    ctx.p()
    ctx.p(s.bold("Metrics") + s.dim("   0 to 1, the middle line is 0.5"))
    name_w = max(len(m["name"]) for m in summary["metrics"])
    mbar = max(10, min(40, w - name_w - 34))
    for m in summary["metrics"]:
        kind = s.kind(m["kind"]) + " " * (9 - len("Real" if m["kind"] == "real" else "Inferred"))
        facts = f"{m['facts_measured']}/{m['facts_total']}"
        note = s.dim(" middle, nothing usable") if m.get("middle") and w >= 110 else ""
        ctx.p(f"  {m['name'].ljust(name_w)}  {draw.score_bar(s, m['score'], mbar, m['kind'])} {m['score']:.2f}  {kind}{s.dim(facts.rjust(6))}{note}")
    f = summary["facts"]
    ctx.p(s.dim(f"  {f['measured']} of {f['total']} facts measured. Solid: Real (found for this disclosure). Shaded: Inferred (a stand-in)."))
    raised = [g for g in summary.get("gates") or [] if g["state"] == "raised"] + [{"name": x, "why": ""} for x in summary.get("flags_raised") or []]
    ctx.p()
    if raised:
        ctx.p(s.bad("Flags: ") + ", ".join(g["name"] for g in raised))
    checks = ", ".join(f"{g['name']} {g['state']}" for g in summary.get("gates") or [])
    if checks:
        for line in s.wrap("Checks: " + checks).splitlines():
            ctx.p(s.dim(line))
    ctx.p(s.dim(f"Next: {subject['id']} WHY · CMP · GRF" if s.color else f"Next: {subject['id']} WHY, CMP, GRF"))


def screen_why(ctx, subject):
    from urllib.parse import quote

    s = ctx.s
    d = ctx.api.get(f"/disclosures/{quote(subject['id'], safe='')}/drivers")["drivers"]
    if ctx.out.as_json:
        return ctx.out.data(d)
    heading(ctx, subject, "WHY", f"deal chance {pct(d.get('deal_chance'))}")
    w = s.width
    if d.get("available"):
        b = d["baseline"]
        ctx.p(s.bold("What moves the deal chance") + s.dim("   the fitted model's own terms, in log-odds against an average record"))
        ctx.p(s.dim(f"  An average record in the history: {pct(b['deal_chance'])} (log-odds {b['log_odds']:+.2f})"))
        terms = d["terms"]
        scale = max(abs(t["contribution"]) for t in terms) or 1
        label_w = min(42, max(len(t["label"]) for t in terms))
        bar_w = max(12, min(40, w - label_w - 22))
        for t in terms:
            label = t["label"] if len(t["label"]) <= label_w else t["label"][: label_w - 1] + "…"
            ctx.p(f"  {label.ljust(label_w)} {draw.diverging(s, t['contribution'], scale, bar_w)} {t['contribution']:+.2f}")
        c = d["check"]
        total = b["log_odds"] + sum(t["contribution"] for t in terms)
        ctx.p(s.dim(f"  Sum: {b['log_odds']:+.2f} {sum(t['contribution'] for t in terms):+.2f} = {total:+.2f} log-odds, "
                    f"which is a deal chance of {pct(c['model_deal_chance'], 2)} (stored: {pct(d['deal_chance'], 2)})."))  # fmt: skip
        ctx.p()
        ctx.p(s.bold("If a modelled metric were the middle (0.5)"))
        for m in d["against_middle"]:
            state = "" if m["measured"] else s.dim(" (not measured now)")
            change = f"{-m['log_odds_change']:+.2f} log-odds"
            ctx.p(f"  {m['label'].ljust(24)} deal chance {pct(m['deal_chance_at_middle'], 2):>7}  {s.dim(change)}{state}")
        ctx.p(s.dim("  " + d.get("inputs_note", "")))
    else:
        ctx.p(s.warn("The model's split is not shown: ") + d.get("why_not_available", "not available"))
        ctx.p(s.dim("Nothing is estimated in its place."))
    a = d.get("assumed") or {}
    if a.get("terms"):
        ctx.p()
        ctx.p(s.bold("The full estimate's assumed part") + s.dim(f"   coefficient {a.get('coefficient')}, not fitted"))
        for t in a["terms"]:
            lo = f"{t['log_odds']:+.2f}" if t.get("log_odds") is not None else "n/a"
            pad = " " * (8 - len("Real" if t["kind"] == "real" else "Inferred"))
            ctx.p(f"  {t['label'].ljust(24)} {t['score']:.2f}  {s.kind(t['kind'])}{pad}  {s.dim(lo + ' log-odds')}")
        for line in s.wrap(a.get("note", ""), indent="  ").splitlines():
            ctx.p(s.dim(line))
    missing = d.get("missing") or []
    if missing:
        ctx.p()
        ctx.p(s.bold(f"Facts not found that would count ({len(missing)})"))
        shown = missing if ctx.opts.get("all") else missing[:12]
        for f in shown:
            for line in s.wrap(f"{f['metric']}: {f['fact']}, {f['reason']}", indent="  ").splitlines():
                ctx.p(line)
        if len(missing) > len(shown):
            ctx.p(s.dim(f"  and {len(missing) - len(shown)} more; add --all"))
        ctx.p(s.dim("  " + d.get("missing_note", "")))


def screen_cmp(ctx, subject):
    s = ctx.s
    summary = _summary(ctx, subject)
    comp = summary.get("comparables") or {}
    if ctx.out.as_json:
        return ctx.out.data(comp)
    heading(ctx, subject, "CMP", "comparables the report holds")
    rows = comp.get("closest") or []
    key = (ctx.opts.get("sort") or "weight").lower()
    keys = {
        "weight": lambda r: -(r.get("weight") or 0),
        "similarity": lambda r: -(r.get("text_similarity") or 0),
        "date": lambda r: r.get("as_of") or "",
        "outcome": lambda r: r.get("outcome") or "",
    }
    rows = sorted(rows, key=keys.get(key, keys["weight"]))
    ctx.p(
        s.bold("Closest earlier records")
        + s.dim(f"   how far each got by the disclosure date; sorted by {key} (--sort weight|similarity|date|outcome)")
    )
    if rows:

        def num(v):
            return "" if v is None else f"{v:.2f}"

        table = s.table(
            [
                [
                    r.get("title", ""),
                    r.get("institution", ""),
                    (r.get("as_of") or "")[:10],
                    r.get("outcome", ""),
                    num(r.get("weight")),
                    num(r.get("text_similarity")),
                ]
                for r in rows
            ],
            ["Record", "Institution", "As of", "How far it got", "Weight", "Text sim."],
            shrink=0,
        )
        for line in table.splitlines():
            ctx.p(line)
    else:
        ctx.p(s.dim("  none held for this disclosure"))
    for group, items in (comp.get("lookalikes") or {}).items():
        if not items:
            continue
        ctx.p()
        ctx.p(s.bold(f"Look-alikes: {group.upper()}"))
        order = [("number", "Patent"), ("nct", "Trial"), ("title", "Title"), ("filed", "Filed"), ("start", "Start"), ("owner", "Owner"),
                 ("sponsor", "Sponsor"), ("phase", "Phase"), ("status", "Status")]  # fmt: skip
        cols = [(k, h) for k, h in order if any(x.get(k) not in (None, "") for x in items)]
        keys = [k for k, _ in cols]
        cells = [[str(x.get(k) or "")[:10] if k in ("filed", "start") else str(x.get(k) or "") for k in keys] for x in items]
        table = s.table(cells, [h for _, h in cols], shrink=keys.index("title") if "title" in keys else None)
        for line in table.splitlines():
            ctx.p(line)


GROUP_ORDER = ("patents", "people", "owners", "classes", "trials", "disclosures", "other")


def screen_grf(ctx, subject):
    s = ctx.s
    node = subject.get("node") or subject["id"]
    res = ctx.api.get("/graph/map?" + _context_query(ctx, node=node, _bounded=True))
    if ctx.out.as_json:
        return ctx.out.data(res)
    center = res.get("center") or {}
    heading(ctx, subject, "GRF", f"{center.get('type', '')} in {res.get('graph', '')}")
    tee, last, pipe = ("├─", "└─", "│  ") if s.color else ("|-", "`-", "|  ")
    groups = [(g, res["groups"][g]) for g in GROUP_ORDER if g in res.get("groups", {})]
    ctx.p(s.bold(center.get("name") or node) + "  " + s.dim(node))
    for gi, (g, items) in enumerate(groups):
        end = gi == len(groups) - 1
        tot = res["totals"][g]
        counts = f"{tot['one']} linked, {tot['two']} two links out"
        ctx.p(f"{s.dim(last if end else tee)} {s.accent(g)} {s.dim(counts)}")
        branch = "   " if end else pipe
        one = items.get("one") or []
        for i, n in enumerate(one):
            mark = last if i == len(one) - 1 and not items.get("two") else tee
            line = f"{s.dim(branch + mark)} {s.bold(n['id'])}  {n.get('name') or ''}  {s.dim(n.get('relation', ''))}"
            ctx.p(_fit(s, line))
        two = items.get("two") or []
        for i, n in enumerate(two[:6]):
            mark = last if i == min(len(two), 6) - 1 else tee
            line = f"{s.dim(branch + mark)} {s.dim('··')} {n['id']}  {n.get('name') or ''}  {s.dim('via ' + n.get('via', ''))}"
            ctx.p(_fit(s, line))
        more = tot["one"] - len(one) + tot["two"] - min(len(two), 6)
        if more > 0:
            ctx.p(s.dim(f"{branch}   and {more} more"))
    ctx.p()
    ctx.p(s.dim(f"Follow any record: phaneris <record id> GRF   (one lookup each, {res.get('per_group')} shown per group)"))


def _fit(s, line):
    if visible_len(line) <= s.width:
        return line
    plain = re.sub(r"\033\[[0-9;?]*[A-Za-z]", "", line)
    return plain[: s.width - 1] + "…"


def screen_port(ctx, subject):
    s = ctx.s
    res = ctx.api.get("/board")
    if ctx.out.as_json:
        return ctx.out.data(res)
    ctx.p(f"{s.accent('PORT')}  {s.bold('Office board')}  {s.dim(res.get('office', ''))}")
    ctx.p(s.rule())
    if ctx.opts.get("all"):
        ctx.p(s.warn("Only your office: there is no board across offices yet, for any account."))
    rows = res.get("disclosures") or []
    order = ["ipd", "ms", "eq", "ia", "tf", "rp", "fto", "ta", "cp"]
    table_rows = []
    for i, r in enumerate(rows, 1):
        by = {m["id"]: m for m in r["metrics"]}
        heat = "".join(draw.heat(s, by.get(m, {}).get("score"), by.get(m, {}).get("kind")) for m in order)
        flags = ", ".join(dict.fromkeys(r.get("flags_raised", []) + r.get("checks_raised", [])))
        table_rows.append(
            [
                str(i),
                r["id"],
                r["name"],
                pct(r["deal_chance"]["real_data"]),
                r.get("recommendation") or "",
                f"{round(r['real_share'] * 9)}/9",
                heat,
                flags or "",
            ]
        )
    table = s.table(
        table_rows, ["#", "ID", "Name", "Deal", "Rec.", "Real", "ipd ms eq ia tf rp fto ta cp" if s.width >= 140 else "Metrics", "Flags"], shrink=2
    )
    for line in table.splitlines():
        ctx.p(line)
    ctx.p()
    ctx.p(s.dim("Metrics, in order ipd ms eq ia tf rp fto ta cp: darker is higher; green Real, amber Inferred."))
    ctx.p(s.dim("Open one: phaneris <ID> SCR"))


def screen_ask(ctx, subject):
    from .main import ask_loop

    if subject["kind"] == "disclosure":
        scope, about = {"kind": "disclosure", "disclosure": subject["id"]}, f"{subject['name']} ({subject['id']})"
    elif ctx.opts.get("graph"):
        scope, about = {"kind": "graph"}, "the whole knowledge graph (metered)"
    elif ctx.context:
        scope = {"kind": "disclosure", "disclosure": ctx.context}
        about = f"{subject.get('name', 'this record')}, within what {ctx.context} connects to"
    else:
        scope, about = {"kind": "graph"}, "the whole knowledge graph (metered)"
    args = ctx.args
    args.cites = getattr(args, "cites", False)
    ask_loop(ctx.api, scope, about, args, ctx.out)


SCREENS = {
    "DES": screen_des,
    "SCR": screen_scr,
    "WHY": screen_why,
    "CMP": screen_cmp,
    "GRF": screen_grf,
    "ASK": screen_ask,
    "PORT": screen_port,
    "HELP": screen_help,
}


# ------------------------------------------------------------------ the command bar


def session_subjects(ctx):
    """Subjects seen in this session: what was opened, and the office's disclosure ids and names."""
    seen = list(ctx.recent)
    try:
        from .main import disclosure_rows

        for r in disclosure_rows(ctx.console()):
            seen += [r["id"], r["name"]]
    except ApiError:
        pass
    return list(dict.fromkeys(seen))


def _reader(ctx):
    """How the bar reads a line: the suggesting editor on a color terminal, readline elsewhere, plain input last."""
    from . import editor, history

    s = ctx.s
    prompt = s.accent("phaneris› ") if s.color else "phaneris> "

    def suggest(typed):
        return history.suggestions(typed, history.load(), list(CODES), session_subjects(ctx))

    if s.color and editor.available():
        return lambda: editor.read_line(prompt, suggest, history.load(), s.dim)
    try:
        import readline
    except ImportError:
        return lambda: input(prompt)
    for line in history.load():
        readline.add_history(line)
    state = {"options": []}

    def complete(text, n):
        if n == 0:
            state["options"] = suggest(readline.get_line_buffer())
        return state["options"][n] if n < len(state["options"]) else None

    readline.set_completer(complete)
    readline.set_completer_delims("")  # complete whole lines, so "SUBJECT CODE" suggestions fit
    if "libedit" in (readline.__doc__ or ""):
        readline.parse_and_bind("bind ^I rl_complete")
    else:
        readline.parse_and_bind("tab: complete")
        if hasattr(readline, "set_completion_display_matches_hook"):  # GNU readline: list best first, not sorted

            def show(substitution, matches, longest):
                print()
                for m in state["options"]:
                    print("  " + m)
                print(prompt + readline.get_line_buffer(), end="", flush=True)

            readline.set_completion_display_matches_hook(show)
    return lambda: input(prompt)


def command_bar(ctx):
    """A line-mode prompt: type a subject and a code, Enter runs it; ? is help; Ctrl-D leaves. Tab suggests from your
    own earlier commands first (see history.py); questions typed into a conversation are never kept."""
    from . import history
    from .main import Fail, Fail_and_exit, explain

    s = ctx.s
    read = _reader(ctx)
    ctx.p(s.bold("Phaneris command bar.") + s.dim("  T-000003 SCR, then Enter. Tab suggests, ? helps, Ctrl-D leaves."))
    while True:
        try:
            line = read().strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not line:
            continue
        if line in ("?", "help", "HELP"):
            screen_help(ctx, {"kind": "none"})
            continue
        if line.lower() in ("quit", "exit"):
            return
        history.add(line)
        try:
            run(ctx, shlex.split(line))
        except Fail as f:
            Fail_and_exit(ctx.out, f, exit=False)
        except ApiError as e:
            Fail_and_exit(ctx.out, explain(e), exit=False)
        print()
