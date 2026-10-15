"""Stub source for examples/oauth-callback.grafli."""

from users.store import upsert_user


def exchange(code):
    token = provider.post(TOKEN_URL, code)
    if token.iss != EXPECTED_ISSUER or token.aud != CLIENT_ID:
        raise InvalidToken(token)
    profile = provider.get(USERINFO_URL, token)
    return upsert_user(profile)
