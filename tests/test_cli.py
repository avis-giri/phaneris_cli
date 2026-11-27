"""The command line against a small fake Phaneris server (no network, no keychain)."""

import io
import json
import os
import stat
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

from phaneris_cli import main as cli
from phaneris_cli import store
from phaneris_cli.style import Style

TOKEN = "phc_" + "t" * 43
SECRET = "correct horse battery"
CONSOLE = {
    "run": {
        "ideas": {
            "g": {"id": "T-1", "title": "A test disclosure", "inst": "Test University", "patent": "123", "asof": "2010-01-01"},
            "J-1": {"id": "NEW-1", "title": "Scored live", "inst": "", "patent": "", "asof": "2026-01-01", "live": True},
            "J-2": {"id": "OPEN-1", "title": "Opened alone", "opened": True},
        },
        "ui": {"names": {"g": {"name": "Test one"}}},
        "complete": {"ideas": {"g": {"real": {"p_out": 0.05}, "complete": {"p_out": 0.07, "verdict": "Review"}}}},
    },
    "states": {},
}
SUMMARY = {
    "id": "T-1",
    "name": "Test one",
    "title": "A test disclosure",
    "institution": "Test University",
    "patent": "123",
    "as_of": "2010-01-01",
    "scored": "in the data import",
    "main_class": "A01B1/00",
    "deal_chance": {"real_data": 0.05, "range": [0.04, 0.06], "percentile": 59, "times_average": 0.96},
    "full_estimate": {"p_out": 0.07, "percentile": 67},
    "recommendation": "Review",
    "flags_raised": [],
    "gates": [{"name": "Term", "state": "clear", "why": "20 years left"}],
    "metrics": [
        {"id": "ipd", "name": "IP defensibility", "score": 0.52, "kind": "real", "middle": False, "facts_measured": 6, "facts_total": 13},
        {"id": "cp", "name": "Capital path", "score": 0.5, "kind": "inferred", "middle": True, "facts_measured": 0, "facts_total": 2},
    ],
    "facts": {"measured": 6, "total": 15},
    "not_measured": [{"metric": "Capital path", "fact": f"fact {i}", "reason": "Inferred, placeholder from the report plan"} for i in range(12)],
    "scale": "Scores run from 0 to 1; 0.5 is the middle of earlier comparable records.",
    "stages": {"leaves": {"out": 0.05, "licensed": 0.01, "spinout": 0.04, "maintained": 0.6, "inactive": 0.35}, "intervals": {}},
    "distribution": {"max": 0.15, "counts": [1, 4, 9, 6, 3, 2, 1, 0, 1, 0], "records": 27, "above": 2},
    "comparables": {
        "closest": [
            {
                "title": "An earlier record",
                "institution": "Somewhere",
                "as_of": "2004-04-19",
                "outcome": "licensed",
                "weight": 2.2,
                "text_similarity": 0.8,
            },
            {
                "title": "Another earlier record",
                "institution": "Elsewhere",
                "as_of": "1999-01-01",
                "outcome": "inactive",
                "weight": 1.1,
                "text_similarity": 0.9,
            },
        ],
        "lookalikes": {
            "fto": [{"number": "9283184", "title": "A look-alike patent", "filed": "2011-08-16", "owner": "An owner", "status": "Patented Case"}],
            "ms": [{"nct": "NCT01428492", "title": "A trial", "status": "Completed"}],
        },
    },
}
DRIVERS = {
    "id": "T-1",
    "name": "Test one",
    "available": True,
    "deal_chance": 0.05,
    "baseline": {"log_odds": -3.0, "deal_chance": 0.0474},
    "terms": [
        {"input": "ia", "label": "Inventor alignment score", "contribution": 0.2},
        {"input": "tf", "label": "Translational funding score", "contribution": -0.144},
    ],
    "check": {"model_log_odds": -2.944, "model_deal_chance": 0.05, "difference": 0.0},
    "against_middle": [{"metric": "ipd", "label": "IP defensibility", "measured": True, "log_odds_change": 0.1, "deal_chance_at_middle": 0.045}],
    "inputs_note": "The model reads its own metric scores.",
    "assumed": {
        "coefficient": 0.8,
        "note": "An assumption, not a fitted model.",
        "terms": [{"metric": "cp", "label": "Capital path", "score": 0.5, "kind": "inferred", "log_odds": 0.0}],
    },
    "missing": [{"metric": "IP defensibility", "fact": "Family size", "reason": "Patent family source not connected"}],
    "missing_note": "Facts in the four modelled metrics change the deal chance through the fitted model.",
}
TIMELINE = {
    "as_of": "2010-01-01",
    "hindsight": 2,
    "items": [
        {"date": "2008-02-01", "kind": "trial", "what": "trial NCT1 starts", "who": "", "hindsight": False},
        {"date": "2009-05-01", "kind": "patent", "what": "first application filed", "who": "", "hindsight": False},
        {"date": "2012-03-01", "kind": "patent", "what": "granted", "who": "", "hindsight": True},
        {"date": "2013-01-05", "kind": "licence", "what": "exclusive license", "who": "A LICENSEE", "hindsight": True},
    ],
}
CLASS = {
    "node": "cpc:A01B 1/00",
    "code": "A01B 1/00",
    "graph": "phaneron",
    "total_patents": 100,
    "in_force": 40,
    "active_ratio": 0.4,
    "distinct_owners": 12,
    "total_filings": 1878,
    "licences": 3,
    "filings_by_year": {"2006": 4, "2007": 9, "2008": 12, "2009": 20},
    "owners_by_year": {"2008": 5, "2009": 7},
    "top_owners": [{"owner": "AN OWNER", "patents": 5}],
    "note": "Yearly counts cover only the years the pipeline fetched for this class (2006, 2007, 2008, 2009).",
}
BOARD = {
    "office": "aldermoor",
    "disclosures": [
        {
            "id": "T-1",
            "name": "Test one",
            "deal_chance": {"real_data": 0.05},
            "recommendation": "Review",
            "flags_raised": ["Ownership"],
            "checks_raised": ["Ownership"],
            "real_share": 0.56,
            "metrics": [{"id": "ipd", "name": "IP", "score": 0.52, "kind": "real"}, {"id": "cp", "name": "CP", "score": 0.5, "kind": "inferred"}],
        }
    ],
}
MAP = {
    "graph": "phaneron",
    "center": {"id": "inv:a", "type": "inventor", "name": "Ada Shared"},
    "groups": {
        "people": {
            "one": [{"id": "inv:c", "type": "inventor", "name": "Cy Third", "relation": "co_inventor"}],
            "two": [
                {"id": "inv:b", "type": "inventor", "name": "Bo Second", "via": "pat:2", "relation": "invented_by"},
                {"id": "far:1", "type": "inventor", "name": "Far Away", "via": "pat:2", "relation": "invented_by"},
            ],
        },
        "disclosures": {"one": [{"id": "T-1", "type": "asset", "name": "Test one", "relation": "protected_by"}], "two": []},
    },
    "totals": {"people": {"one": 1, "two": 1}, "disclosures": {"one": 1, "two": 0}},
    "per_group": 12,
}


RELATED = {
    "id": "T-1", "name": "Test one", "graphs": ["demo"], "per_group": 200,
    "groups": [
        {"group": "patents", "count": 10, "records": [{"id": f"pat:{i}", "name": f"Patent {i}", "type": "patent", "graph": "demo",
                                                        "links": 1} for i in range(10)]},
        {"group": "people", "count": 1, "records": [{"id": "inv:a", "name": "Ada Shared", "type": "inventor", "graph": "demo", "links": 2}]},
        {"group": "classes", "count": 1, "records": [{"id": "cpc:A01B 1/00", "name": "A01B 1/00", "type": "cpc_class_pivot", "graph": "demo",
                                                       "links": 2}]},
    ],
}  # fmt: skip


def SUBGRAPH(center):
    """A small neighbourhood around any record, as the server's subgraph route answers."""
    kinds = {"T-1": "disclosure", "inv:a": "person", "pat:2": "patent", "cpc:A01B 1/00": "class", "pat:1": "patent"}
    ids = [center] + [i for i in ("T-1", "pat:1", "inv:a", "pat:2", "cpc:A01B 1/00") if i != center]
    nodes = [{"id": i, "kind": kinds.get(i, "patent" if i.startswith("pat:") else "other"), "label": f"Label of {i}", "degree": 2,
              "depth": 0 if i == center else 1} for i in ids]  # fmt: skip
    edges = [{"from": center, "to": i, "relation": "linked_to"} for i in ids[1:]] + [{"from": "inv:a", "to": "pat:2", "relation": "invented_by"}]
    return {"graph": "phaneron", "center": center, "depth": 1, "nodes": nodes, "edges": edges, "truncated": False, "left_out": {}, "limit": 150}


HISTORY = {
    "id": "T-1",
    "name": "Test one",
    "versions": [
        {"source": "job", "import_id": None, "job_public_id": "J-9", "pack": "p1", "scored_at": "2026-11-25T10:00:00+00:00", "deal_chance": 0.08,
         "full_estimate": 0.1, "recommendation": "Pursue", "metrics": {}, "moved": [{"what": "deal chance", "from": 0.05, "to": 0.08},
                                                                                     {"what": "ipd score", "metric": "ipd", "from": 0.5, "to": 0.7}]},
        {"source": "import", "import_id": 3, "job_public_id": None, "pack": "p1", "scored_at": "2026-10-01T10:00:00+00:00", "deal_chance": 0.05,
         "full_estimate": 0.07, "recommendation": "Review", "metrics": {}, "moved": []},
    ],
    "why": {"available": True, "log_odds_change": 0.45, "note": "Each input's push.",
            "inputs": [{"input": "ipd", "label": "IP defensibility score", "from": 0.1, "to": 0.5, "change": 0.4},
                       {"input": "mass", "label": "Share of facts found", "from": 0.0, "to": 0.05, "change": 0.05}]},
}  # fmt: skip


SUGGEST = {
    "Ada Shard": [{"id": "inv:a", "name": "Ada Shared", "kind": "person", "score": 0.95},
                  {"id": "inv:z", "name": "Ada Other", "kind": "person", "score": 0.8}],
    "US 456788": [{"id": "pat:456789", "name": "A patent", "kind": "patent", "score": 0.93}],
    "Tset one": [{"id": "T-1", "name": "Test one", "kind": "disclosure", "score": 0.9}],
}  # fmt: skip


def _account_usage():
    """What /api/account/usage answers for the fake person, from Fake.quota and Fake.graph_left."""
    q = Fake.quota
    admin = Fake.role == "admin" or q.get("unlimited")
    days = [{"date": f"2026-11-{d:02d}", "disclosure": d % 3, "graph": 1 if d % 7 == 0 else 0, "bought": 0} for d in range(1, 31)]

    def m(key, label, used, limit, window, resets=None):
        share = None if admin and key.endswith("questions") else round(used / limit, 3)
        state = "unlimited" if share is None else "empty" if used >= limit else "low" if share >= 0.8 else "ok"
        bounded = share is not None
        return {"key": key, "label": label, "used": used, "limit": limit if bounded else None, "remaining": limit - used if bounded else None,
                "unlimited": not bounded, "window": window, "resets_at": resets, "share_used": share, "state": state, "note": ""}  # fmt: skip

    lim = q.get("limit", 10)
    return {
        "plan": "Admin, no limits" if admin else ("Free plus bought questions" if q.get("credits") else "Free"),
        "admin": bool(admin),
        "meters": [
            m("disclosure_questions", "Questions about your disclosures", lim - q.get("free_left", lim), lim, "free, any 12 hours", q.get("next_at")),
            m("graph_questions", "Questions across the whole knowledge graph", 5 - Fake.graph_left, 5, "free, in total"),
            m("lookups", "Knowledge graph lookups (terminal)", 12, 300, "per hour", "2026-11-26T18:00:00+00:00"),
            m("new_disclosures", "New disclosures scored", 1, 25, "per day", "2026-11-27T09:00:00+00:00"),
        ],
        "bought": {
            "balance": q.get("credits", 0),
            "bought_total": q.get("credits", 0),
            "used": 0,
            "pack": {"questions": 100, "price_usd": 5},
            "online_payment": False,
            "history": [],
        },  # fmt: skip
        "pack_request": None,
        "history": days,
        "history_days": 30,
        "sign_in": {"idle_minutes": 2, "terminal_sign_in_days": 30},
        "rules": ["Questions about your disclosures: 10 free in any 12 hours."],
    }


class Fake(BaseHTTPRequestHandler):
    account_usage = staticmethod(_account_usage)
    log = []
    background = []
    graph_left = 4
    explore_fail = None
    approved = False
    role = "client"
    two_step = False  # the account has two-step sign-in on: password sign-in needs code 123456
    idle = False  # the server has ended the sign-in for being idle
    drivers = DRIVERS
    quota = {"unlimited": False, "kind": "disclosure", "limit": 10, "window_hours": 12, "free_left": 9, "credits": 0, "remaining": 9}

    def log_message(self, *a):
        pass

    def _send(self, status, body, ctype="application/json"):
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _authed(self):
        if Fake.idle:
            self._send(401, {"error": "Signed out after 2 minutes without use. Run phaneris login.", "code": "idle_signed_out"})
            return False
        if self.headers.get("Authorization") != f"Bearer {TOKEN}":
            self._send(401, {"error": "Sign in to continue.", "code": "signed_out"})
            return False
        return True

    def do_GET(self):  # noqa: N802
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        Fake.log.append(("GET", url.path, q))
        if self.headers.get("X-Phaneris-Background"):
            Fake.background.append(url.path)
        if url.path == "/api/health":
            return self._send(200, {"ok": True, "version": "abc1234", "idle_minutes": 2})
        if url.path == "/api/workspaces":
            return self._send(200, {"workspaces": [{"id": "aldermoor", "name": "Aldermoor", "kind": "office"}]})
        if not self._authed():
            return
        if url.path == "/api/auth/me":
            return self._send(200, {"user": {"username": "pat", "display_name": "Pat", "role": Fake.role, "workspace": "aldermoor"}})
        if url.path == "/api/console":
            return self._send(200, CONSOLE)
        if url.path == "/api/disclosures/T-1/summary":
            return self._send(200, {"summary": SUMMARY})
        if url.path == "/api/disclosures/T-1/drivers":
            return self._send(200, {"drivers": Fake.drivers})
        if url.path == "/api/board":
            return self._send(200, BOARD)
        if url.path == "/api/graph/suggest":
            found = SUGGEST.get(q["q"], [])
            if "disclosure" not in q and Fake.role != "admin":  # like the server: only your disclosures and the codes
                found = [x for x in found if x["kind"] in ("disclosure", "code")]
            return self._send(200, {"query": q["q"], "suggestions": found})
        if url.path == "/api/disclosures/T-1/related":
            return self._send(200, {"related": RELATED})
        if url.path == "/api/disclosures/T-1/history":
            return self._send(200, {"history": HISTORY})
        if url.path == "/api/disclosures/T-1/timeline":
            return self._send(200, {"timeline": {"id": "T-1", "name": "Test one", **TIMELINE}})
        if url.path in ("/api/graph/timeline", "/api/graph/class"):
            if "disclosure" not in q and Fake.role != "admin":
                return self._send(400, {"error": "Name one of your disclosures.", "code": "disclosure_required"})
            if url.path == "/api/graph/class":
                if q.get("code", "").replace(" ", "").upper() == "H01L9/99":
                    return self._send(404, {"error": "That class is not within reach of this disclosure.", "code": "out_of_reach"})
                return self._send(200, {"class": CLASS})
            return self._send(
                200, {"timeline": {"node": q["node"], "graph": "phaneron", "id": q["node"], "type": "patent", "name": "A patent", **TIMELINE}}
            )
        if url.path == "/api/graph/map":
            if "disclosure" not in q and Fake.role != "admin":
                return self._send(400, {"error": "Name one of your disclosures.", "code": "disclosure_required"})
            if q.get("node") == "far:1":
                return self._send(404, {"error": "That record is not within reach of this disclosure.", "code": "out_of_reach"})
            return self._send(200, {**MAP, "center": {**MAP["center"], "id": q.get("node", "inv:a")}})
        if url.path == "/api/account/usage":
            return self._send(200, Fake.account_usage())
        if url.path == "/api/explore/usage":
            return self._send(
                200,
                {
                    "quota": Fake.quota,
                    "graph_quota": {**Fake.quota, "kind": "graph", "limit": 5, "window_hours": None, "free_left": Fake.graph_left},
                    "pack_requested": False,
                },  # fmt: skip
            )
        if url.path == "/api/reports/Phaneris_Report_T-1.pdf":
            return self._send(200, b"%PDF-1.4 test", "application/pdf")
        if url.path == "/api/jobs/J-1/report.pdf":
            return self._send(200, b"%PDF-1.4 made", "application/pdf")
        if url.path.startswith("/api/jobs/J-9"):
            return self._send(
                200,
                {
                    "job": {
                        "id": "J-9",
                        "status": "scored",
                        "stage": "done",
                        "disclosure_id": "NEW-2",
                        "scorecard": {"leaves": {"out": 0.08}},
                        "runner_online": False,
                    }
                },
            )
        if url.path == "/api/jobs":
            return self._send(200, {"jobs": [{"id": "J-9", "disclosure_id": "NEW-2", "status": "scored", "created_at": "2026-11-24T10:00:00"}]})
        if url.path.startswith("/api/graph/"):
            if "disclosure" not in q and Fake.role != "admin":
                return self._send(400, {"error": "Name one of your disclosures.", "code": "disclosure_required"})
            if url.path == "/api/graph/search":
                hits = [{"id": "inv:a", "type": "inventor", "name": "Ada Shared", "cite": "graph:phaneron:inv:a"},
                        {"id": "inv:z", "type": "inventor", "name": "Ada Other", "cite": "graph:phaneron:inv:z"},
                        {"id": "author:ETHAN STANCLIFFE", "type": "author", "name": "ETHAN STANCLIFFE"},
                        {"id": "pat:PCTUS2023082308", "type": "patent", "name": "Ethan Stancliff patent"}]  # fmt: skip
                hits = [h for h in hits if q["q"].lower() in h["name"].lower()]
                return self._send(200, {"total": len(hits), "records": hits})
            if url.path == "/api/graph/subgraph":
                if q["node"] in ("pat:999999", "far:1"):
                    return self._send(404, {"error": "That record is not within reach of this disclosure.", "code": "out_of_reach"})
                return self._send(200, {**SUBGRAPH(q["node"]), "depth": int(q.get("depth") or 1)})  # as the server: the depth used
            if url.path == "/api/graph/record":
                if q["node"] in ("pat:999999", "pat:456788"):
                    return self._send(404, {"error": "That record is not within reach of this disclosure.", "code": "out_of_reach"})
                return self._send(
                    200,
                    {
                        "graph": "phaneron",
                        "record": {
                            "id": q["node"],
                            "type": "patent",
                            "name": "A patent",
                            "fields": {"title": "A patent"},
                            "links_out": 2,
                            "links_in": 1,
                        },
                        "claim_excerpt": "1. A method",
                    },
                )
            if url.path == "/api/graph/related":
                return self._send(
                    200,
                    {
                        "graph": "phaneron",
                        "neighbors": [{"relation": "invented_by", "direction": "out", "id": "inv:a", "type": "inventor", "name": "Ada Shared"}],
                    },
                )
        self._send(404, {"error": "Not found."})

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        Fake.log.append(("POST", self.path, body))
        if self.path == "/api/cli/login/password":
            if body.get("password") != SECRET:
                return self._send(401, {"error": "The username or password is not right."})
            if Fake.two_step and not body.get("code"):
                return self._send(401, {"error": "Enter the 6-digit code from your authenticator app.", "code": "two_step_required"})
            if Fake.two_step and body.get("code") != "123456":
                return self._send(401, {"error": "That code is not right.", "code": "two_step_invalid"})
            return self._send(200, {"status": "approved", "token": TOKEN, "workspace": body.get("workspace") or "aldermoor"})
        if self.path == "/api/cli/login/start":
            return self._send(200, {"device_code": "dev", "user_code": "ABCD-EFGH", "expires_in": 30, "interval": 0})
        if self.path == "/api/cli/login/poll":
            Fake.approved = not Fake.approved  # pending once, then approved
            return self._send(200, {"status": "approved", "token": TOKEN} if not Fake.approved else {"status": "pending"})
        if not self._authed():
            return
        if self.path == "/api/graph/subgraph":
            if "disclosure" not in body and Fake.role != "admin":
                return self._send(400, {"error": "Name one of your disclosures.", "code": "disclosure_required"})
            cited = [n.split(":", 2)[2] if n.startswith("graph:") else n for n in body["nodes"]]
            sub = SUBGRAPH(cited[0])
            return self._send(200, {**sub, "cited": cited, "not_in_reach": 0})
        if self.path == "/api/explore":
            if Fake.explore_fail:  # the server's own failures, as it sends them
                return self._send(*Fake.explore_fail)
            if body["scope"].get("kind") == "graph" and Fake.quota["remaining"] == 0:
                return self._send(429, {"error": "You have used your 5 free questions.", "code": "question_limit"})
            entities = {"graph:demo:T-1": {"name": "Test one", "type": "asset"}}
            answer = f"Answer to {body['question']} [graph:demo:T-1]."
            if body["scope"].get("kind") == "graph":  # also a record outside the person's reach
                entities["graph:phaneron:pat:999999"] = {"name": "Far patent", "type": "patent", "assignee": "SOMEONE ELSE"}
                answer += " [graph:phaneron:pat:999999]"
            return self._send(200, {"answer": answer, "quota": Fake.quota, "steps": [], "entities": entities})
        if self.path in ("/api/explore/request-pack", "/api/cli/logout"):
            return self._send(200, {"ok": True})
        if self.path == "/api/intake":
            return self._send(201, {"job": "J-9"})
        self._send(404, {"error": "Not found."})


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("PHANERIS_NO_KEYCHAIN", "1")
    for var in ("PHANERIS_TOKEN", "PHANERIS_USERNAME", "NO_COLOR"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(store, "CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(store, "CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setattr(store, "TOKEN_FILE", str(tmp_path / "token.json"))
    monkeypatch.setattr(cli.time, "sleep", lambda s: None)
    monkeypatch.setattr(cli.webbrowser, "open", lambda url: None)
    Fake.log, Fake.approved, Fake.role, Fake.drivers, Fake.graph_left, Fake.explore_fail = [], False, "client", DRIVERS, 4, None
    Fake.background, Fake.two_step, Fake.idle = [], False, False
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", tmp_path
    httpd.shutdown()


def run(capsys, *args):
    cli.main(list(args))
    return capsys.readouterr().out


def failed(capsys, *args):
    with pytest.raises(SystemExit) as e:
        cli.main(list(args))
    assert e.value.code != 0
    return capsys.readouterr().err


def signed(server, capsys, monkeypatch):
    url, _ = server
    monkeypatch.setattr("sys.stdin", io.StringIO(SECRET + "\n"))
    run(capsys, "--server", url, "login", "--username", "pat", "--password-stdin")
    return url


# ------------------------------------------------------------ sign-in


def test_password_sign_in_from_stdin_keeps_a_private_file(server, capsys, monkeypatch):
    url, tmp = server
    monkeypatch.setattr("sys.stdin", io.StringIO(SECRET + "\n"))
    out = run(capsys, "--server", url, "login", "--username", "pat", "--password-stdin")
    assert "Signed in as Pat" in out and "only your account can read" in out and "\033" not in out
    sent = [x for x in Fake.log if x[1] == "/api/cli/login/password"][-1][2]
    assert sent["username"] == "pat" and sent["password"] == SECRET and sent["workspace"] is None
    assert stat.S_IMODE(os.stat(tmp / "token.json").st_mode) == 0o600
    assert SECRET not in (tmp / "token.json").read_text() and SECRET not in (tmp / "config.json").read_text()


def test_the_password_is_never_an_argument(server, capsys):
    url, _ = server
    with pytest.raises(SystemExit):
        cli.main(["--server", url, "login", "--username", "pat", "--password", SECRET])
    assert "unrecognized arguments" in capsys.readouterr().err


def test_password_sign_in_without_a_terminal_points_to_the_options(server, capsys, monkeypatch):
    url, _ = server
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    err = failed(capsys, "--server", url, "login", "--username", "pat")
    assert "--password-stdin" in err and "--browser" in err


def test_wrong_password_is_a_clear_error(server, capsys, monkeypatch):
    url, _ = server
    monkeypatch.setattr("sys.stdin", io.StringIO("nope\n"))
    assert "not right" in failed(capsys, "--server", url, "login", "--username", "pat", "--password-stdin")


def test_browser_approval_still_works(server, capsys):
    url, _ = server
    out = run(capsys, "--server", url, "login", "--browser", "--no-browser")
    assert "ABCD-EFGH" in out and "Signed in as Pat" in out
    assert "aldermoor" in run(capsys, "whoami")


def test_office_choice_is_sent(server, capsys, monkeypatch):
    url, _ = server
    monkeypatch.setattr("sys.stdin", io.StringIO(SECRET + "\n"))
    run(capsys, "--server", url, "login", "--username", "pat", "--password-stdin", "--office", "halden")
    assert [x for x in Fake.log if x[1] == "/api/cli/login/password"][-1][2]["workspace"] == "halden"


# ------------------------------------------------------------ reports


def test_report_shows_real_and_inferred(server, capsys, monkeypatch):
    signed(server, capsys, monkeypatch)
    out = run(capsys, "disclosures", "show", "T-1")
    assert "IP defensibility" in out and "Real" in out and "Inferred" in out and "middle (0.5)" in out
    assert "range 4.0% to 6.0%" in out and "0.5 is the middle" in out and "and 2 more" in out
    assert "and 2 more" not in run(capsys, "report", "T-1", "--all")
    data = json.loads(run(capsys, "--json", "report", "T-1"))
    assert data["metrics"][1]["kind"] == "inferred"


def test_disclosures_list_and_json(server, capsys, monkeypatch):
    signed(server, capsys, monkeypatch)
    out = run(capsys, "disclosures")
    assert "T-1" in out and "NEW-1" in out and "OPEN-1" not in out and "5.0%" in out
    assert {r["id"] for r in json.loads(run(capsys, "--json", "disclosures"))} == {"T-1", "NEW-1"}


def test_report_pdf(server, capsys, monkeypatch, tmp_path):
    signed(server, capsys, monkeypatch)
    target = tmp_path / "r.pdf"
    assert "Saved" in run(capsys, "report", "T-1", "--pdf", str(target))
    assert target.read_bytes().startswith(b"%PDF")


def test_report_pdf_of_a_live_disclosure_is_the_designed_one(server, capsys, monkeypatch, tmp_path):
    signed(server, capsys, monkeypatch)
    target = tmp_path / "live.pdf"
    assert "Saved" in run(capsys, "report", "NEW-1", "--pdf", str(target))
    assert target.read_bytes() == b"%PDF-1.4 made"


def test_score_follows_the_job(server, capsys, monkeypatch, tmp_path):
    signed(server, capsys, monkeypatch)
    f = tmp_path / "d.json"
    f.write_text(json.dumps(cli.EXAMPLE))
    assert "Scored: NEW-2, deal chance 8.0%" in run(capsys, "score", str(f))


# ------------------------------------------------------------ questions


def test_ask_strips_tags_lists_cited_records_and_remembers_the_disclosure(server, capsys, monkeypatch):
    signed(server, capsys, monkeypatch)
    out = run(capsys, "ask", "How strong?", "--disclosure", "T-1")
    assert "Answer to How strong?." in out and "[graph" not in out and "Records cited" in out and "9 of 10 free left" in out
    run(capsys, "ask", "And then?")  # the last disclosure is used again
    sent = [x for x in Fake.log if x[1] == "/api/explore"][-1][2]
    assert sent["scope"] == {"kind": "disclosure", "disclosure": "T-1"}


def test_interactive_ask_keeps_the_conversation(server, capsys, monkeypatch):
    signed(server, capsys, monkeypatch)
    answers = iter(["first question", "second question", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    run(capsys, "ask", "-i", "--disclosure", "T-1")
    calls = [x[2] for x in Fake.log if x[1] == "/api/explore"]
    assert calls[0]["history"] == [] and calls[1]["history"][0] == {"role": "user", "content": "first question"}


def test_whole_graph_limit_points_to_buy(server, capsys, monkeypatch):
    signed(server, capsys, monkeypatch)
    monkeypatch.setattr(Fake, "quota", {**Fake.quota, "remaining": 0})
    assert "phaneris buy" in failed(capsys, "ask", "Anything?", "--graph")
    assert "Requested 100 questions" in run(capsys, "buy")


# ------------------------------------------------------------ knowledge graph


def test_graph_commands_send_the_disclosure(server, capsys, monkeypatch):
    signed(server, capsys, monkeypatch)
    assert "Ada Shared" in run(capsys, "graph", "search", "Ada", "--disclosure", "T-1")
    out = run(capsys, "graph", "record", "pat:1")  # the last disclosure is used again
    assert "Claim excerpt" in out and "1. A method" in out
    assert "invented_by" in run(capsys, "graph", "related", "pat:1")
    lookups = [x for x in Fake.log if x[1].startswith("/api/graph/")]
    assert all(x[2].get("disclosure") == "T-1" for x in lookups) and lookups[1][2]["node"] == "pat:1"


def test_admins_may_look_across_the_whole_graph(server, capsys, monkeypatch):
    Fake.role = "admin"
    signed(server, capsys, monkeypatch)
    run(capsys, "graph", "search", "Ada")
    assert "disclosure" not in [x for x in Fake.log if x[1] == "/api/graph/search"][-1][2]


def test_office_users_must_name_a_disclosure(server, capsys, monkeypatch):
    signed(server, capsys, monkeypatch)
    assert "--disclosure" in failed(capsys, "graph", "search", "Ada")


# ------------------------------------------------------------ setup and output


def test_version_and_doctor(server, capsys, monkeypatch):
    url = signed(server, capsys, monkeypatch)
    assert "abc1234" in run(capsys, "version")
    checks = json.loads(run(capsys, "--json", "doctor"))
    assert {c["check"]: c["ok"] for c in checks} == {"Python": True, "Server": True, "Sign-in": True, "Kept in": True}
    assert url in run(capsys, "doctor")


def test_logout_forgets_the_sign_in(server, capsys, monkeypatch):
    url = signed(server, capsys, monkeypatch)
    assert "Signed out" in run(capsys, "logout")
    assert "phaneris login" in failed(capsys, "whoami")
    assert store.load_token(url) is None


def test_plain_http_is_refused_except_this_computer(server, capsys):
    assert "https" in failed(capsys, "--server", "http://example.com", "login", "--browser", "--no-browser")


def test_help_is_grouped_by_task(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    out = capsys.readouterr().out
    for group in ("Account", "Disclosures and reports", "Questions", "Knowledge graph (Phaneron)"):
        assert group in out


class TTY(io.StringIO):
    def isatty(self):
        return True


def test_color_only_on_a_terminal_and_never_with_no_color(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    assert Style(stream=TTY()).color and not Style(stream=io.StringIO()).color
    monkeypatch.setenv("NO_COLOR", "1")
    assert not Style(stream=TTY()).color
    assert not Style(color=False, stream=TTY()).color  # --no-color and --json


def test_the_wordmark_is_skipped_without_color_and_brief_with_it(monkeypatch):
    plain = io.StringIO()
    Style(color=False, stream=plain).wordmark()
    assert plain.getvalue() == ""
    monkeypatch.setenv("PHANERIS_NO_ANIMATION", "1")
    still = TTY()
    Style(color=True, stream=still).wordmark()
    assert "phaneris." in still.getvalue() and still.getvalue().count("\r") == 0
    monkeypatch.delenv("PHANERIS_NO_ANIMATION")
    import phaneris_cli.style as style_mod

    slept = []
    monkeypatch.setattr(style_mod.time, "sleep", lambda s: slept.append(s))
    moving = TTY()
    Style(color=True, stream=moving).wordmark()
    assert 0.3 < sum(slept) < 1.0 and "\033[?25h" in moving.getvalue()  # under a second, cursor restored


def test_json_and_no_color_print_no_escape_codes(server, capsys, monkeypatch):
    signed(server, capsys, monkeypatch)
    assert "\033" not in run(capsys, "--no-color", "disclosures", "show", "T-1")
    assert "\033" not in run(capsys, "--json", "usage")


# ------------------------------------------------------------ subjects and function codes


def test_grammar():
    from phaneris_cli.term import parse

    assert parse(["T-1", "scr"]) == ("T-1", "SCR", {})
    assert parse(["PORT"]) == ("", "PORT", {})
    assert parse(["Ada Shared", "GRF"]) == ("Ada Shared", "GRF", {})
    assert parse(['"Ada', 'Shared"', "des"]) == ("Ada Shared", "DES", {})
    assert parse(["T-1"]) == ("T-1", "DES", {"_default_code": True})  # no code given: what it is
    assert parse([]) == ("", "HELP", {"_default_code": True})
    assert parse(["T-1", "CMP", "--sort", "date"]) == ("T-1", "CMP", {"sort": "date"})
    assert parse(["T-1 scr"]) == ("T-1", "SCR", {})
    assert parse(["Ada Shared GRF"]) == ("Ada Shared", "GRF", {})


def test_scr_draws_stages_metrics_and_the_strip(server, capsys, monkeypatch):
    signed(server, capsys, monkeypatch)
    out = run(capsys, "T-1", "scr")
    for part in ("Deal chance, real data", "range 4.0% to 6.0%", "59th percentile", "2 above 15%", "Deal stages", "Spin-out", "Inactive",
                 "IP defensibility", "Real", "Inferred", "6 of 15 facts measured", "Checks: Term clear"):  # fmt: skip
        assert part in out, part
    assert json.loads(run(capsys, "--json", "T-1", "SCR"))["stages"]["leaves"]["out"] == 0.05


def test_why_shows_the_models_terms_and_says_when_it_cannot(server, capsys, monkeypatch):
    signed(server, capsys, monkeypatch)
    out = run(capsys, "T-1", "WHY")
    assert "Inventor alignment score" in out and "+0.20" in out and "Sum: -3.00 +0.06 = -2.94" in out and "stored: 5.00%" in out
    assert "If a modelled metric were the middle" in out and "not fitted" in out and "Family size" in out
    monkeypatch.setattr(Fake, "drivers", {**DRIVERS, "available": False, "why_not_available": "scored with another model"})
    out = run(capsys, "T-1", "WHY")
    assert "not shown: scored with another model" in out and "Nothing is estimated" in out and "Sum:" not in out


def test_cmp_sorts_and_lists_look_alikes(server, capsys, monkeypatch):
    signed(server, capsys, monkeypatch)
    out = run(capsys, "T-1", "CMP", "--sort", "date")
    assert out.index("Another earlier record") < out.index("An earlier record") and "licensed" in out
    assert "9283184" in out and "NCT01428492" in out and "Trial" in out


def test_grf_draws_the_neighbourhood_with_ids(server, capsys, monkeypatch):
    signed(server, capsys, monkeypatch)
    assert "around one of your disclosures" in failed(capsys, "Ada Shared", "GRF")  # office users: bounded to a disclosure
    run(capsys, "T-1", "DES")
    out = run(capsys, "Ada Shared", "GRF")
    assert "people" in out and "inv:c" in out and "inv:b" in out and "via pat:2" in out and "T-1" in out
    assert [x for x in Fake.log if x[1] == "/api/graph/map"][-1][2]["disclosure"] == "T-1"


def test_port_board(server, capsys, monkeypatch):
    signed(server, capsys, monkeypatch)
    out = run(capsys, "PORT")
    assert "Test one" in out and "5.0%" in out and "5/9" in out and out.count("Ownership") == 1
    assert "Only your office" in run(capsys, "PORT", "--all")


def test_subjects_resolve_through_the_server(server, capsys, monkeypatch):
    signed(server, capsys, monkeypatch)
    assert "Test one" in run(capsys, "US 123", "DES")  # a patent of one of my disclosures opens the disclosure (and sets the context)
    assert "A patent" in run(capsys, "US 456789", "DES")  # another patent opens its record
    assert "not within reach" in failed(capsys, "999999", "DES")
    assert "Ada Shared" in run(capsys, "Ada Shared", "DES")
    err = failed(capsys, "Ada", "DES")  # two matches and no terminal to pick on
    assert "matches 2 records" in err and "inv:a" in err and "inv:z" in err
    assert "does not apply" in failed(capsys, "Ada Shared", "SCR")


def test_go_and_help(server, capsys, monkeypatch):
    signed(server, capsys, monkeypatch)
    assert "Deal stages" in run(capsys, "go", "t-1 scr")
    out = run(capsys, "HELP")
    assert all(c in out for c in ("DES", "SCR", "WHY", "CMP", "GRF", "ASK", "PORT")) and "for a disclosure" in out
    assert "PORT" not in run(capsys, "T-1", "HELP")


def test_no_words_without_a_terminal_prints_help(capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    cli.main([])
    assert "Functions: phaneris <SUBJECT> <CODE>" in capsys.readouterr().out


def test_ask_code_opens_the_conversation(server, capsys, monkeypatch):
    signed(server, capsys, monkeypatch)
    answers = iter(["What is it?", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    run(capsys, "T-1", "ASK")
    assert [x for x in Fake.log if x[1] == "/api/explore"][-1][2]["scope"] == {"kind": "disclosure", "disclosure": "T-1"}


@pytest.mark.parametrize("cols", [60, 100, 160])
def test_screens_fit_the_terminal(server, capsys, monkeypatch, cols):
    signed(server, capsys, monkeypatch)
    run(capsys, "T-1", "DES")
    monkeypatch.setenv("COLUMNS", str(cols))
    for words in (["T-1", "SCR"], ["T-1", "WHY"], ["T-1", "CMP"], ["T-1", "DES"], ["Ada Shared", "GRF"], ["PORT"], ["HELP"]):
        out = run(capsys, *words)
        assert max(len(line) for line in out.splitlines()) <= cols, (words, cols)


def test_themes_and_no_color(server, capsys, monkeypatch):
    signed(server, capsys, monkeypatch)
    monkeypatch.setenv("COLORTERM", "truecolor")
    amber = Style(color=True, stream=TTY(), theme="amber")
    line = amber.line(amber.bold("Deal chance"))
    assert "48;2;0;0;0" in line and "255;176;0" in line  # amber on black
    assert "48;2" not in Style(color=True, stream=TTY(), theme="phaneris").line("x")
    monkeypatch.setenv("PHANERIS_THEME", "amber")
    assert Style(color=True, stream=TTY()).theme == "amber"
    monkeypatch.setenv("NO_COLOR", "1")
    assert not Style(stream=TTY()).color
    assert "\033" not in run(capsys, "--theme", "amber", "T-1", "SCR")  # not a terminal: plain text


def test_command_bar_runs_codes_and_survives_errors(server, capsys, monkeypatch):
    import argparse

    from phaneris_cli import term

    url = signed(server, capsys, monkeypatch)
    lines = iter(["?", "T-1 SCR", "Ada Shared SCR", "", "PORT"])

    def fake_input(prompt=""):
        try:
            return next(lines)
        except StopIteration:
            raise EOFError from None

    monkeypatch.setattr("builtins.input", fake_input)
    args = argparse.Namespace(server=url, json=False, no_color=True, theme=None, disclosure=None, cites=False)
    out = cli.Out(args)
    term.command_bar(term.Ctx(cli.signed_in(args), out, args))
    captured = capsys.readouterr()
    assert "Functions" in captured.out and "Deal stages" in captured.out and "Test one" in captured.out
    assert "does not apply" in captured.err  # an error is shown and the bar carries on


# ------------------------------------------------------------ command bar history and suggestions


def test_ranking_puts_frequent_and_recent_first():
    from phaneris_cli import history

    assert history.ranked(["A SCR", "B SCR", "A SCR"])[0] == "A SCR"  # used twice
    assert history.ranked(["X DES", "Y DES"])[0] == "Y DES"  # same use, newer first
    codes = ["DES", "SCR", "WHY", "CMP", "GRF", "ASK", "PORT", "HELP"]
    got = history.suggestions("T-1 ", ["T-1 WHY", "T-1 SCR", "T-1 SCR"], codes, ["T-100046"])
    assert got[:2] == ["T-1 SCR", "T-1 WHY"]  # whole lines from history first, most used first
    assert "T-1 DES" in got  # then codes for the word being typed
    assert history.suggestions("sc", [], codes, [])[0] == "SCR"
    assert history.suggestions("T-10", ["T-1 SCR"], codes, ["T-100046"]) == ["T-100046"]  # session subjects last
    assert history.suggestions("", ["a DES", "b DES", "c DES"], codes, []) == ["c DES", "b DES", "a DES"]  # empty line: last commands


def test_history_file_is_private_bounded_and_free_of_secrets(server, capsys, monkeypatch, tmp_path):
    from phaneris_cli import history

    for line in ("T-1 SCR", "phc_abcdef SCR", "my password is x", "A" * 40, "?", "  "):
        history.add(line)
    assert history.load() == ["T-1 SCR"]
    assert stat.S_IMODE(os.stat(history.path()).st_mode) == 0o600
    for i in range(510):
        history.add(f"T-{i} DES")
    assert len(history.load()) == 500 and history.load()[-1] == "T-509 DES"
    assert "empty" in run(capsys, "history", "--clear") and history.load() == []


def test_questions_in_a_conversation_are_never_kept(server, capsys, monkeypatch):
    import argparse

    from phaneris_cli import history, term

    url = signed(server, capsys, monkeypatch)
    lines = iter(["T-1 ASK", "a private question about money", "", "PORT"])

    def fake_input(prompt=""):
        try:
            return next(lines)
        except StopIteration:
            raise EOFError from None

    monkeypatch.setattr("builtins.input", fake_input)
    args = argparse.Namespace(server=url, json=False, no_color=True, theme=None, disclosure=None, cites=False)
    term.command_bar(term.Ctx(cli.signed_in(args), cli.Out(args), args))
    kept = history.load()
    assert kept == ["T-1 ASK", "PORT"] and not any("question" in x for x in kept)
    assert "a private question about money" in [x[2].get("question") for x in Fake.log if x[1] == "/api/explore"]  # it was asked


def test_the_bar_works_without_readline(server, capsys, monkeypatch):
    import argparse
    import sys

    from phaneris_cli import term

    url = signed(server, capsys, monkeypatch)
    monkeypatch.setitem(sys.modules, "readline", None)  # import readline now fails
    lines = iter(["T-1 DES"])

    def fake_input(prompt=""):
        try:
            return next(lines)
        except StopIteration:
            raise EOFError from None

    monkeypatch.setattr("builtins.input", fake_input)
    args = argparse.Namespace(server=url, json=False, no_color=True, theme=None, disclosure=None, cites=False)
    term.command_bar(term.Ctx(cli.signed_in(args), cli.Out(args), args))
    assert "Test one" in capsys.readouterr().out


def test_editor_ghost_text_tab_and_keys():
    from phaneris_cli.editor import Editor, common_prefix

    shown = []
    options = ["T-1 SCR", "T-1 SAY", "T-100046 DES"]
    ed = Editor("> ", lambda t: [o for o in options if o.lower().startswith(t.lower())], ["PORT", "T-1 WHY"], lambda g: f"<{g}>", shown.append)
    for k in "T-1 S":
        ed.key(k)
    assert ed.ghost() == "CR" and "<CR>" in shown[-1]  # the best suggestion shows after the cursor
    ed.key("\x1b[C")  # Right arrow takes it
    assert ed.buf == "T-1 SCR"
    ed.key("\x15")  # Ctrl-U clears
    for k in "T-1":
        ed.key(k)
    ed.key("\t")  # several matches: list them, best first, and grow to what they share
    assert "  T-1 SCR\r\n  T-1 SAY" in shown[-2] and ed.buf == "T-1"
    ed.key("\t")  # Tab again takes the best
    assert ed.buf == "T-1 SCR"
    assert ed.key("\r") == "T-1 SCR"
    ed2 = Editor("> ", lambda t: [], ["PORT", "T-1 WHY"], str, shown.append)
    ed2.key("\x1b[A")
    assert ed2.buf == "T-1 WHY"  # Up: the last command
    ed2.key("\x15")
    with pytest.raises(EOFError):
        ed2.key("\x04")  # Ctrl-D on an empty line leaves
    assert common_prefix(["T-1 SCR", "t-1 say"]) == "T-1 S"


def test_ghost_text_only_on_a_color_terminal(monkeypatch):
    from phaneris_cli import editor

    monkeypatch.setenv("TERM", "dumb")
    assert editor.available() is False


def test_own_draws_the_timeline_with_the_disclosure_date(server, capsys, monkeypatch):
    signed(server, capsys, monkeypatch)
    out = run(capsys, "T-1", "OWN")
    assert out.index("first application filed") < out.index("---- disclosure date 2010-01-01") < out.index("granted")
    assert "hindsight" in out and "A LICENSEE" in out and "2 of 4 records come after it" in out
    assert "A patent" in run(capsys, "US 456789", "OWN")  # a patent's own timeline, within reach of T-1
    assert json.loads(run(capsys, "--json", "T-1", "OWN"))["hindsight"] == 2


def test_cls_for_a_class_a_disclosure_and_out_of_reach(server, capsys, monkeypatch):
    signed(server, capsys, monkeypatch)
    out = run(capsys, "T-1", "CLS")  # the disclosure's main class
    assert "Class A01B 1/00" in out and "Filings by year" in out and "AN OWNER" in out and "2006" in out and "peak 20" in out
    last = [x for x in Fake.log if x[1] == "/api/graph/class"][-1][2]
    assert last["disclosure"] == "T-1" and "code" not in last  # the class it is linked to in the graph
    assert "Class A01B 1/00" in run(capsys, "A01B 1/00", "CLS")
    assert "not within reach" in failed(capsys, "H01L 9/99", "CLS")


@pytest.mark.parametrize("cols", [60, 120])
def test_own_and_cls_fit_the_terminal(server, capsys, monkeypatch, cols):
    signed(server, capsys, monkeypatch)
    run(capsys, "T-1", "DES")
    monkeypatch.setenv("COLUMNS", str(cols))
    for words in (["T-1", "OWN"], ["T-1", "CLS"]):
        out = run(capsys, *words)
        assert max(len(line) for line in out.splitlines()) <= cols, (words, cols)


def test_braille_chart_draws_dots_on_a_color_terminal():
    from phaneris_cli import draw

    rows = draw.braille_line(Style(color=True, stream=TTY()), [1, 5, 3, 9], 8, 3)
    plain = [__import__("re").sub(r"\033\[[0-9;]*m", "", r) for r in rows]
    assert len(plain) == 3 and all(len(r) == 8 for r in plain) and any(ch != "\u2800" for r in plain for ch in r)
    assert all(0x2800 <= ord(ch) <= 0x28FF for r in plain for ch in r)
    assert len(draw.braille_line(Style(color=False), [1, 2, 3], 10)) == 1  # plain: one ASCII row


def test_tui_without_the_extra_or_a_terminal_says_what_to_do(server, capsys, monkeypatch):
    signed(server, capsys, monkeypatch)
    monkeypatch.setattr(cli, "tui_available", lambda: False)
    err = failed(capsys, "tui")
    assert "optional extra" in err and "pipx inject phaneris-cli textual" in err
    monkeypatch.setattr(cli, "tui_available", lambda: True)
    assert "needs a terminal" in failed(capsys, "tui")


def test_cls_draws_no_line_across_missing_years(server, capsys, monkeypatch):
    signed(server, capsys, monkeypatch)
    monkeypatch.setitem(CLASS, "filings_by_year", {"2011": 98, "2022": 1, "2023": 1})
    run(capsys, "T-1", "DES")
    out = run(capsys, "A01B 1/00", "CLS")
    assert "2011: 98   2022: 1   2023: 1" in out and "years missing in between" in out and "peak" not in out


def posts(path):
    return [x[2] for x in Fake.log if x[0] == "POST" and x[1] == path]


def test_hist_lists_versions_and_why(server, capsys, monkeypatch):
    signed(server, capsys, monkeypatch)
    out = run(capsys, "T-1", "HIST")
    assert "2 versions kept" in out and out.index("2026-11-25") < out.index("2026-10-01")
    assert "re-score J-9" in out and "data import" in out and "      deal chance 5.0% to 8.0%\n      ipd score 0.50 to 0.70" in out
    monkeypatch.setenv("COLUMNS", "140")
    assert "re-score J-9          deal chance 5.0% to 8.0%; ipd score 0.50 to 0.70" in run(capsys, "T-1", "HIST")
    moved, HISTORY["versions"][0]["moved"] = HISTORY["versions"][0]["moved"], []
    try:
        assert "Nothing moved between the two latest versions." in run(capsys, "T-1", "HIST")
    finally:
        HISTORY["versions"][0]["moved"] = moved
    assert "first kept version" in out and "IP defensibility score" in out and "+0.40" in out and "+0.45 log-odds" in out
    assert json.loads(run(capsys, "--json", "T-1", "HIST"))["why"]["available"] is True
    assert "History" in run(capsys, "T-1", "SCR") and "5.0% on 2026-10-01 to 8.0% now, 2 versions" in run(capsys, "T-1", "SCR")
    assert "HIST" in run(capsys, "T-1", "HELP") and "HIST does not apply" in failed(capsys, "pat:1", "HIST", "--disclosure", "T-1")


@pytest.mark.parametrize("cols", [60, 120])
def test_hist_fits_the_terminal(server, capsys, monkeypatch, cols):
    signed(server, capsys, monkeypatch)
    monkeypatch.setenv("COLUMNS", str(cols))
    out = run(capsys, "T-1", "HIST")
    assert max(len(line) for line in out.splitlines()) <= cols


def terminal(monkeypatch, *answers):
    """A terminal that types the answers given."""
    monkeypatch.setattr("sys.stdin", TTY())
    monkeypatch.setattr("sys.stdout.isatty", lambda: True, raising=False)
    typed = iter(answers)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(typed))


def test_did_you_mean_lists_close_matches_without_a_terminal(server, capsys, monkeypatch):
    signed(server, capsys, monkeypatch)
    run(capsys, "T-1", "DES")  # sets the disclosure the lookups are bounded to
    err = failed(capsys, "Ada Shard", "GRF")
    assert ("No exact match for 'Ada Shard'. Did you mean: 1. Ask the whole knowledge graph about 'Ada Shard' (4 free whole-graph "
            "questions left)  2. Ada Shared (person) inv:a  3. Ada Other (person) inv:z") in err  # fmt: skip
    assert 'Ask the whole knowledge graph: phaneris ask --graph "Who or what is Ada Shard?". Or open a match: phaneris inv:a GRF' in err
    assert not posts("/api/explore")  # listed, never sent without the person choosing it
    assert [x[2] for x in Fake.log if x[1] == "/api/graph/suggest"][-1] == {"q": "Ada Shard", "disclosure": "T-1"}
    with pytest.raises(SystemExit) as e:
        cli.main(["--json", "Ada Shard", "GRF"])
    found = json.loads(capsys.readouterr().out)["suggestions"]
    assert e.value.code != 0 and found[0]["kind"] == "ask" and found[1]["id"] == "inv:a"
    assert "No exact match for 'US 456788'" in failed(capsys, "US 456788", "DES")  # a patent number a digit off
    err = failed(capsys, "Nobody Atall", "GRF")  # nothing close: asking the whole graph is the one suggestion
    assert 'Nothing named "Nobody Atall" within reach around T-1. Instead: 1. Ask the whole knowledge graph about' in err
    assert 'phaneris ask --graph "Who or what is Nobody Atall?"' in err
    cli.remember(role="admin")  # admins reach the whole graph already: nothing close is the plain error
    Fake.role = "admin"
    assert "nothing named" in failed(capsys, "Nobody Atall", "GRF")


def test_did_you_mean_picks_on_a_terminal(server, capsys, monkeypatch):
    signed(server, capsys, monkeypatch)
    run(capsys, "T-1", "DES")
    terminal(monkeypatch, "2")
    out = run(capsys, "Ada Shard", "GRF")
    assert "Did you mean:" in out and "2. Ada Shared (person) inv:a" in out and not posts("/api/explore")
    assert [x[2]["node"] for x in Fake.log if x[1] == "/api/graph/map"][-1] == "inv:a"  # the same code, on the pick
    terminal(monkeypatch, "2")
    assert "Deal stages" in run(capsys, "Tset one", "SCR")  # a disclosure's name
    terminal(monkeypatch, "1")  # the person chooses to ask the whole graph: only now is a question sent
    out = run(capsys, "Nobody Atall", "GRF")
    assert posts("/api/explore")[-1] == {"question": "Who or what is Nobody Atall?", "history": [], "scope": {"kind": "graph"}}
    assert "Answer to Who or what is Nobody Atall?" in out
    terminal(monkeypatch, "")
    assert "cancelled" in failed(capsys, "Ada Shard", "GRF")
    terminal(monkeypatch)  # the input ends (Ctrl-D): cancelled, no traceback
    monkeypatch.setattr("builtins.input", lambda prompt="": (_ for _ in ()).throw(EOFError))
    assert "cancelled" in failed(capsys, "Ada Shard", "GRF")
    assert "nothing chosen" in failed(capsys, "Ada", "DES")
    assert not [p for p in posts("/api/explore") if p["question"] != "Who or what is Nobody Atall?"]


def test_a_mistyped_code_suggests_the_code(server, capsys, monkeypatch):
    signed(server, capsys, monkeypatch)
    err = failed(capsys, "T-1", "SRC")
    assert "No exact code for 'SRC'. Did you mean: 1. SCR (scores)\nnext: Run it with the code, for example: phaneris T-1 SCR" in err
    terminal(monkeypatch, "1")
    assert "Deal stages" in run(capsys, "T-1", "SRC")
    terminal(monkeypatch, "1")
    assert "2 versions kept" in run(capsys, "T-1", "HSIT")


def test_no_disclosure_open_still_suggests_disclosures(server, capsys, monkeypatch):
    signed(server, capsys, monkeypatch)
    err = failed(capsys, "Tset one", "SCR")
    assert "2. Test one (disclosure) T-1" in err
    assert [x[2] for x in Fake.log if x[1] == "/api/graph/suggest"][-1] == {"q": "Tset one"}
    err = failed(capsys, "Ada Shard", "GRF")  # no close disclosure: asking the whole graph is offered, nothing sent
    assert "1. Ask the whole knowledge graph about 'Ada Shard'" in err and not posts("/api/explore")


def test_record_ids_with_spaces_open_and_are_quoted(server, capsys, monkeypatch):
    signed(server, capsys, monkeypatch)
    run(capsys, "T-1", "DES")
    assert "A patent" in run(capsys, "author:ETHAN STANCLIFFE", "DES")  # one quoted word on the command line
    assert [x[2]["node"] for x in Fake.log if x[1] == "/api/graph/record"][-1] == "author:ETHAN STANCLIFFE"
    run(capsys, "go", "author:ETHAN STANCLIFFE DES")  # unquoted, in one line
    assert [x[2]["node"] for x in Fake.log if x[1] == "/api/graph/record"][-1] == "author:ETHAN STANCLIFFE"
    err = failed(capsys, "Ethan", "DES")  # two matches, no terminal: the hint names a real id, quoted
    assert '"Ethan" matches 2 records' in err and 'phaneris "author:ETHAN STANCLIFFE" DES' in err and "inventor:123" not in err
    from phaneris_cli import term

    assert term.arg("author:ETHAN STANCLIFFE") == '"author:ETHAN STANCLIFFE"' and term.arg("pat:1") == "pat:1"
    assert term.is_record_id("author:ETHAN STANCLIFFE") and term.is_record_id("T-020387") and not term.is_record_id("Ethan Stancliff")
    ctx = term.Ctx(cli.signed_in(cli.global_options(["--server", server[0]])[0]), cli.Out(cli.global_options([])[0]), None)
    ctx.opts = {}
    term.resolve(ctx, "author:ETHAN STANCLIFFE")
    assert ctx.recent[0] == '"author:ETHAN STANCLIFFE"'  # Tab offers it the way the bar takes it


def test_questions_are_recognised():
    from phaneris_cli import term

    assert term.question_of("Who invented it?") == ("Who invented it?", None)
    assert term.question_of("ask who owns it") == ("who owns it", None) and term.question_of("/ask who owns it") == ("who owns it", None)
    assert term.question_of("/kg What is CAR-T?") == ("What is CAR-T?", "graph")
    assert term.question_of("ask --graph What is CAR-T") == ("What is CAR-T", "graph")
    for not_one in ("?", "? watch", "T-1 SCR", "Carl H. June GRF", "ask", ":guide"):
        assert term.question_of(not_one) is None, not_one


def test_allowances_line():
    from phaneris_cli import term

    usage = {"quota": {"free_left": 8, "limit": 10, "credits": 0}, "graph_quota": {"free_left": 4, "limit": 5, "credits": 0}}
    assert term.allowances_line(usage) == "Questions: 8 of 10 free about disclosures, 4 of 5 whole graph, 0 bought"
    assert term.allowances_line({"quota": {"unlimited": True}, "graph_quota": {"unlimited": True}}) == "Questions: no limit"


def test_news_watch_and_feed_were_removed(server, capsys, monkeypatch):
    signed(server, capsys, monkeypatch)
    for words in (("T-1", "WATCH"), ("NEWS",), ("feed",), ("watch", "add", "T-1")):
        assert "removed in 0.7.0" in failed(capsys, *words), words
    assert "WATCH" not in run(capsys, "HELP") and "NEWS" not in run(capsys, "HELP")


def test_no_words_without_the_window_opens_the_bar_with_a_hint(server, capsys, monkeypatch):
    signed(server, capsys, monkeypatch)
    monkeypatch.setenv("PHANERIS_NO_WELCOME", "1")  # straight to the bar (the welcome is tested in test_welcome.py)
    monkeypatch.setattr(cli, "tui_available", lambda: False)
    monkeypatch.setattr("sys.stdin", TTY())
    monkeypatch.setattr("sys.stdout.isatty", lambda: True, raising=False)
    from phaneris_cli import term

    monkeypatch.setattr(term, "_reader", lambda ctx: lambda prompt="": (_ for _ in ()).throw(EOFError))
    out = run(capsys)
    assert "The Phaneris window needs one extra: pipx inject phaneris-cli textual" in out and "command bar" in out


# ------------------------------------------------------------------ every way a question can fail, as an office user

FAILURES = {
    "not yours": (400, {"error": "T-1 is not one of your disclosures in this office. Questions and lookups are about one of your "
                        "disclosures, or across the whole knowledge graph.", "code": "not_your_disclosure"}),
    "graph limit": (429, {"error": "You have used your 5 free questions about the whole knowledge graph. 100 more cost $5.",
                          "code": "question_limit"}),
    "idle": (401, {"error": "You were signed out after 2 minutes without use.", "code": "idle_signed_out"}),
    "off": (503, {"error": "Questions are not switched on yet."}),
    "busy": (503, {"error": "The answer service is busy. Try again in a moment."}),
    "failed": (502, {"error": "The answer service could not answer just now."}),
}  # fmt: skip
NEXT = {"not yours": "phaneris ask --graph", "graph limit": "phaneris buy", "idle": "phaneris login", "off": "Nothing was counted",
        "busy": "Nothing was counted", "failed": "Nothing was counted"}  # fmt: skip


@pytest.mark.parametrize("case", list(FAILURES))
def test_every_question_failure_is_a_plain_message_with_the_next_step(server, capsys, monkeypatch, case):
    signed(server, capsys, monkeypatch)
    Fake.explore_fail = FAILURES[case]
    err = failed(capsys, "ask", "Who owns it?", "--disclosure", "T-1")
    assert "Traceback" not in err and FAILURES[case][1]["error"].split(".")[0] in err and NEXT[case] in err, err


def test_a_conversation_stops_when_the_sign_in_ends_and_carries_on_after_a_busy_answer(server, capsys, monkeypatch):
    signed(server, capsys, monkeypatch)
    answers = iter(["first", "second", "third", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    Fake.explore_fail = FAILURES["busy"]
    out = run(capsys, "ask", "-i", "--disclosure", "T-1")  # busy: said, and the conversation goes on
    assert out.count("The answer service is busy") == 3 and "Nothing was counted" in out
    answers = iter(["first", "second"])
    Fake.explore_fail = FAILURES["idle"]
    err = failed(capsys, "ask", "-i", "--disclosure", "T-1")
    assert "signed out" in err and "phaneris login" in err and len([x for x in Fake.log if x[1] == "/api/explore"]) == 4  # stopped


def test_asking_about_something_that_is_not_a_disclosure(server, capsys, monkeypatch):
    signed(server, capsys, monkeypatch)
    run(capsys, "T-1", "DES")  # the disclosure the person came from
    cli.main(["ask", "Who is this?", "--disclosure", "inv:a"])  # a person within its reach: asked about T-1
    assert "inv:a is not a disclosure; asking about T-1, which it is reached from" in capsys.readouterr().err
    assert posts("/api/explore")[-1]["scope"] == {"kind": "disclosure", "disclosure": "T-1"}
    n = len(posts("/api/explore"))
    err = failed(capsys, "ask", "Who is this?", "--disclosure", "pat:999999")  # out of reach, no terminal: nothing spent
    assert "pat:999999 is not one of your disclosures" in err and 'phaneris ask --graph "..."  (4 free whole-graph questions left)' in err
    assert len(posts("/api/explore")) == n
    terminal(monkeypatch, "n")
    assert "nothing was asked" in failed(capsys, "ask", "Who is this?", "--disclosure", "pat:999999") and len(posts("/api/explore")) == n
    terminal(monkeypatch, "y")  # confirmed: the whole graph
    run(capsys, "ask", "Who is this?", "--disclosure", "pat:999999")
    assert posts("/api/explore")[-1]["scope"] == {"kind": "graph"}


def test_ask_code_on_a_record_with_no_disclosure_open_spends_nothing(server, capsys, monkeypatch):
    signed(server, capsys, monkeypatch)
    cli.remember(role="admin")  # an admin may look the record up anywhere; asking still needs a scope
    Fake.role = "admin"
    err = failed(capsys, "Ada Shared", "ASK")
    assert "is not one of your disclosures" in err and "phaneris ask --graph" in err and not posts("/api/explore")


def test_questions_in_the_line_mode_bar(server, capsys, monkeypatch):
    signed(server, capsys, monkeypatch)
    from phaneris_cli import term

    lines = iter(["Who owns it?", "/kg Who owns CAR-T?", "T-1 DES", "Who owns it?", "ask what else?"])

    def read(prompt=""):
        try:
            return next(lines)
        except StopIteration:
            raise EOFError from None

    monkeypatch.setattr(term, "_reader", lambda ctx: read)
    ctx = term.Ctx(cli.signed_in(cli.global_options(["--server", server[0]])[0]), cli.Out(cli.global_options([])[0]), None)
    Fake.explore_fail = None
    term.command_bar(ctx)
    out = capsys.readouterr().out
    scopes = [p["scope"] for p in posts("/api/explore")]
    assert "No disclosure is open, so nothing was asked." in out
    assert scopes == [{"kind": "graph"}, {"kind": "disclosure", "disclosure": "T-1"}, {"kind": "disclosure", "disclosure": "T-1"}]
    from phaneris_cli import history

    assert not [h for h in history.load() if "owns" in h]  # questions are never kept


def test_rel_lists_the_related_graph_by_kind(server, capsys, monkeypatch):
    signed(server, capsys, monkeypatch)
    out = run(capsys, "T-1", "REL")
    assert "12 records within its reach" in out and "Patents (10)" in out and "People (1)" in out and "Classes (1)" in out
    assert "and 2 more: phaneris T-1 REL --all" in out and "Patent 9" not in out
    assert "Patent 9" in run(capsys, "T-1", "REL", "--all")
    assert json.loads(run(capsys, "--json", "T-1", "REL"))["groups"][0]["count"] == 10
    assert "REL does not apply" in failed(capsys, "inv:a", "REL", "--disclosure", "T-1")


def test_out_of_reach_hints_read_plainly(server, capsys, monkeypatch):
    signed(server, capsys, monkeypatch)
    run(capsys, "T-1", "DES")
    err = failed(capsys, "pat:999999", "DES")
    assert "error: pat:999999 is not within reach around T-1. Instead: 1. Ask the whole knowledge graph" in err  # the id as written
    assert 'next: Lookups reach what your disclosure connects to. Or: Ask the whole knowledge graph: phaneris ask --graph "Who or what' in err
    Fake.explore_fail = (503, {"error": "Questions are not switched on yet."})
    assert "Questions are being set up on this site; try again later." in failed(capsys, "ask", "Hi?", "--disclosure", "T-1")


def test_graph_in_line_mode_draws_and_gives_json(server, capsys, monkeypatch):
    signed(server, capsys, monkeypatch)
    out = run(capsys, "T-1", "GRAPH")
    assert "GRAPH  Test one  T-1  5 records, 5 links, one link out" in out and "disclosure 1" in out and "patent 2" in out and "--depth 2" in out
    assert [x[2] for x in Fake.log if x[1] == "/api/graph/subgraph"][-1] == {"node": "T-1", "depth": "1", "disclosure": "T-1"}
    data = json.loads(run(capsys, "--json", "inv:a", "GRAPH", "--depth", "2"))
    assert data["center"] == "inv:a" and {"nodes", "edges"} <= set(data)
    assert [x[2] for x in Fake.log if x[1] == "/api/graph/subgraph"][-1] == {"node": "inv:a", "depth": "2", "disclosure": "T-1"}  # bounded


@pytest.mark.parametrize("cols", [100, 200])
def test_graph_fits_the_terminal(server, capsys, monkeypatch, cols):
    signed(server, capsys, monkeypatch)
    monkeypatch.setenv("COLUMNS", str(cols))
    out = run(capsys, "T-1", "GRAPH")
    assert max(len(line) for line in out.splitlines()) <= cols


def test_graph_of_a_record_with_no_disclosure_open_is_refused_plainly(server, capsys, monkeypatch):
    signed(server, capsys, monkeypatch)
    err = failed(capsys, "inv:a", "GRAPH")
    assert "Traceback" not in err and "around one of your disclosures" in err
    assert not [x for x in Fake.log if x[1] == "/api/graph/subgraph"]


def test_graph_on_a_person_goes_two_links_out(server, capsys, monkeypatch):
    signed(server, capsys, monkeypatch)
    run(capsys, "T-1", "DES")
    out = run(capsys, "Ada Shared", "GRAPH")  # an inventor: two links out by default, still one lookup
    assert "two links out" in out and "One link out: phaneris inv:a GRAPH --depth 1" in out
    sent = [x[2] for x in Fake.log if x[1] == "/api/graph/subgraph"]
    assert sent[-1] == {"node": "inv:a", "depth": "2", "disclosure": "T-1"} and len(sent) == 1
    run(capsys, "Ada Shared", "GRAPH", "--depth", "1")  # asked for one: one
    assert [x[2] for x in Fake.log if x[1] == "/api/graph/subgraph"][-1]["depth"] == "1"
    run(capsys, "pat:2", "GRAPH")  # anything else: one link out
    assert [x[2] for x in Fake.log if x[1] == "/api/graph/subgraph"][-1]["depth"] == "1"
    from phaneris_cli import term

    assert term.is_person({"kind": "record", "node": "inventor:5718883-2"}) and term.is_person({"kind": "record", "node": "author:X"})
    assert not term.is_person({"kind": "disclosure", "id": "T-1"}) and not term.is_person({"kind": "record", "node": "pat:1", "type": "patent"})
