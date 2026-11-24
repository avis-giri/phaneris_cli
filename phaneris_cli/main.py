"""phaneris: use Phaneris from a terminal with your own account.

What you can see and do is exactly what the console allows your account. The server decides every limit; this
program shows what it answers.
"""

import argparse
import getpass
import json
import os
import platform
import re
import sys
import time
import webbrowser
from urllib.parse import quote

from . import __version__, store
from .api import Api, ApiError
from .style import Style, pct

DEFAULT_SERVER = "https://www.phaneris.co"
STAGE_WIDTH = 28
NOT_MEASURED_SHOWN = 10

HELP = """\
Use Phaneris from a terminal with your own account.

Account
  login                 sign in with your username and password (or --browser to approve in the console)
  logout                end this sign-in
  whoami [--banner]     who you are signed in as
  version               this program's version and the server's
  doctor                check Python, the server, your sign-in and where it is kept

Disclosures and reports
  disclosures           your office's disclosures
  disclosures show ID   one disclosure's report: every score marked Real or Inferred
  report ID [--pdf F]   the same report; --pdf saves the stored PDF
  score FILE            enter a new disclosure from a JSON file and follow its scoring
  jobs                  your scoring jobs

Questions
  ask "Q" --disclosure ID   ask about one of your disclosures and what it connects to
  ask "Q" --graph           ask across the whole knowledge graph (metered)
  ask -i                    a conversation, keeping the earlier questions
  usage                     questions you have left
  buy                       request 100 more questions ($5)

Knowledge graph (Phaneron)
  graph search TEXT --disclosure ID    records around your disclosure that match
  graph record NODE --disclosure ID    one record and what it links to
  graph related NODE --disclosure ID   the records one step from it

Options for every command: --json (machine-readable), --no-color, --server URL.
Run "phaneris COMMAND --help" for a command's options. Documentation: https://www.phaneris.co/docs/terminal
"""


# ------------------------------------------------------------------ output


class Out:
    def __init__(self, args):
        self.as_json = args.json
        self.no_color = args.json or args.no_color
        self.s = Style(color=False if self.no_color else None)

    def data(self, value, text=None):
        """JSON with --json, otherwise the readable text (a string, or a function that prints it)."""
        if self.as_json:
            print(json.dumps(value, indent=2, default=str))
        elif callable(text):
            text()
        elif text is not None:
            print(text)


class Fail(Exception):
    def __init__(self, message, hint=None, code=1):
        super().__init__(message)
        self.message, self.hint, self.code = message, hint, code


def fail(message, hint=None, code=1):
    raise Fail(message, hint, code)


# ------------------------------------------------------------------ setup


def server_of(args):
    return (args.server or os.environ.get("PHANERIS_URL") or store.read_config().get("server") or DEFAULT_SERVER).rstrip("/")


def check_server(server):
    if not (server.startswith("https://") or re.match(r"^http://(localhost|127\.0\.0\.1)(:\d+)?$", server)):
        fail("the server must use https (or be this computer).", "Use --server https://...")


def signed_in(args):
    server = server_of(args)
    token = store.load_token(server)
    if not token:
        fail(f"not signed in to {server}.", "Run: phaneris login")
    return Api(server, token)


def remember(**values):
    cfg = store.read_config()
    cfg.update({k: v for k, v in values.items() if v is not None})
    store.write_config(cfg)


def api_errors(fn):
    def run(args, out):
        try:
            fn(args, out)
        except ApiError as e:
            if e.status == 0:
                fail(e.message, "Check your network, then run: phaneris doctor")
            if e.status == 401:
                fail(e.message, "Your sign-in may have ended. Run: phaneris login")
            if e.code == "browser_only":
                fail(e.message, "Open the console in a browser for this.")
            if e.code == "question_limit":
                fail(e.message, "See what is left with: phaneris usage. More: phaneris buy")
            if e.code == "lookup_limit":
                fail(e.message, "The limit resets within the hour.")
            if e.code == "disclosure_required":
                fail(e.message, "Add --disclosure ID (see: phaneris disclosures).")
            if e.code == "password_change_required":
                fail(e.message, "Sign in once at the console in a browser, choose your password, then run: phaneris login")
            fail(e.message)

    return run


# ------------------------------------------------------------------ console data


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


def resolve_disclosure(api, ident):
    r = find_row(api.get("/console"), ident)
    if not r:
        fail(f"no disclosure {ident} in your office.", "List them with: phaneris disclosures")
    remember(last_disclosure=r["id"])
    return r


# ------------------------------------------------------------------ account


@api_errors
def cmd_login(args, out):
    server = server_of(args)
    check_server(server)
    api = Api(server)
    name = args.name or f"{os.environ.get('USER') or os.environ.get('USERNAME') or 'user'} on {platform.node()}"[:60]
    if args.browser:
        token = browser_login(api, server, name, args, out)
    else:
        token = password_login(api, name, args, out)
    where = store.save_token(server, token)
    me = Api(server, token).get("/auth/me")["user"]
    remember(server=server, role=me["role"], username=me["username"])
    s = out.s

    def text():
        print()
        s.wordmark()
        print(f"Signed in as {s.bold(me['display_name'])} ({me['username']}, {me['role']}) in {s.bold(me['workspace'])}.")
        if where == "keychain":
            print(s.dim("The sign-in is kept in the macOS keychain and lasts 30 days."))
        else:
            print(s.warn("No keychain was found, so the sign-in is in a file only your account can read: " + where))

    out.data({"signed_in": True, "server": server, "user": me, "kept_in": "keychain" if where == "keychain" else "file"}, text)


def password_login(api, name, args, out):
    username = args.username or os.environ.get("PHANERIS_USERNAME")
    if args.password_stdin:
        if not username:
            fail("--password-stdin needs --username or PHANERIS_USERNAME.")
        password = sys.stdin.readline().rstrip("\r\n")
    else:
        if not sys.stdin.isatty():
            fail("no terminal to ask for the password.", "Use --password-stdin with a secrets manager, or --browser.")
        if not username:
            username = input("Username: ").strip()
        password = getpass.getpass("Password: ")
    if not username or not password:
        fail("enter your username and password.")
    office = args.office
    if office is None and sys.stdin.isatty() and not args.password_stdin and not out.as_json:
        office = choose_office(api, out)
    try:
        got = api.post("/cli/login/password", {"username": username, "password": password, "workspace": office or None, "client_name": name})
    except ApiError as e:
        if e.status == 401:
            fail(e.message, "Check the username and password. After 5 wrong tries the username waits 15 minutes.")
        if e.status == 429:
            fail(e.message)
        if e.code == "workspace_not_allowed":
            fail(e.message, "Leave out --office to use your own office.")
        raise
    finally:
        password = None  # noqa: F841  dropped as soon as it is sent
    return got["token"]


def choose_office(api, out):
    try:
        offices = [w for w in api.get("/workspaces")["workspaces"]]
    except ApiError:
        return None
    if len(offices) < 2:
        return None
    print("Office (Enter for your own):")
    for i, w in enumerate(offices, 1):
        note = "  (Phaneris staff only)" if w.get("kind") == "admin" else ""
        print(f"  {i}. {w['name']}{note}")
    pick = input("Number: ").strip()
    if pick.isdigit() and 1 <= int(pick) <= len(offices):
        return offices[int(pick) - 1]["id"]
    return None


def browser_login(api, server, name, args, out):
    start = api.post("/cli/login/start", {"client_name": name})
    url = f"{server}/console/cli?code={start['user_code']}"
    if not out.as_json:
        print(f"To sign in, open {url}")
        print(f"and approve the code {out.s.bold(start['user_code'])} while signed in to the console.")
        print("Waiting for approval (Ctrl-C to stop)...", flush=True)
    if not args.no_browser:
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001  the printed link still works
            pass
    interval = max(2, int(start.get("interval", 4)))
    deadline = time.time() + int(start.get("expires_in", 600))
    while time.time() < deadline:
        time.sleep(interval)
        got = api.post("/cli/login/poll", {"device_code": start["device_code"]})
        if got.get("status") == "slow_down":
            interval += 2
        elif got.get("status") == "approved":
            return got["token"]
    fail("the code expired before it was approved.", "Run: phaneris login --browser")


@api_errors
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


@api_errors
def cmd_whoami(args, out):
    api = signed_in(args)
    me = api.get("/auth/me")["user"]
    remember(role=me["role"], username=me["username"])
    s = out.s

    def text():
        if args.banner:
            s.wordmark()
        print(f"{s.bold(me['display_name'])} ({me['username']}), {me['role']}, office {me['workspace']}, on {api.server}")

    out.data({"server": api.server, "user": me}, text)


@api_errors
def cmd_version(args, out):
    server = server_of(args)
    try:
        health = Api(server).get("/health")
        server_version = health.get("version", "unknown")
    except ApiError as e:
        server_version = f"unreachable ({e.message})"
    out.data(
        {"client": __version__, "server": server, "server_version": server_version, "python": platform.python_version()},
        f"phaneris {__version__} (Python {platform.python_version()})\nserver {server}: {server_version}",
    )


@api_errors
def cmd_doctor(args, out):
    s = out.s
    server = server_of(args)
    checks = []

    def check(name, ok, detail, hint=None):
        checks.append({"check": name, "ok": ok, "detail": detail, **({"next": hint} if hint and not ok else {})})

    v = sys.version_info
    check("Python", v >= (3, 10), platform.python_version(), "Install Python 3.10 or newer.")
    try:
        t0 = time.time()
        health = Api(server).get("/health")
        check("Server", bool(health.get("ok")), f"{server} answered in {int((time.time() - t0) * 1000)} ms, version {health.get('version', '?')}")
    except ApiError as e:
        check("Server", False, f"{server}: {e.message}", "Check your network or --server.")
    token = store.load_token(server)
    if not token:
        check("Sign-in", False, "not signed in", "Run: phaneris login")
    else:
        try:
            me = Api(server, token).get("/auth/me")["user"]
            check("Sign-in", True, f"{me['username']} ({me['role']}) in {me['workspace']}")
        except ApiError as e:
            check("Sign-in", False, e.message, "Run: phaneris login")
    kept = store.where_kept(server)
    check(
        "Kept in",
        kept != "file-open",
        {
            "keychain": "the macOS keychain",
            "file": store.TOKEN_FILE + " (only you can read it)",
            "file-open": store.TOKEN_FILE + " can be read by others",
            "none": "nothing stored",
        }[kept],  # fmt: skip
        "Run: chmod 600 " + store.TOKEN_FILE,
    )

    def text():
        for c in checks:
            line = f"{s.mark(c['ok'])}  {c['check']:<9} {c['detail']}"
            print(line)
            if c.get("next"):
                print(f"   {s.dim('next:')} {c['next']}")

    out.data(checks, text)
    if not all(c["ok"] for c in checks if c["check"] != "Sign-in"):
        sys.exit(1)


# ------------------------------------------------------------------ disclosures and reports


@api_errors
def cmd_disclosures(args, out):
    api = signed_in(args)
    if args.action == "show":
        if not args.id:
            fail("give a disclosure id.", "Example: phaneris disclosures show T-000003")
        return show_report(api, args.id, args, out)
    rows = disclosure_rows(api.get("/console"))
    s = out.s

    def text():
        print(
            s.table(
                [[r["id"], r["name"], r["as_of"], pct(r["deal_chance"]), r["recommendation"] or ""] for r in rows],
                ["ID", "Name", "As of", "Deal chance", "Recommendation"],
            )
        )
        print(s.dim(f"\n{len(rows)} disclosure{'s' if len(rows) != 1 else ''}. Open one with: phaneris disclosures show ID"))

    out.data(rows, text)


def show_report(api, ident, args, out):
    r = resolve_disclosure(api, ident)
    summary = api.get(f"/disclosures/{quote(r['id'], safe='')}/summary")["summary"]
    s = out.s

    def text():
        print(s.bold(summary["name"]) + "  " + s.dim(summary["id"]))
        if summary.get("title") and summary["title"] != summary["name"]:
            print(s.wrap(summary["title"]))
        bits = [b for b in (summary.get("institution"), summary.get("patent") and f"patent {summary['patent']}", f"as of {summary.get('as_of')}",
                            f"scored {summary.get('scored')}") if b]  # fmt: skip
        print(s.dim(" · ".join(bits) if s.color else ", ".join(bits)))
        print()
        print(s.rule("Outlook"))
        d, f = summary["deal_chance"], summary["full_estimate"]
        rng = d.get("range") or []
        extra = []
        if len(rng) == 2:
            extra.append(f"range {pct(rng[0])} to {pct(rng[1])}")
        if d.get("percentile") is not None:
            extra.append(f"{d['percentile']:.0f}th percentile")
        if d.get("times_average") is not None:
            extra.append(f"{d['times_average']}× average")
        print(f"  {'Deal chance, real data':<26}{s.bold(pct(d.get('real_data'))):<8}  {s.dim(', '.join(extra))}")
        fe = [f"{f['percentile']:.0f}th percentile"] if f.get("percentile") is not None else []
        print(f"  {'Full estimate':<26}{s.bold(pct(f.get('p_out'))):<8}  {s.dim(', '.join(fe + ['adds the metrics with no history']))}")
        print(f"  {'Recommendation':<26}{s.bold(summary.get('recommendation') or 'not set')}")
        if summary.get("flags_raised"):
            print(f"  {'Flags raised':<26}{s.bad(', '.join(summary['flags_raised']))}")
        for g in summary.get("gates") or []:
            state = s.bad(g["state"]) if g["state"] == "raised" else g["state"]
            print(f"  {'Check: ' + g['name']:<26}{state}")
            if g.get("why"):
                print(s.dim(s.wrap(g["why"], indent=" " * 28)))
        print()
        print(s.rule("Metrics"))
        middle = "middle (0.5), nothing usable"
        rows = [[m["name"], f"{m['score']:.2f}", m["kind"], f"{m['facts_measured']} of {m['facts_total']}", middle if m.get("middle") else ""]
                for m in summary["metrics"]]  # fmt: skip
        print(s.table(rows, ["Metric", "Score", "Basis", "Facts found", "Note"], {2: lambda c: s.kind(c.strip()) + c[len(c.strip()) :]}))
        facts = summary["facts"]
        print(s.dim(f"\n{facts['measured']} of {facts['total']} facts measured for this disclosure. {summary['scale']}"))
        nm = summary.get("not_measured") or []
        if nm:
            print()
            print(s.rule(f"Not measured ({len(nm)})"))
            shown = nm if args.all else nm[:NOT_MEASURED_SHOWN]
            for x in shown:
                print(s.wrap(f"{x['metric']}: {x['fact']}, {x['reason']}", indent="  "))
            if len(nm) > len(shown):
                print(s.dim(f"  and {len(nm) - len(shown)} more; add --all to list every one"))
        print()
        print(s.dim("Real: found for this disclosure. Inferred: a stand-in where nothing usable was found; never evidence."))
        print(f"Full report: {s.accent(api.server + '/console/disclosures/' + summary['id'])}")

    out.data(summary, text)


@api_errors
def cmd_report(args, out):
    api = signed_in(args)
    if args.pdf:
        r = resolve_disclosure(api, args.id)
        name = f"Phaneris_Report_{r['id']}.pdf"
        try:
            content, ctype = api.get(f"/reports/{quote(name)}", raw=True)
        except ApiError as e:
            if e.status == 404:
                fail(
                    f"there is no stored PDF for {r['id']}.",
                    f"Open it in the console and use Save as PDF: {api.server}/console/disclosures/{r['id']}",
                )
            raise
        if not ctype.startswith("application/pdf"):
            fail("the server did not send a PDF.")
        with open(args.pdf, "wb") as fh:
            fh.write(content)
        out.data({"saved": args.pdf, "bytes": len(content)}, f"Saved {args.pdf} ({len(content) // 1024} KB).")
        return
    show_report(api, args.id, args, out)


EXAMPLE = {
    "id": "OTV-2026-001",
    "title": "A sensor that measures soil freezing from radar returns",
    "domain": "remote sensing",
    "abstract": (
        "A ground radar unit and processing method that estimate the share of frozen soil water from the change in radar backscatter between passes."
    ),
    "keywords": ["soil freezing", "radar"],
    "affiliations": ["Aldermoor University"],
    "patents": [],
    "publications": [],
    "grants": [],
    "clinical_trials": [],
    "inventors": [{"name": "Jane Doe", "orcid": ""}],
    "disclosure_date": "2026-01-15",
}


@api_errors
def cmd_score(args, out):
    api = signed_in(args)
    try:
        with open(args.file) as fh:
            body = json.load(fh)
    except (OSError, ValueError) as e:
        fail(f"could not read {args.file}: {e}", "Start from: phaneris score --example > disclosure.json")
    try:
        sub = api.post("/intake", body)
    except ApiError as e:
        if e.status == 400:
            fail(e.message, "Check the file against: phaneris score --example")
        raise
    job_id = sub["job"]
    if not out.as_json:
        print(f"Saved {body.get('id')}. Scoring job {job_id}.", flush=True)
    job = api.get(f"/jobs/{job_id}")["job"]
    if job["status"] == "queued" and not job.get("runner_online"):
        if not out.as_json:
            print("Scoring on the site from the disclosure and the knowledge graph...", flush=True)
        job = api.post(f"/jobs/{job_id}/run")["job"]
    last = None
    while job["status"] in ("queued", "running") and not args.no_follow:
        line = f"{job['stage']:<{STAGE_WIDTH}} {int((job.get('stage_progress') or 0) * 100):>3}%  about {job.get('eta_seconds', 0)} s left"
        if line != last and not out.as_json:
            print(line, flush=True)
            last = line
        time.sleep(3)
        job = api.get(f"/jobs/{job_id}")["job"]
    leaves = (job.get("scorecard") or {}).get("leaves") or {}
    if job["status"] == "scored":
        remember(last_disclosure=job["disclosure_id"])
    out.data(
        {"job": job_id, "status": job["status"], "disclosure": job["disclosure_id"], "deal_chance": leaves.get("out")},
        lambda: print(
            f"{job['status'].capitalize()}: {job['disclosure_id']}"
            + (f", deal chance {pct(leaves.get('out'))}" if leaves else "")
            + (f"\nSee the report with: phaneris report {job['disclosure_id']}" if job["status"] == "scored" else f"\n{job.get('message') or ''}")
        ),
    )


@api_errors
def cmd_jobs(args, out):
    api = signed_in(args)
    rows = api.get("/jobs").get("jobs", [])
    s = out.s

    def text():
        if not rows:
            print("No scoring jobs.")
            return
        print(s.table([[j["id"], j["disclosure_id"], j["status"], (j.get("created_at") or "")[:16].replace("T", " ")] for j in rows],
                      ["Job", "Disclosure", "Status", "Started"]))  # fmt: skip

    out.data(rows, text)


# ------------------------------------------------------------------ questions


def quota_line(q):
    if not q:
        return ""
    what = "about the whole knowledge graph" if q.get("kind") == "graph" else "about your disclosures"
    if q.get("unlimited"):
        return f"Questions {what}: no limit (admin)."
    window = f" in any {q['window_hours']} hours" if q.get("window_hours") else ""
    bought = f", {q['credits']} bought" if q.get("credits") else ""
    return f"Questions {what}: {q['free_left']} of {q['limit']} free left{window}{bought}."


def ask_scope(api, args):
    if args.graph:
        return {"kind": "graph"}, "the whole knowledge graph"
    ident = args.disclosure or store.read_config().get("last_disclosure")
    if not ident:
        fail("say what to ask about.", "Add --disclosure ID, or --graph for the whole knowledge graph.")
    r = resolve_disclosure(api, ident)
    return {"kind": "disclosure", "disclosure": r["id"]}, f"{r['name']} ({r['id']})"


def strip_cites(text):
    return re.sub(r"\s*\[(?:graph|report):[^\]]+\]", "", text)


def cited(res):
    out = []
    for cite, b in (res.get("entities") or {}).items():
        b = b or {}
        out.append({"cite": cite, "name": b.get("name") or b.get("title") or cite.split(":")[-1], "type": b.get("type") or b.get("kind") or ""})
    return out


def print_answer(res, out, keep_cites):
    s = out.s
    answer = res.get("answer", "")
    print(answer if keep_cites else strip_cites(answer))
    refs = cited(res)
    if refs:
        print()
        print(s.dim("Records cited:"))
        for c in refs[:8]:
            print(f"  {c['name']}" + (s.dim(f"  {c['type']}") if c["type"] else "") + s.dim(f"  {c['cite']}"))
        if len(refs) > 8:
            print(s.dim(f"  and {len(refs) - 8} more"))
    print()
    print(s.dim(quota_line(res.get("quota"))))


@api_errors
def cmd_ask(args, out):
    api = signed_in(args)
    scope, about = ask_scope(api, args)
    if args.interactive:
        return ask_loop(api, scope, about, args, out)
    if not args.question:
        fail("type a question.", 'Example: phaneris ask "Who are the inventors?" --disclosure T-000003')
    res = api.post("/explore", {"question": args.question, "history": [], "scope": scope})
    if out.as_json:
        out.data(res)
    else:
        print_answer(res, out, args.cites)


def ask_loop(api, scope, about, args, out):
    s = out.s
    if out.as_json:
        fail("--json does not go with -i.", "Ask one question at a time with --json.")
    print(s.bold(f"Asking about {about}.") + s.dim(" Empty line or Ctrl-D to stop; the conversation keeps your earlier questions."))
    history = []
    while True:
        try:
            q = input(s.accent("› ") if s.color else "> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not q:
            return
        try:
            res = api.post("/explore", {"question": q, "history": history[-12:], "scope": scope})
        except ApiError as e:
            if e.code == "question_limit":
                fail(e.message, "More: phaneris buy")
            print(s.bad(e.message))
            continue
        print()
        print_answer(res, out, args.cites)
        print()
        history += [{"role": "user", "content": q}, {"role": "assistant", "content": res.get("answer", "")}]


@api_errors
def cmd_usage(args, out):
    api = signed_in(args)
    u = api.get("/explore/usage")
    s = out.s

    def text():
        print(quota_line(u.get("quota")))
        print(quota_line(u.get("graph_quota")))
        if u.get("pack_requested"):
            print(s.dim("A pack of 100 questions ($5) is requested and waiting to be added."))
        elif not (u.get("quota") or {}).get("unlimited"):
            print(s.dim("More questions: phaneris buy  (100 for $5)"))

    out.data(u, text)


@api_errors
def cmd_buy(args, out):
    api = signed_in(args)
    api.post("/explore/request-pack")
    out.data({"requested": True}, "Requested 100 questions for $5. Online payment opens soon; until then an administrator adds them to your account.")


# ------------------------------------------------------------------ knowledge graph lookups


def graph_query(api, args, **params):
    """Lookups reach what a disclosure connects to. Admins may leave the disclosure out to read the whole graph."""
    ident = args.disclosure
    if not ident and store.read_config().get("role") != "admin":
        ident = store.read_config().get("last_disclosure")
        if not ident:
            fail("name one of your disclosures.", "Add --disclosure ID (see: phaneris disclosures).")
    if ident:
        params["disclosure"] = resolve_disclosure(api, ident)["id"]
    return "&".join(f"{k}={quote(str(v), safe='')}" for k, v in params.items())


@api_errors
def cmd_graph(args, out):
    api = signed_in(args)
    s = out.s
    if args.action == "search":
        res = api.get("/graph/search?" + graph_query(api, args, q=args.target))
        rows = res.get("records") or []

        def text():
            if not rows:
                print("Nothing matched within reach." + ("" if args.disclosure is None else f" Lookups reach what {args.disclosure} connects to."))
                return
            for r in rows:
                cite = r.get("cite") or ""
                graph = cite.split(":")[1] if cite.count(":") >= 2 else ""
                print(f"  {s.bold(r.get('id', ''))}  {s.dim(r.get('type', ''))}  {r.get('name') or ''}" + (s.dim(f"  in {graph}") if graph else ""))
            print(s.dim(f"\n{res.get('total', len(rows))} found. Open one with: phaneris graph record RECORD"))

        return out.data(res, text)
    if args.action == "record":
        res = api.get("/graph/record?" + graph_query(api, args, node=args.target))

        def text():
            rec = res.get("record") or {}
            print(s.bold(rec.get("name") or args.target) + "  " + s.dim(f"{rec.get('type', '')} in {res.get('graph')}"))
            print(s.rule("Fields"))
            for k, v in (rec.get("fields") or {}).items():
                val = v if isinstance(v, str) else json.dumps(v, default=str)
                print(s.wrap(f"{k}: {val[:300]}", indent="  "))
            if res.get("claim_excerpt"):
                print()
                print(s.rule("Claim excerpt"))
                print(s.wrap(res["claim_excerpt"], indent="  "))
            print(s.dim(f"\nLinks: {rec.get('links_out', 0)} out, {rec.get('links_in', 0)} in. See them with: phaneris graph related {args.target}"))

        return out.data(res, text)
    res = api.get("/graph/related?" + graph_query(api, args, node=args.target))
    rows = res.get("neighbors") or []

    def text():
        if not rows:
            print("No linked records within reach.")
            return
        for n in rows:
            arrow = "→" if n.get("direction") == "out" else "←"
            if not s.color:
                arrow = "->" if n.get("direction") == "out" else "<-"
            print(f"  {s.dim(n.get('relation', ''))} {arrow} {s.bold(n.get('id', ''))}  {s.dim(n.get('type', ''))}  {n.get('name') or ''}")

    out.data(res, text)


# ------------------------------------------------------------------ entry


class Parser(argparse.ArgumentParser):
    def format_help(self):
        return HELP if self.prog == "phaneris" else super().format_help()


def build_parser():
    p = Parser(prog="phaneris", description=__doc__.split("\n\n")[0])
    p.add_argument("--version", action="version", version=f"phaneris {__version__}")
    p.add_argument("--server", help=f"the Phaneris site (default {DEFAULT_SERVER}, or PHANERIS_URL)")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--no-color", action="store_true", help="no color or symbols")
    sub = p.add_subparsers(dest="command", required=True, parser_class=argparse.ArgumentParser)

    s = sub.add_parser("login", help="sign in")
    s.add_argument("--username", help="your username (or PHANERIS_USERNAME)")
    s.add_argument("--office", help="the office to work in (default: your own)")
    s.add_argument("--password-stdin", action="store_true", help="read the password from standard input, for scripts with a secrets manager")
    s.add_argument("--browser", action="store_true", help="approve the sign-in in the console instead of typing a password")
    s.add_argument("--no-browser", action="store_true", help="with --browser: only print the link")
    s.add_argument("--name", help="what to call this computer in your list of sign-ins")
    s.set_defaults(fn=cmd_login)
    sub.add_parser("logout", help="end this sign-in").set_defaults(fn=cmd_logout)
    s = sub.add_parser("whoami", help="who you are signed in as")
    s.add_argument("--banner", action="store_true", help="show the wordmark")
    s.set_defaults(fn=cmd_whoami)
    sub.add_parser("version", help="client and server versions").set_defaults(fn=cmd_version)
    sub.add_parser("doctor", help="check this setup").set_defaults(fn=cmd_doctor)

    s = sub.add_parser("disclosures", help="your office's disclosures")
    s.add_argument("action", nargs="?", choices=("list", "show"), default="list")
    s.add_argument("id", nargs="?")
    s.add_argument("--all", action="store_true", help="with show: list every fact not measured")
    s.set_defaults(fn=cmd_disclosures)

    s = sub.add_parser("report", help="a disclosure's report; --pdf saves the stored PDF")
    s.add_argument("id")
    s.add_argument("--pdf", metavar="FILE")
    s.add_argument("--all", action="store_true", help="list every fact not measured")
    s.set_defaults(fn=cmd_report)

    s = sub.add_parser("score", help="enter a new disclosure from a JSON file and follow its scoring")
    s.add_argument("file", nargs="?")
    s.add_argument("--no-follow", action="store_true", help="return once it is saved")
    s.add_argument("--example", action="store_true", help="print an example file and stop")
    s.set_defaults(fn=cmd_score)
    sub.add_parser("jobs", help="your scoring jobs").set_defaults(fn=cmd_jobs)

    s = sub.add_parser("ask", help="ask about a disclosure or the whole knowledge graph")
    s.add_argument("question", nargs="?")
    where = s.add_mutually_exclusive_group()
    where.add_argument("--disclosure", metavar="ID", help="one of your disclosures (default: the last one you used)")
    where.add_argument("--graph", action="store_true", help="the whole knowledge graph (metered)")
    s.add_argument("-i", "--interactive", action="store_true", help="a conversation that keeps your earlier questions")
    s.add_argument("--cites", action="store_true", help="keep the record tags in the answer")
    s.set_defaults(fn=cmd_ask)
    sub.add_parser("usage", help="questions left").set_defaults(fn=cmd_usage)
    sub.add_parser("buy", help="request 100 more questions ($5)").set_defaults(fn=cmd_buy)

    s = sub.add_parser("graph", help="look records up in the knowledge graph around your disclosure")
    s.add_argument("action", choices=("search", "record", "related"))
    s.add_argument("target", metavar="TEXT_OR_RECORD")
    s.add_argument("--disclosure", metavar="ID", help="one of your disclosures (default: the last one you used; admins may leave it out)")
    s.set_defaults(fn=cmd_graph)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    out = Out(args)
    if args.command == "score":
        if args.example:
            print(json.dumps(EXAMPLE, indent=2))
            return
        if not args.file:
            Fail_and_exit(out, Fail("give a JSON file.", "phaneris score disclosure.json (start from: phaneris score --example)"))
    if args.command == "login" and args.no_browser and not args.browser:
        args.browser = True
    try:
        args.fn(args, out)
    except Fail as f:
        Fail_and_exit(out, f)
    except KeyboardInterrupt:
        Fail_and_exit(out, Fail("stopped.", code=130))


def Fail_and_exit(out, f):  # noqa: N802
    s = Style(color=False if out.no_color else None, stream=sys.stderr)
    if out.as_json:
        print(json.dumps({"error": f.message, **({"next": f.hint} if f.hint else {})}), file=sys.stderr)
    else:
        print(f"{s.bad('error:')} {f.message}", file=sys.stderr)
        if f.hint:
            print(f"{s.dim('next:')} {f.hint}", file=sys.stderr)
    sys.exit(f.code)


if __name__ == "__main__":
    main()
