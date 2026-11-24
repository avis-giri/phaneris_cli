# Phaneris command line

Use Phaneris from a terminal with your own account: your workspace's disclosures and reports, scoring a new
disclosure, and questions about a disclosure or the whole knowledge graph. You see and do exactly what the console
allows your account; the command line adds no access of its own.

## Install

Needs Python 3.10 or newer.

```bash
pipx install git+https://github.com/YOUR-ORG/phaneris-cli
```

(or `pip install --user .` from a copy of this folder). It has no other dependencies.

## Sign in

```bash
phaneris login
```

It prints a link and a code such as `ABCD-EFGH` and opens the link in your browser. Sign in to the console there if
you are not already, check that the code matches, and approve it. The command line is then signed in as you, in the
workspace you approved from. To use another workspace, switch to it in the console and run `phaneris login` again.

Your sign-in lasts 30 days. It is kept in the macOS keychain; on other systems, in
`~/.config/phaneris/token.json`, readable only by your account. See and end your sign-ins on the console's Settings
page; administrators can end anyone's on Users.

```bash
phaneris whoami
phaneris logout
```

## Commands

| Command | What it does |
| --- | --- |
| `phaneris disclosures` | Your workspace's disclosures with deal chance and recommendation |
| `phaneris disclosures show ID` | One disclosure: score cards and the nine metric scores, each marked real or inferred |
| `phaneris report ID [--pdf FILE]` | The same summary and a link to the full report; `--pdf` saves the stored PDF when there is one |
| `phaneris score FILE` | Enter a new disclosure from a JSON file and follow its scoring until the report is ready |
| `phaneris score --example` | Print an example disclosure file to start from |
| `phaneris jobs` | Your scoring jobs |
| `phaneris ask "question" --disclosure ID` | Ask about one of your disclosures and what it connects to |
| `phaneris ask "question" --graph` | Ask across the whole knowledge graph (a few free questions, then bought ones) |
| `phaneris usage` | Questions you have left |
| `phaneris buy` | Request 100 more questions for $5 |

Add `--json` to any command for machine-readable output, for example `phaneris --json disclosures`.

## Questions and limits

The server decides every limit, the same as in the console:

- About your disclosures: a number of free questions in any 12 hours.
- Across the whole knowledge graph: a few free questions in all.
- After that, bought questions, 100 for $5 (`phaneris buy`). Online payment is coming; until then an administrator
  adds the pack once you request it.
- Phaneris administrators ask without a limit.

Answers cite the records they come from; add `--cites` to `phaneris ask` to keep those tags in the text.

## Settings

| Name | What |
| --- | --- |
| `--server URL` or `PHANERIS_URL` | The Phaneris site (default `https://www.phaneris.co`). Must be https, or this computer for testing. |
| `PHANERIS_TOKEN` | Use this token instead of the stored sign-in (for scripts; keep it out of files and shell history). |
| `PHANERIS_NO_KEYCHAIN=1` | Keep the sign-in in the file even on macOS. |

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -e . pytest ruff
.venv/bin/python -m pytest
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

The tests run against a small fake server and touch no network or keychain.
