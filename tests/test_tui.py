"""Full-screen mode, driven headless with Textual's test pilot against the fake server."""

import argparse
import asyncio
import json
import os
import stat
import time

import pytest

pytest.importorskip("textual")

from test_cli import Fake, server, signed  # noqa: E402, F401  the fake server and sign-in

from phaneris_cli import main as cli  # noqa: E402
from phaneris_cli import store, tui  # noqa: E402


def make_app(srv, capsys, monkeypatch, start=None, idle=None, theme=None):
    url = signed(srv, capsys, monkeypatch)
    args = argparse.Namespace(server=url, json=False, no_color=False, theme=theme, disclosure=None, cites=False)
    return tui.PhanerisApp(cli.signed_in(args), args, start=start, idle_seconds=idle)


async def settle(pilot, app):
    for _ in range(3):
        await pilot.pause()
        await app.workers.wait_for_complete()
    await pilot.pause()


def text_of(app):
    """Everything the visible screen views say, as plain text."""
    out = []
    for view in app.query(tui.ScreenView):
        static = view.query_one(".body")
        out.append(str(static.render()))
    return "\n".join(out)


async def type_line(pilot, line):
    await pilot.click("#bar")
    for ch in line:
        await pilot.press(ch if ch != " " else "space")
    await pilot.press("enter")


def run(coro):
    return asyncio.run(coro)


def test_the_bar_opens_screens_in_tabs_and_panes(server, capsys, monkeypatch):  # noqa: F811
    app = make_app(server, capsys, monkeypatch)

    async def go():
        async with app.run_test(size=(140, 45)) as pilot:
            assert app.query(tui.WelcomeView)  # with no saved layout, the default opens the welcome pane
            await type_line(pilot, "T-1 SCR")
            await settle(pilot, app)
            assert "Deal stages" in text_of(app) and len(app.pane().tabs.query("TabPane")) == 2
            await type_line(pilot, "T-1 WHY")
            await settle(pilot, app)
            assert len(app.pane().tabs.query("TabPane")) == 3
            await pilot.press("ctrl+w")
            await settle(pilot, app)
            assert len(app.pane().tabs.query("TabPane")) == 2
            await pilot.press("ctrl+n")
            await settle(pilot, app)
            assert len(app.panes()) == 2 and app.focused_pane == 1
            await type_line(pilot, "PORT")
            await settle(pilot, app)
            assert app.query(tui.BoardView)
            await pilot.press("ctrl+x")
            await settle(pilot, app)
            assert len(app.panes()) == 1
            for _ in range(5):
                await pilot.press("ctrl+n")
                await settle(pilot, app)
            assert len(app.panes()) == tui.MAX_PANES

    run(go())


def test_board_rows_open_their_scores(server, capsys, monkeypatch):  # noqa: F811
    app = make_app(server, capsys, monkeypatch, start="PORT")

    async def go():
        async with app.run_test(size=(140, 40)) as pilot:
            await settle(pilot, app)
            table = app.query_one(tui.DataTable)
            table.focus()
            await pilot.press("enter")
            await settle(pilot, app)
            titles = [str(t.label) for t in app.pane().tabs.query("Tab")]
            assert any("T-1 SCR" in t for t in titles)

    run(go())


def test_the_map_walks_forward_and_back(server, capsys, monkeypatch):  # noqa: F811
    app = make_app(server, capsys, monkeypatch, start="T-1 DES")
    notes = []

    async def go():
        async with app.run_test(size=(140, 40)) as pilot:
            await settle(pilot, app)
            app.notify = lambda msg, **kw: notes.append(msg)
            app.open_tab("Ada Shared GRF")
            await settle(pilot, app)
            walker = app.query_one(tui.Walker)
            ol = walker.query_one(tui.OptionList)
            ids = [ol.get_option_at_index(i).id for i in range(ol.option_count)]
            ol.highlighted = ids.index("1|inv:c")
            await pilot.press("enter")
            await settle(pilot, app)
            await pilot.press("backspace")
            await settle(pilot, app)
            maps = [x[2]["node"] for x in Fake.log if x[1] == "/api/graph/map"]
            assert maps == ["inv:a", "inv:c", "inv:a"] and all(x[2].get("disclosure") == "T-1" for x in Fake.log if x[1] == "/api/graph/map")
            ol.highlighted = ids.index("1|inv:c")
            await pilot.press("d")
            await settle(pilot, app)
            assert walker.has_class("-brief") and "A patent" in str(walker.query_one(".brief-body").render())
            ol.highlighted = ids.index("2|far:1")
            await pilot.press("enter")
            await settle(pilot, app)
            assert any("Out of reach" in n for n in notes)

    run(go())


@pytest.mark.parametrize("width", [90, 170])
def test_timeline_and_class_draw_for_the_pane_width(server, capsys, monkeypatch, width):  # noqa: F811
    app = make_app(server, capsys, monkeypatch, start="T-1 OWN")

    async def go():
        async with app.run_test(size=(width, 50)) as pilot:
            await settle(pilot, app)
            app.open_tab("T-1 CLS")
            await settle(pilot, app)
            views = list(app.query(tui.ScreenView))
            own = str(views[0].query_one(".body").render())
            cls = str(views[-1].query_one(".body").render())
            assert "disclosure date 2010-01-01" in own and "hindsight" in own
            assert "Filings by year" in cls and "AN OWNER" in cls
            for view in views:
                body = str(view.query_one(".body").render())
                assert max(len(line) for line in body.splitlines()) <= width

    run(go())


def test_idle_lock_signs_out_and_leaves(server, capsys, monkeypatch):  # noqa: F811
    app = make_app(server, capsys, monkeypatch, start="T-1 SCR", idle=3600)

    async def go():
        async with app.run_test(size=(120, 40)) as pilot:
            await settle(pilot, app)
            app.check_idle_lock()
            assert not app.is_locked  # just used: no lock
            app.idle_seconds = 60
            app.last_activity = time.monotonic() - 61  # longer ago than the idle time
            app.check_idle_lock()
            for _ in range(5):
                await pilot.pause()
            assert app.is_locked and any(isinstance(s, tui.LockScreen) for s in app.screen_stack)
            for _ in range(20):  # the sign-in is ended on the server and forgotten here, in the background
                if ("POST", "/api/cli/logout", {"why": "idle"}) in Fake.log:
                    break
                await asyncio.sleep(0.05)
            assert ("POST", "/api/cli/logout", {"why": "idle"}) in Fake.log
            assert store.load_token(app.api.server) is None
            await pilot.press("x")
            await pilot.pause()
            assert app._exit  # any key leaves full-screen mode

    run(go())


def test_layouts_are_saved_privately_and_restored(server, capsys, monkeypatch):  # noqa: F811
    app = make_app(server, capsys, monkeypatch, start="T-1 SCR")

    async def go():
        async with app.run_test(size=(140, 40)) as pilot:
            await settle(pilot, app)
            await pilot.press("ctrl+n")
            await settle(pilot, app)
            app.open_tab("PORT")
            await settle(pilot, app)
            await pilot.press("ctrl+s")
            await settle(pilot, app)

    run(go())
    path = tui.layouts_path()
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    saved = json.loads(open(path).read())["default"]
    assert saved["panes"] == [{"tabs": ["T-1 SCR"]}, {"tabs": ["PORT"]}]
    again = make_app(server, capsys, monkeypatch)

    async def back():
        async with again.run_test(size=(140, 40)) as pilot:
            await settle(pilot, again)
            assert len(again.panes()) == 2 and again.layout_now()["panes"] == saved["panes"]

    run(back())


def test_help_status_and_amber(server, capsys, monkeypatch):  # noqa: F811
    app = make_app(server, capsys, monkeypatch, theme="amber")

    async def go():
        async with app.run_test(size=(120, 40)) as pilot:
            await settle(pilot, app)
            status = str(app.query_one("#status").render())
            assert "Pat (client)" in status and "office aldermoor" in status
            assert "Questions: 9 of 10 free about disclosures, 4 of 5 whole graph, 0 bought" in status and "server abc1234" in status
            assert app.has_class("amber")
            app.screen.set_focus(None)  # not typing in the bar
            await pilot.press("question_mark")
            await pilot.pause()
            assert isinstance(app.screen, tui.HelpScreen)
            await pilot.press("x")
            await pilot.pause()
            assert not isinstance(app.screen, tui.HelpScreen)

    run(go())


def test_tab_in_the_bar_suggests_from_history(server, capsys, monkeypatch):  # noqa: F811
    from phaneris_cli import history

    app = make_app(server, capsys, monkeypatch)
    history.add("T-1 WHY")
    history.add("T-1 SCR")
    history.add("T-1 SCR")

    async def go():
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.click("#bar")
            for ch in "T-1 ":
                await pilot.press(ch if ch != " " else "space")
            await pilot.press("tab")
            await pilot.pause()
            box = app.query_one("#suggest")
            assert box.has_class("-show") and str(box.get_option_at_index(0).prompt) == "T-1 SCR"  # most used first
            await pilot.press("enter")
            await pilot.pause()
            assert app.query_one("#bar").value == "T-1 SCR"

    run(go())


def test_guide_pane_from_the_bar(server, capsys, monkeypatch):  # noqa: F811
    app = make_app(server, capsys, monkeypatch, start="T-1 DES")

    async def go():
        async with app.run_test(size=(120, 40)) as pilot:
            await settle(pilot, app)
            await type_line(pilot, "? questions")
            await settle(pilot, app)
            view = app.query_one(tui.GuideView)
            assert "Questions and limits" in str(view.query_one(".body").render())
            await type_line(pilot, ":guide")
            await settle(pilot, app)
            assert len(app.query(tui.GuideView)) == 2
            titles = [str(t.label) for t in app.pane().tabs.query("Tab")]
            assert "Guide questions" in titles and "Guide" in titles

    run(go())


def test_ambiguous_names_become_rows_to_open(server, capsys, monkeypatch):  # noqa: F811
    monkeypatch.setattr(Fake, "role", "admin")
    app = make_app(server, capsys, monkeypatch, start="Ethan DES")

    async def go():
        async with app.run_test(size=(120, 40)) as pilot:
            await settle(pilot, app)
            box = app.query_one("#choices", tui.OptionList)
            assert box.option_count == 2 and "matches 2 records" in text_of(app) and "error" not in text_of(app)
            box.focus()
            box.highlighted = 0
            await pilot.press("enter")
            await settle(pilot, app)
            titles = [str(t.label) for t in app.pane().tabs.query("Tab")]
            assert "author:ETHAN STANCLIFFE DES" in titles
            assert [x[2]["node"] for x in Fake.log if x[1] == "/api/graph/record"][-1] == "author:ETHAN STANCLIFFE"

    run(go())


def test_status_line_refreshes_and_says_when_the_server_is_not_answering(server, capsys, monkeypatch):  # noqa: F811
    monkeypatch.setattr(tui, "STATUS_SECONDS", 0.3)
    app = make_app(server, capsys, monkeypatch)

    async def go():
        async with app.run_test(size=(120, 40)) as pilot:
            await settle(pilot, app)
            status = lambda: str(app.query_one("#status").render())  # noqa: E731
            assert "server abc1234" in status() and "/api/health" in Fake.background  # marked as not the person's activity
            real = app.api.server
            app.api.server = "http://127.0.0.1:9"  # nothing listens there
            await pilot.pause(0.8)
            await app.workers.wait_for_complete()
            assert "server not answering" in status() and "Could not reach" not in status()
            app.api.server = real
            before = len([x for x in Fake.log if x[1] == "/api/health"])
            await pilot.pause(0.8)
            await app.workers.wait_for_complete()
            assert len([x for x in Fake.log if x[1] == "/api/health"]) > before and "server abc1234" in status()

    run(go())


def posts(path):
    return [x[2] for x in Fake.log if x[0] == "POST" and x[1] == path]


def log_of(view):
    return "\n".join(str(line.text) for line in view.query_one(tui.RichLog).lines)


def test_welcome_pane_shows_what_to_type_the_disclosures_and_the_allowances(server, capsys, monkeypatch):  # noqa: F811
    app = make_app(server, capsys, monkeypatch)

    async def go():
        async with app.run_test(size=(140, 45)) as pilot:
            await settle(pilot, app)
            w = app.query_one(tui.WelcomeView)
            intro = str(w.query_one(".intro").render())
            assert "/kg QUESTION or Ctrl-G" in intro and "T-000003 SCR" in intro and "Tab" in intro
            assert w.query_one(tui.DataTable).row_count == 1  # the office's disclosures (PORT)
            assert "Questions: 9 of 10 free about disclosures, 4 of 5 whole graph" in str(w.query_one(".allowances").render())
            w.query_one(tui.DataTable).focus()
            await pilot.press("enter")
            await settle(pilot, app)
            assert any("T-1 SCR" in str(t.label) for t in app.pane().tabs.query("Tab"))

    run(go())


async def typed(pilot, text):
    await pilot.click("#bar")
    app = pilot.app
    app.query_one("#bar").value = text
    await pilot.pause()
    return str(app.query_one("#scope").render())


def test_questions_from_the_bar_follow_the_scope_chip(server, capsys, monkeypatch):  # noqa: F811
    app = make_app(server, capsys, monkeypatch, start="T-1 SCR")

    async def go():
        async with app.run_test(size=(140, 45)) as pilot:
            await settle(pilot, app)
            assert await typed(pilot, "Who invented it?") == "About T-1"  # the disclosure in focus
            assert await typed(pilot, "/kg What is CAR-T?") == "Whole knowledge graph"
            assert not posts("/api/explore")  # the chip shows the scope before anything is sent
            await type_line(pilot, "Who invented it?")
            await settle(pilot, app)
            assert posts("/api/explore")[-1]["scope"] == {"kind": "disclosure", "disclosure": "T-1"}
            await type_line(pilot, "/kg What is CAR-T?")
            await settle(pilot, app)
            assert posts("/api/explore")[-1] == {"question": "What is CAR-T?", "history": [], "scope": {"kind": "graph"}}
            await type_line(pilot, "/kg And its owners?")  # the same scope: the same conversation, with its history
            await settle(pilot, app)
            assert posts("/api/explore")[-1]["history"][0] == {"role": "user", "content": "What is CAR-T?"}
            titles = [str(t.label) for t in app.pane().tabs.query("Tab")]
            assert titles.count("Ask: whole graph") == 1 and "Ask: T-1" in titles
            from phaneris_cli import history

            assert not [h for h in history.load() if "CAR-T" in h or "invented" in h]  # questions are never kept

    run(go())


def test_ctrl_g_switches_to_the_whole_graph_and_no_disclosure_sends_nothing(server, capsys, monkeypatch):  # noqa: F811
    app = make_app(server, capsys, monkeypatch)
    notes = []
    monkeypatch.setattr(app, "notify", lambda message, **kw: notes.append(message))

    async def go():
        async with app.run_test(size=(140, 45)) as pilot:
            await settle(pilot, app)
            assert await typed(pilot, "Who owns it?") == "No disclosure open · Ctrl-G: whole graph"
            await type_line(pilot, "Who owns it?")
            await settle(pilot, app)
            assert not posts("/api/explore") and "No disclosure is open" in notes[-1]
            await pilot.press("ctrl+g")
            assert await typed(pilot, "Who owns it?") == "Whole knowledge graph" and app.query_one("#scope").has_class("-graph")
            await type_line(pilot, "Who owns it?")
            await settle(pilot, app)
            assert posts("/api/explore")[-1]["scope"] == {"kind": "graph"}

    run(go())


def test_cited_records_open_within_reach_and_explain_otherwise(server, capsys, monkeypatch):  # noqa: F811
    from phaneris_cli import main as cli_main

    app = make_app(server, capsys, monkeypatch, start="T-1 SCR")
    cli_main.remember(last_disclosure="T-1")

    async def go():
        async with app.run_test(size=(140, 45)) as pilot:
            await settle(pilot, app)
            await type_line(pilot, "/kg What is near it?")
            await settle(pilot, app)
            view = app.query_one(tui.AskView)
            box = view.query_one("#cited", tui.OptionList)
            assert box.option_count == 2 and "Records cited, below" in log_of(view)
            box.focus()
            box.highlighted = 1  # pat:999999: outside the reach of T-1
            await pilot.press("enter")
            await settle(pilot, app)
            text = " ".join(log_of(view).split())  # the log wraps lines
            assert "Far patent" in text and "SOMEONE ELSE" in text and "cannot be opened further: it is outside the reach of T-1" in text
            box.focus()
            box.highlighted = 0  # T-1: within reach, opens its brief
            await pilot.press("enter")
            await settle(pilot, app)
            assert any(str(t.label).startswith("T-1 DES") for t in app.pane().tabs.query("Tab"))

    run(go())


def test_a_name_out_of_reach_offers_the_whole_graph_and_spends_only_on_enter(server, capsys, monkeypatch):  # noqa: F811
    from phaneris_cli import main as cli_main

    cli_main.remember(last_disclosure="T-1")
    app = make_app(server, capsys, monkeypatch, start="Nobody Atall GRF")
    cli_main.remember(last_disclosure="T-1")

    async def go():
        async with app.run_test(size=(140, 45)) as pilot:
            await settle(pilot, app)
            box = app.query_one("#choices", tui.OptionList)
            assert str(box.get_option_at_index(0).prompt).startswith("Ask the whole knowledge graph about 'Nobody Atall' (4 free")
            assert not posts("/api/explore")  # nothing spent by showing it
            box.focus()
            box.highlighted = 0
            await pilot.press("enter")  # the confirmation
            await settle(pilot, app)
            assert posts("/api/explore") == [{"question": "Who or what is Nobody Atall?", "history": [], "scope": {"kind": "graph"}}]

    run(go())


def test_a_saved_layout_with_news_still_opens(server, capsys, monkeypatch):  # noqa: F811
    app = make_app(server, capsys, monkeypatch)
    tui.write_layouts({"default": {"split": 0.5, "panes": [{"tabs": ["NEWS", "T-1 WATCH", "T-1 SCR"]}]}})
    notes = []
    monkeypatch.setattr(app, "notify", lambda message, **kw: notes.append(message))

    async def go():
        async with app.run_test(size=(140, 45)) as pilot:
            await settle(pilot, app)
            titles = [str(t.label) for t in app.pane().tabs.query("Tab")]
            assert titles == ["T-1 SCR"] and sum("removed in 0.7.0" in n for n in notes) == 2

    run(go())


def test_ctrl_b_twice_requests_the_pack(server, capsys, monkeypatch):  # noqa: F811
    app = make_app(server, capsys, monkeypatch)

    async def go():
        async with app.run_test(size=(140, 45)) as pilot:
            await settle(pilot, app)
            await pilot.press("ctrl+b")
            await settle(pilot, app)
            assert not posts("/api/explore/request-pack")
            await pilot.press("ctrl+b")
            await settle(pilot, app)
            assert len(posts("/api/explore/request-pack")) == 1

    run(go())


WINDOW_NEXT = {"not yours": "/kg QUESTION", "graph limit": "Ctrl-B", "idle": "phaneris login", "off": "Nothing was counted",
               "busy": "Nothing was counted", "failed": "Nothing was counted"}  # fmt: skip


@pytest.mark.parametrize("case", list(WINDOW_NEXT))
def test_a_failed_question_is_shown_in_the_pane_with_the_next_step(server, capsys, monkeypatch, case):  # noqa: F811
    from test_cli import FAILURES

    app = make_app(server, capsys, monkeypatch, start="T-1 SCR")
    Fake.explore_fail = FAILURES[case]

    async def go():
        async with app.run_test(size=(140, 45)) as pilot:
            await settle(pilot, app)
            await type_line(pilot, "Who owns it?")
            await settle(pilot, app)
            text = " ".join(log_of(app.query_one(tui.AskView)).split())
            assert FAILURES[case][1]["error"].split(".")[0] in text and WINDOW_NEXT[case] in text
            assert app.is_running  # shown in the pane, not a crash

    run(go())


def test_ask_on_a_record_with_no_disclosure_open_sends_nothing(server, capsys, monkeypatch):  # noqa: F811
    monkeypatch.setattr(Fake, "role", "admin")
    app = make_app(server, capsys, monkeypatch, start="Ada Shared ASK")

    async def go():
        async with app.run_test(size=(140, 45)) as pilot:
            await settle(pilot, app)
            text = " ".join(log_of(app.query_one(tui.AskView)).split())
            assert "is not a disclosure, and no disclosure is open, so nothing will be asked here" in text and "/kg QUESTION" in text
            assert not posts("/api/explore")

    run(go())
