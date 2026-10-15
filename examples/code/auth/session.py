"""Stub source for examples/oauth-callback.grafli."""


def mint_session(user):
    sid = random_token(32)
    redis.set(sid, user.id, ttl=THIRTY_DAYS)
    return sid
