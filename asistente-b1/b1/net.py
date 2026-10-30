"""HTTP for the assistant: keys never follow a redirect to another origin.

``urllib`` copies every header, ``Authorization`` and ``X-Voice-Key`` included,
onto the request it makes after a redirect, wherever that points. A factory or
model server that redirects to another host (or from https to http) would hand
the key over. Here a redirect is followed only within the same scheme and host.
"""

from __future__ import annotations

import os
import urllib.error
import urllib.parse
import urllib.request

_LOOPBACK = {"127.0.0.1", "localhost", "::1"}
_SECRET_HEADERS = ("authorization", "x-voice-key")


class _SameOriginRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old = urllib.parse.urlsplit(req.full_url)
        new = urllib.parse.urlsplit(urllib.parse.urljoin(req.full_url, newurl))
        if (old.scheme, old.netloc) != (new.scheme, new.netloc):
            raise urllib.error.HTTPError(
                newurl, code, "redirect to another origin refused", headers, fp
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_SameOriginRedirects)


class InsecureTransport(urllib.error.URLError):
    """A key would cross the network unencrypted."""


def _carries_a_key(request: urllib.request.Request) -> bool:
    return any(
        request.get_header(name.capitalize()) or request.get_header(name.title())
        for name in _SECRET_HEADERS
    )


def check_transport(request: urllib.request.Request) -> None:
    """Refuse to send a key over plain http to another machine.

    The factory and the model server usually run on this computer, where http
    is fine. Anywhere else the key would travel in clear text; set
    ``B1_ALLOW_INSECURE_HTTP=1`` only on a network you trust.
    """
    url = urllib.parse.urlsplit(request.full_url)
    if url.scheme != "http" or (url.hostname or "") in _LOOPBACK:
        return
    if not _carries_a_key(request):
        return
    if os.getenv("B1_ALLOW_INSECURE_HTTP", "").strip() in {"1", "true", "yes"}:
        return
    raise InsecureTransport(
        f"refusing to send a key over plain http to {url.hostname}: use https, "
        "or set B1_ALLOW_INSECURE_HTTP=1 on a network you trust"
    )


def urlopen(request: urllib.request.Request, timeout: float):
    """``urllib.request.urlopen`` that refuses cross-origin redirects and
    keys over plain http to another machine."""
    check_transport(request)
    return _OPENER.open(request, timeout=timeout)
