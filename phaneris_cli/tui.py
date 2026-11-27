"""Full-screen mode: `phaneris tui` (or `phaneris` with no words when the optional extra is installed).

A command bar on top (the same grammar, with Tab suggestions from your own history), up to four panes with tabs, a
status line, a help overlay, two themes, an idle lock, and saved layouts. Every pane shows one screen (DES, SCR, WHY,
CMP, OWN, CLS, HIST, GRF, PORT, ASK) drawn for the pane's width from the same server routes as the command line, under the
same bounds and limits. Needs Textual: `pipx inject phaneris-cli textual`.
"""

import json
import os
import re
import shlex
import stat
import time
from urllib.parse import quote

from rich.text import Text
from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.css.query import NoMatches
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.suggester import Suggester
from textual.widgets import DataTable, Input, OptionList, RichLog, Static, TabbedContent, TabPane, Tree
from textual.widgets.option_list import Option

from . import __version__, graphview, history, idle, store, term
from .api import ApiError, CachedApi
from .style import Style, pct

MAX_PANES = 4
STATUS_SECONDS = 60
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
    """One function screen, drawn for this pane's width. Reads once; re-drawing at a new width reads nothing again.
    g opens the node-link graph of its subject."""

    DEFAULT_CSS = "ScreenView { padding: 0 1; }"
    BINDINGS = [Binding("g", "graph", "Graph")]

    def action_graph(self):
        subject, code, opts = term.parse(shlex.split(self.line))
        if not subject or code in ("PORT", "HELP"):
            return self.app.notify("This pane has no disclosure or record to draw.", severity="warning")
        around = f" --disclosure {term.arg(opts['disclosure'])}" if opts.get("disclosure") else ""
        self.app.open_tab(f"{term.arg(subject)} GRAPH{around}")

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
        text = self.app.draw_screen(self.line, width, self.api, view=self)
        self.app.call_from_thread(self._show, text, width)

    def _show(self, text, width):
        self.drawn_width = width + 3
        self.query_one(".body", Static).update(Text.from_ansi(text))
        choices = getattr(self, "choices", None)
        if choices and not self.query("#choices"):
            box = OptionList(*[Option(label, id=str(i)) for i, (label, _) in enumerate(choices)], id="choices")
            self.mount(box)
            box.focus()
        self.app.server_answered()

    def on_option_list_option_selected(self, event):
        """A row of matches: Enter opens that one with the same code, in a new tab (the list stays, to open others)."""
        if event.option_list.id == "choices":
            event.stop()
            self.app.open_tab(self.choices[int(event.option.id)][1])


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


WELCOME = """\
[b]The Phaneris window[/b]   type in the bar above, then Enter.

  [b]Open anything[/b]   a disclosure id or title, a person, an owner, a patent or a class, then a code
                  T-000003 SCR    "Carl H. June" GRF    US 8916381 OWN    A61K CLS    (no code: DES)
  [b]Ask[/b]             a question ending in ?, or ask ...    about the disclosure that is open
                  /kg QUESTION or Ctrl-G                 across the whole knowledge graph
                  the chip beside the bar shows which one Enter will use, before anything is sent
  [b]Tab[/b] completes from what you ran before    [b]?[/b] help    [b]? TOPIC[/b] the guide    [b]Ctrl-B[/b] buy 100 questions ($5)
"""


class WelcomeView(BoardView):
    """The window's first pane: what to type, the person's disclosures (PORT, Enter opens one, g its graph) and their
    question allowances."""

    BINDINGS = [Binding("g", "graph", "Graph of the disclosure")]

    def action_graph(self):
        table = self.query_one(DataTable)
        if table.row_count:
            did = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
            self.app.open_tab(f"{term.arg(did)} GRAPH")

    def compose(self) -> ComposeResult:
        yield Static(WELCOME, classes="intro")
        yield Static("", classes="allowances")
        yield Static("", classes="title")
        yield DataTable(cursor_type="row", zebra_stripes=True)

    def on_mount(self):  # Textual also runs BoardView.on_mount (the table and the board)
        self.allowances()

    @work(thread=True)
    def allowances(self):
        try:
            usage = self.app.api.get("/explore/usage")
        except ApiError:
            return
        line = "  " + term.allowances_line(usage) + ".  Buying more: Ctrl-B or phaneris buy."
        self.app.call_from_thread(self.query_one(".allowances", Static).update, line)


class RelatedView(Vertical):
    """REL in the window: the disclosure's related knowledge graph as an expandable tree, grouped by kind with counts.
    Enter opens a record (a class in CLS, one of your disclosures in SCR, anything else in DES); g its map, o its
    timeline, c its class trends. Everything stays within the disclosure's reach."""

    BINDINGS = [Binding("g", "graph", "Graph"), Binding("o", "open('OWN')", "Timeline"), Binding("c", "open('CLS')", "Class")]
    DEFAULT_CSS = "RelatedView Tree { height: 1fr; }"

    def action_graph(self):
        """g: the node-link graph of the record under the cursor, or of the disclosure itself."""
        node = self.query_one(Tree).cursor_node
        if node is not None and node.data:
            return self._open(node.data, "GRAPH")
        if self.did:
            self.app.open_tab(f"{term.arg(self.did)} GRAPH")

    def __init__(self, line, **kw):
        super().__init__(**kw)
        self.line, self.did = line, None

    def compose(self) -> ComposeResult:
        yield Static("Loading", classes="title")
        yield Tree("Related knowledge graph")

    def on_mount(self):
        self.load()

    @work(thread=True)
    def load(self):
        ctx = self.app.ctx()
        subject_text = term.parse(shlex.split(self.line))[0]
        try:
            subject = term.resolve(ctx, subject_text)
            if subject["kind"] != "disclosure":
                raise term_fail()("REL is for one of your disclosures.")
            rel = term.related(ctx, subject["id"])
        except ApiError as e:
            from .main import explain

            f = explain(e)
            return self.app.call_from_thread(self._error, f.message + (f"  {f.hint}" if f.hint else ""))
        except term_fail() as f:
            return self.app.call_from_thread(self._error, f.message)
        self.did = subject["id"]
        self.app.call_from_thread(self._fill, rel)

    def _error(self, message):
        self.query_one(".title", Static).update(Text(message, style="red"))

    def _fill(self, rel):
        total = sum(g["count"] for g in rel["groups"])
        self.query_one(".title", Static).update(
            Text.from_markup(
                f"[b]REL[/b]  [b]{rel['name']}[/b]  {rel['id']}  [dim]{total} records within its reach. "
                "Enter opens one, g map, o timeline, c class trends.[/dim]"
            )  # fmt: skip
        )
        tree = self.query_one(Tree)
        tree.root.set_label(f"{rel['name']}  {rel['id']}")
        for i, g in enumerate(rel["groups"]):
            branch = tree.root.add(f"{g['group'].capitalize()} ({g['count']})", expand=i == 0)
            for r in g["records"]:
                links = "linked" if r.get("links") == 1 else f"{r['links']} links out" if r.get("links") else ""
                branch.add_leaf(f"{(r.get('name') or r['id'])[:70]}  {r['id']}  {links}".rstrip(), data=(r["id"], g["group"]))
        tree.root.expand()
        tab = self.app._tab_of(self)
        if tab and any(p.tabs.active == tab for p in self.app.panes()):  # focusing a widget in a background tab would bring it forward
            tree.focus()

    def _open(self, data, code=None):
        node, group = data
        ctx = self.app.ctx()
        ctx.context = self.did
        code = code or term.REL_CODE.get(group, "DES")
        line = f"{term.arg(node)} {code}" if group == "your other disclosures" else term._line(ctx, node, code)
        if ctx.role == "admin" and group != "your other disclosures":  # admins: still around this disclosure, like everyone
            line += f" --disclosure {term.arg(self.did)}"
        self.app.open_tab(line)

    def on_tree_node_selected(self, event):
        if event.node.data:
            event.stop()
            self._open(event.node.data)

    def action_open(self, code):
        node = self.query_one(Tree).cursor_node
        if node is not None and node.data:
            self._open(node.data, code)


class GraphView(Vertical, can_focus=True):
    """GRAPH in the window: the knowledge graph as nodes and edges (graphview.py), drawn for the pane's size.
    Arrows pan, + and - zoom, 0 resets, Tab and Shift-Tab move the selection (nearest first), Enter re-centres on it,
    e expands it one step, f filters kinds (then 1 to 9), l labels, d its brief, o / c / s open OWN / CLS / SCR.
    A click selects the nearest node. Everything stays within the reach of the disclosure in use (admins: anywhere)."""

    DEFAULT_CSS = """
    GraphView { padding: 0 1; }
    GraphView #canvas-row { height: 1fr; }
    GraphView #canvas { width: 1fr; height: 1fr; }
    GraphView #side { width: 42; display: none; padding: 0 1; border-left: solid $panel-lighten-2; }
    GraphView #side.-show { display: block; }
    GraphView #info { height: auto; max-height: 3; color: $text-muted; }
    """
    BINDINGS = [
        Binding("left", "pan(-1, 0)", show=False), Binding("right", "pan(1, 0)", show=False),
        Binding("up", "pan(0, -1)", show=False), Binding("down", "pan(0, 1)", show=False),
        Binding("plus,equals_sign", "zoom(1.25)", "Zoom in", show=False), Binding("minus", "zoom(0.8)", "Zoom out", show=False),
        Binding("0", "reset", show=False), Binding("tab", "cycle(1)", priority=True, show=False),
        Binding("shift+tab", "cycle(-1)", priority=True, show=False), Binding("enter", "recentre", show=False),
        Binding("e", "expand", "Expand"), Binding("f", "filter", "Filter"), Binding("l", "labels", "Labels"),
        Binding("d", "brief", "Brief"), Binding("o", "open('OWN')", show=False), Binding("c", "open('CLS')", show=False),
        Binding("s", "open('SCR')", show=False),
    ] + [Binding(str(i), f"toggle_kind({i})", show=False) for i in range(1, 10)]  # fmt: skip

    def __init__(self, line, cited=None, disclosure=None, **kw):
        super().__init__(**kw)
        self.line, self.cited, self.disclosure = line, cited, disclosure
        self.sub, self.pos, self.at, self.selected = None, {}, {}, None
        self.view = graphview.View()
        self.labels, self.hidden, self.filtering = True, set(), False

    def compose(self) -> ComposeResult:
        with Horizontal(id="canvas-row"):
            yield Static("Loading the graph", id="canvas")
            yield Static("", id="side")
        yield Static("", id="info")

    def on_mount(self):
        self.load()

    def ctx(self):
        ctx = self.app.ctx()
        if self.disclosure:
            ctx.context = self.disclosure
        return ctx

    @work(thread=True, exclusive=True, group="graph")
    def load(self, node=None):
        from .main import explain

        ctx = self.ctx()
        try:
            if self.cited is not None and node is None:
                sub = term.subgraph_of(ctx, self.cited, self.disclosure)
            else:
                text, _, opts = term.parse(shlex.split(self.line)) if node is None else (node, None, {})
                if opts.get("disclosure"):
                    ctx.context = self.disclosure = opts["disclosure"]
                subject = term.resolve(ctx, text) if node is None else {"kind": "record", "node": node, "name": node}
                if subject["kind"] == "disclosure":
                    self.disclosure = self.disclosure or subject["id"]
                sub = term.subgraph(ctx, subject, opts.get("depth") or 1)
            self.disclosure = self.disclosure or ctx.context
        except ApiError as e:
            f = explain(e)
            return self.app.call_from_thread(self._message, f.message + (f"  {f.hint}" if f.hint else ""))
        except term_fail() as f:
            return self.app.call_from_thread(self._message, f.message)
        self.app.call_from_thread(self._show, sub)

    def _message(self, text):
        self.query_one("#canvas", Static).update(Text(text, style="yellow"))

    def _show(self, sub, keep=None):
        self.sub = sub
        self.pos = graphview.layout(sub["nodes"], sub["edges"], sub.get("center"), fixed=keep)
        if keep is None:
            self.selected = self.anchor = sub.get("center")
            self.view.reset()
        self.redraw()

    def on_resize(self, event):
        self.redraw()

    def redraw(self):
        if not self.sub:
            return
        canvas = self.query_one("#canvas", Static)
        cols, rows = max(20, canvas.size.width), max(8, canvas.size.height)
        theme = self.app.theme_name if self.app.theme_name in ("phaneris", "amber") else "phaneris"
        cells, self.at = graphview.render(self.sub, self.pos, cols, rows, theme, self.view, self.selected, self.labels, self.hidden)
        canvas.update(cells_text(cells))
        self.query_one("#info", Static).update(self.info(theme))

    def info(self, theme):
        s = Style(color=True, theme=theme, truecolor=True)
        legend = term.graph_footer(s, self.sub, self.hidden)
        n = self.node(self.selected)
        sel = f"{n['label']}  ({n['kind']}, {n['id']}, {n.get('degree', 0)} links)" if n else ""
        keys = "arrows pan  + - zoom  0 reset  Tab next  Enter re-centre  e expand  f filter  l labels  d brief  o c s open"
        return Text.from_ansi(f"{legend}\n{s.bold(sel)}\n{s.dim(keys)}")

    def node(self, ident):
        return next((n for n in (self.sub or {}).get("nodes", []) if n["id"] == ident), None)

    # ------------------------------------------------------------ keys

    def action_pan(self, dx, dy):
        self.view.pan(dx, dy)
        self.redraw()

    def action_zoom(self, factor):
        self.view.scale(float(factor))
        self.redraw()

    def action_reset(self):
        if self.filtering:
            return
        self.view.reset()
        self.redraw()

    def action_cycle(self, step):
        if getattr(self, "anchor", None) not in self.at:
            self.anchor = self.selected
        self.selected = graphview.nearest(self.at, self.selected, int(step), self.anchor)
        self.redraw()

    def action_recentre(self):
        if self.selected and self.selected != (self.sub or {}).get("center"):
            self.cited = None
            self.load(self.selected)

    @work(thread=True, exclusive=True, group="graph")
    def action_expand(self):
        if not self.selected:
            return
        ctx = self.ctx()
        try:
            more = term.subgraph(ctx, {"kind": "record", "node": self.selected, "name": self.selected})
        except ApiError as e:
            return self.app.call_from_thread(self.app.notify, e.message, severity="warning")
        merged = graphview.merge(self.sub, more)
        self.app.call_from_thread(self._show, merged, dict(self.pos))

    def action_filter(self):
        self.filtering = not self.filtering
        side = self.query_one("#side", Static)
        side.set_class(self.filtering, "-show")
        self._filter_list()

    def _filter_list(self):
        if not self.filtering or not self.sub:
            return
        theme = self.app.theme_name if self.app.theme_name in ("phaneris", "amber") else "phaneris"
        rows = [Text("Kinds: press a number to show or hide, f to close", style="bold")]
        for i, (kind, n, off) in enumerate(graphview.legend(self.sub, self.hidden), 1):
            rgb = graphview.kind_rgb(theme, kind)
            rows.append(Text.assemble(f"{i}  ", ("[ ] " if off else "[x] "), (graphview.GLYPH[kind], f"rgb({rgb[0]},{rgb[1]},{rgb[2]})"),
                                      f" {kind} ({n})"))  # fmt: skip
        self.query_one("#side", Static).update(Text("\n").join(rows))

    def action_toggle_kind(self, number):
        if not self.filtering or not self.sub:
            return
        kinds = [k for k, _, _ in graphview.legend(self.sub, self.hidden)]
        if 1 <= int(number) <= len(kinds):
            self.hidden ^= {kinds[int(number) - 1]}
            self._filter_list()
            self.redraw()

    def action_labels(self):
        self.labels = not self.labels
        self.redraw()

    @work(thread=True)
    def action_brief(self):
        if not self.selected:
            return
        ctx = self.ctx()
        try:
            rec = self.app.api.get("/graph/record?" + term._context_query(ctx, node=self.selected, _bounded=True))
        except ApiError as e:
            return self.app.call_from_thread(self.app.notify, e.message, severity="warning")
        r = rec.get("record") or {}
        lines = [Text(r.get("name") or self.selected, style="bold"), Text(f"{r.get('type', '')} in {rec.get('graph', '')}", style="dim")]
        for k, v in list((r.get("fields") or {}).items())[:14]:
            val = term._value(v)
            if val is not None and k not in ("type", "label"):
                lines.append(Text.assemble((k.replace("_", " ") + ": ", "dim"), str(val)[:200]))
        self.filtering = False
        self.app.call_from_thread(self._side, Text("\n").join(lines))

    def _side(self, text):
        side = self.query_one("#side", Static)
        side.update(text)
        side.add_class("-show")

    def action_open(self, code):
        n = self.node(self.selected)
        if not n:
            return
        if code == "SCR" and n["kind"] != "disclosure":
            return self.app.notify("s opens a disclosure's scores; this is a " + n["kind"] + ".", severity="warning")
        if code == "CLS" and n["kind"] not in ("class", "patent", "disclosure"):
            return self.app.notify("c opens patent class trends: for a class, a patent or a disclosure.", severity="warning")
        ctx = self.ctx()
        line = f"{term.arg(n['id'])} {code}" if n["kind"] == "disclosure" else term._line(ctx, n["id"], code)
        self.app.open_tab(line)

    def on_click(self, event):
        canvas = self.query_one("#canvas", Static)
        if not self.at:
            return
        x, y = event.screen_x - canvas.region.x, event.screen_y - canvas.region.y
        self.selected = self.anchor = min(self.at, key=lambda i: (self.at[i][0] - y) ** 2 * 4 + (self.at[i][1] - x) ** 2)
        self.focus()
        self.redraw()


def cells_text(cells):
    """Canvas rows (char, rgb, bold) as one Rich Text."""
    out = Text()
    for r, row in enumerate(cells):
        if r:
            out.append("\n")
        run, key = "", None
        for ch, rgb, bold in row:
            k = (rgb, bold)
            if k != key and run:
                out.append(run, style=_rich_style(*key))
                run = ""
            key = k
            run += ch
        if run:
            out.append(run, style=_rich_style(*key))
    return out


def _rich_style(rgb, bold):
    style = f"rgb({rgb[0]},{rgb[1]},{rgb[2]})" if rgb else ""
    return (style + " bold").strip() if bold else style


class Walker(Horizontal):
    """GRF you can walk: arrows move between records, Enter re-centres on one (one more lookup), Backspace goes back,
    d shows the record's brief beside the map, o opens it in a new tab."""

    BINDINGS = [
        Binding("backspace", "back", "Back"),
        Binding("d", "brief", "Brief"),
        Binding("o", "open", "Open in a tab"),
        Binding("g", "graph", "Graph"),
    ]

    def action_graph(self):
        """g: the record in the middle of the map as a node-link graph."""
        node = self._selected() or self.center
        if node:
            around = f" --disclosure {term.arg(self.context)}" if self.context else ""
            self.app.open_tab(f"{term.arg(node)} GRAPH{around}")

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
        subject_text, _, opts = term.parse(shlex.split(self.line))
        ctx.opts = {"_code": "GRF"}
        if opts.get("disclosure"):
            ctx.context = opts["disclosure"]
        try:
            subject = term.resolve(ctx, subject_text)
        except term.Choose as c:  # several matches, or none: rows to choose from, as on any screen
            self.app.call_from_thread(self._choices, c)
            return
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

    def _choices(self, c):
        self.choices = c.choices
        for child in list(self.children):
            child.remove()
        box = OptionList(*[Option(label, id=str(i)) for i, (label, _) in enumerate(c.choices)], id="choices")
        self.mount(Vertical(Static(Text(c.message.split(":")[0] + ":  Enter opens one in a new tab.", style="bold")), box))
        box.focus()

    def on_option_list_option_selected(self, event):
        if event.option_list.id == "choices":
            event.stop()
            return self.app.open_tab(self.choices[int(event.option.id)][1])
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
    """A conversation in one scope: about a disclosure, or across the whole knowledge graph (metered). It keeps the
    earlier questions of this scope, shows the records each answer cites as rows (Enter opens DES, g opens GRF) and the
    questions left. Questions are never written to the history file."""

    DEFAULT_CSS = """
    AskView RichLog { height: 1fr; }
    AskView #cited { height: auto; max-height: 8; display: none; }
    AskView #cited.-show { display: block; }
    AskView Input { dock: bottom; }
    """
    BINDINGS = [Binding("g", "graph_map", "Graph of the record", show=False), Binding("G", "graph_all", "Graph of the cited records")]

    def __init__(self, line, scope=None, first=None, **kw):
        super().__init__(**kw)
        self.line, self.scope, self.turns, self.first = line, scope, [], first
        self.cites, self.briefs = [], {}

    def compose(self) -> ComposeResult:
        yield RichLog(wrap=True, markup=False)
        yield OptionList(id="cited")
        yield Input(placeholder="Ask a follow-up, then Enter")

    def on_mount(self):
        if self.scope:
            self._started()
        else:
            self.prepare()

    def about(self):
        return "the whole knowledge graph" if self.scope["kind"] == "graph" else f"disclosure {self.scope['disclosure']}"

    def _started(self):
        note = "metered: free ones first, then bought" if self.scope["kind"] == "graph" else "what it connects to"
        self.query_one(RichLog).write(Text(f"Asking about {self.about()} ({note}).", style="bold"))
        if self.first:
            self.send(self.first)
            self.first = None

    @work(thread=True)
    def prepare(self):
        """A conversation opened by a line (T-000003 ASK, ASK --graph): its scope from the subject."""
        ctx = self.app.ctx()
        subject_text, _, opts = term.parse(shlex.split(self.line))
        if opts.get("graph"):
            self.scope = {"kind": "graph"}
        else:
            try:
                subject = term.resolve(ctx, subject_text)
            except (term_fail(), ApiError) as e:
                self.app.call_from_thread(self.app.notify, getattr(e, "message", str(e)), severity="error")
                return
            d = subject["id"] if subject["kind"] == "disclosure" else ctx.context
            if not d:  # nothing to ask it about; the whole graph is metered, so only when the person asks for it
                note = (f"{subject.get('name') or subject_text} is not a disclosure, and no disclosure is open, so nothing will be asked "
                        "here. Open one of yours, or ask the whole knowledge graph: /kg QUESTION in the bar (or Ctrl-G).")  # fmt: skip
                return self.app.call_from_thread(self.query_one(RichLog).write, Text(note, style="yellow"))
            self.scope = {"kind": "disclosure", "disclosure": d}
        self.app.call_from_thread(self._started)

    def on_input_submitted(self, event):
        event.stop()
        q = event.value.strip()
        event.input.value = ""
        if q and self.scope:
            self.send(q)

    def send(self, q):
        self.query_one(RichLog).write(Text("› " + q, style="bold"))
        self.ask(q)

    @work(thread=True)
    def ask(self, q):
        from .main import cited, quota_line, strip_cites

        log = self.query_one(RichLog)
        try:
            res = self.app.api.post("/explore", {"question": q, "history": self.turns[-12:], "scope": self.scope})
        except ApiError as e:  # every failure is a plain line in the pane, with what to do next
            from .main import explain

            f = explain(e)
            hint = f.hint or ""
            if e.code == "question_limit" or e.status == 429:
                hint = "Buy 100 more for $5: Ctrl-B (twice), or phaneris buy."
            elif e.status == 401:
                hint = "Sign in again: leave with Ctrl-Q and run phaneris login."
            elif e.code == "not_your_disclosure":
                hint = "Open one of yours, or ask the whole knowledge graph: /kg QUESTION in the bar (or Ctrl-G)."
            self.app.call_from_thread(log.write, Text(f.message, style="red"))
            if hint:
                self.app.call_from_thread(log.write, Text(hint, style="dim"))
            self.app.call_from_thread(self.app.refresh_status)
            return
        self.turns += [{"role": "user", "content": q}, {"role": "assistant", "content": res.get("answer", "")}]
        self.app.call_from_thread(log.write, Text(strip_cites(res.get("answer", ""))))
        refs = cited(res)
        self.briefs.update(res.get("entities") or {})
        if refs:
            self.app.call_from_thread(
                log.write, Text("Records cited, below: Enter opens one (DES), g its graph; G all of them as one graph.", style="dim")
            )
        self.app.call_from_thread(log.write, Text(quota_line(res.get("quota")), style="dim"))
        self.app.call_from_thread(self._cited, refs)
        self.app.call_from_thread(self.app.refresh_status)

    def _cited(self, refs):
        box = self.query_one("#cited", OptionList)
        for r in refs:
            if r["cite"] not in self.cites:
                self.cites.append(r["cite"])
                box.add_option(Option(f"{r['name']}  {r['type']}  {node_of(r['cite'])}", id=r["cite"]))
        box.set_class(bool(self.cites), "-show")

    def on_option_list_option_selected(self, event):
        if event.option_list.id == "cited":
            event.stop()
            self.open_cited(event.option.id, "DES")

    def action_graph_map(self):
        box = self.query_one("#cited", OptionList)
        if box.has_focus and box.highlighted is not None:
            self.open_cited(box.get_option_at_index(box.highlighted).id, "GRAPH")

    def action_graph_all(self):
        """G: the records the answers cited, as one node-link graph (within reach, like every lookup)."""
        if not self.cites:
            return self.app.notify("No records cited yet.", severity="warning")
        disclosure = (self.scope or {}).get("disclosure") or self.app.ctx().context
        view = GraphView("GRAPH", cited=list(self.cites), disclosure=disclosure)
        self.app._add_tab(":graph-cited", "Graph: cited records", view)

    @work(thread=True)
    def open_cited(self, cite, code):
        """Open a cited record. Admins reach every record; everyone else only within reach of one of their disclosures,
        so it is checked first (one lookup); otherwise the brief the answer returned is shown, and why."""
        node = node_of(cite)
        ctx = self.app.ctx()
        around = self.scope.get("disclosure") or ctx.context
        if ctx.role != "admin":
            if not around:
                return self.app.call_from_thread(self._outside, cite, "no disclosure is open to look it up around")
            try:
                self.app.api.get(f"/graph/record?node={quote(node, safe='')}&disclosure={quote(around, safe='')}")
            except ApiError as e:
                if e.status in (400, 404):
                    return self.app.call_from_thread(self._outside, cite, f"it is outside the reach of {around}")
                return self.app.call_from_thread(self.app.notify, e.message, severity="error")
        ctx.context = around
        self.app.call_from_thread(self.app.open_tab, term._line(ctx, node, code))

    def _outside(self, cite, why):
        b = self.briefs.get(cite) or {}
        log = self.query_one(RichLog)
        log.write(Text(f"{b.get('name') or node_of(cite)}  {b.get('type', '')}  {node_of(cite)}", style="bold"))
        for k, v in b.items():
            if k not in ("name", "type", "id", "cite") and isinstance(v, (str, int, float)) and str(v).strip():
                log.write(Text(f"  {k.replace('_', ' ')}: {str(v)[:200]}"))
        log.write(Text(f"This is what the answer returned. It cannot be opened further: {why}. Lookups reach what your "
                       "disclosures connect to; ask the whole knowledge graph (/kg) for more.", style="dim"))  # fmt: skip


def node_of(cite):
    """The record id in a cite: graph:phaneron:author:ETHAN STANCLIFFE gives author:ETHAN STANCLIFFE."""
    return cite.split(":", 2)[2] if cite.count(":") >= 2 else cite


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

Codes: DES what it is · SCR scores · WHY what moves the score · CMP comparables · OWN timeline
       CLS class trends · GRF neighbourhood map · ASK a conversation · PORT office board
       HIST score history

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
    """Shown at the idle limit, after the sign-in has been ended on the server and forgotten here. Covers every pane;
    any key leaves full-screen mode."""

    DEFAULT_CSS = (
        "LockScreen { align: center middle; background: $background 100%; } LockScreen > Static { width: 70; padding: 1 2; border: round $accent; }"
    )

    def compose(self) -> ComposeResult:
        minutes = round(self.app.idle_seconds / 60)
        unit = "minute" if minutes == 1 else "minutes"
        yield Static(f"[b]phaneris.[/b]  Signed out after {minutes} {unit} without use.\n\nPress any key to leave, then run: phaneris login")

    def on_key(self, event):
        event.stop()
        self.app.exit()


# ------------------------------------------------------------------ the app


class PhanerisApp(App):
    TITLE = "phaneris"
    CSS = """
    Screen { layout: vertical; }
    #barrow { height: auto; }
    #bar { margin: 0 0 0 1; width: 1fr; }
    #scope { width: auto; height: 3; padding: 1 1; margin: 0 1 0 0; background: $panel; color: $text; }
    #scope.-graph { background: $accent; color: $text; }
    WelcomeView .intro { padding: 0 1; }
    WelcomeView .allowances { padding: 0 1 1 1; color: $text-muted; }
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
        Binding("ctrl+g", "whole_graph", "Whole graph", priority=True),
        Binding("ctrl+b", "buy", "Buy questions", priority=True),
        Binding("ctrl+q", "quit", "Leave", priority=True),
        Binding("escape", "hide_suggestions", show=False),
    ]

    def __init__(self, api, args, start=None, idle_seconds=None):
        super().__init__()
        self.api, self.args, self.start_line = api, args, start
        self.theme_name = (getattr(args, "theme", None) or os.environ.get("PHANERIS_THEME") or "phaneris").lower()
        # the server's idle limit, so the terminal and the console agree (it ends idle sign-ins by itself too)
        self.idle_seconds = idle_seconds or idle.minutes(api) * 60
        self.last_activity = time.monotonic()
        self.focused_pane = 0
        self.split = 0.5
        self.recent = []
        self.tab_lines = {}
        self._tab_n = 0
        self.graph_mode = False  # Ctrl-G: questions go to the whole knowledge graph
        self.ask_tabs = {}  # one conversation per scope: "graph" or "disclosure:ID" -> tab id
        self.disclosure_ids = {}  # the office's disclosures, id or lower-case name -> id, for the scope chip
        self.buy_armed = 0.0
        self.is_locked = False

    # ---------------------------------------------------------------- building blocks

    def compose(self) -> ComposeResult:
        with Horizontal(id="barrow"):
            yield CommandBar(placeholder="A name, disclosure or question, then Enter.  T-000003 SCR   Who invented it?   ? help",
                             id="bar", suggester=HistorySuggester(self))  # fmt: skip
            yield Static("", id="scope")
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
        self.set_interval(STATUS_SECONDS, self.refresh_status)  # a key press, not this, is what counts as activity
        if self.start_line:
            self.open_tab(self.start_line)
        elif "default" in read_layouts():
            self.load_layout("default", quiet=True)
        else:  # the default layout: the welcome pane, with the office's disclosures and the allowances
            self.open_tab(":welcome")
        self.load_disclosures()
        self.set_interval(0.5, self.update_scope)

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

    def draw_screen(self, line, width, api, view=None):
        """A screen's text, drawn `width` characters wide, as ANSI. A subject that needs choosing leaves its choices on
        the view, which shows them as rows."""
        from .main import Fail, Out, explain

        lines = []
        out = Out(self.args)
        style = Style(color=True, theme=self.theme_name, width=width, truecolor=True)
        ctx = term.Ctx(api, out, self.args, sink=lines, style=style)
        ctx.interactive = False
        try:
            term.run(ctx, shlex.split(line))
        except term.Choose as c:
            if view is not None:
                view.choices = c.choices
                lines.append(style.bold(c.message.split(":")[0] + ":") + style.dim("  Enter opens one in a new tab."))
            else:
                lines.append(style.bad("error: ") + c.message + "\n" + style.dim("next: " + c.hint))
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
        question = term.question_of(line)
        if question:  # asked in the scope the chip shows; never written to the history file
            return self.ask_from_bar(*question)
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
        """Open one screen in a new tab of the pane in focus (or the pane given). ":guide TOPIC" opens the guide,
        ":welcome" the welcome pane, ":askkg QUESTION" asks the whole knowledge graph (chosen from a suggestion)."""
        if line == ":graph-cited":  # an answer's graph is not kept in a layout: it belongs to its conversation
            return None
        if line == ":welcome":
            return self._add_tab(line, "Welcome", WelcomeView(line), pane)
        if line.startswith(":askkg "):
            return self.ask_in({"kind": "graph"}, line[len(":askkg ") :].strip())
        words = line.split()
        if not line.startswith(":") and words and words[-1].upper().strip("\"'") in term.REMOVED_CODES:  # a layout saved before 0.7.0
            self.notify(f"Skipped {line}: NEWS and WATCH were removed in 0.7.0.", severity="warning")
            return None
        if line.startswith(":guide"):
            topic = line[len(":guide") :].strip()
            return self._add_tab(line, f"Guide {topic}".strip(), GuideView(topic), pane)
        subject, code, _ = term.parse(shlex.split(line))
        views = {"PORT": BoardView, "GRF": Walker, "ASK": AskView, "REL": RelatedView, "GRAPH": GraphView}
        widget = views.get(code, ScreenView)(line)
        tab = self._add_tab(line, f"{subject} {code}".strip() if subject else code, widget, pane)
        self._related_beside(subject, code, pane, front=tab)
        return tab

    def _related_beside(self, subject, code, pane=None, front=None):
        """A disclosure opened in the window gets its related knowledge graph as the next tab (once per disclosure)."""
        if not subject or code in ("REL", "ASK", "PORT"):
            return
        if self.ctx().role == "staff":  # developers: no automatic REL tab (they may open others' disclosures); type ID REL for it
            return
        did = self.disclosure_ids.get(subject.lower()) or (subject if code in ("SCR", "WHY", "CMP", "HIST") else None)
        if not did:
            return
        line = f"{term.arg(did)} REL"
        if line in self.tab_lines.values() or getattr(self, "_loading_layout", False):
            return
        target = pane if pane is not None else self.pane()
        self._tab_n += 1
        tab_id = f"tab{self._tab_n}"
        self.tab_lines[tab_id] = line

        async def add_behind():  # once it is in, the disclosure goes back in front (adding a pane can activate it)
            await target.tabs.add_pane(TabPane(f"{did} REL"[:28], RelatedView(line), id=tab_id))
            if front and target.tabs.query(f"#{front}"):
                target.tabs.active = front

        self.call_later(add_behind)

    def _add_tab(self, line, title, widget, pane=None, activate=True):
        self._tab_n += 1
        tab_id = f"tab{self._tab_n}"
        target = pane if pane is not None else self.pane()
        self.tab_lines[tab_id] = line
        target.tabs.add_pane(TabPane(title[:28], widget, id=tab_id))
        if activate:
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
            self._loading_layout = True  # a saved layout already says which REL tabs it wants
            for pane, lines in zip(self.panes(), wanted, strict=False):
                for line in lines:
                    self.open_tab(line, pane=pane)
            self._loading_layout = False
            self._focus(0)
            if not quiet:
                self.notify(f"Layout {name} loaded.")

        self.call_after_refresh(fill)

    # ---------------------------------------------------------------- questions and their scope

    @work(thread=True)
    def load_disclosures(self):
        from .main import disclosure_rows

        try:
            rows = disclosure_rows(self.api.get("/console"))
        except (ApiError, KeyError):
            return
        ids = {}
        for r in rows:
            ids[r["id"].lower()] = r["id"]
            ids[r["name"].lower()] = r["id"]
        self.disclosure_ids = ids

    def current_disclosure(self):
        """The disclosure a question is about: the one in the focused tab (its subject, or the one it is looked up
        around), else the last one opened."""
        try:
            tab = self.pane().tabs.active
        except Exception:  # noqa: BLE001  no pane yet
            tab = None
        line = self.tab_lines.get(tab or "", "")
        view = self.ask_views().get(tab)
        if view is not None and view.scope and view.scope.get("disclosure"):
            return view.scope["disclosure"]
        if line and not line.startswith(":"):
            try:
                subject, _, opts = term.parse(shlex.split(line))
            except ValueError:
                subject, opts = "", {}
            if opts.get("disclosure"):
                return opts["disclosure"]
            if subject.lower() in self.disclosure_ids:
                return self.disclosure_ids[subject.lower()]
        return store.read_config().get("last_disclosure")

    def scope_for(self, explicit=None):
        """The scope Enter will use: the whole graph (/kg, ask --graph, Ctrl-G), else the current disclosure; None when
        there is no disclosure (nothing is sent then)."""
        if explicit == "graph" or self.graph_mode:
            return {"kind": "graph"}
        d = self.current_disclosure()
        return {"kind": "disclosure", "disclosure": d} if d else None

    def chip_text(self, scope):
        if scope is None:
            return "No disclosure open · Ctrl-G: whole graph"
        return "Whole knowledge graph" if scope["kind"] == "graph" else f"About {scope['disclosure']}"

    def update_scope(self):
        """The scope chip beside the bar: where a question typed now would go."""
        try:
            typed = self.query_one("#bar", Input).value
            chip = self.query_one("#scope", Static)
        except Exception:  # noqa: BLE001  the screen is locked or closing
            return
        q = term.question_of(typed) if typed.strip() else None
        text = self.chip_text(self.scope_for(q[1] if q else None))
        if str(chip.render()) != text:
            chip.update(text)
        chip.set_class(self.graph_mode or bool(q and q[1] == "graph"), "-graph")

    def on_input_changed(self, event):
        if event.input.id == "bar":
            self.update_scope()

    def action_whole_graph(self):
        self.graph_mode = not self.graph_mode
        self.update_scope()
        self.notify("Questions go to the whole knowledge graph (metered)." if self.graph_mode else "Questions go to the open disclosure.")

    def ask_views(self):
        return {tab: v for v in self.query(AskView) for tab in [self._tab_of(v)] if tab}

    def _tab_of(self, widget):
        for node in widget.ancestors:
            if isinstance(node, TabPane):
                return node.id
        return None

    def ask_from_bar(self, question, explicit):
        scope = self.scope_for(explicit)
        if scope is None:
            self.notify("No disclosure is open. Open one (T-000003 DES), or ask the whole knowledge graph: /kg QUESTION or Ctrl-G.",
                        severity="warning")  # fmt: skip
            return None
        return self.ask_in(scope, question)

    def ask_in(self, scope, question):
        """Ask in a scope's conversation: the open one (its earlier questions are kept), or a new tab."""
        key = "graph" if scope["kind"] == "graph" else f"disclosure:{scope['disclosure']}"
        tab = self.ask_tabs.get(key)
        views = self.ask_views()
        if tab in views:
            for pane in self.panes():
                if pane.tabs.query(f"#{tab}"):
                    pane.tabs.active = tab
            views[tab].send(question)
            return tab
        line = "ASK --graph" if scope["kind"] == "graph" else f"{term.arg(scope['disclosure'])} ASK"
        title = "Ask: whole graph" if scope["kind"] == "graph" else f"Ask: {scope['disclosure']}"
        tab = self._add_tab(line, title, AskView(line, scope=scope, first=question))
        self.ask_tabs[key] = tab
        return tab

    def action_buy(self):
        """Ctrl-B twice: record a request for 100 questions ($5). Nothing is charged here; an administrator fills it."""
        now = time.monotonic()
        if now - self.buy_armed > 5:
            self.buy_armed = now
            self.notify("Press Ctrl-B again within 5 seconds to request 100 questions for $5.")
            return
        self.buy_armed = 0.0
        self.request_pack()

    @work(thread=True)
    def request_pack(self):
        try:
            self.api.post("/explore/request-pack", {})
        except ApiError as e:
            return self.call_from_thread(self.notify, e.message, severity="error")
        self.call_from_thread(self.notify, "Requested 100 questions for $5. An administrator adds them until online payment opens.")

    # ---------------------------------------------------------------- status, help, idle lock

    @work(thread=True, exclusive=True, group="status")
    def refresh_status(self):
        parts = []
        try:
            me = self.api.get("/auth/me", background=True)["user"]
            parts.append(f"{me['display_name']} ({me['role']})")
            parts.append(f"office {me['workspace']}")
        except ApiError as e:
            parts.append(e.message)
        try:
            parts.append(term.allowances_line(self.api.get("/explore/usage", background=True)))
        except ApiError:
            pass
        try:
            v = self.api.get("/health", background=True).get("version", "?")
        except ApiError:
            v = None
        self.server_down = v is None
        if v is None and parts and parts[0].startswith("Could not reach"):
            parts[0] = "server not answering"
        parts.append(f"server {v or 'not answering'} · phaneris {__version__} · ? help")
        self.call_from_thread(self._set_status, "  ·  ".join(parts))

    def _set_status(self, text):
        try:
            self.query_one("#status", Static).update(text)
        except NoMatches:  # the window is closing, or the screen is locked
            pass

    def server_answered(self):
        """A screen loaded: if the status line said the server was not answering, check again now."""
        if getattr(self, "server_down", False):
            self.server_down = False
            self.refresh_status()

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
        """Clear every pane, end the sign-in on the server and forget it here, then say why."""
        self.is_locked = True
        for pane in self.panes():
            pane.remove_children()
        self.push_screen(LockScreen())
        self.end_sign_in()

    @work(thread=True)
    def end_sign_in(self):
        try:
            self.api.post("/cli/logout", {"why": "idle"})
        except ApiError:
            pass  # already ended on the server
        store.delete_token(self.api.server)

    @work(thread=True)
    def check_sign_in(self):
        try:
            self.api.get("/auth/me")
        except ApiError as e:
            if e.status == 401:
                self.call_from_thread(self.notify, "Your sign-in has ended. Leave with ctrl+q and run: phaneris login", severity="error", timeout=30)


def run(api, args, start=None):
    PhanerisApp(api, args, start=start).run()
