"""Idle sign-out and two-step sign-in in the command line."""

import io
import os
import signal
import time

import pytest
from test_cli import SECRET, Fake, failed, run, server, signed  # noqa: F401  the fake server and helpers

from phaneris_cli import idle, store, term
from phaneris_cli.api import Api


def test_an_idle_sign_out_from_the_server_is_explained_and_forgotten(server, capsys, monkeypatch):  # noqa: F811
    url = signed(server, capsys, monkeypatch)
    assert store.load_token(url)
    Fake.idle = True
    err = failed(capsys, "--server", url, "whoami")
    assert "2 minutes without use" in err and "phaneris login" in err
    assert store.load_token(url) is None  # forgotten here too


def test_password_sign_in_asks_for_the_two_step_code(server, capsys, monkeypatch):  # noqa: F811
    url, _ = server
    Fake.two_step = True
    monkeypatch.setattr("sys.stdin", io.StringIO(SECRET + "\n"))
    err = failed(capsys, "--server", url, "login", "--username", "pat", "--password-stdin")
    assert "--code" in err  # a script is told how to give the code
    monkeypatch.setattr("sys.stdin", io.StringIO(SECRET + "\n"))
    out = run(capsys, "--server", url, "login", "--username", "pat", "--password-stdin", "--code", "123456")
    assert "Signed in as Pat" in out
    sent = [x for x in Fake.log if x[1] == "/api/cli/login/password"][-1][2]
    assert sent["code"] == "123456"
    monkeypatch.setattr("sys.stdin", io.StringIO(SECRET + "\n"))
    err = failed(capsys, "--server", url, "login", "--username", "pat", "--password-stdin", "--code", "000000")
    assert "not right" in err


def test_the_idle_limit_comes_from_the_server(server):  # noqa: F811
    url, _ = server
    assert idle.minutes(Api(url)) == 2


@pytest.mark.skipif(not hasattr(signal, "SIGALRM"), reason="needs the alarm signal")
def test_a_read_that_waits_past_the_limit_times_out():
    def slow():
        time.sleep(5)
        return "never"

    t0 = time.time()
    with pytest.raises(idle.IdleTimeout):
        idle.timed(slow, 1)
    assert time.time() - t0 < 3
    assert idle.timed(lambda: "typed", 5) == "typed"


def test_the_command_bar_locks_after_the_limit(server, capsys, monkeypatch):  # noqa: F811
    url = signed(server, capsys, monkeypatch)
    monkeypatch.setattr(idle, "minutes", lambda api: 1)

    def never_typed(read, seconds):
        assert seconds == 60
        raise idle.IdleTimeout()

    monkeypatch.setattr(idle, "timed", never_typed)
    monkeypatch.setattr(term, "_reader", lambda ctx: lambda: "unused")
    from phaneris_cli import main as cli

    args = cli.build_parser().parse_args(["--server", url, "whoami"])
    api = cli.signed_in(args)
    ctx = term.Ctx(api, cli.Out(args), args)
    term.command_bar(ctx)
    out = capsys.readouterr().out
    assert "Signed out after 1 minutes without use" in out
    assert ("POST", "/api/cli/logout", {"why": "idle"}) in Fake.log
    assert store.load_token(url) is None
    assert not os.path.exists(store.TOKEN_FILE) or url not in open(store.TOKEN_FILE).read()
