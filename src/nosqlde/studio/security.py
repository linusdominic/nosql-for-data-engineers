"""Request protection for a local server that runs database commands from a browser.

* The server binds 127.0.0.1 only (see nosqlde.studio.server.serve).
* Every /api/ request must carry the per-start random token in the X-Studio-Token
  header. The token is printed in the terminal URL; the page moves it from the URL into
  sessionStorage and sends it as a header, so other sites cannot read or replay it.
* The Host header must be 127.0.0.1:<port> or localhost:<port>. A DNS-rebinding page
  (evil.example resolving to 127.0.0.1) sends its own host name and is refused.
* An Origin header, when present, must be this server's origin; Sec-Fetch-Site, when
  present, must not be cross-site for /api/. No CORS headers are ever sent, so a
  cross-origin preflight is refused too.
* Every response carries a strict Content-Security-Policy (no inline script, no other
  origins), nosniff, no framing, and Referrer-Policy: no-referrer so the token in the
  start URL never leaks to a link target such as GitHub.
"""

from __future__ import annotations

import hmac
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

TOKEN_HEADER = "x-studio-token"
MAX_BODY_BYTES = 512 * 1024

SECURITY_HEADERS = {
    "content-security-policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; "
        "form-action 'none'; frame-ancestors 'none'"
    ),
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
    "cross-origin-opener-policy": "same-origin",
    "cross-origin-resource-policy": "same-origin",
    "cache-control": "no-store",
}

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


def allowed_hosts(port: int) -> set[str]:
    return {f"127.0.0.1:{port}", f"localhost:{port}"}


def allowed_origins(port: int) -> set[str]:
    return {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}


def host_ok(host: str | None, port: int) -> bool:
    return host is not None and host.lower() in allowed_hosts(port)


def origin_ok(origin: str | None, port: int) -> bool:
    """No Origin (same-origin GET, curl) is fine; a present one must be ours."""
    return origin is None or origin in allowed_origins(port)


def token_ok(given: str | None, token: str) -> bool:
    return given is not None and hmac.compare_digest(given.encode(), token.encode())


def verdict(
    *,
    method: str,
    path: str,
    headers: dict[str, str],
    token: str,
    port: int,
) -> tuple[int, str] | None:
    """None if the request may proceed, else (status, reason). Pure, for unit tests."""
    if not host_ok(headers.get("host"), port):
        return 421, "This server only answers to 127.0.0.1 and localhost on its own port."
    if not origin_ok(headers.get("origin"), port):
        return 403, "Cross-origin requests are refused."
    is_api = path == "/api" or path.startswith("/api/")
    if is_api:
        if headers.get("sec-fetch-site") == "cross-site":
            return 403, "Cross-site requests are refused."
        if method == "OPTIONS":
            return 403, "No cross-origin access."
        if not token_ok(headers.get(TOKEN_HEADER), token):
            return 401, "Missing or wrong studio token. Open the URL printed by `make studio`."
        length = headers.get("content-length")
        if length is not None:
            try:
                if int(length) > MAX_BODY_BYTES:
                    return 413, "Request too large."
            except ValueError:
                return 400, "Bad Content-Length."
    return None


class Guard:
    """ASGI middleware applying `verdict` and adding the security headers."""

    def __init__(self, app: ASGIApp, *, token: str, port: int) -> None:
        self.app = app
        self.token = token
        self.port = port

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            if scope["type"] == "websocket":  # nothing here speaks websocket
                await send({"type": "websocket.close", "code": 1008})
                return
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        refused = verdict(
            method=scope.get("method", "GET"),
            path=scope.get("path", "/"),
            headers=headers,
            token=self.token,
            port=self.port,
        )
        if refused is not None:
            status, reason = refused
            body = ('{"detail": "' + reason.replace('"', "'") + '"}').encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": status,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                    ]
                    + [(k.encode(), v.encode()) for k, v in SECURITY_HEADERS.items()],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                existing = [
                    (k, v)
                    for k, v in message.get("headers", [])
                    if k.decode().lower() not in SECURITY_HEADERS
                ]
                message["headers"] = existing + [
                    (k.encode(), v.encode()) for k, v in SECURITY_HEADERS.items()
                ]
            await send(message)

        await self.app(scope, receive, send_with_headers)
