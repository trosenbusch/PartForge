"""FastAPI application factory: API routers, host + session-token guard and the SPA.

Security model (PartForge runs a local HTTP server on 127.0.0.1 that a browser talks to):

* **Host validation** – every request (API, SSE, static assets and the SPA ``index.html`` that carries
  the session token) must carry a loopback ``Host`` header: ``127.0.0.1``, ``localhost`` or ``[::1]``
  (any port, compared case-insensitively; a trailing dot or anything else is rejected). A foreign host
  is answered with **HTTP 421** and a short German text and **never** the token. An absolute-form request
  target (``GET http://host/ HTTP/1.1``) names the effective host itself (RFC 9112 §3.2.2): the real server's
  protocol (:func:`http_protocol`) moves its authority into the ``Host`` header, and the guard checks an
  absolute ``raw_path`` (h11) as well – a foreign host there is refused the same way. This defeats DNS
  rebinding: an attacker web page whose host resolves to 127.0.0.1 would be same-origin for the browser
  and could read ``/`` – but its requests carry the attacker's ``Host`` header, so they are refused
  before the token is ever emitted. The allowed set is configurable for tests (:func:`create_app`
  ``allowed_hosts`` / env ``PARTFORGE_TEST_HOSTS``); the real program passes ``allowed_hosts=frozenset()``
  (``partforge.__main__``) and so only ever allows loopback – it never reads the test hook.
* **Cross-site guard** – an unsafe request (POST/PUT/PATCH/DELETE) from a *foreign* site (``Origin`` of
  a non-loopback host, or ``Sec-Fetch-Site: cross-site``) is refused with **HTTP 403**. Same-origin
  requests of the SPA (``Origin`` = loopback) and requests without ``Origin`` from non-browser clients
  keep working.
* **SPA only for own navigations** – the ``index.html`` that carries the token is only rendered for a
  navigation the user started (address bar, bookmark, desktop window: ``Sec-Fetch-Site: none``) or that
  PartForge's own page started (``same-origin``), as a top-level document (``Sec-Fetch-Dest: document``);
  requests without these headers (non-browser clients, old browsers) count as such. A link, redirect or
  frame of another website (``cross-site``/``same-site``, ``Sec-Fetch-Dest: iframe`` …) gets **HTTP 403**
  with a short German page that links to ``/`` – no token, no query, so the SPA never runs for a foreign
  page (:func:`navigation_may_carry_token`).
* **No framing** – every response carries ``X-Frame-Options: DENY`` and ``Content-Security-Policy:
  frame-ancestors 'none'`` (merged into a route's own policy), so no website can frame PartForge
  (clickjacking).
* **Session token** – ``/api`` (except ``/api/health``) requires the per-process token in the
  ``X-PartForge-Token`` header or ``?token=`` query parameter (the latter only for EventSource, ``<img>``
  and downloads, which cannot set headers). A logging filter redacts ``token=`` from every logged URL.
"""
from __future__ import annotations

import contextlib
import functools
import importlib
import logging
import os
import secrets
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

from . import __version__

log = logging.getLogger("partforge")

# PARTFORGE_WEB_DIR lets developers/agents serve their own frontend build (e.g. parallel tests).
WEB_DIR = Path(os.environ.get("PARTFORGE_WEB_DIR") or (Path(__file__).parent / "web"))

# Every router module lives in partforge/api/routes_<name>.py and exposes `router`.
ROUTER_MODULES = [
    "system",
    "categories",
    "parts",
    "series",
    "symbols",
    "footprints",
    "libraries",
    "altium",
    "datasheets",
    "libimport",
    "housestyle",
]

TOKEN_HEADER = "X-PartForge-Token"
_PUBLIC_API = {"/api/health"}
_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

#: Host names PartForge accepts – the loopback interface it binds to, nothing else. The real program
#: never accepts any other name; tests add their own (``create_app(allowed_hosts=…)`` / PARTFORGE_TEST_HOSTS).
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

_HOST_REJECTED = "Ungültiger Host. PartForge nimmt nur lokale Verbindungen (127.0.0.1, localhost) an."
_CROSS_SITE_REJECTED = "Anfrage von einer fremden Website abgelehnt."

#: ``Sec-Fetch-Site`` of a navigation that may receive the SPA with the token: started by the user (address bar,
#: bookmark, desktop window, ``webbrowser.open``: ``none``) or by PartForge's own page (reload, link:
#: ``same-origin``). Empty = header missing (non-browser client, browser without Fetch Metadata).
_OWN_NAVIGATION_SITES = frozenset({"", "none", "same-origin"})
#: ``Sec-Fetch-Dest`` of such a navigation: a top-level document – never a frame, ``<object>``/``<embed>`` or fetch.
_TOP_LEVEL_DESTS = frozenset({"", "document"})
#: Every response forbids framing (clickjacking); merged into a route's own Content-Security-Policy.
_FRAME_ANCESTORS = "frame-ancestors 'none'"

#: Answer to a foreign website's navigation or frame: no token, no query, no SPA – only a link to the start page
#: (clicking it is a same-origin navigation of PartForge itself, which gets the SPA).
_FOREIGN_NAVIGATION_PAGE = """<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PartForge</title>
<style>
body{margin:0;min-height:100vh;display:grid;place-items:center;background:#090b10;color:#e8eaf0;
font:15px/1.55 "Segoe UI",system-ui,sans-serif}
main{max-width:34rem;padding:2rem}
h1{margin:0 0 .75rem;font-size:1.2rem;font-weight:600}
p{margin:0 0 1rem;color:#a9afbd}
a{color:#ff8a3d;font-weight:600}
@media (prefers-color-scheme: light){body{background:#f5f6fa;color:#161a22}p{color:#4c5466}a{color:#c2410c}}
</style>
</head>
<body>
<main>
<h1>PartForge wurde von einer anderen Website aufgerufen</h1>
<p>Zum Schutz Ihrer Bibliothek öffnet sich PartForge nicht über Links oder eingebettete Rahmen fremder Seiten.
Es wurde nichts ausgeführt.</p>
<p><a href="/">PartForge öffnen</a></p>
</main>
</body>
</html>
"""


def resolve_allowed_hosts(explicit: frozenset[str] | set[str] | None) -> frozenset[str]:
    """The set of accepted host names. ``explicit`` (from :func:`create_app`) wins; otherwise the test
    hook ``PARTFORGE_TEST_HOSTS`` (comma-separated, set only by tests) is honoured. The loopback names are
    always included; the real program, which passes neither, accepts only loopback."""
    hosts = set(LOOPBACK_HOSTS)
    if explicit is not None:
        hosts |= {h.strip().lower() for h in explicit if h and h.strip()}
    else:
        env = os.environ.get("PARTFORGE_TEST_HOSTS", "")
        hosts |= {h.strip().lower() for h in env.split(",") if h.strip()}
    return frozenset(hosts)


def request_host_name(host_header: str | None) -> str | None:
    """The bare host name from a ``Host`` header (port and IPv6 brackets stripped, lower-cased), or
    ``None`` when the value is missing, malformed, or carries a trailing dot (``localhost.``) – such a
    value is never a loopback name and must be rejected."""
    raw = (host_header or "").strip()
    if not raw or any(c in raw for c in "/\\@ \t\r\n"):
        return None
    if raw.startswith("["):  # [::1] or [::1]:port
        end = raw.find("]")
        if end == -1:
            return None
        host, rest = raw[1:end], raw[end + 1:]
        if rest and not (rest.startswith(":") and rest[1:].isdigit()):
            return None
    elif raw.count(":") > 1:  # bare IPv6 without brackets, e.g. "::1"
        host = raw
    else:
        host, _, port = raw.partition(":")
        if port and not port.isdigit():
            return None
    host = host.strip()
    if not host or host.endswith("."):
        return None
    return host.lower()


def host_is_allowed(host_header: str | None, allowed: frozenset[str]) -> bool:
    name = request_host_name(host_header)
    return name is not None and name in allowed


def absolute_target_is_allowed(target: bytes, allowed: frozenset[str]) -> bool:
    """Whether an absolute-form request target (``http://host:port/path``) names an allowed host. Anything
    that is not ``scheme://authority…`` (or carries user info) is refused."""
    try:
        parts = urlsplit(target.decode("latin-1"))
    except ValueError:
        return False
    if not parts.scheme or not parts.netloc:
        return False
    return host_is_allowed(parts.netloc, allowed)


@functools.cache
def http_protocol() -> Any:
    """The uvicorn ``http`` protocol of the real server: httptools (uvicorn's default) with one change –
    an absolute-form request target replaces the ``Host`` header by its own authority, as RFC 9112 §3.2.2
    requires. uvicorn's httptools parser otherwise keeps only the path of such a target, so the host guard
    would see the client's ``Host`` header instead of the host the request really names. Without httptools
    ``"h11"``, whose absolute ``raw_path`` the guard checks itself."""
    try:
        import httptools
        from uvicorn.protocols.http.httptools_impl import HttpToolsProtocol
    except ImportError:  # pragma: no cover - httptools is a dependency of uvicorn[standard]
        return "h11"

    class LoopbackHttpToolsProtocol(HttpToolsProtocol):
        def on_headers_complete(self) -> None:
            if self.url[:1] not in (b"/", b"*"):  # absolute-form (or broken) request target
                authority = b"invalid."
                with contextlib.suppress(Exception):
                    parsed = httptools.parse_url(self.url)
                    if parsed.host:
                        host = b"[" + parsed.host + b"]" if b":" in parsed.host else parsed.host
                        authority = host + (b":%d" % parsed.port if parsed.port else b"")
                # self.headers is the list in scope["headers"]: replace the Host header in place
                self.headers[:] = [(name, value) for name, value in self.headers if name != b"host"]
                self.headers.append((b"host", authority))
            super().on_headers_complete()

    return LoopbackHttpToolsProtocol


def _origin_is_foreign(origin: str | None, allowed: frozenset[str]) -> bool:
    """True when ``Origin`` names a non-loopback site (a cross-site request). A missing ``Origin`` is not
    foreign (non-browser clients send none); an ``Origin`` of ``null`` counts as foreign."""
    if not origin:
        return False
    value = origin.strip()
    if value.lower() == "null":
        return True
    host = urlsplit(value).hostname  # already lower-cased, brackets stripped
    if host is None:
        return True
    return host.rstrip(".").lower() not in allowed


def navigation_may_carry_token(headers: Any) -> bool:
    """Whether a request for the SPA ``index.html`` may receive the session token: a top-level navigation the
    user started (``Sec-Fetch-Site: none`` – address bar, bookmark, desktop window) or PartForge's own page
    started (``same-origin`` – reload, link). A navigation, redirect or frame of another website (``cross-site``,
    ``same-site`` – e.g. another local server –, ``Sec-Fetch-Dest: iframe``/``object``/``embed``/fetch) must not:
    the SPA would run with the token for that page (e.g. ``/altium`` actions, clickjacking). Without these headers
    (non-browser clients, browsers without Fetch Metadata) the request counts as the user's own."""
    site = (headers.get("sec-fetch-site") or "").strip().lower()
    dest = (headers.get("sec-fetch-dest") or "").strip().lower()
    return site in _OWN_NAVIGATION_SITES and dest in _TOP_LEVEL_DESTS


def deny_framing(response: Response) -> Response:
    """No website may frame PartForge (clickjacking): ``X-Frame-Options: DENY`` and ``frame-ancestors 'none'``,
    appended to a Content-Security-Policy the route set itself (e.g. the sandbox policy of SVG previews)."""
    response.headers["X-Frame-Options"] = "DENY"
    policy = response.headers.get("content-security-policy")
    if not policy:
        response.headers["Content-Security-Policy"] = _FRAME_ANCESTORS
    elif "frame-ancestors" not in policy.lower():
        response.headers["Content-Security-Policy"] = f"{policy.rstrip('; ')}; {_FRAME_ANCESTORS}"
    return response


def create_app(token: str | None = None, *, allowed_hosts: frozenset[str] | set[str] | None = None) -> FastAPI:
    """Create the app. ``token`` protects ``/api`` against requests from foreign web pages; ``allowed_hosts``
    overrides the accepted ``Host`` names (tests only – the real program accepts only loopback)."""
    session_token = token or secrets.token_urlsafe(24)
    accepted_hosts = resolve_allowed_hosts(allowed_hosts)
    app = FastAPI(
        title="PartForge API",
        version=__version__,
        description="Datenbankbasierte Bauteilbibliotheken für Altium Designer",
    )
    app.state.token = session_token
    app.state.allowed_hosts = accepted_hosts

    def refusal(request: Request) -> Response | None:
        """The guard's answer for a request that must not reach a route (``None``: let it through)."""
        # 1) Host validation for EVERY request (incl. "/" which carries the token). No token in the reply.
        if not host_is_allowed(request.headers.get("host"), accepted_hosts):
            return JSONResponse({"detail": _HOST_REJECTED}, status_code=421)
        raw_path = request.scope.get("raw_path") or b""
        if raw_path[:1] not in (b"/", b"*", b"") and not absolute_target_is_allowed(raw_path, accepted_hosts):
            return JSONResponse({"detail": _HOST_REJECTED}, status_code=421)  # absolute-form target (h11)
        # 2) Cross-site guard for unsafe methods (defense in depth; same-origin/no-origin keep working).
        if request.method in _UNSAFE_METHODS:
            if (request.headers.get("sec-fetch-site") == "cross-site"
                    or _origin_is_foreign(request.headers.get("origin"), accepted_hosts)):
                return JSONResponse({"detail": _CROSS_SITE_REJECTED}, status_code=403)
        # 3) Session token for /api (except the public health check and CORS preflight).
        path = request.url.path
        if path.startswith("/api/") and path not in _PUBLIC_API and request.method != "OPTIONS":
            supplied = request.headers.get(TOKEN_HEADER) or request.query_params.get("token")
            if supplied != session_token:
                return JSONResponse({"detail": "Ungültiges oder fehlendes Sitzungstoken"}, status_code=401)
        return None

    @app.middleware("http")
    async def security_guard(request: Request, call_next):
        response = refusal(request)
        if response is None:
            response = await call_next(request)
        # 4) No framing by any website – on every response, refusals included (clickjacking).
        return deny_framing(response)

    for name in ROUTER_MODULES:
        module = importlib.import_module(f"partforge.api.routes_{name}")
        app.include_router(module.router, prefix="/api")

    _mount_spa(app, session_token)
    return app


def _mount_spa(app: FastAPI, token: str) -> None:
    index = WEB_DIR / "index.html"

    def render_index(request: Request) -> Response:
        # the token only for the user's own navigation (or PartForge's): never for another website's link,
        # redirect or frame – the page names no token and no query, its link to "/" is same-origin
        if not navigation_may_carry_token(request.headers):
            return HTMLResponse(_FOREIGN_NAVIGATION_PAGE, status_code=403, headers={"Cache-Control": "no-store"})
        if not index.is_file():
            return HTMLResponse(
                "<h1>PartForge</h1><p>Frontend ist nicht gebaut. Bitte <code>npm run build</code> im Ordner "
                "<code>frontend</code> ausführen.</p>",
                status_code=503,
            )
        from .config import load_settings

        html = index.read_text(encoding="utf-8")
        theme = load_settings().theme
        meta = f'<meta name="partforge-token" content="{token}"><meta name="partforge-theme" content="{theme}">'
        html = html.replace("</head>", f"{meta}</head>", 1)
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    @app.get("/", include_in_schema=False)
    async def root(request: Request) -> Response:
        return render_index(request)

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str, request: Request) -> Response:
        if path.startswith("api/"):
            return JSONResponse({"detail": "Nicht gefunden"}, status_code=404)
        candidate = (WEB_DIR / path).resolve()
        if WEB_DIR.resolve() in candidate.parents and candidate.is_file():
            headers = {"Cache-Control": "public, max-age=31536000, immutable"} if "/assets/" in f"/{path}" else {}
            return FileResponse(candidate, headers=headers)
        return render_index(request)
