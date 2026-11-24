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
| `phaneris doctor` | Check Python, the server, your sign-in and where it is kept |
| `phaneris disclosures` | Your office's disclosures with deal chance and recommendation |
| `phaneris disclosures show ID [--all]` | One disclosure's report: outlook, checks, every metric with Real or Inferred, facts not measured |
| `phaneris report ID [--pdf FILE] [--all]` | The same report; `--pdf` saves the stored PDF when there is one |
| `phaneris score FILE` / `score --example` | Enter a new disclosure from a JSON file and follow its scoring |
| `phaneris jobs` | Your scoring jobs |
| `phaneris ask "question" [--disclosure ID]` | Ask about one of your disclosures (default: the last one you used) |
| `phaneris ask "question" --graph` | Ask across the whole knowledge graph (metered) |
| `phaneris ask -i` | A conversation that keeps your earlier questions |
| `phaneris usage` / `buy` | Questions you have left; request 100 more for $5 |
| `phaneris graph search TEXT [--disclosure ID]` | Records around your disclosure that match |
| `phaneris graph record NODE [--disclosure ID]` | One record, with a short claim excerpt for a patent |
| `phaneris graph related NODE [--disclosure ID]` | The records one step from it |

Every command takes `--json` for machine-readable output and `--no-color` for plain text. Color and the wordmark
appear only on a terminal, never with `NO_COLOR` set; `PHANERIS_NO_ANIMATION=1` turns the animation off.

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

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -e . pytest ruff
.venv/bin/python -m pytest
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

The tests run against a small fake server and touch no network or keychain.
