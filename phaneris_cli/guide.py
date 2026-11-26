"""The guide inside the terminal: `phaneris guide [TOPIC]`, `phaneris help TOPIC`, `phaneris guide --search WORD`.

Offline and shipped with this version of the client, so it always describes the commands you have. The same facts
are on the website: https://www.phaneris.co/docs/terminal. Paragraphs are wrapped to the terminal; lines that start
with two spaces (examples, tables) are kept as written.
"""

import os
import re
import shlex
import shutil
import subprocess
import sys
import textwrap

from . import __version__

DOCS = "https://www.phaneris.co/docs/terminal"

TOPICS = [
    (
        "start",
        "Getting started",
        """
The Phaneris command line lets you use Phaneris from a terminal with your own account: your office's disclosures and reports with every score marked Real or Inferred, scoring new disclosures, questions, lookups in the knowledge graph around your disclosures, watchlists and score history. It shows exactly what the console shows your account; it adds no access of its own.

Install it with pipx (Python 3.10 or newer, no other dependencies), then sign in:

  pipx install git+https://github.com/avis-giri/phaneris_cli
  phaneris login
  phaneris disclosures
  phaneris T-000003 SCR

Most of the work is done with a subject and a function code: phaneris SUBJECT CODE. The subject is what you want to look at (a disclosure, a patent, a person, an owner, a class); the code is the screen (SCR for scores, WHY for what moves them). See: phaneris guide subjects.

With no words on a terminal, phaneris opens the command bar (or full-screen mode, if its extra is installed). Every command takes --json for scripts.

Topics: phaneris guide (the list), phaneris guide TOPIC, phaneris guide --search WORD. The website has the same guide: """
        + DOCS
        + ".",
    ),
    (
        "commands",
        "Every command",
        """
Account
  login                 sign in with your username and password (--browser: approve a code in the console)
  logout                end this sign-in
  whoami [--banner]     who you are signed in as
  version               this program's version and the server's
  doctor                check Python, the server, your sign-in and where it is kept
  history [--clear]     what you ran in the command bar, used for Tab suggestions
  tui [SUBJECT CODE]    full-screen mode (needs the optional extra)
  guide [TOPIC]         this guide; help TOPIC does the same; --search WORD finds a word

Disclosures and reports
  disclosures           your office's disclosures
  disclosures show ID   one disclosure's report: every score marked Real or Inferred
  report ID [--pdf F]   the same report; --pdf saves the designed report PDF
  score FILE            enter a new disclosure from a JSON file and follow its scoring (score --example shows one)
  jobs                  your scoring jobs

Questions
  ask "Q" --disclosure ID   ask about one of your disclosures and what it connects to
  ask "Q" --graph           ask across the whole knowledge graph (metered)
  ask -i                    a conversation, keeping the earlier questions
  usage                     questions you have left
  buy                       request 100 more questions ($5)

Knowledge graph (Phaneron)
  graph search TEXT --disclosure ID    records around your disclosure that match
  graph record NODE --disclosure ID    one record and what it links to
  graph related NODE --disclosure ID   the records one step from it

What changed
  watch add SUBJECT     watch a disclosure, or a record around one (--disclosure ID); up to 200
  watch remove SUBJECT  stop watching it
  watch list            what you watch
  feed [--all]          what changed since you last looked (--all: everything kept)

Functions
  phaneris SUBJECT CODE   a screen, for example phaneris T-000003 SCR. See: phaneris guide subjects.
  go "SUBJECT CODE"     the same, as one quoted line (for scripts and aliases)
""",
    ),
    (
        "signin",
        "Signing in and security",
        """
phaneris login asks for your username, your password (not shown as you type) and the office to work in (Enter for your own). The password goes only to Phaneris over HTTPS, once, and is checked exactly as the console checks it. It is never stored, logged or shown, and it is never accepted as a command-line argument, where other people on the computer could see it.

  phaneris login --username jdoe --office aldermoor
  phaneris login --browser          approve a code in the console instead of typing a password
  phaneris login --username jdoe --password-stdin    for scripts, from a secrets manager only

After 5 wrong passwords the username waits 15 minutes, and an address that starts too many sign-ins in an hour has to wait. An account that still has its one-time password must choose its own password in the console first.

With --browser, approve only a code you started yourself: approving someone else's code would let their computer act as you. Codes last 10 minutes.

What the terminal keeps is a separate sign-in, not your password. It lasts 30 days and is kept in the macOS keychain, or elsewhere in ~/.config/phaneris/token.json, readable only by your account. The service keeps only a one-way fingerprint of it. A sign-in acts only in its office, with your role, and never reaches administration.

Sessions: see and end your sign-ins on the console's Settings page; administrators can end anyone's on Users. If you lose a computer, end its sign-in there. If your account is disabled, its sign-ins stop at once. phaneris logout ends this one.

Idle sign-out is being added to the service: once it is on, a browser session or terminal sign-in left idle for the set time ends, and you sign in again. Every sign-in and every ending of one is recorded with the account, the time and how it was made.
""",
    ),
    (
        "bar",
        "The command bar and Tab",
        """
phaneris with no words on a terminal opens a prompt. Type a subject and a code and press Enter. ? shows the codes, ? TOPIC opens a topic of this guide, Ctrl-D leaves.

Tab suggests from your own earlier commands first (most used and most recent first), then codes, then subjects you have seen in this session; Tab on an empty line offers your last commands. On a color terminal the best suggestion shows dimmed after the cursor; Right arrow or Tab takes it. Up and Down walk earlier commands.

What you run in the bar is kept in ~/.config/phaneris/history (only you can read it, at most 500 lines) for these suggestions. Questions typed into a conversation are never kept, nor anything that looks like a password or a sign-in. phaneris history shows it; phaneris history --clear empties it.
""",
    ),
    (
        "subjects",
        "Subjects and codes",
        """
A subject is a disclosure id, short name or patent number (T-000003, "Cancer T-cell therapy", US 8916381), a patent number of any patent within reach, a "person or owner" in quotes, a patent class (A61K, A61K 39/39) or a record id from another screen (inventor:123, pat:8916381). Codes are case-insensitive.

Records are looked up around the disclosure you opened last; administrators can reach the whole graph. Open one first with phaneris T-ID DES, or add --disclosure ID.

A name that matches several records gives a numbered list to choose from. A name that matches nothing gives the closest matches ("did you mean"): on a terminal, type a number to run the same code on it (Enter cancels); in a script, they are listed and the command exits with an error. A mistyped code (SRC) suggests the right one (SCR).

The codes:
  DES    what it is: the record brief                       phaneris T-000003 DES
  SCR    scores: deal chance, stages, nine metrics           phaneris T-000003 SCR
  WHY    what moves the score: the model's own terms         phaneris T-000003 WHY
  CMP    comparables and how far they got                    phaneris T-000003 CMP --sort date
  GRF    the neighbourhood in Phaneron, a map                phaneris "Carl H. June" GRF
  OWN    ownership and timeline, later items as hindsight    phaneris US 8916381 OWN
  CLS    patent class trends                                 phaneris A61K CLS
  HIST   score history: versions, what moved and why         phaneris T-000003 HIST
  WATCH  watch it, or stop watching (a toggle)               phaneris T-000003 WATCH
  NEWS   what changed in what you watch                      phaneris NEWS
  ASK    a conversation about it                             phaneris T-000003 ASK
  PORT   your office's board                                 phaneris PORT
  HELP   what applies to a subject                           phaneris T-000003 HELP

DES, GRF, OWN, WATCH and NEWS apply to a disclosure or a record; SCR, WHY, CMP and HIST to a disclosure; CLS also to a class; PORT to your office.
""",
    ),
    (
        "screens",
        "Reading the screens",
        """
Scores. Every score runs from 0 to 1, where 0.5 is the middle of earlier comparable records. Each one says how it was reached:
  Real       made only from facts found for this disclosure, dated on or before the disclosure date, ranked against
             earlier records or scored by a fixed rule
  Inferred   at least one stand-in is used: a placeholder from the report plan, or the middle (0.5) where nothing
             usable was found. Inferred scores keep the picture complete and are never evidence.
On a color terminal Real bars are solid and Inferred ones shaded. "middle, nothing usable" marks a metric with no usable fact at all.

The nine metrics: IP defensibility (ipd), Market signal (ms), Evidence quality (eq), Inventor alignment (ia), Translational funding (tf), Regulatory path (rp), FTO risk (fto), Technical advantage (ta), Capital path (cp).

SCR. The deal chance is the chance of going out (licensed or spin-out), from real data, with its range. The strip under it is a small chart of the earlier records' deal chances, with this disclosure's place (its percentile) marked; "times the average" compares it with the average record. The full estimate adds the five metrics with no outcome history (eq, rp, fto, ta, cp) at an assumed weight. The recommendation uses the full estimate: Pursue at 1.5 times the average or more with no flag raised, Hold under 0.75 times, otherwise Review. The deal-stage tree splits going out into licensed and spin-out, and not going out into maintained and inactive. Each metric bar has a middle line at 0.5, its score, Real or Inferred, and the facts measured out of the facts it reads. Flags and checks are listed last, then a one-line score history.

WHY. The deal chance comes from a fitted model with eleven inputs. Each line is one input's push up or down in log-odds: its coefficient times its distance from the average record in the history. The terms are checked to add up to the stored deal chance; if they do not (another model scored it), the screen says so and shows no split, and nothing is estimated in its place. It also shows the change if a modelled metric were the middle, and the full estimate's assumed part, labelled as an assumption.

CMP. The closest earlier records and how far each got by the disclosure date, with their weight and similarity (--sort weight, similarity, date or outcome), then the look-alike patents and trials.

GRF. The neighbourhood in Phaneron, one and two links out, grouped by patents, people, owners, classes and trials. Two dots mark a record two links out, with the record it is reached through. Each map is one lookup.

OWN. Filings, grant, assignments, licences, trials and papers in date order, with the disclosure date as a rule. Everything after it is marked as hindsight: context, never part of a score. For a record, its own dates and the dated records one link away.

CLS. Filings by year as a line, share in force and the top owners. The yearly counts cover only the years fetched for the class; a line is drawn only across consecutive years, because a missing year is unknown, not zero. For a disclosure, the class it is grouped under in the graph.

PORT. Your office's disclosures ranked by deal chance, with the recommendation, how many of the nine metrics are Real, and a heat row of the nine (in order ipd ms eq ia tf rp fto ta cp: darker is higher, green Real, amber Inferred). There is no board across offices yet, for any account.

NEWS. What changed in what you watch, grouped by item, newest first; each item says which screen opens it. See: phaneris guide watch.

HIST. Every kept version of a disclosure's score: when it was scored, the deal chance, the full estimate, the recommendation, where it came from (a data import or a re-score) and what moved. Under it, why the latest version moved: the change in each fitted input's push between the two latest versions, shown only when both were scored with the model the site holds.
""",
    ),
    (
        "questions",
        "Questions and limits",
        """
There are two kinds of question. The service decides every limit; the command line shows what it answers.

  About a disclosure (--disclosure ID)   that disclosure, its report and the records it connects to.
                                         10 free in any 12 hours.
  Across the whole graph (--graph)       every public record, never another institution's disclosures.
                                         5 free in total.
  After the free ones                    bought questions, shared between both kinds: 100 for $5.
  Administrators                         no limit.

A question the answer service could not answer does not count. phaneris usage shows what you have left. phaneris buy records a request for 100 more; until online payment opens, an administrator adds them and marks the request filled. Bought questions do not expire.

Lookups (graph commands, DES, GRF, OWN, CLS on records, did-you-mean, adding a watch) reach only what your disclosure connects to: the disclosure, its patents and the records within two links of them, never another institution's disclosures. Administrators may leave the disclosure out and reach the whole graph. Lookups are limited to 300 an hour per person, to keep the graph from being copied in bulk.
""",
    ),
    (
        "watch",
        "Watchlists and the feed",
        """
Watch the disclosures and records you care about, and NEWS (phaneris feed) shows what changed since you last looked:
  new or removed patents, assignments, licences, trials, grants and papers
  a changed application status, grant date or owner
  a score that moved: the deal chance, the recommendation, any metric by more than 0.05, or a metric turning Real
  or Inferred

  phaneris watch add T-000003
  phaneris watch add "US 8916381" --disclosure T-000003
  phaneris watch list
  phaneris feed
  phaneris feed --all

You can watch your own disclosures and records within reach of one of them, up to 200 items; adding one counts as a lookup. Changes are found when new data is loaded and when a disclosure is scored again, and only for watched items. Reading the feed marks it as seen; --all shows everything kept and does not. The feed is checked against what you may see each time it is read: a change about a record that has left your reach does not name it, and a watched record that has left your reach stops showing. A re-score's numbers are shown only to the person who entered it.

Each item says which screen opens it: a score move opens HIST, anything else the timeline (OWN), a class CLS. In full-screen mode, Enter on a NEWS line opens it, and w on a disclosure or record screen watches it. The console's Overview shows the same changes in a small "What changed" panel.
""",
    ),
    (
        "tui",
        "Full-screen mode keys",
        """
Several screens side by side, keyboard first. It needs one optional extra:

  pipx inject phaneris-cli textual

Then phaneris tui (or phaneris tui T-000003 SCR); with the extra installed, phaneris with no words opens it too. The bar on top takes the same subjects and codes. With no saved layout it opens on NEWS.

  ctrl+k or /       the bar                    ctrl+n          a new pane (up to four)
  f6, ctrl+right    next pane                  shift+f6        previous pane
  [  ]              previous, next tab         ctrl+w          close the tab
  <  >              narrow, widen the pane     ctrl+x          close the pane
  ctrl+s            save this layout           ?  f1           help
  w                 watch this pane's subject  ctrl+q          leave
  :save NAME   :load NAME   :layouts   :theme amber|phaneris   :guide TOPIC   :quit

In a map (GRF): arrows move, Enter re-centres (one lookup), Backspace goes back, d shows the record's brief beside it, o opens it in a tab. On the board (PORT): Enter opens the disclosure's scores. In NEWS: Enter opens what changed. :guide opens this guide in a pane.

Layouts are kept in ~/.config/phaneris/layouts.json (only you can read it); "default" opens by itself. After 30 minutes without a key the screen locks until a key is pressed; your password is never asked for or kept.
""",
    ),
    (
        "output",
        "Themes and output for scripts",
        """
Themes: --theme phaneris (the default, a violet accent) or --theme amber (amber on black, high contrast), or set PHANERIS_THEME. Color appears only on a terminal and never with NO_COLOR set; --no-color turns it off for one command. PHANERIS_NO_ANIMATION=1 turns the sign-in animation off. Screens fit the terminal's width.

Scripts: every command and code takes --json and prints machine-readable output; errors go to standard error as JSON with "error" and "next", and the exit status is not zero. With no terminal, nothing asks a question: a choice between records, or a did-you-mean list, is printed and the command stops.

  phaneris --json T-000003 SCR
  phaneris --json feed --all
  PHANERIS_TOKEN=... phaneris --json disclosures     a sign-in from a secrets manager, kept out of files

Settings: --server URL or PHANERIS_URL (default https://www.phaneris.co; https, or this computer for testing), PHANERIS_USERNAME, PHANERIS_TOKEN, PHANERIS_NO_KEYCHAIN=1 (keep the sign-in in the file even on macOS), PAGER (the pager for this guide).
""",
    ),
    (
        "trouble",
        "Troubleshooting",
        """
  phaneris: command not found        pipx's folder is not on your PATH: run pipx ensurepath and open a new terminal.
  The username or password is not right.
                                     Check both; the message is the same for either, on purpose.
  Too many failed sign-ins           5 wrong passwords: wait 15 minutes, or ask an administrator to reset it.
  Choose your own password in the console first
                                     The account still has its one-time password: set one in the console.
  no terminal to ask for the password
                                     In a script: use --password-stdin with a secrets manager, or --browser.
  Sign in to continue                The sign-in expired after 30 days, was ended, or the account was disabled:
                                     run phaneris login.
  not within reach                   Lookups reach only what the named disclosure connects to; ask across the
                                     whole graph with phaneris ask --graph.
  Name one of your disclosures       Lookups need --disclosure ID, or a disclosure you opened before.
  300 knowledge graph lookups        The hourly limit; it frees up as the hour passes.
  the code expired                   Browser codes last 10 minutes: run phaneris login again.
  No exact match ... Did you mean    The name found nothing; pick one of the close matches, or use the id.
  You are watching 200 items         Remove one with phaneris watch remove ID.

phaneris doctor checks Python, the server, your sign-in and where it is kept. To report a problem, use the contact form on the website with the command and the message it printed; never include your password or sign-in.
""",
    ),
    (
        "privacy",
        "Privacy: what is kept on disk",
        """
Everything is kept under ~/.config/phaneris (or $XDG_CONFIG_HOME/phaneris), readable only by your account:
  token.json      the sign-in, when there is no keychain (on macOS it is in the keychain instead)
  config.json     the server, your username and role, and the last disclosure you opened
  history         what you ran in the command bar, at most 500 lines; never questions, passwords or sign-ins
  layouts.json    saved full-screen layouts

Your password is never kept. Questions typed into a conversation are kept only in memory while it is open. Reports and PDFs are saved only where you ask (--pdf FILE). phaneris history --clear empties the history; phaneris logout ends the sign-in and removes it from this computer.

The service keeps what the console keeps for your account: your watchlist, the feed's last-seen time, score history, and a count of lookups and questions (not their text) for the limits.
""",
    ),
]

SLUGS = {slug: (title, body) for slug, title, body in TOPICS}
ALIASES = {
    "getting-started": "start",
    "login": "signin",
    "security": "signin",
    "sessions": "signin",
    "codes": "subjects",
    "functions": "subjects",
    "scores": "screens",
    "real": "screens",
    "inferred": "screens",
    "limits": "questions",
    "feed": "watch",
    "news": "watch",
    "watchlist": "watch",
    "keys": "tui",
    "full-screen": "tui",
    "json": "output",
    "themes": "output",
    "scripts": "output",
    "help": "trouble",
    "troubleshooting": "trouble",
    "disk": "privacy",
}
for _code in ("scr", "why", "cmp", "grf", "own", "cls", "port", "hist"):
    ALIASES.setdefault(_code, "screens")


def find(name):
    """The topic slug for a name, an alias or a code; None if there is none."""
    n = (name or "").strip().lower()
    if n in SLUGS:
        return n
    if n in ALIASES:
        return ALIASES[n]
    starts = [s for s, (title, _) in SLUGS.items() if s.startswith(n) or title.lower().startswith(n)]
    return starts[0] if n and len(starts) == 1 else None


def _kept(line, width):
    """An indented line (an example or a table row) as written, wrapped with a hanging indent only if it is too wide."""
    if len(line) <= width:
        return [line]
    lead = " " * min(len(line) - len(line.lstrip(" ")), width // 3)  # a narrow terminal keeps a short indent
    return textwrap.wrap(line.strip(), width, initial_indent=lead, subsequent_indent=lead + "    ", break_on_hyphens=False) or [""]


def render(slug, width):
    """One topic as lines, paragraphs wrapped to `width`, indented lines kept (wrapped only if too wide)."""
    title, body = SLUGS[slug]
    out = [title, "-" * min(width, len(title))]
    for para in body.strip("\n").split("\n\n"):
        lines = para.split("\n")
        if any(line.startswith("  ") for line in lines):
            for line in lines:
                out += _kept(line, width) if line.startswith("  ") else textwrap.wrap(line, width) or [""]
        else:
            out += textwrap.wrap(" ".join(lines), width) or [""]
        out.append("")
    return out


def contents(width):
    out = textwrap.wrap(f"The Phaneris guide (version {__version__})", width) + [""]
    for slug, title, _ in TOPICS:
        out += _kept(f"  {slug:<10} {title}", width)
    out.append("")
    for text in ("Open one: phaneris guide TOPIC (or phaneris help TOPIC). Find a word: phaneris guide --search WORD.",
                 f"The same guide is on the website: {DOCS}"):  # fmt: skip
        out += textwrap.wrap(text, width, break_on_hyphens=False)
    return out


def search(word, width):
    """Every sentence (or example and table row) of the guide with the word, under its topic."""
    out, n = [], 0
    rx = re.compile(re.escape(word), re.I)
    for slug, title, body in TOPICS:
        hits = []
        for para in body.strip("\n").split("\n\n"):
            for line in para.split("\n"):
                parts = [line.strip()] if line.startswith("  ") else re.split(r"(?<=[.!?])\s+", line)
                hits += [p for p in parts if rx.search(p)]
        if hits:
            out += textwrap.wrap(f"{title}  (phaneris guide {slug})", width, subsequent_indent="    ")
            for h in hits:
                out += textwrap.wrap(h, width, initial_indent="  ", subsequent_indent="    ", break_on_hyphens=False)
            out.append("")
            n += len(hits)
    return out, n


def as_data():
    return {"version": __version__, "docs": DOCS, "topics": [{"id": s, "title": t, "text": b.strip()} for s, t, b in TOPICS]}


def page(lines, out=None):
    """Show lines: through $PAGER or a simple pager on a terminal, plainly when piped."""
    out = out or sys.stdout
    text = "\n".join(lines).rstrip() + "\n"
    if not (out.isatty() and sys.stdin.isatty()):
        out.write(text)
        return
    rows = shutil.get_terminal_size((100, 24)).lines - 1
    if len(lines) <= rows:
        out.write(text)
        return
    pager = os.environ.get("PAGER")
    if pager:
        try:
            subprocess.run(shlex.split(pager), input=text, text=True, check=False)  # noqa: S603  the person's own pager
            return
        except OSError:
            pass
    i = 0
    while i < len(lines):
        out.write("\n".join(lines[i : i + rows]) + "\n")
        i += rows
        if i >= len(lines):
            break
        try:
            answer = input(f"-- more ({min(100, round(100 * i / len(lines)))}%): Enter for the next page, q to stop --")
        except EOFError:
            break
        if answer.strip().lower().startswith("q"):
            break
