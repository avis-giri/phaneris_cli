"""phaneris: use Phaneris from a terminal with your own account.

What you can see and do is exactly what the console allows your account: your workspace's disclosures and reports,
scoring new disclosures, and questions within your allowance. Add --json to any command for machine-readable output.
"""

import argparse
import json
import os
import re
import sys
import time
import webbrowser

from . import __version__, store
from .api import Api, ApiError

DEFAULT_SERVER = "https://www.phaneris.co"
REAL_BASIS = ("crowd", "rule", "unscored", "info")
STAGE_WIDTH = 28


# ------------------------------------------------------------------ output


class Out:
    def __init__(self, as_json):
        self.as_json = as_json

    def data(self, value, text=None):
        """Print JSON with --json, otherwise the readable text (a string or a function that prints it)."""
        if self.as_json:
            print(json.dumps(value, indent=2, default=str))
        elif callable(text):
            text()
        elif text is not None:
            print(text)


def pct(v):
    return "" if v is None else f"{v * 100:.1f}%"


def table(rows, headers):
    if not rows:
        return
    widths = [max(len(str(h)), *(len(str(r[i])) for r in rows)) for i, h in enumerate(headers)]
    print("  ".join(str(h).ljust(w) for h, w in zip(headers, widths, strict=True)).rstrip())
    print("  ".join("-" * w for w in widths))
    for r in rows:
        print("  ".join(str(c).ljust(w) for c, w in zip(r, widths, strict=True)).rstrip())


def fail(message, code=1):
    print(f"phaneris: {message}", file=sys.stderr)
    sys.exit(code)


# ------------------------------------------------------------------ setup


def server_of(args):
    return (args.server or os.environ.get("PHANERIS_URL") or store.read_config().get("server") or DEFAULT_SERVER).rstrip("/")


def check_server(server):
    if not (server.startswith("https://") or re.match(r"^http://(localhost|127\.0\.0\.1)(:\d+)?$", server)):
        fail("the server must use https (or be this computer).")


def signed_in(args):
    server = server_of(args)
    token = store.load_token(server)
    if not token:
        fail(f"not signed in to {server}. Run: phaneris login")
    return Api(server, token)


def guard(fn):
    def run(args, out):
        try:
            fn(args, out)
        except ApiError as e:
            if e.status == 401:
                fail(f"{e.message} Your sign-in may have ended; run: phaneris login")
            fail(e.message)

    return run


# ------------------------------------------------------------------ console data helpers


def console(api):
    return api.get("/console")


def disclosure_rows(data):
    run = data["run"]
    names = (run.get("ui") or {}).get("names") or {}
    complete = (run.get("complete") or {}).get("ideas") or {}
    states = data.get("states") or {}
    rows = []
    for key, idea in run["ideas"].items():
        if idea.get("opened") or states.get(idea["id"]) == "deleted":
            continue
        c = complete.get(key) or {}
        rows.append(
            {
                "key": key,
                "id": idea["id"],
                "name": (names.get(key) or {}).get("name") or idea.get("title", ""),
                "title": idea.get("title", ""),
                "institution": idea.get("inst", ""),
                "patent": idea.get("patent", ""),
                "as_of": idea.get("asof", ""),
                "deal_chance": (c.get("real") or {}).get("p_out"),
                "full_estimate": (c.get("complete") or {}).get("p_out"),
                "recommendation": (c.get("complete") or {}).get("verdict"),
                "scored_live": bool(idea.get("live")),
                "state": states.get(idea["id"], "active"),
            }
        )
    return rows


def find_row(data, ident):
    want = ident.strip().lower()
    for r in disclosure_rows(data):
        if want in (r["id"].lower(), r["key"].lower(), r["name"].lower(), str(r["patent"]).lower()):
            return r
    return None


def metric_rows(data, key):
    c = (data["run"].get("complete") or {}).get("ideas", {}).get(key) or {}
    out = []
    for m, v in (c.get("metrics") or {}).items():
        basis = v.get("basis")
        kind = "" if basis is None else ("real" if basis in REAL_BASIS else "inferred")
        out.append({"metric": m, "name": v.get("name", m), "score": v.get("score"), "kind": kind})
    return out


# ------------------------------------------------------------------ commands


@guard
def cmd_login(args, out):
    server = server_of(args)
    check_server(server)
    api = Api(server)
    name = args.name or f"{os.environ.get('USER', 'user')} on {os.uname().nodename}"[:60]
    start = api.post("/cli/login/start", {"client_name": name})
    url = f"{server}/console/cli?code={start['user_code']}"
    if not out.as_json:
        print(f"To sign in, open {url}")
        print(f"and approve the code {start['user_code']} while signed in to the console.")
        print("Waiting for approval (Ctrl-C to stop)...", flush=True)
    if not args.no_browser:
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001  a terminal without a browser still works with the printed link
            pass
    interval = max(2, int(start.get("interval", 4)))
    deadline = time.time() + int(start.get("expires_in", 600))
    while time.time() < deadline:
        time.sleep(interval)
        try:
            got = api.post("/cli/login/poll", {"device_code": start["device_code"]})
        except ApiError as e:
            fail(e.message)
        if got.get("status") == "slow_down":
            interval += 2
        elif got.get("status") == "approved":
            where = store.save_token(server, got["token"])
            cfg = store.read_config()
            cfg["server"] = server
            store.write_config(cfg)
            me = Api(server, got["token"]).get("/auth/me")["user"]
            kept = "the macOS keychain" if where == "keychain" else where
            out.data(
                {
                    "signed_in": True,
                    "server": server,
                    "user": me,
                    "kept_in": "keychain" if where == "keychain" else "file",
                },
                "\n".join(
                    [
                        f"Signed in as {me['display_name']} ({me['username']}, {me['role']}) in workspace {me['workspace']}.",
                        f"The sign-in is kept in {kept}.",
                    ]
                    + (
                        []
                        if where == "keychain"
                        else ["Note: no keychain was found, so it is in a file only your account can read. Keep this computer locked."]
                    )
                ),
            )
            return
    fail("the code expired before it was approved. Run phaneris login again.")


@guard
def cmd_logout(args, out):
    server = server_of(args)
    token = store.load_token(server)
    if token:
        try:
            Api(server, token).post("/cli/logout")
        except ApiError:
            pass  # already ended on the server; forget it here anyway
    store.delete_token(server)
    out.data({"signed_out": True, "server": server}, f"Signed out of {server}.")


@guard
def cmd_whoami(args, out):
    api = signed_in(args)
    me = api.get("/auth/me")["user"]
    out.data(
        {"server": api.server, "user": me},
        f"{me['display_name']} ({me['username']}), {me['role']}, workspace {me['workspace']}, on {api.server}",
    )


@guard
def cmd_disclosures(args, out):
    api = signed_in(args)
    data = console(api)
    if args.action == "show":
        if not args.id:
            fail("give a disclosure id: phaneris disclosures show T-000003")
        return show_disclosure(data, args.id, out)
    rows = disclosure_rows(data)
    out.data(
        rows,
        lambda: (
            table(
                [[r["id"], r["name"][:40], r["as_of"], pct(r["deal_chance"]), r["recommendation"] or ""] for r in rows],
                ["ID", "Name", "As of", "Deal chance", "Recommendation"],
            ),
            print(f"\n{len(rows)} disclosure{'s' if len(rows) != 1 else ''}. Open one with: phaneris disclosures show ID"),
        ),
    )


def show_disclosure(data, ident, out):
    r = find_row(data, ident)
    if not r:
        fail(f"no disclosure {ident} in your workspace.")
    metrics = metric_rows(data, r["key"])
    cards = ((data["run"].get("ui") or {}).get("score_cards") or {}).get(r["key"]) or []

    def text():
        print(f"{r['name']}  ({r['id']})")
        print(r["title"])
        print(f"{r['institution']}, patent {r['patent'] or 'none'}, as of {r['as_of']}")
        print()
        for c in cards:
            print(f"  {c['label']}: {c['value']}  ({c.get('sub', '')})")
        print()
        table(
            [[m["name"], "not measured" if m["score"] is None else f"{m['score']:.2f}", m["kind"]] for m in metrics],
            ["Metric", "Score", "Real or inferred"],
        )
        print("\nScores run from 0 to 1; 0.5 is the middle of earlier comparable records.")

    out.data({**r, "score_cards": cards, "metrics": metrics}, text)


@guard
def cmd_report(args, out):
    api = signed_in(args)
    data = console(api)
    r = find_row(data, args.id)
    if not r:
        fail(f"no disclosure {args.id} in your workspace.")
    if args.pdf:
        name = f"Phaneris_Report_{r['id']}.pdf"
        try:
            content, ctype = api.get(f"/reports/{name}", raw=True)
        except ApiError as e:
            if e.status == 404:
                fail(f"there is no stored PDF for {r['id']}. Open it in the console and use Save as PDF: {api.server}/console/disclosures/{r['id']}")
            raise
        if not ctype.startswith("application/pdf"):
            fail("the server did not send a PDF.")
        with open(args.pdf, "wb") as fh:
            fh.write(content)
        out.data({"saved": args.pdf, "bytes": len(content)}, f"Saved {args.pdf} ({len(content) // 1024} KB).")
        return
    show_disclosure(data, args.id, out)
    if not out.as_json:
        print(f"\nThe full eight-step report: {api.server}/console/disclosures/{r['id']}")


@guard
def cmd_score(args, out):
    api = signed_in(args)
    try:
        with open(args.file) as fh:
            body = json.load(fh)
    except (OSError, ValueError) as e:
        fail(f"could not read {args.file}: {e}")
    try:
        sub = api.post("/intake", body)
    except ApiError as e:
        if e.status == 400:
            fail(f"{e.message} Check the file against: phaneris score --example")
        raise
    job_id = sub["job"]
    if not out.as_json:
        print(f"Saved {body.get('id')}. Scoring job {job_id}.")
    job = api.get(f"/jobs/{job_id}")["job"]
    if job["status"] == "queued" and not job.get("runner_online"):
        if not out.as_json:
            print("Scoring on the site from the disclosure and the knowledge graph...")
        job = api.post(f"/jobs/{job_id}/run")["job"]
    last = None
    while job["status"] in ("queued", "running") and not args.no_follow:
        line = f"{job['stage']:<{STAGE_WIDTH}} {int((job.get('stage_progress') or 0) * 100):>3}%  about {job.get('eta_seconds', 0)} s left"
        if line != last and not out.as_json:
            print(line, flush=True)
            last = line
        time.sleep(3)
        job = api.get(f"/jobs/{job_id}")["job"]
    card = job.get("scorecard") or {}
    leaves = card.get("leaves") or {}
    out.data(
        {
            "job": job_id,
            "status": job["status"],
            "disclosure": job["disclosure_id"],
            "deal_chance": leaves.get("out"),
            "scorecard": card,
        },
        lambda: print(
            f"{job['status'].capitalize()}: {job['disclosure_id']}"
            + (f", deal chance {pct(leaves.get('out'))}" if leaves else "")
            + (f"\nSee it with: phaneris report {job['disclosure_id']}" if job["status"] == "scored" else f"\n{job.get('message') or ''}")
        ),
    )


EXAMPLE = {
    "id": "OTV-2026-001",
    "title": "A sensor that measures soil freezing from radar returns",
    "domain": "remote sensing",
    "abstract": "Describe the invention in at least forty characters: what it does, how, and why it is new.",
    "keywords": ["soil freezing", "radar"],
    "affiliations": ["Your University"],
    "patents": [],
    "publications": [],
    "grants": [],
    "clinical_trials": [],
    "inventors": [{"name": "Jane Doe", "orcid": ""}],
    "disclosure_date": "2026-01-15",
}


@guard
def cmd_ask(args, out):
    api = signed_in(args)
    if args.graph:
        scope = {"kind": "graph"}
    else:
        if not args.disclosure:
            fail("say what to ask about: --disclosure ID, or --graph for the whole knowledge graph.")
        r = find_row(console(api), args.disclosure)
        if not r:
            fail(f"no disclosure {args.disclosure} in your workspace.")
        scope = {"kind": "disclosure", "disclosure": r["id"]}
    try:
        res = api.post("/explore", {"question": args.question, "history": [], "scope": scope})
    except ApiError as e:
        if e.status == 429:
            fail(f"{e.message} Request a pack with: phaneris buy")
        raise
    q = res.get("quota") or {}
    answer = res.get("answer", "")
    if not args.cites:
        answer = re.sub(r"\s*\[[a-z]+:[^\]]+\]", "", answer)
    out.data(res, lambda: (print(answer), print(), print(quota_line(q))))


def quota_line(q):
    if not q:
        return ""
    what = "about the whole knowledge graph" if q.get("kind") == "graph" else "about your disclosures"
    if q.get("unlimited"):
        return f"Questions {what}: no limit (admin)."
    window = f" in any {q['window_hours']} hours" if q.get("window_hours") else ""
    bought = f", {q['credits']} bought" if q.get("credits") else ""
    return f"Questions {what}: {q['free_left']} of {q['limit']} free left{window}{bought}."


@guard
def cmd_usage(args, out):
    api = signed_in(args)
    u = api.get("/explore/usage")

    def text():
        print(quota_line(u.get("quota")))
        print(quota_line(u.get("graph_quota")))
        if u.get("pack_requested"):
            print("A pack of 100 questions ($5) is requested and waiting to be added.")
        elif not (u.get("quota") or {}).get("unlimited"):
            print("More questions: phaneris buy  (100 for $5)")

    out.data(u, text)


@guard
def cmd_buy(args, out):
    api = signed_in(args)
    api.post("/explore/request-pack")
    out.data(
        {"requested": True},
        "Requested 100 questions for $5. Online payment opens soon; until then an administrator adds them to your account.",
    )


@guard
def cmd_jobs(args, out):
    api = signed_in(args)
    rows = api.get("/jobs").get("jobs", [])
    out.data(
        rows,
        lambda: (
            table(
                [[j["id"], j["disclosure_id"], j["status"], (j.get("created_at") or "")[:16].replace("T", " ")] for j in rows],
                ["Job", "Disclosure", "Status", "Started"],
            )
            or (not rows and print("No scoring jobs."))
        ),
    )


# ------------------------------------------------------------------ entry


def build_parser():
    p = argparse.ArgumentParser(prog="phaneris", description=__doc__.split("\n\n")[0])
    p.add_argument("--version", action="version", version=f"phaneris {__version__}")
    p.add_argument("--server", help=f"the Phaneris site (default {DEFAULT_SERVER}, or PHANERIS_URL)")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("login", help="sign in with a code you approve in the console")
    s.add_argument("--name", help="what to call this computer in your list of sign-ins")
    s.add_argument("--no-browser", action="store_true", help="only print the link")
    s.set_defaults(fn=cmd_login)
    sub.add_parser("logout", help="end this sign-in").set_defaults(fn=cmd_logout)
    sub.add_parser("whoami", help="who you are signed in as").set_defaults(fn=cmd_whoami)

    s = sub.add_parser("disclosures", help="your workspace's disclosures")
    s.add_argument("action", nargs="?", choices=("list", "show"), default="list")
    s.add_argument("id", nargs="?")
    s.set_defaults(fn=cmd_disclosures)

    s = sub.add_parser("report", help="a disclosure's report; --pdf saves the stored PDF")
    s.add_argument("id")
    s.add_argument("--pdf", metavar="FILE")
    s.set_defaults(fn=cmd_report)

    s = sub.add_parser("score", help="enter a new disclosure from a JSON file and follow its scoring")
    s.add_argument("file", nargs="?")
    s.add_argument("--no-follow", action="store_true", help="return once it is queued")
    s.add_argument("--example", action="store_true", help="print an example file and stop")
    s.set_defaults(fn=cmd_score)

    s = sub.add_parser("ask", help="ask a question about a disclosure or the whole knowledge graph")
    s.add_argument("question")
    where = s.add_mutually_exclusive_group()
    where.add_argument("--disclosure", metavar="ID")
    where.add_argument("--graph", action="store_true", help="the whole knowledge graph (metered)")
    s.add_argument("--cites", action="store_true", help="keep the record tags after each line")
    s.set_defaults(fn=cmd_ask)

    sub.add_parser("usage", help="questions left").set_defaults(fn=cmd_usage)
    sub.add_parser("buy", help="request 100 more questions ($5)").set_defaults(fn=cmd_buy)
    sub.add_parser("jobs", help="your scoring jobs").set_defaults(fn=cmd_jobs)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    out = Out(args.json)
    if args.command == "score":
        if args.example:
            print(json.dumps(EXAMPLE, indent=2))
            return
        if not args.file:
            fail("give a JSON file: phaneris score disclosure.json  (see phaneris score --example)")
    try:
        args.fn(args, out)
    except KeyboardInterrupt:
        fail("stopped.", 130)


if __name__ == "__main__":
    main()
