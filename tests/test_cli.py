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
}


class Fake(BaseHTTPRequestHandler):
    log = []
    approved = False
    role = "client"
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
        if self.headers.get("Authorization") != f"Bearer {TOKEN}":
            self._send(401, {"error": "Sign in to continue.", "code": "signed_out"})
            return False
        return True

    def do_GET(self):  # noqa: N802
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        Fake.log.append(("GET", url.path, q))
        if url.path == "/api/health":
            return self._send(200, {"ok": True, "version": "abc1234"})
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
        if url.path == "/api/explore/usage":
            return self._send(
                200, {"quota": Fake.quota, "graph_quota": {**Fake.quota, "kind": "graph", "limit": 5, "window_hours": None}, "pack_requested": False}
            )
        if url.path == "/api/reports/Phaneris_Report_T-1.pdf":
            return self._send(200, b"%PDF-1.4 test", "application/pdf")
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
                return self._send(
                    200, {"total": 1, "records": [{"id": "inv:a", "type": "inventor", "name": "Ada Shared", "cite": "graph:phaneron:inv:a"}]}
                )
            if url.path == "/api/graph/record":
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
            return self._send(200, {"status": "approved", "token": TOKEN, "workspace": body.get("workspace") or "aldermoor"})
        if self.path == "/api/cli/login/start":
            return self._send(200, {"device_code": "dev", "user_code": "ABCD-EFGH", "expires_in": 30, "interval": 0})
        if self.path == "/api/cli/login/poll":
            Fake.approved = not Fake.approved  # pending once, then approved
            return self._send(200, {"status": "approved", "token": TOKEN} if not Fake.approved else {"status": "pending"})
        if not self._authed():
            return
        if self.path == "/api/explore":
            if body["scope"].get("kind") == "graph" and Fake.quota["remaining"] == 0:
                return self._send(429, {"error": "You have used your 5 free questions.", "code": "question_limit"})
            return self._send(200, {"answer": f"Answer to {body['question']} [graph:demo:T-1].", "quota": Fake.quota, "steps": [],
                                    "entities": {"graph:demo:T-1": {"name": "Test one", "type": "asset"}}})  # fmt: skip
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
    Fake.log, Fake.approved, Fake.role = [], False, "client"
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
