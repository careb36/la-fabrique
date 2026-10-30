"""HTTP for the assistant: keys never follow a redirect to another origin.

``urllib`` copies every header, ``Authorization`` and ``X-Voice-Key`` included,
onto the request it makes after a redirect, wherever that points. A factory or
model server that redirects to another host (or from https to http) would hand
the key over. Here a redirect is followed only within the same scheme and host.
"""

from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request


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


def urlopen(request: urllib.request.Request, timeout: float):
    """``urllib.request.urlopen`` that refuses cross-origin redirects."""
    return _OPENER.open(request, timeout=timeout)
