"""phaneris usage, the USAGE code, and the notice at 80% and when free questions are used up."""

import json

from phaneris_cli import usage as usage_view
from phaneris_cli.style import Style
from test_cli import Fake, run, server, signed  # noqa: F401  the fake server and sign-in


def test_usage_shows_the_plan_meters_resets_and_next_steps(server, capsys, monkeypatch):  # noqa: F811
    url = signed(server, capsys, monkeypatch)
    out = run(capsys, "--server", url, "usage")
    for text in ("Usage and limits", "Plan  Free", "Bought questions left: 0", "Questions about your disclosures", "1 of 10 used, 9 left",
                 "Questions across the whole knowledge graph", "Knowledge graph lookups", "New disclosures scored",
                 "Questions, last 30 days", "phaneris buy", "2 minutes without use"):  # fmt: skip
        assert text in out, text
    assert "\033[" not in out  # not a terminal here: plain text


def test_usage_json_is_the_service_object(server, capsys, monkeypatch):  # noqa: F811
    url = signed(server, capsys, monkeypatch)
    data = json.loads(run(capsys, "--server", url, "--json", "usage"))
    assert data["plan"] == "Free" and [m["key"] for m in data["meters"]][:2] == ["disclosure_questions", "graph_questions"]


def test_the_usage_code_works_on_the_command_line(server, capsys, monkeypatch):  # noqa: F811
    url = signed(server, capsys, monkeypatch)
    out = run(capsys, "--server", url, "USAGE")
    assert "Usage and limits" in out and "Plan" in out


def test_admins_see_no_limit(server, capsys, monkeypatch):  # noqa: F811
    url = signed(server, capsys, monkeypatch)
    Fake.quota = {**Fake.quota, "unlimited": True}
    try:
        out = run(capsys, "--server", url, "usage")
    finally:
        Fake.quota = {**Fake.quota, "unlimited": False}
    assert "Admin, no limits" in out and "no limit" in out and "phaneris buy" not in out


def test_statement_fits_narrow_terminals_and_colours_only_on_a_terminal():
    u = Fake.account_usage()
    plain = usage_view.statement(Style(color=False, width=60), u)
    assert all(len(line) <= 60 for line in plain)  # fitted to the width
    coloured = usage_view.statement(Style(color=True, width=100), u)
    assert any("█" in line for line in coloured) and not any("█" in line for line in plain)


def test_notice_at_eighty_percent_and_when_empty():
    q = {"unlimited": False, "kind": "disclosure", "limit": 10, "free_left": 2, "credits": 0}
    assert usage_view.notice(q) == "2 of 10 free questions about your disclosures left."
    assert usage_view.notice({**q, "free_left": 3}) is None
    assert "phaneris buy" in usage_view.notice({**q, "free_left": 0})
    assert "(40 left)" in usage_view.notice({**q, "free_left": 0, "credits": 40})
    g = {**q, "kind": "graph", "limit": 5, "free_left": 0}
    assert "do not renew" in usage_view.notice(g)
    assert usage_view.notice({"unlimited": True}) is None
    u = Fake.account_usage()
    assert usage_view.notice(u, "disclosure") is None


def test_ask_prints_the_notice_when_free_questions_run_low(server, capsys, monkeypatch):  # noqa: F811
    url = signed(server, capsys, monkeypatch)
    old = Fake.quota
    Fake.quota = {**old, "free_left": 1, "remaining": 1}
    try:
        out = run(capsys, "--server", url, "ask", "Who owns it?", "--disclosure", "T-1")
    finally:
        Fake.quota = old
    assert "1 of 10 free questions about your disclosures left." in out
