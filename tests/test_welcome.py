"""The welcome phaneris shows first: tailored, with the window as the first option, and out of the way of scripts."""

import io
import re

import pytest
from test_cli import TTY, Fake, failed, run, server, signed  # noqa: F401  the fake server and helpers

from phaneris_cli import main as cli
from phaneris_cli import store, term


def plain(text):
    return re.sub(r"\033\[[0-9;?]*[A-Za-z]", "", text)


@pytest.fixture
def terminal(monkeypatch):
    """A terminal where the person types the answers given; records whether the window or the bar opened."""
    monkeypatch.delenv("PHANERIS_NO_WELCOME", raising=False)
    monkeypatch.setattr("sys.stdin", TTY())
    monkeypatch.setattr("sys.stdout.isatty", lambda: True, raising=False)
    opened = []
    monkeypatch.setattr(cli, "open_tui", lambda args, out, start: opened.append(("window", start)))
    monkeypatch.setattr(term, "command_bar", lambda ctx: opened.append(("bar", None)))

    def answers(*typed):
        monkeypatch.setattr("sys.stdin", TTY())  # after signing in, which reads the password from stdin
        monkeypatch.setattr("sys.stdout.isatty", lambda: True, raising=False)
        it = iter(typed)

        def ask(prompt=""):
            try:
                return next(it)
            except StopIteration:
                raise EOFError from None

        monkeypatch.setattr("builtins.input", ask)

    return opened, answers


def test_the_welcome_is_tailored_and_enter_opens_the_window(server, capsys, monkeypatch, terminal):  # noqa: F811
    signed(server, capsys, monkeypatch)
    opened, answers = terminal
    monkeypatch.setattr(cli, "tui_available", lambda: True)
    answers("")
    out = plain(run(capsys))
    assert "Welcome back, Pat." in out and "Aldermoor · Office user · 2 disclosures" in out
    assert "9 of 10 free about your disclosures" in out and "4 of 5 across the whole graph · 0 bought" in out
    assert out.index("Press Enter to open the Phaneris window (full screen)") < out.index("Next")
    assert "T-000003 SCR    open a disclosure" in out and "/kg QUESTION    ask across" in out and "phaneris guide  everything" in out
    assert max(len(line) for line in out.splitlines()) <= 80  # fits a standard terminal
    assert opened == [("window", None)]


def test_without_the_extra_enter_shows_the_one_command_and_the_bar(server, capsys, monkeypatch, terminal):  # noqa: F811
    signed(server, capsys, monkeypatch)
    opened, answers = terminal
    monkeypatch.setattr(cli, "tui_available", lambda: False)
    answers("")
    out = plain(run(capsys))
    assert "Press Enter to see how to add the Phaneris window" in out and "pipx inject phaneris-cli textual" in out
    assert opened == [("bar", None)]


def test_b_n_q_and_a_typed_command(server, capsys, monkeypatch, terminal):  # noqa: F811
    signed(server, capsys, monkeypatch)
    opened, answers = terminal
    monkeypatch.setattr(cli, "tui_available", lambda: True)
    answers("b")
    run(capsys)
    assert opened == [("bar", None)]
    answers("q")
    run(capsys)
    assert opened == [("bar", None)]  # q: nothing opened
    answers("T-1 SCR")  # a command typed straight away runs
    assert "Deal stages" in plain(run(capsys))
    answers("n")  # don't show again: remembered, and the window opens
    out = plain(run(capsys))
    assert "The welcome is off" in out and opened[-1] == ("window", None) and store.read_config()["welcome"] is False
    answers()
    out = plain(run(capsys))  # next time: straight to the window, no welcome
    assert "Welcome back" not in out and opened[-1] == ("window", None)
    assert "The welcome is on" in run(capsys, "welcome", "--on") and store.read_config()["welcome"] is True


def test_low_and_empty_allowances_are_warned(server, capsys, monkeypatch, terminal):  # noqa: F811
    signed(server, capsys, monkeypatch)
    _, answers = terminal
    monkeypatch.setattr(cli, "tui_available", lambda: True)
    monkeypatch.setattr(Fake, "quota", {**Fake.quota, "free_left": 1, "remaining": 1})
    monkeypatch.setattr(Fake, "graph_left", 0)
    answers("q")
    out = plain(run(capsys))
    assert "1 of 10 free questions about your disclosures left." in out
    assert "Your free whole-graph questions are used and do not renew. More: phaneris buy (100 for $5)." in out


def test_signed_out_says_what_phaneris_is_and_how_to_sign_in(server, capsys, monkeypatch, terminal):  # noqa: F811
    url, _ = server
    answers = terminal[1]
    answers()
    out = plain(run(capsys, "--server", url))
    assert (
        "Welcome to Phaneris." in out
        and "Phaneris scores inventions and shows the evidence behind every score." in out
        and "Sign in to get started:  phaneris login" in out
    )
    assert terminal[0] == []


def test_no_welcome_for_scripts_or_when_turned_off(server, capsys, monkeypatch, terminal):  # noqa: F811
    signed(server, capsys, monkeypatch)
    opened, answers = terminal
    monkeypatch.setattr(cli, "tui_available", lambda: True)
    answers()
    monkeypatch.setenv("PHANERIS_NO_WELCOME", "1")
    assert "Welcome back" not in plain(run(capsys)) and opened == [("window", None)]
    monkeypatch.delenv("PHANERIS_NO_WELCOME")
    assert "Welcome back" not in plain(run(capsys, "--json"))  # --json: no welcome
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    monkeypatch.setattr("sys.stdout.isatty", lambda: False, raising=False)
    out = plain(run(capsys))  # no terminal: the help, as before
    assert "Welcome back" not in out and "Use Phaneris from a terminal" in out
