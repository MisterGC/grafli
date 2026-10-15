"""Stub source for examples/oauth-callback.grafli, so its @path:line refs
resolve and `grafli diagnose` can check them."""

from auth.oauth import exchange


def handle_callback(req):
    if req.method != "POST" or not rate_limit_ok(req.ip):
        return Response(405)
    if not csrf_match(req.query.state, req.cookie):
        return Response(400, "csrf_mismatch")
    return exchange(req.query.code)


def finalize(sid, return_to):
    if return_to not in ALLOWED_RETURN_TO:
        return Response(400, "bad return_to")
    return Response(302, location=return_to, cookie=sid)
