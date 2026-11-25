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
from phaneris_cli import tui  # noqa: E402


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
            await type_line(pilot, "T-1 SCR")
            await settle(pilot, app)
            assert "Deal stages" in text_of(app) and len(app.pane().tabs.query("TabPane")) == 1
            await type_line(pilot, "T-1 WHY")
            await settle(pilot, app)
            assert len(app.pane().tabs.query("TabPane")) == 2
            await pilot.press("ctrl+w")
            await settle(pilot, app)
            assert len(app.pane().tabs.query("TabPane")) == 1
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


def test_idle_lock_covers_the_screen_until_a_key(server, capsys, monkeypatch):  # noqa: F811
    app = make_app(server, capsys, monkeypatch, start="T-1 SCR", idle=0.2)

    async def go():
        async with app.run_test(size=(120, 40)) as pilot:
            await settle(pilot, app)
            time.sleep(0.3)
            app.check_idle_lock()
            await settle(pilot, app)
            assert isinstance(app.screen, tui.LockScreen)
            await pilot.press("x")
            await settle(pilot, app)
            assert not isinstance(app.screen, tui.LockScreen)

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
            assert "Pat (client)" in status and "office aldermoor" in status and "9 of 10 free" in status and "server abc1234" in status
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
