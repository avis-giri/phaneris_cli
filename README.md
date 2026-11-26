# Phaneris command line

Use Phaneris from a terminal with your own account: your office's disclosures and reports with every score marked
Real or Inferred, scoring new disclosures, questions about a disclosure or the whole knowledge graph, and lookups in
the knowledge graph around your disclosures. You see and do exactly what the console allows your account; the
command line adds no access of its own.

Full documentation: https://www.phaneris.co/docs/terminal

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

## Commands

| Command | What it does |
| --- | --- |
| `phaneris login` / `logout` | Sign in, or end this sign-in |
| `phaneris whoami [--banner]` | Who you are signed in as (with the wordmark) |
| `phaneris version` | This program's version and the server's |
| `phaneris history [--clear]` | What you ran in the command bar (used for Tab suggestions); `--clear` empties it |
| `phaneris tui [SUBJECT CODE]` | Full-screen mode (needs the optional extra) |
| `phaneris doctor` | Check Python, the server, your sign-in and where it is kept |
| `phaneris disclosures` | Your office's disclosures with deal chance and recommendation |
| `phaneris disclosures show ID [--all]` | One disclosure's report: outlook, checks, every metric with Real or Inferred, facts not measured |
| `phaneris report ID [--pdf FILE] [--all]` | The same report; `--pdf` saves the designed report PDF |
| `phaneris score FILE` / `score --example` | Enter a new disclosure from a JSON file and follow its scoring |
| `phaneris jobs` | Your scoring jobs |
| `phaneris ask "question" [--disclosure ID]` | Ask about one of your disclosures (default: the last one you used) |
| `phaneris ask "question" --graph` | Ask across the whole knowledge graph (metered) |
| `phaneris ask -i` | A conversation that keeps your earlier questions |
| `phaneris usage` / `buy` | Questions you have left; request 100 more for $5 |
| `phaneris graph search TEXT [--disclosure ID]` | Records around your disclosure that match |
| `phaneris graph record NODE [--disclosure ID]` | One record, with a short claim excerpt for a patent |
| `phaneris graph related NODE [--disclosure ID]` | The records one step from it |
| `phaneris watch add SUBJECT [--disclosure ID]` | Watch a disclosure, or a record around one of yours (up to 200) |
| `phaneris watch remove SUBJECT` / `watch list` | Stop watching it; what you watch |
| `phaneris feed [--all]` | What changed in what you watch since you last looked (`--all`: everything kept) |

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
| WATCH | Watch it, or stop watching (a toggle; `--on`, `--off`); with no subject, what you watch | a disclosure or a record |
| NEWS | What changed in what you watch, grouped by item, newest first; for a subject, its own changes | anything |
| ASK | A conversation about it | anything |
| PORT | Your office's board, ranked by deal chance, with a heat row of the nine metrics | your office |
| HELP | What applies to the subject | anything |

Codes are case-insensitive. A name that matches several records gives a numbered list to choose from. Records are
looked up around the disclosure you opened last (administrators can reach the whole graph); open one first with
`phaneris T-ID DES`.

**WHY uses only the model's real numbers.** The deal chance is a fitted logistic model; the screen shows each of its
eleven inputs' push, coefficient times the input's distance from the training average, and checks that the terms add up
to the stored deal chance. If they do not (another model scored it), it says so and shows no split.

### What changed

Watch the disclosures and records you care about, and `phaneris feed` (or NEWS) shows what changed since you last
looked: new or removed patents, assignments, licences, trials, grants and papers; a changed application status, grant
date or owner; and a score that moved (the deal chance, the recommendation, any metric by more than 0.05, or a metric
turning Real or Inferred). Changes are found when new data is loaded and when a disclosure is scored again. Each line
says which screen opens it (a score move opens HIST, anything else the timeline).

```bash
phaneris watch add T-000003
phaneris watch add "US 8916381" --disclosure T-000003
phaneris feed
```

You can watch your own disclosures, and records within reach of one of them, up to 200 items. The feed is checked
against what you may see each time it is read: a change about a record that has left your reach is not named, and a
watched record that has left your reach stops showing. SCR shows a one-line score history; HIST shows every kept version.

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
| `w` | watch the disclosure or record in this pane, or stop watching |
| `?` | help; `ctrl+q` leaves |

With no saved layout, it opens on NEWS: Enter on a line opens that change's screen in a new tab. On any disclosure or
record screen, `w` watches it (or stops watching).

GRF is a map you can walk: arrows move, Enter re-centres on a record (one more lookup), Backspace goes back, `d` shows
the record's brief beside it, `o` opens it in a tab. On PORT, Enter opens a disclosure's scores. Layouts are kept in
`~/.config/phaneris/layouts.json` (only you can read it); "default" opens by itself. After 30 minutes without a key the
screen locks until a key is pressed; your password is never asked for or kept.

### Themes

`--theme phaneris` (the default: the site's violet accent) or `--theme amber` (amber on black, high contrast), or set
`PHANERIS_THEME`. Color appears only on a terminal and never with `NO_COLOR`; screens fit the terminal's width.

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
