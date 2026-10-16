"""Stub source for examples/oauth-callback.grafli, so its @path:line refs
resolve and `grafli diagnose` can check them."""

from auth.oauth import exchange


def rate_limit_ok(*args):
    """True while the caller's IP is under its limit."""
    raise NotImplementedError


def csrf_match(*args):
    """True when the state matches the signed cookie."""
    raise NotImplementedError



def handle_callback(req):
    if req.method != "POST" or not rate_limit_ok(req.ip):
        return Response(405)
    if not csrf_match(req.query.state, req.cookie):
        return Response(400, "csrf_mismatch")
    return exchange(req.query.code)


def Response(*args):
    """An HTTP response."""
    raise NotImplementedError


def constant_time_eq(*args):
    """Compare two strings in constant time."""
    raise NotImplementedError


def parse_state(*args):
    """Decode the state parameter."""
    raise NotImplementedError


def sign_cookie(*args):
    """Sign a cookie value."""
    raise NotImplementedError


def verify_cookie(*args):
    """Check a signed cookie."""
    raise NotImplementedError


def load_allowlist(*args):
    """Read the allowed return URLs."""
    raise NotImplementedError


def audit(*args):
    """Record a security event."""
    raise NotImplementedError


def client_ip(*args):
    """The caller's IP behind the proxy."""
    raise NotImplementedError


def error_page(*args):
    """Render an error page."""
    raise NotImplementedError


ALLOWED_SCHEMES = ("https",)
STATE_TTL_S = 600


def finalize(sid, return_to):
    if return_to not in load_allowlist():
        return Response(400, "bad return_to")
    return Response(302, location=return_to, cookie=sid)
