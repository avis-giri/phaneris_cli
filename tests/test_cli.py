"""The command line against a small fake Phaneris server (no network, no keychain)."""

import json
import os
import stat
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from phaneris_cli import main as cli
from phaneris_cli import store

TOKEN = "phc_" + "t" * 43
CONSOLE = {
    "run": {
        "ideas": {
            "g": {
                "id": "T-1",
                "title": "A test disclosure",
                "inst": "Test University",
                "patent": "123",
                "asof": "2010-01-01",
            },
            "J-1": {
                "id": "NEW-1",
                "title": "Scored live",
                "inst": "",
                "patent": "",
                "asof": "2026-01-01",
                "live": True,
            },
            "J-2": {"id": "OPEN-1", "title": "Opened alone", "opened": True},
        },
        "ui": {
            "names": {"g": {"name": "Test one"}},
            "score_cards": {"g": [{"label": "Deal chance, real data", "value": "5.0%", "sub": "x"}]},
        },
        "complete": {
            "ideas": {
                "g": {
                    "real": {"p_out": 0.05},
                    "complete": {"p_out": 0.07, "verdict": "Review"},
                    "metrics": {
                        "ipd": {"name": "IP defensibility", "score": 0.4, "basis": "crowd"},
                        "cp": {"name": "Capital path", "score": 0.5, "basis": "placeholder"},
                    },
                }
            }
        },
    },
    "states": {},
}


class Fake(BaseHTTPRequestHandler):
    log = []
    approved = False
    quota = {
        "unlimited": False,
        "kind": "disclosure",
        "limit": 10,
        "window_hours": 12,
        "free_left": 9,
        "credits": 0,
        "remaining": 9,
    }

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
        Fake.log.append(("GET", self.path))
        if not self._authed():
            return
        if self.path == "/api/auth/me":
            return self._send(200, {"user": {"username": "pat", "display_name": "Pat", "role": "client", "workspace": "aldermoor"}})
        if self.path == "/api/console":
            return self._send(200, CONSOLE)
        if self.path == "/api/explore/usage":
            return self._send(
                200,
                {
                    "quota": Fake.quota,
                    "graph_quota": {**Fake.quota, "kind": "graph", "limit": 5, "window_hours": None},
                    "pack_requested": False,
                },
            )
        if self.path == "/api/reports/Phaneris_Report_T-1.pdf":
            return self._send(200, b"%PDF-1.4 test", "application/pdf")
        if self.path.startswith("/api/jobs/J-9"):
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
        if self.path == "/api/jobs":
            return self._send(
                200,
                {"jobs": [{"id": "J-9", "disclosure_id": "NEW-2", "status": "scored", "created_at": "2026-11-24T10:00:00"}]},
            )
        self._send(404, {"error": "Not found."})

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        Fake.log.append(("POST", self.path, body))
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
            return self._send(200, {"answer": "It is strong [graph:demo:T-1].", "quota": Fake.quota, "steps": []})
        if self.path in ("/api/explore/request-pack", "/api/cli/logout"):
            return self._send(200, {"ok": True})
        if self.path == "/api/intake":
            return self._send(201, {"job": "J-9"})
        self._send(404, {"error": "Not found."})


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("PHANERIS_NO_KEYCHAIN", "1")
    monkeypatch.delenv("PHANERIS_TOKEN", raising=False)
    monkeypatch.setattr(store, "CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(store, "CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setattr(store, "TOKEN_FILE", str(tmp_path / "token.json"))
    monkeypatch.setattr(cli.time, "sleep", lambda s: None)
    monkeypatch.setattr(cli.webbrowser, "open", lambda url: None)
    Fake.log, Fake.approved = [], False
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", tmp_path
    httpd.shutdown()


def run(capsys, *args):
    cli.main(list(args))
    return capsys.readouterr().out


def test_login_keeps_the_token_in_a_private_file_without_a_keychain(server, capsys):
    url, tmp = server
    out = run(capsys, "--server", url, "login", "--no-browser")
    assert "ABCD-EFGH" in out and "Signed in as Pat" in out and "only your account can read" in out
    mode = stat.S_IMODE(os.stat(tmp / "token.json").st_mode)
    assert mode == 0o600 and json.loads((tmp / "token.json").read_text())[url] == TOKEN
    assert "aldermoor" in run(capsys, "whoami")  # the server is remembered


def signed(server, capsys):
    url, _ = server
    run(capsys, "--server", url, "login", "--no-browser")
    return url


def test_disclosures_list_show_and_json(server, capsys):
    signed(server, capsys)
    out = run(capsys, "disclosures")
    assert "T-1" in out and "NEW-1" in out and "OPEN-1" not in out and "5.0%" in out
    shown = run(capsys, "disclosures", "show", "T-1")
    assert "IP defensibility" in shown and "real" in shown and "inferred" in shown
    rows = json.loads(run(capsys, "--json", "disclosures"))
    assert {r["id"] for r in rows} == {"T-1", "NEW-1"}


def test_report_pdf(server, capsys, tmp_path):
    signed(server, capsys)
    target = tmp_path / "r.pdf"
    assert "Saved" in run(capsys, "report", "T-1", "--pdf", str(target))
    assert target.read_bytes().startswith(b"%PDF")


def test_ask_strips_tags_and_shows_the_allowance(server, capsys):
    signed(server, capsys)
    out = run(capsys, "ask", "How strong?", "--disclosure", "T-1")
    assert "It is strong." in out and "[graph" not in out and "9 of 10 free left" in out
    sent = [x for x in Fake.log if x[1] == "/api/explore"][-1][2]
    assert sent["scope"] == {"kind": "disclosure", "disclosure": "T-1"}


def test_whole_graph_limit_points_to_buy(server, capsys, monkeypatch):
    signed(server, capsys)
    monkeypatch.setattr(Fake, "quota", {**Fake.quota, "remaining": 0})
    with pytest.raises(SystemExit):
        run(capsys, "ask", "Anything?", "--graph")
    assert "phaneris buy" in capsys.readouterr().err
    assert "Requested 100 questions" in run(capsys, "buy")


def test_score_follows_the_job(server, capsys, tmp_path):
    signed(server, capsys)
    f = tmp_path / "d.json"
    f.write_text(json.dumps(cli.EXAMPLE))
    out = run(capsys, "score", str(f))
    assert "Scored: NEW-2, deal chance 8.0%" in out


def test_logout_forgets_the_token(server, capsys):
    url = signed(server, capsys)
    assert "Signed out" in run(capsys, "logout")
    assert ("POST", "/api/cli/logout", {}) in Fake.log
    with pytest.raises(SystemExit):
        run(capsys, "whoami")
    assert store.load_token(url) is None


def test_plain_http_is_refused_except_this_computer(server, capsys):
    with pytest.raises(SystemExit):
        run(capsys, "--server", "http://example.com", "login", "--no-browser")
