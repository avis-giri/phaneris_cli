"""The window's USAGE pane: F2 opens it once and shows the plan and meters."""

import asyncio

import pytest

pytest.importorskip("textual")

from test_cli import Fake, server  # noqa: E402, F401  the fake server
from test_tui import make_app, settle, text_of  # noqa: E402

from phaneris_cli import tui  # noqa: E402


def test_f2_opens_usage_once(server, capsys, monkeypatch):  # noqa: F811
    app = make_app(server, capsys, monkeypatch)

    async def go():
        async with app.run_test(size=(140, 45)) as pilot:
            await settle(pilot, app)
            await pilot.press("f2")
            await settle(pilot, app)
            assert "USAGE" in app.tab_lines.values()
            assert "Usage and limits" in text_of(app) and "Questions about your disclosures" in text_of(app)
            await pilot.press("f2")
            await settle(pilot, app)
            assert list(app.tab_lines.values()).count("USAGE") == 1

    asyncio.run(go())


def test_welcome_and_status_name_f2(server, capsys, monkeypatch):  # noqa: F811
    app = make_app(server, capsys, monkeypatch)

    async def go():
        async with app.run_test(size=(140, 45)) as pilot:
            await settle(pilot, app)
            assert "F2" in str(app.query_one(tui.WelcomeView).query_one(".allowances").render())
            assert "F2 usage" in str(app.query_one("#status").render())

    asyncio.run(go())


def test_the_welcome_pane_warns_when_free_questions_run_low(server, capsys, monkeypatch):  # noqa: F811
    old = Fake.quota
    Fake.quota = {**old, "free_left": 1, "remaining": 1}
    try:
        app = make_app(server, capsys, monkeypatch)

        async def go():
            async with app.run_test(size=(140, 45)) as pilot:
                await settle(pilot, app)
                assert "1 of 10 free questions about your disclosures left." in str(app.query_one(tui.WelcomeView).query_one(".allowances").render())

        asyncio.run(go())
    finally:
        Fake.quota = old
