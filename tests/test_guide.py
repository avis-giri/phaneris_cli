"""The guide inside the terminal: every code and command is in it, it fits, pages on a terminal, searches."""

import io
import json
import re

import pytest
from test_cli import TTY, failed, run, server, signed  # noqa: F401  the fake server and helpers

from phaneris_cli import guide, term
from phaneris_cli import main as cli

# Facts the guide shares with the website's docs page (tests/test_docs_pages.py in the service checks the same list).
SHARED_FACTS = ("10 free in any 12 hours", "5 free in total", "100 for $5", "300 an hour", "30 days", "15 minutes", "Codes last 10 minutes",
                "0.5 is the middle")  # fmt: skip


def text():
    return "\n".join(b for _, _, b in guide.TOPICS)


def test_every_code_and_command_is_in_the_guide():
    body = text()
    for code in term.CODES:
        assert re.search(rf"^  {code}\b", body, re.M), code  # in the codes table, with an example
        assert "phaneris " in body and re.search(rf"phaneris [^\n]*\b{code}\b", body), code
    for command in cli.SUBCOMMANDS:
        assert re.search(rf"^  {command}\b", body, re.M), command
    for command in ("graph search", "graph record", "graph related", "disclosures show"):
        assert f"  {command}" in body, command
    for fact in SHARED_FACTS:
        assert fact in body, fact
    assert "—" not in body and "–" not in body and guide.DOCS in body


@pytest.mark.parametrize("width", [40, 60, 100])
def test_it_fits_the_terminal(width):
    for slug in guide.SLUGS:
        assert max(len(line) for line in guide.render(slug, width)) <= width, slug
    assert max(len(line) for line in guide.contents(width)) <= width
    assert max(len(line) for line in guide.search("the", width)[0]) <= width


def test_topics_by_name_alias_and_code():
    assert guide.find("window") == guide.find("kg") == guide.find("ask") == "window" and guide.find("watch") is None
    assert guide.find("scr") == "screens" and guide.find("security") == "signin" and guide.find("priv") == "privacy"
    assert guide.find("nonsense") is None


def test_guide_and_help_topic_commands(capsys, monkeypatch):
    monkeypatch.setenv("COLUMNS", "80")
    out = run(capsys, "guide")
    assert "The Phaneris guide (version" in out and out.index("  window     The Phaneris window") < out.index("  start ")
    assert "Reading the screens" in run(capsys, "help", "screens") and "Deal stages" not in run(capsys, "help", "questions")
    assert "HIST. Every kept version" in run(capsys, "guide", "hist")
    assert 'no topic "nonsense"' in failed(capsys, "guide", "nonsense")
    found = run(capsys, "guide", "--search", "Inferred")
    assert found.startswith('"Inferred":') and "(phaneris guide screens)" in found
    assert "is not in the guide" in failed(capsys, "guide", "--search", "zzzq")
    data = json.loads(run(capsys, "--json", "guide"))
    assert data["version"] and {t["id"] for t in data["topics"]} == set(guide.SLUGS)
    assert json.loads(run(capsys, "--json", "guide", "signin"))["id"] == "signin"


def test_paged_on_a_terminal_plain_when_piped(monkeypatch):
    long = [f"line {i}" for i in range(100)]
    piped = io.StringIO()
    guide.page(long, piped)
    assert piped.getvalue().count("\n") == 100  # all of it, no prompts
    monkeypatch.setattr("sys.stdin", TTY())
    seen = {}
    monkeypatch.setenv("PAGER", "less -R")
    monkeypatch.setattr(guide.subprocess, "run", lambda cmd, input, **kw: seen.update(cmd=cmd, text=input))
    guide.page(long, TTY())
    assert seen["cmd"] == ["less", "-R"] and seen["text"].startswith("line 0\n")
    monkeypatch.delenv("PAGER")
    shown = TTY()
    prompts = []
    monkeypatch.setattr("builtins.input", lambda prompt="": prompts.append(prompt) or "q")
    guide.page(long, shown)
    assert len(prompts) == 1 and "q to stop" in prompts[0] and "line 99" not in shown.getvalue()


def test_question_mark_topics_in_the_command_bar(server, capsys, monkeypatch):  # noqa: F811
    signed(server, capsys, monkeypatch)
    lines = iter(["? window", "?", "guide", "? nonsense"])

    def ask(prompt=""):
        try:
            return next(lines)
        except StopIteration:
            raise EOFError from None

    monkeypatch.setattr("builtins.input", ask)
    monkeypatch.setattr(term, "_reader", lambda ctx: ask, raising=False)
    ctx = term.Ctx(cli.signed_in(cli.global_options(["--server", server[0]])[0]), cli.Out(cli.global_options([])[0]), None)
    term.command_bar(ctx)
    out = capsys.readouterr().out
    assert "The Phaneris window" in out and "Guide topics: ? window" in out and out.count("The Phaneris guide (version") == 2


def test_who_reaches_what():
    body = text()
    assert "Office users and developers stay inside the named disclosure's neighbourhood" in body
    assert "Administrators read every graph, whole, even when they name a disclosure" in body


def test_the_window_comes_first_and_says_how_to_ask():
    assert guide.TOPICS[0][0] == "window"
    body = guide.SLUGS["window"][1]
    for must in ("Type phaneris and press Enter", "pipx inject phaneris-cli textual", "/kg QUESTION", "Ctrl-G", "scope chip",
                 "About T-000003", "Whole knowledge graph", "Questions: 8 of 10 free about disclosures, 4 of 5 whole graph, 0 bought",
                 "100 for $5", "Ctrl-B", "It is sent only when you choose it"):  # fmt: skip
        assert must in body, must
    assert "watch" not in text().lower().replace("names news or watch", "")


def test_rel_and_the_question_messages_are_in_the_guide():
    body = text()
    assert "REL. A disclosure's related knowledge graph" in body and "Administrators see the same view" in body
    assert "asked before a question is spent" in body and "Nothing was counted" in body
