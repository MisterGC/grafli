"""Stub source for examples/oauth-callback.grafli, so its @path:line refs
resolve and `grafli diagnose` can check them."""

from users.store import upsert_user


TOKEN_URL = "https://provider.example/token"
USERINFO_URL = "https://provider.example/userinfo"
EXPECTED_ISSUER = "https://provider.example"
CLIENT_ID = "grafli-example"


def InvalidToken(*args):
    """The provider's token failed a check."""
    raise NotImplementedError


def post(*args):
    """POST to the provider."""
    raise NotImplementedError


def get(*args):
    """GET from the provider."""
    raise NotImplementedError


def decode_jwt(*args):
    """Decode a JWT without trusting it."""
    raise NotImplementedError


def fetch_jwks(*args):
    """Fetch the provider's signing keys."""
    raise NotImplementedError


def verify_signature(*args):
    """Check a token's signature."""
    raise NotImplementedError


def check_expiry(*args):
    """Reject an expired token."""
    raise NotImplementedError


def refresh(*args):
    """Refresh an access token."""
    raise NotImplementedError


def revoke(*args):
    """Revoke a token at the provider."""
    raise NotImplementedError


def build_auth_url(*args):
    """The URL the login button opens."""
    raise NotImplementedError


def pkce_pair(*args):
    """A PKCE verifier and challenge."""
    raise NotImplementedError


def nonce(*args):
    """A fresh nonce."""
    raise NotImplementedError


def store_verifier(*args):
    """Keep the PKCE verifier for the callback."""
    raise NotImplementedError


SCOPES = ("openid", "profile", "email")
TIMEOUT_S = 10
RETRIES = 2


def exchange(code):
    token = post(TOKEN_URL, code)
    if token.iss != EXPECTED_ISSUER or token.aud != CLIENT_ID:
        raise InvalidToken(token)
    profile = get(USERINFO_URL, token)
    return upsert_user(profile)
