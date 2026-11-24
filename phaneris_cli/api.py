"""Talking to the Phaneris API. Standard library only.

Every limit (role, workspace, disclosures in reach, question allowance) is decided by the server; this client only
shows what the server answers.
"""

import json
import platform
import urllib.error
import urllib.request

from . import __version__

TIMEOUT = 120  # scoring on the site can take a while


class ApiError(Exception):
    def __init__(self, status, message, code=None):
        super().__init__(message)
        self.status, self.message, self.code = status, message, code


class Api:
    def __init__(self, server, token=None):
        self.server = server.rstrip("/")
        self.token = token

    def call(self, method, path, body=None, raw=False):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.server + "/api" + path, data=data, method=method)
        req.add_header("User-Agent", f"phaneris-cli/{__version__} ({platform.system()})")
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as res:  # noqa: S310  the server URL is https or this machine
                payload = res.read()
                if raw:
                    return payload, res.headers.get("Content-Type", "")
                return json.loads(payload) if payload else {}
        except urllib.error.HTTPError as e:
            try:
                err = json.loads(e.read() or b"{}")
            except ValueError:
                err = {}
            raise ApiError(e.code, err.get("error") or f"The server answered {e.code}.", err.get("code")) from None
        except urllib.error.URLError as e:
            raise ApiError(0, f"Could not reach {self.server}: {e.reason}") from None

    def get(self, path, **kw):
        return self.call("GET", path, **kw)

    def post(self, path, body=None):
        return self.call("POST", path, body if body is not None else {})
