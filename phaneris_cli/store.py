"""Where the sign-in is kept: the macOS keychain when it is there, otherwise a file only this user can read.

The token never goes on a command line (where other users could see it in the process list): the keychain is
written through `security -i`, which reads its command from standard input.
"""

import json
import os
import shutil
import stat
import subprocess
import sys

SERVICE = "phaneris-cli"
CONFIG_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "phaneris")
CONFIG = os.path.join(CONFIG_DIR, "config.json")
TOKEN_FILE = os.path.join(CONFIG_DIR, "token.json")


def _keychain():
    return sys.platform == "darwin" and shutil.which("security") and not os.environ.get("PHANERIS_NO_KEYCHAIN")


def read_config():
    try:
        with open(CONFIG) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def write_config(cfg):
    os.makedirs(CONFIG_DIR, mode=0o700, exist_ok=True)
    with open(CONFIG, "w") as fh:
        json.dump(cfg, fh, indent=2)


def save_token(server, token):
    """Returns where it was kept: "keychain" or the file path."""
    if _keychain():
        cmd = f'add-generic-password -U -a "{server}" -s "{SERVICE}" -l "Phaneris command line" -w "{token}"\n'
        done = subprocess.run(["security", "-i"], input=cmd, text=True, capture_output=True, check=False)  # noqa: S603, S607
        if done.returncode == 0 and _keychain_read(server) == token:
            return "keychain"
    os.makedirs(CONFIG_DIR, mode=0o700, exist_ok=True)
    tokens = _file_tokens()
    tokens[server] = token
    fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(fd, "w") as fh:
        json.dump(tokens, fh)
    os.chmod(TOKEN_FILE, stat.S_IRUSR | stat.S_IWUSR)
    return TOKEN_FILE


def load_token(server):
    if os.environ.get("PHANERIS_TOKEN"):
        return os.environ["PHANERIS_TOKEN"]
    if _keychain():
        t = _keychain_read(server)
        if t:
            return t
    return _file_tokens().get(server)


def delete_token(server):
    if _keychain():
        subprocess.run(["security", "delete-generic-password", "-a", server, "-s", SERVICE], capture_output=True, check=False)  # noqa: S603, S607
    tokens = _file_tokens()
    if tokens.pop(server, None) is not None:
        fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_TRUNC)
        with os.fdopen(fd, "w") as fh:
            json.dump(tokens, fh)


def _keychain_read(server):
    done = subprocess.run(  # noqa: S603
        ["security", "find-generic-password", "-a", server, "-s", SERVICE, "-w"],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    return done.stdout.strip() if done.returncode == 0 else None


def _file_tokens():
    try:
        with open(TOKEN_FILE) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def where_kept(server):
    """keychain, file (only this user can read it), file-open (others can read it), or none."""
    if _keychain() and _keychain_read(server):
        return "keychain"
    if server in _file_tokens():
        mode = stat.S_IMODE(os.stat(TOKEN_FILE).st_mode)
        return "file" if not mode & 0o077 else "file-open"
    return "none"
