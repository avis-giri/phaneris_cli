# Phaneris command line

Use Phaneris from a terminal with your own account: your office's disclosures and reports with every score marked
Real or Inferred, scoring new disclosures, questions about a disclosure or the whole knowledge graph, and lookups in
the knowledge graph around your disclosures. You see and do exactly what the console allows your account; the
command line adds no access of its own.

Full documentation: https://www.phaneris.co/docs/terminal

## The Phaneris window

Type `phaneris` and press Enter: the Phaneris window opens, with a bar at the top, panes below and a status line.

```text
 A name, disclosure or question, then Enter.                               About T-000003
 The Phaneris window   type in the bar above, then Enter.
   Open anything   a disclosure id or title, a person, an owner, a patent or a class, then a code
                   T-000003 SCR    "Carl H. June" GRF    US 8916381 OWN    A61K CLS    (no code: DES)
   Ask             a question ending in ?, or ask ...    about the disclosure that is open
                   /kg QUESTION or Ctrl-G                 across the whole knowledge graph
 Questions: 8 of 10 free about disclosures, 4 of 5 whole graph, 0 bought.  Buying more: Ctrl-B or phaneris buy.
```

- **Open anything** by typing a disclosure id or title, a person, an owner, a patent or a class, then a code (Enter
  alone opens DES). Tab completes. Several matches, or none, show as rows; Enter opens one.
- **Ask** by typing a question (ending in `?`, or starting with `ask` or `/ask`): it goes to the disclosure that is
  open. `/kg QUESTION`, `ask --graph QUESTION` or **Ctrl-G** sends it across the **whole knowledge graph** instead.
  The **scope chip** beside the bar shows where Enter will send it ("About T-000003", "Whole knowledge graph", or "No
  disclosure open", when nothing is sent) before anything is sent. Each scope keeps its own conversation.
- **A disclosure's related knowledge graph** opens as the next tab whenever you open a disclosure (REL): its records
  grouped by kind with counts, as an expandable tree. Enter opens one; `g` map, `o` timeline, `c` class trends.
- **The knowledge graph view** (GRAPH, or `g` on any record): nodes and edges you can pan, zoom, select, re-centre and
  expand; `G` in an answer draws all its cited records. See `phaneris guide graph`.
- **Cited records** in an answer are rows: Enter opens one (DES), `g` its map (GRF). A record outside your
  disclosures' reach shows the brief the answer returned and says why it cannot be opened further.
- **A name you cannot reach** offers "Ask the whole knowledge graph about 'NAME' (N free whole-graph questions left)"
  first; it is sent only when you choose it and press Enter.
- **Allowances**: 10 free questions about your disclosures in any 12 hours, 5 free across the whole graph in total,
  then bought questions shared by both (100 for $5); administrators have no limit. The status line shows them
  ("Questions: 8 of 10 free about disclosures, 4 of 5 whole graph, 0 bought"). **Ctrl-B** twice or `phaneris buy`
  records a request for 100 more.

The window needs one optional extra: `pipx inject phaneris-cli textual`. Without it, `phaneris` opens the line-mode
command bar and says so. Keys and more: `phaneris guide window`.

## Install

Needs Python 3.10 or newer and pipx. It has no other dependencies.

```bash
pipx install git+https://github.com/avis-giri/phaneris_cli
pipx upgrade phaneris-cli
pipx uninstall phaneris-cli
```

## Sign in

```bash
phaneris login
```

It asks for your username, your password (not shown as you type), and the office to work in (Enter for your own),
then shows the Phaneris wordmark and who you are signed in as. The password goes only to Phaneris over HTTPS and is
not kept; the terminal keeps only a sign-in you can end at any time. After 5 wrong passwords the username waits 15
minutes. An account that still has a one-time password must choose its own password in the console first.

Other ways in:

```bash
phaneris login --username jdoe --office aldermoor     # skip the questions
phaneris login --browser                              # approve a code in the console instead of typing a password
security find-generic-password -s phaneris-jdoe -w | phaneris login --username jdoe --password-stdin   # scripts (macOS keychain)
```

The password is never accepted as a command-line argument, where other people on the computer could see it. Use
`--password-stdin` only with a secrets manager, never with a password typed into a script.

The sign-in lasts 30 days. It is kept in the macOS keychain, or elsewhere in `~/.config/phaneris/token.json`,
readable only by your account. See and end your sign-ins on the console's Settings page; administrators can end
anyone's on Users.

### Two-step sign-in and signing out after idle time

If your account has two-step sign-in on (admins must), `phaneris login` asks for the 6-digit code from your
authenticator app after the password; a recovery code works too. Scripts pass it with `--code`.

A sign-in ends after **2 minutes without use** (the server's limit, the same as the console). The next command then
says "Signed out after 2 minutes without use" and forgets the old sign-in; run `phaneris login` again. The command
bar and full-screen mode watch the keyboard too: at the limit they clear the screen, end the sign-in on the server
and say why. The sign-in also ends at 30 days, when you change your password, or when you end it on the console's
Settings page.

## Commands

| Command | What it does |
| --- | --- |
| `phaneris login` / `logout` | Sign in, or end this sign-in |
| `phaneris whoami [--banner]` | Who you are signed in as (with the wordmark) |
| `phaneris version` | This program's version and the server's |
| `phaneris history [--clear]` | What you ran in the command bar (used for Tab suggestions); `--clear` empties it |
| `phaneris tui [SUBJECT CODE]` | Full-screen mode (needs the optional extra) |
| `phaneris doctor` | Check Python, the server, your sign-in and where it is kept |
| `phaneris guide [TOPIC]` / `help TOPIC` | The full guide, offline and versioned with this program; `--search WORD` finds a word |
| `phaneris disclosures` | Your office's disclosures with deal chance and recommendation |
| `phaneris disclosures show ID [--all]` | One disclosure's report: outlook, checks, every metric with Real or Inferred, facts not measured |
| `phaneris report ID [--pdf FILE] [--all]` | The same report; `--pdf` saves the designed report PDF |
| `phaneris score FILE` / `score --example` | Enter a new disclosure from a JSON file and follow its scoring |
| `phaneris jobs` | Your scoring jobs |
| `phaneris ask "question" [--disclosure ID]` | Ask about one of your disclosures (default: the last one you used) |
| `phaneris ask "question" --graph` | Ask across the whole knowledge graph (metered) |
| `phaneris ask -i` | A conversation that keeps your earlier questions |
| `phaneris usage` / `buy` | Your plan and every limit (used, left, when it opens again), bought questions, last 30 days; request 100 more for $5 |
| `phaneris graph search TEXT [--disclosure ID]` | Records around your disclosure that match |
| `phaneris graph record NODE [--disclosure ID]` | One record, with a short claim excerpt for a patent |
| `phaneris graph related NODE [--disclosure ID]` | The records one step from it |

Every command takes `--json` for machine-readable output and `--no-color` for plain text. Color and the wordmark
appear only on a terminal, never with `NO_COLOR` set; `PHANERIS_NO_ANIMATION=1` turns the animation off.

## Functions

Type a subject and a function code; the screen draws in the terminal:

```bash
phaneris T-000003 SCR          # one of your disclosures, by id, name or patent number
phaneris "US 8916381" DES      # a patent
phaneris "Carl H. June" GRF    # a person or an owner, in quotes
phaneris A61K GRF              # a patent class
phaneris PORT                  # your office's board
phaneris go "T-000003 WHY"     # the same, as one line
```

| Code | Screen | Applies to |
| --- | --- | --- |
| DES | What it is: the record brief | a disclosure or a record |
| SCR | Deal chance with its range, the percentile strip, the deal-stage tree, nine metric bars with the 0.5 middle line, Real (solid) or Inferred (shaded), flags | a disclosure |
| WHY | What moves the deal chance: the fitted model's own terms against an average record, the change if a metric were 0.5, the full estimate's assumed part, and the facts not found | a disclosure |
| CMP | The closest earlier records and how far they got, and the look-alike patents and trials (`--sort weight\|similarity\|date\|outcome`) | a disclosure |
| GRF | The neighbourhood in Phaneron, one and two links out, grouped by patents, people, owners, classes, trials | a disclosure or a record |
| OWN | Ownership and timeline: filings, grant, assignments, licences, trials, papers, with the disclosure date as a rule and later items marked as hindsight | a disclosure or a record |
| CLS | Patent class trends: filings by year (a braille line chart), share in force, owners. For a disclosure, the class it is grouped under in the graph | a disclosure, a record or a class |
| HIST | Score history: each kept version's date, deal chance, full estimate and recommendation, what moved, and why the latest moved (the fitted model's terms in the two latest versions) | a disclosure |
| REL | Related knowledge graph: the records within the disclosure's reach, grouped by kind with counts (`--all` for every one). In the window it opens as the next tab of any disclosure, as an expandable tree | a disclosure |
| GRAPH | The knowledge graph as nodes and edges around it, on a braille canvas with a legend (`--depth 2`, `--json`). In the window: arrows pan, `+` `-` zoom, Tab selects, Enter re-centres, `e` expands, `f` filters, `d` brief | a disclosure or a record |
| ASK | A conversation about it | anything |
| PORT | Your office's board, ranked by deal chance, with a heat row of the nine metrics | your office |
| HELP | What applies to the subject | anything |

Codes are case-insensitive. A name that matches several records gives a numbered list to choose from. A name that
matches nothing gives the closest matches the server finds among what you may see ("No exact match for 'Carl Jun'.
Did you mean: 1. Carl H. June (person) ..."): on a terminal, type a number to run the same code on it (Enter cancels);
with `--json` or in a script they are listed and the command exits non-zero. A mistyped code (`SRC`) suggests the
right one (`SCR`). Each such check counts as one lookup. Records are
looked up around the disclosure you opened last (administrators can reach the whole graph); open one first with
`phaneris T-ID DES`.

**WHY uses only the model's real numbers.** The deal chance is a fitted logistic model; the screen shows each of its
eleven inputs' push, coefficient times the input's distance from the training average, and checks that the terms add up
to the stored deal chance. If they do not (another model scored it), it says so and shows no split.

### The guide

`phaneris guide` lists the topics; `phaneris guide TOPIC` (or `phaneris help TOPIC`) opens one: getting started, every
command, signing in and security, the command bar, subjects and codes, reading each screen, questions and limits,
full-screen keys, output for scripts, troubleshooting, and what is kept on disk. It ships with
this version, so it works offline and matches the commands you have. On a terminal it pages (your `PAGER`, or a
simple built-in pager); piped, it prints plainly. `phaneris guide --search WORD` finds a word. In the command bar,
`? TOPIC`; in full-screen mode, `? TOPIC` or `:guide TOPIC` opens it in a tab.

### The command bar

`phaneris` with no words on a terminal opens a prompt. Type a subject and a code and press Enter; `?` shows help;
Ctrl-D leaves. Tab suggests from your own earlier commands first (most used and most recent first), then codes, then
subjects you have seen; Tab on an empty line offers your last commands. On a color terminal the best suggestion shows
dimmed after the cursor; Right arrow or Tab takes it. Up and Down walk earlier commands.

What you run in the bar is kept in `~/.config/phaneris/history` (only you can read it, at most 500 lines) for these
suggestions. Questions typed into a conversation are never kept, nor anything that looks like a password or a sign-in.
`phaneris history` shows it; `phaneris history --clear` empties it.

### Full-screen mode

Several screens side by side, keyboard first. It needs one optional extra (the plain command line does not):

```bash
pipx inject phaneris-cli textual
# or from the start:
pipx install "phaneris-cli[tui] @ git+https://github.com/avis-giri/phaneris_cli"
```

Then `phaneris tui` (or `phaneris tui T-000003 SCR`); with the extra installed, `phaneris` with no words opens it too.
The bar on top takes the same subjects and codes, with the same history suggestions; Enter opens the screen as a new
tab in the pane in focus. Up to four panes, each with tabs and drawn for its own width; a status line shows who you
are, your office, the questions left and the server's version.

| Key | Does |
| --- | --- |
| `ctrl+k` or `/` | the bar |
| `ctrl+n`, `ctrl+x` | a new pane (up to four); close the pane |
| `f6`, `shift+f6` | next, previous pane |
| `[`, `]`, `ctrl+w` | previous, next tab; close the tab |
| `<`, `>` | narrow, widen the pane |
| `ctrl+s` | save this layout (`:save NAME`, `:load NAME`, `:layouts`) |
| `ctrl+g`, `ctrl+b` | whole knowledge graph on or off; buy 100 questions (press twice) |
| `?` | help; `ctrl+q` leaves |

With no saved layout, it opens on the welcome pane (see The Phaneris window above). A layout saved before 0.7.0 that
names NEWS or WATCH still opens; those tabs are skipped with a note.

GRF is a map you can walk: arrows move, Enter re-centres on a record (one more lookup), Backspace goes back, `d` shows
the record's brief beside it, `o` opens it in a tab. On PORT, Enter opens a disclosure's scores. Layouts are kept in
`~/.config/phaneris/layouts.json` (only you can read it); "default" opens by itself. After 30 minutes without a key the
screen locks until a key is pressed; your password is never asked for or kept.

### Themes

`--theme phaneris` (the default: the site's violet accent) or `--theme amber` (amber on black, high contrast), or set
`PHANERIS_THEME`. Color appears only on a terminal and never with `NO_COLOR`; screens fit the terminal's width.

## Usage and limits

`phaneris usage`, `USAGE` in the bar, or F2 in the window shows your plan and limits; the console has the same on its
Usage and limits page.

| Limit | Amount |
| --- | --- |
| Questions about your disclosures | 10 free in any 12 hours |
| Questions across the whole knowledge graph | 5 free in total (these do not renew) |
| Bought questions | used after the free ones, for both kinds: 100 for $5; they do not expire |
| Knowledge graph lookups | 300 an hour (2,000 for administrators) |
| New disclosures scored | 25 a day |
| Sign-in | ends after 2 minutes without use; terminal sign-ins last at most 30 days |
| Administrators | no limit on questions |

At 80% of a kind of free question, and when it is used up, a short notice says so after each answer. `phaneris buy`
records a request for 100 questions; until online payment opens, an administrator adds them.

## What you can reach

- About a disclosure (questions and lookups): that disclosure and what it connects to in the knowledge graph, never
  another institution's disclosures. 10 free questions in any 12 hours. Lookups: 300 an hour.
- The whole knowledge graph: through `phaneris ask --graph`, 5 free questions in all, then bought ones (100 for $5).
- Administrators: questions and lookups across the whole graph without a question limit.
- Administration (accounts, data, the scoring queue) stays in the browser for everyone.

## Settings

| Name | What |
| --- | --- |
| `--server URL` or `PHANERIS_URL` | The Phaneris site (default `https://www.phaneris.co`). Must be https, or this computer for testing. |
| `PHANERIS_USERNAME` | The username to sign in with. |
| `PHANERIS_TOKEN` | Use this sign-in instead of the stored one (for scripts; keep it out of files and shell history). |
| `PHANERIS_NO_KEYCHAIN=1` | Keep the sign-in in the file even on macOS. |
| `NO_COLOR`, `PHANERIS_NO_ANIMATION=1` | No color; no animation. |
| `PHANERIS_THEME` | `phaneris` or `amber`. |

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -e . pytest ruff
.venv/bin/python -m pytest
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

The tests run against a small fake server and touch no network or keychain.
