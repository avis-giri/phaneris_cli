"""Full-screen mode: `phaneris tui` (or `phaneris` with no words when the optional extra is installed).

A command bar on top (the same grammar, with Tab suggestions from your own history), up to four panes with tabs, a
status line, a help overlay, two themes, an idle lock, and saved layouts. Every pane shows one screen (DES, SCR, WHY,
CMP, OWN, CLS, HIST, NEWS, GRF, PORT, ASK) drawn for the pane's width from the same server routes as the command line, under the
same bounds and limits. Needs Textual: `pipx inject phaneris-cli textual`.
"""

import json
import os
import re
import shlex
import stat
import time

from rich.text import Text
from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.suggester import Suggester
from textual.widgets import DataTable, Input, OptionList, RichLog, Static, TabbedContent, TabPane
from textual.widgets.option_list import Option

from . import __version__, history, store, term
from .api import ApiError, CachedApi
from .style import Style, pct

MAX_PANES = 4
IDLE_SECONDS = 30 * 60
CODES = list(term.CODES)
ANSI = re.compile(r"\033\[[0-9;?]*[A-Za-z]")


def layouts_path():
    return os.path.join(store.CONFIG_DIR, "layouts.json")


def read_layouts():
    try:
        with open(layouts_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_layouts(data):
    os.makedirs(store.CONFIG_DIR, mode=0o700, exist_ok=True)
    fd = os.open(layouts_path(), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.chmod(layouts_path(), stat.S_IRUSR | stat.S_IWUSR)


# ------------------------------------------------------------------ the command bar


class HistorySuggester(Suggester):
    """Ghost text in the bar: the best suggestion from your own history, then codes, then subjects seen."""

    def __init__(self, app):
        super().__init__(use_cache=False, case_sensitive=False)
        self.ph = app

    async def get_suggestion(self, value):
        for s in self.ph.suggestions(value):
            if s.lower().startswith(value.lower()) and len(s) > len(value):
                return s
        return None


class CommandBar(Input):
    BINDINGS = [Binding("tab", "complete", "Complete", priority=True, show=False)]

    def action_complete(self):
        options = [s for s in self.app.suggestions(self.value) if s.lower().startswith(self.value.lower())]
        if not options:
            return
        if len(options) == 1:
            self.value = options[0]
            self.cursor_position = len(self.value)
            return
        self.app.show_suggestions(options)


# ------------------------------------------------------------------ panes and their screens


class ScreenView(VerticalScroll):
    """One function screen, drawn for this pane's width. Reads once; re-drawing at a new width reads nothing again."""

    DEFAULT_CSS = "ScreenView { padding: 0 1; }"
    BINDINGS = [Binding("w", "watch", "Watch")]

    def __init__(self, line, **kw):
        super().__init__(**kw)
        self.line, self.drawn_width, self.api = line, 0, None

    def compose(self) -> ComposeResult:
        yield Static("Loading", classes="body")

    def on_mount(self):
        self.api = CachedApi(self.app.api)
        self.call_after_refresh(self.redraw)

    def on_resize(self, event):
        if abs(self.size.width - self.drawn_width) > 1:
            self.call_after_refresh(self.redraw)

    @work(thread=True, exclusive=True, group="draw")
    def redraw(self):
        width = max(30, self.size.width - 3)
        text = self.app.draw_screen(self.line, width, self.api)
        self.app.call_from_thread(self._show, text, width)

    def _show(self, text, width):
        self.drawn_width = width + 3
        self.query_one(".body", Static).update(Text.from_ansi(text))

    @work(thread=True, group="watch")
    def action_watch(self):
        """w: watch this pane's disclosure or record, or stop watching it. Its changes appear in NEWS."""
        subject_text, code, opts = term.parse(shlex.split(self.line))
        ctx = self.app.ctx()
        if opts.get("disclosure"):
            ctx.context = opts["disclosure"]
        try:
            if not subject_text or code in ("PORT", "NEWS", "WATCH"):
                raise term_fail()("this pane has no disclosure or record to watch.")
            subject = term.resolve(ctx, subject_text)
            if subject["kind"] not in ("disclosure", "record"):
                raise term_fail()("only a disclosure or a record can be watched.")
            watching, _ = term.watch_toggle(ctx, subject)
            name = subject.get("name") or subject_text
            self.app.call_from_thread(self.app.notify, f"Watching {name}." if watching else f"Stopped watching {name}.")
        except ApiError as e:
            self.app.call_from_thread(self.app.notify, e.message, severity="error")
        except term_fail() as f:
            self.app.call_from_thread(self.app.notify, f.message, severity="warning")


class GuideView(VerticalScroll):
    """A topic of the guide shipped with this version (phaneris guide), or its list of topics. Reads nothing."""

    DEFAULT_CSS = "GuideView { padding: 0 1; }"

    def __init__(self, topic, **kw):
        super().__init__(**kw)
        self.topic = topic

    def compose(self) -> ComposeResult:
        yield Static("", classes="body")

    def on_mount(self):
        self.call_after_refresh(self.redraw)

    def on_resize(self, event):
        self.call_after_refresh(self.redraw)

    def redraw(self):
        from . import guide

        width = max(30, self.size.width - 3)
        slug = guide.find(self.topic) if self.topic else None
        lines = guide.render(slug, width) if slug else guide.contents(width)
        if self.topic and not slug:
            lines = [f'No topic "{self.topic}". The topics:', ""] + lines
        self.query_one(".body", Static).update(Text("\n".join(lines)))


class NewsView(Vertical):
    """NEWS as a table, newest first: Enter on a line opens its screen (a score move its history, a change its timeline)
    in a new tab. Showing it marks the feed as seen, as `phaneris feed` does."""

    def __init__(self, line, **kw):
        super().__init__(**kw)
        self.line, self.lines = line, {}

    def compose(self) -> ComposeResult:
        yield Static("", classes="title")
        yield DataTable(cursor_type="row", zebra_stripes=True)

    def on_mount(self):
        self.query_one(DataTable).add_columns("When", "Item", "What changed")
        self.load()

    @work(thread=True)
    def load(self):
        ctx = self.app.ctx()
        ctx.opts = term.parse(shlex.split(self.line))[2]
        try:
            res = term.feed(ctx)
            if not res.get("all"):
                self.app.api.post("/feed/seen", {})
        except ApiError as e:
            self.app.call_from_thread(self.app.notify, e.message, severity="error")
            return
        self.app.call_from_thread(self._fill, res)

    def _fill(self, res):
        s = Style(color=True, theme=self.app.theme_name, truecolor=True)
        since = res.get("since")
        extra = "since you started watching"
        if res.get("all"):
            extra = "everything kept"
        elif since:
            extra = f"since you last looked, {since[:16].replace('T', ' ')}"
        events = sum(len(i["events"]) for i in res.get("items") or [])
        note = f"{events} change{'s' if events != 1 else ''}" if events else "nothing new"
        if res.get("hidden"):
            note += f", {res['hidden']} not shown (no longer within reach)"
        self.query_one(".title", Static).update(Text.from_ansi(f"{s.accent('NEWS')}  {s.bold('What changed')}  {s.dim(extra + ', ' + note)}"))
        table = self.query_one(DataTable)
        rows = [(e, item) for item in res.get("items") or [] for e in item["events"]]
        rows.sort(key=lambda r: r[0]["at"], reverse=True)
        for e, item in rows:
            key = str(e["id"])
            self.lines[key] = term.open_line(item, e)
            what = Text.from_ansi(term.event_text(s, e))
            table.add_row(e["at"][:10], f"{item['label'][:32]}  {item['target']}", what, key=key)

    def on_data_table_row_selected(self, event):
        line = self.lines.get(event.row_key.value)
        if line:
            self.app.open_tab(line)


class BoardView(Vertical):
    """PORT as a table: Enter on a row opens that disclosure's SCR in a new tab."""

    def __init__(self, line, **kw):
        super().__init__(**kw)
        self.line = line

    def compose(self) -> ComposeResult:
        yield Static("", classes="title")
        yield DataTable(cursor_type="row", zebra_stripes=True)

    def on_mount(self):
        table = self.query_one(DataTable)
        table.add_columns("#", "ID", "Name", "Deal", "Rec.", "Real", "Metrics", "Flags")
        self.load()

    @work(thread=True)
    def load(self):
        try:
            res = self.app.api.get("/board")
        except ApiError as e:
            self.app.call_from_thread(self.app.notify, e.message, severity="error")
            return
        self.app.call_from_thread(self._fill, res)

    def _fill(self, res):
        from . import draw

        s = Style(color=True, theme=self.app.theme_name, truecolor=True)
        order = ["ipd", "ms", "eq", "ia", "tf", "rp", "fto", "ta", "cp"]
        self.query_one(".title", Static).update(
            Text.from_ansi(s.accent("PORT") + "  " + s.bold("Office board") + "  " + s.dim(res.get("office", "")))
        )
        table = self.query_one(DataTable)
        for i, r in enumerate(res.get("disclosures") or [], 1):
            by = {m["id"]: m for m in r["metrics"]}
            heat = Text.from_ansi("".join(draw.heat(s, by.get(m, {}).get("score"), by.get(m, {}).get("kind")) for m in order))
            flags = ", ".join(dict.fromkeys(r.get("flags_raised", []) + r.get("checks_raised", [])))
            table.add_row(
                str(i),
                r["id"],
                r["name"],
                pct(r["deal_chance"]["real_data"]),
                r.get("recommendation") or "",
                f"{round(r['real_share'] * 9)}/9",
                heat,
                flags,
                key=r["id"],
            )

    def on_data_table_row_selected(self, event):
        self.app.open_tab(f"{event.row_key.value} SCR")


class Walker(Horizontal):
    """GRF you can walk: arrows move between records, Enter re-centres on one (one more lookup), Backspace goes back,
    d shows the record's brief beside the map, o opens it in a new tab."""

    BINDINGS = [
        Binding("backspace", "back", "Back"),
        Binding("d", "brief", "Brief"),
        Binding("o", "open", "Open in a tab"),
    ]
    DEFAULT_CSS = """
    Walker OptionList { width: 1fr; }
    Walker .brief { width: 1fr; display: none; padding: 0 1; border-left: solid $panel-lighten-2; }
    Walker.-brief .brief { display: block; }
    """

    def __init__(self, line, **kw):
        super().__init__(**kw)
        self.line, self.trail, self.center, self.context = line, [], None, None

    def compose(self) -> ComposeResult:
        yield OptionList()
        yield VerticalScroll(Static("", classes="brief-body"), classes="brief")

    def on_mount(self):
        self.start()

    @work(thread=True)
    def start(self):
        ctx = self.app.ctx()
        subject_text, _, _ = term.parse(shlex.split(self.line))
        try:
            subject = term.resolve(ctx, subject_text)
        except term_fail() as f:
            self.app.call_from_thread(self.app.notify, f.message, severity="error")
            return
        except ApiError as e:
            self.app.call_from_thread(self.app.notify, e.message, severity="error")
            return
        self.context = ctx.context
        self._go(subject.get("node") or subject.get("id"), remember=False)

    def _query(self, **params):
        ctx = self.app.ctx()
        ctx.context = self.context or ctx.context
        return term._context_query(ctx, _bounded=True, **params)

    def _go(self, node, remember=True):
        try:
            res = self.app.api.get("/graph/map?" + self._query(node=node))
        except ApiError as e:
            msg = "Out of reach: lookups reach what your disclosure connects to." if e.code == "out_of_reach" else e.message
            self.app.call_from_thread(self.app.notify, msg, severity="warning")
            return
        except Exception as e:  # noqa: BLE001  a failed lookup leaves the map as it was
            self.app.call_from_thread(self.app.notify, str(e), severity="error")
            return
        self.app.call_from_thread(self._show, res, remember)

    def _show(self, res, remember):
        if remember and self.center:
            self.trail.append(self.center)
        self.center = res["center"]["id"]
        ol = self.query_one(OptionList)
        ol.clear_options()
        c = res["center"]
        ol.add_option(Option(Text.assemble(("● ", "bold"), (c.get("name") or c["id"], "bold"), "  ", (c["id"], "dim")), id="center"))
        for group in term.GROUP_ORDER:
            items = (res.get("groups") or {}).get(group)
            if not items:
                continue
            tot = res["totals"][group]
            ol.add_option(None)
            ol.add_option(Option(Text(f"{group}  ({tot['one']} linked, {tot['two']} two links out)", style="dim"), disabled=True))
            for n in items.get("one", []):
                ol.add_option(
                    Option(Text.assemble("  ", (n["id"], "bold"), "  ", n.get("name") or "", "  ", (n.get("relation", ""), "dim")), id="1|" + n["id"])
                )
            for n in items.get("two", [])[:6]:
                ol.add_option(
                    Option(Text.assemble("    ·· ", n["id"], "  ", n.get("name") or "", "  ", (f"via {n.get('via', '')}", "dim")), id="2|" + n["id"])
                )
        ol.highlighted = 0
        ol.focus()

    def _selected(self):
        ol = self.query_one(OptionList)
        if ol.highlighted is None:
            return None
        opt = ol.get_option_at_index(ol.highlighted)
        return self.center if opt.id == "center" else (opt.id or "").split("|", 1)[-1] or None

    def on_option_list_option_selected(self, event):
        node = self._selected()
        if node and node != self.center:
            self.run_worker(lambda: self._go(node), thread=True)

    def action_back(self):
        if self.trail:
            node = self.trail.pop()
            self.run_worker(lambda: self._go(node, remember=False), thread=True)

    def action_brief(self):
        node = self._selected()
        if not node:
            return
        self.add_class("-brief")
        self.run_worker(lambda: self._brief(node), thread=True)

    def _brief(self, node):
        try:
            rec = self.app.api.get("/graph/record?" + self._query(node=node))
        except ApiError as e:
            self.app.call_from_thread(self.app.notify, e.message, severity="warning")
            return
        r = rec.get("record") or {}
        lines = [Text(r.get("name") or node, style="bold"), Text(f"{r.get('type', '')} in {rec.get('graph', '')}", style="dim")]
        for k, v in list((r.get("fields") or {}).items())[:14]:
            val = term._value(v)
            if val is not None and k not in ("type", "label"):
                lines.append(Text.assemble((k.replace("_", " ") + ": ", "dim"), str(val)[:200]))
        if rec.get("claim_excerpt"):
            lines += [Text(""), Text("First claim (excerpt)", style="dim"), Text(rec["claim_excerpt"])]
        self.app.call_from_thread(self.query_one(".brief-body", Static).update, Text("\n").join(lines))

    def action_open(self):
        node = self._selected()
        if node:
            self.app.open_tab(f"{node} DES")


class AskView(Vertical):
    """A conversation about the subject: keeps the earlier questions, shows the records cited and the questions left.
    The questions are not written to the history file."""

    DEFAULT_CSS = "AskView RichLog { height: 1fr; } AskView Input { dock: bottom; }"

    def __init__(self, line, **kw):
        super().__init__(**kw)
        self.line, self.scope, self.turns = line, None, []

    def compose(self) -> ComposeResult:
        yield RichLog(wrap=True, markup=False)
        yield Input(placeholder="Ask a question, then Enter")

    def on_mount(self):
        self.prepare()

    @work(thread=True)
    def prepare(self):
        ctx = self.app.ctx()
        subject_text, _, opts = term.parse(shlex.split(self.line))
        try:
            subject = term.resolve(ctx, subject_text)
        except (term_fail(), ApiError) as e:
            self.app.call_from_thread(self.app.notify, getattr(e, "message", str(e)), severity="error")
            return
        if subject["kind"] == "disclosure":
            self.scope, about = {"kind": "disclosure", "disclosure": subject["id"]}, subject["name"]
        elif ctx.context and not opts.get("graph"):
            self.scope, about = {"kind": "disclosure", "disclosure": ctx.context}, f"{subject.get('name')}, around {ctx.context}"
        else:
            self.scope, about = {"kind": "graph"}, "the whole knowledge graph (metered)"
        self.app.call_from_thread(self.query_one(RichLog).write, Text(f"Asking about {about}.", style="bold"))

    def on_input_submitted(self, event):
        q = event.value.strip()
        event.input.value = ""
        if q and self.scope:
            self.query_one(RichLog).write(Text("› " + q, style="bold"))
            self.ask(q)

    @work(thread=True)
    def ask(self, q):
        from .main import cited, quota_line, strip_cites

        log = self.query_one(RichLog)
        try:
            res = self.app.api.post("/explore", {"question": q, "history": self.turns[-12:], "scope": self.scope})
        except ApiError as e:
            self.app.call_from_thread(log.write, Text(e.message, style="red"))
            return
        self.turns += [{"role": "user", "content": q}, {"role": "assistant", "content": res.get("answer", "")}]
        lines = [Text(strip_cites(res.get("answer", "")))]
        refs = cited(res)
        if refs:
            lines.append(Text("Records cited: " + "; ".join(f"{c['name']} ({c['cite']})" for c in refs[:6]), style="dim"))
        lines.append(Text(quota_line(res.get("quota")), style="dim"))
        for t in lines:
            self.app.call_from_thread(log.write, t)
        self.app.call_from_thread(self.app.refresh_status)


def term_fail():
    from .main import Fail

    return Fail


class Pane(Vertical, can_focus=False):
    DEFAULT_CSS = """
    Pane { border: round $panel-lighten-2; }
    Pane.-focused { border: round $accent; }
    """

    def compose(self) -> ComposeResult:
        yield TabbedContent()

    @property
    def tabs(self):
        return self.query_one(TabbedContent)


# ------------------------------------------------------------------ overlays


HELP_TEXT = """\
[b]Phaneris full-screen mode[/b]

[b]The bar[/b]   type a subject and a code, then Enter: it opens in the pane in focus, in a new tab.
  T-000003 SCR   "Carl H. June" GRF   US 8916381 OWN   A61K CLS   PORT
  Tab suggests from your own earlier commands; the best one shows dimmed, Right arrow takes it.
  :save NAME   :load NAME   :layouts   :theme amber|phaneris   :guide TOPIC   :quit
  ? TOPIC opens a topic of the guide in a tab (? guide: the list)

[b]Keys[/b]
  ctrl+k or /       the bar                 ctrl+n          a new pane (up to four)
  f6, ctrl+right    next pane               shift+f6        previous pane
  [  ]              previous, next tab      ctrl+w          close the tab
  <  >              narrow, widen the pane  ctrl+x          close the pane
  ctrl+s            save this layout        ?  f1           this help
  ctrl+q            leave

[b]In a map (GRF)[/b]   arrows move, Enter re-centres (one lookup), Backspace goes back,
  d shows the record's brief beside it, o opens it in a new tab.
[b]On the board (PORT)[/b]   Enter opens the disclosure's scores.
[b]In NEWS[/b]   Enter opens what changed: a score move its history, anything else its timeline.
[b]On a disclosure or record[/b]   w watches it, or stops watching it.

Codes: DES what it is · SCR scores · WHY what moves the score · CMP comparables · OWN timeline
       CLS class trends · GRF neighbourhood map · ASK a conversation · PORT office board
       HIST score history · WATCH watch it · NEWS what changed in what you watch

Press any key to close."""


class HelpScreen(ModalScreen):
    DEFAULT_CSS = """
    HelpScreen { align: center middle; }
    HelpScreen > Static { width: 90; height: auto; padding: 1 2; border: round $accent; background: $surface; }
    """

    def compose(self) -> ComposeResult:
        yield Static(HELP_TEXT)

    def on_key(self, event):
        event.stop()
        self.dismiss()


class LockScreen(ModalScreen):
    """Shown after a long time without use. Covers every pane; any key brings them back. Nothing is stored: if the
    sign-in has ended in the meantime, it says to sign in again from the command line."""

    DEFAULT_CSS = (
        "LockScreen { align: center middle; background: $background 100%; } LockScreen > Static { width: 70; padding: 1 2; border: round $accent; }"
    )

    def compose(self) -> ComposeResult:
        minutes = round(self.app.idle_seconds / 60)
        yield Static(
            f"[b]phaneris.[/b]  Locked after {minutes} minutes without use.\n\n"
            "Press any key to carry on. If your sign-in has ended, leave with ctrl+q and run: phaneris login"
        )

    def on_key(self, event):
        event.stop()
        self.app.last_activity = time.monotonic()
        self.dismiss()
        self.app.check_sign_in()


# ------------------------------------------------------------------ the app


class PhanerisApp(App):
    TITLE = "phaneris"
    CSS = """
    Screen { layout: vertical; }
    #bar { margin: 0 1; }
    #suggest { display: none; height: auto; max-height: 12; margin: 0 1; }
    #suggest.-show { display: block; }
    #panes { grid-size: 1 1; grid-gutter: 0 1; height: 1fr; }
    #status { height: 1; padding: 0 1; background: $panel; color: $text-muted; }
    .amber Screen, .amber { background: #000000; }
    .amber #status { background: #1a1200; color: #ffb000; }
    .amber Pane.-focused { border: round #ffbf00; }
    """
    BINDINGS = [
        Binding("ctrl+k", "focus_bar", "Bar"),
        Binding("slash", "focus_bar", show=False),
        Binding("ctrl+n", "new_pane", "New pane", priority=True),
        Binding("ctrl+w", "close_tab", "Close tab", priority=True),
        Binding("ctrl+x", "close_pane", "Close pane", priority=True),
        Binding("f6", "next_pane", "Next pane", priority=True),
        Binding("ctrl+right", "next_pane", show=False),
        Binding("shift+f6", "prev_pane", show=False, priority=True),
        Binding("ctrl+left", "prev_pane", show=False),
        Binding("left_square_bracket", "tab(-1)", show=False),
        Binding("right_square_bracket", "tab(1)", show=False),
        Binding("less_than_sign", "resize(-0.1)", show=False),
        Binding("greater_than_sign", "resize(0.1)", show=False),
        Binding("question_mark", "help", "Help"),
        Binding("f1", "help", show=False),
        Binding("ctrl+s", "save_layout", "Save layout", priority=True),
        Binding("ctrl+q", "quit", "Leave", priority=True),
        Binding("escape", "hide_suggestions", show=False),
    ]

    def __init__(self, api, args, start=None, idle_seconds=None):
        super().__init__()
        self.api, self.args, self.start_line = api, args, start
        self.theme_name = (getattr(args, "theme", None) or os.environ.get("PHANERIS_THEME") or "phaneris").lower()
        self.idle_seconds = idle_seconds or float(os.environ.get("PHANERIS_IDLE_MINUTES", IDLE_SECONDS / 60)) * 60
        self.last_activity = time.monotonic()
        self.focused_pane = 0
        self.split = 0.5
        self.recent = []
        self.tab_lines = {}
        self._tab_n = 0
        self.is_locked = False

    # ---------------------------------------------------------------- building blocks

    def compose(self) -> ComposeResult:
        yield CommandBar(placeholder="Subject and code, then Enter.  T-000003 SCR   ? help", id="bar", suggester=HistorySuggester(self))
        yield OptionList(id="suggest")
        yield Grid(Pane(), id="panes")
        yield Static("", id="status")

    def on_mount(self):
        if self.theme_name == "amber":
            self.screen.add_class("amber")
            self.add_class("amber")
        self.panes()[0].add_class("-focused")
        self.query_one("#bar").focus()
        self.refresh_status()
        self.set_interval(5, self.check_idle_lock)
        if self.start_line:
            self.open_tab(self.start_line)
        elif "default" in read_layouts():
            self.load_layout("default", quiet=True)
        else:  # the default layout: what changed in what you watch
            self.open_tab("NEWS")

    def panes(self):
        return list(self.query(Pane))

    def pane(self):
        panes = self.panes()
        self.focused_pane = min(self.focused_pane, len(panes) - 1)
        return panes[self.focused_pane]

    def ctx(self):
        """A non-interactive context for resolving subjects in the background."""
        from .main import Out

        out = Out(self.args)
        c = term.Ctx(self.api, out, self.args, style=Style(color=True, theme=self.theme_name, truecolor=True))
        c.interactive = False
        c.opts = {}
        return c

    def draw_screen(self, line, width, api):
        """A screen's text, drawn `width` characters wide, as ANSI."""
        from .main import Fail, Out, explain

        lines = []
        out = Out(self.args)
        style = Style(color=True, theme=self.theme_name, width=width, truecolor=True)
        ctx = term.Ctx(api, out, self.args, sink=lines, style=style)
        ctx.interactive = False
        try:
            term.run(ctx, shlex.split(line))
        except Fail as f:
            lines.append(style.bad("error: ") + f.message + (("\n" + style.dim("next: " + f.hint)) if f.hint else ""))
        except ApiError as e:
            f = explain(e)
            lines.append(style.bad("error: ") + f.message + (("\n" + style.dim("next: " + f.hint)) if f.hint else ""))
        self._remember(ctx)
        return "\n".join(lines)

    def _remember(self, ctx):
        for r in ctx.recent:
            if r not in self.recent:
                self.recent.insert(0, r)
        del self.recent[40:]

    def suggestions(self, typed):
        return history.suggestions(typed, history.load(), CODES, self.recent)

    # ---------------------------------------------------------------- the bar

    def show_suggestions(self, options):
        box = self.query_one("#suggest", OptionList)
        box.clear_options()
        for o in options:
            box.add_option(Option(o))
        box.add_class("-show")
        box.highlighted = 0
        box.focus()

    def action_hide_suggestions(self):
        self.query_one("#suggest").remove_class("-show")

    def on_option_list_option_selected(self, event):
        if event.option_list.id != "suggest":
            return
        bar = self.query_one("#bar", Input)
        bar.value = str(event.option.prompt)
        bar.cursor_position = len(bar.value)
        event.option_list.remove_class("-show")
        bar.focus()

    def on_input_submitted(self, event):
        if event.input.id != "bar":
            return
        line = event.value.strip()
        event.input.value = ""
        if not line:
            return
        if line in ("?", "help", "HELP"):
            return self.action_help()
        if line.startswith("?"):  # ? TOPIC: that topic of the guide
            return self.open_tab(":guide " + line[1:].strip())
        if line.startswith(":guide"):
            return self.open_tab(line)
        if line.startswith(":"):
            return self.colon(line[1:].split())
        history.add(line)
        self.open_tab(line)

    def colon(self, words):
        cmd, arg = (words + [""])[0].lower(), (words + ["", ""])[1]
        if cmd == "save":
            self.save_layout(arg or "default")
        elif cmd == "load":
            self.load_layout(arg or "default")
        elif cmd == "layouts":
            self.notify(", ".join(read_layouts()) or "No saved layouts yet.")
        elif cmd == "theme" and arg in ("amber", "phaneris"):
            self.theme_name = arg
            self.set_class(arg == "amber", "amber")
            self.screen.set_class(arg == "amber", "amber")
            self.notify(f"Theme {arg}; new tabs use it.")
        elif cmd in ("quit", "q"):
            self.exit()
        else:
            self.notify("Unknown. Try :save NAME, :load NAME, :layouts, :theme amber, :guide TOPIC, :quit", severity="warning")

    # ---------------------------------------------------------------- panes and tabs

    def open_tab(self, line, pane=None):
        """Open one screen in a new tab of the pane in focus (or the pane given). ":guide TOPIC" opens the guide."""
        if line.startswith(":guide"):
            topic = line[len(":guide") :].strip()
            return self._add_tab(line, f"Guide {topic}".strip(), GuideView(topic), pane)
        subject, code, _ = term.parse(shlex.split(line))
        views = {"PORT": BoardView, "GRF": Walker, "ASK": AskView, **({"NEWS": NewsView} if not subject else {})}
        widget = views.get(code, ScreenView)(line)
        return self._add_tab(line, f"{subject} {code}".strip() if subject else code, widget, pane)

    def _add_tab(self, line, title, widget, pane=None):
        self._tab_n += 1
        tab_id = f"tab{self._tab_n}"
        target = pane if pane is not None else self.pane()
        self.tab_lines[tab_id] = line
        target.tabs.add_pane(TabPane(title[:28], widget, id=tab_id))
        target.tabs.active = tab_id
        return tab_id

    def action_focus_bar(self):
        self.query_one("#bar").focus()

    def _focus(self, i):
        panes = self.panes()
        self.focused_pane = i % len(panes)
        for n, p in enumerate(panes):
            p.set_class(n == self.focused_pane, "-focused")
        active = self.pane().tabs.active_pane
        if active:
            active.focus()

    def action_next_pane(self):
        self._focus(self.focused_pane + 1)

    def action_prev_pane(self):
        self._focus(self.focused_pane - 1)

    def _arrange(self):
        n = len(self.panes())
        grid = self.query_one("#panes")
        grid.styles.grid_size_columns = 1 if n == 1 else 2
        grid.styles.grid_size_rows = 1 if n <= 2 else 2
        a = round(self.split * 10)
        grid.styles.grid_columns = "1fr" if n == 1 else f"{a}fr {10 - a}fr"

    def action_new_pane(self):
        if len(self.panes()) >= MAX_PANES:
            self.notify("Four panes at most.", severity="warning")
            return
        self.query_one("#panes").mount(Pane())
        self.call_after_refresh(self._after_new_pane)

    def _after_new_pane(self):
        self._arrange()
        self._focus(len(self.panes()) - 1)
        self.action_focus_bar()

    def action_close_tab(self):
        tabs = self.pane().tabs
        if tabs.active:
            self.tab_lines.pop(tabs.active, None)
            tabs.remove_pane(tabs.active)

    def action_close_pane(self):
        panes = self.panes()
        if len(panes) == 1:
            for tab in list(panes[0].tabs.query(TabPane)):
                self.tab_lines.pop(tab.id, None)
            panes[0].tabs.clear_panes()
            return
        doomed = self.pane()
        for tab in doomed.tabs.query(TabPane):
            self.tab_lines.pop(tab.id, None)
        doomed.remove()
        self.call_after_refresh(lambda: (self._arrange(), self._focus(max(0, self.focused_pane - 1))))

    def action_tab(self, step):
        tabs = self.pane().tabs
        ids = [t.id for t in tabs.query(TabPane)]
        if ids and tabs.active in ids:
            tabs.active = ids[(ids.index(tabs.active) + step) % len(ids)]

    def action_resize(self, step):
        if len(self.panes()) < 2:
            return
        column = self.focused_pane % 2
        self.split = min(0.8, max(0.2, self.split + (step if column == 0 else -step)))
        self._arrange()

    # ---------------------------------------------------------------- layouts

    def layout_now(self):
        panes = []
        for p in self.panes():
            panes.append({"tabs": [self.tab_lines[t.id] for t in p.tabs.query(TabPane) if t.id in self.tab_lines]})
        return {"panes": panes, "split": self.split, "theme": self.theme_name}

    def save_layout(self, name):
        data = read_layouts()
        data[name] = self.layout_now()
        write_layouts(data)
        self.notify(f"Layout {name} saved.")

    def action_save_layout(self):
        self.save_layout("default")

    def load_layout(self, name, quiet=False):
        layout = read_layouts().get(name)
        if not layout:
            if not quiet:
                self.notify(f"No layout called {name}.", severity="warning")
            return
        self.split = float(layout.get("split", 0.5))
        wanted = [p.get("tabs", []) for p in layout.get("panes", [])][:MAX_PANES] or [[]]
        grid = self.query_one("#panes")
        for p in self.panes():
            p.remove()
        self.tab_lines.clear()
        new = [Pane() for _ in wanted]
        grid.mount(*new)

        def fill():
            self._arrange()
            for pane, lines in zip(self.panes(), wanted, strict=False):
                for line in lines:
                    self.open_tab(line, pane=pane)
            self._focus(0)
            if not quiet:
                self.notify(f"Layout {name} loaded.")

        self.call_after_refresh(fill)

    # ---------------------------------------------------------------- status, help, idle lock

    @work(thread=True, exclusive=True, group="status")
    def refresh_status(self):
        parts = []
        try:
            me = self.api.get("/auth/me")["user"]
            parts.append(f"{me['display_name']} ({me['role']})")
            parts.append(f"office {me['workspace']}")
        except ApiError as e:
            parts.append(e.message)
        try:
            q = self.api.get("/explore/usage")["quota"]
            parts.append(
                "questions: no limit" if q.get("unlimited") else f"questions {q['free_left']} of {q['limit']} free, {q.get('credits', 0)} bought"
            )
        except ApiError:
            pass
        try:
            v = self.api.get("/health").get("version", "?")
        except ApiError:
            v = "unreachable"
        parts.append(f"server {v} · phaneris {__version__} · ? help")
        self.call_from_thread(self.query_one("#status", Static).update, "  ·  ".join(parts))

    def action_help(self):
        self.push_screen(HelpScreen())

    async def on_event(self, event):
        if isinstance(event, (events.Key, events.MouseDown, events.Paste)):
            self.last_activity = time.monotonic()
        await super().on_event(event)

    def check_idle_lock(self):
        if not self.is_locked and time.monotonic() - self.last_activity >= self.idle_seconds:
            self.lock_screen()

    def lock_screen(self):
        self.is_locked = True
        self.push_screen(LockScreen(), callback=lambda _: setattr(self, "locked", False))

    @work(thread=True)
    def check_sign_in(self):
        try:
            self.api.get("/auth/me")
        except ApiError as e:
            if e.status == 401:
                self.call_from_thread(self.notify, "Your sign-in has ended. Leave with ctrl+q and run: phaneris login", severity="error", timeout=30)


def run(api, args, start=None):
    PhanerisApp(api, args, start=start).run()
