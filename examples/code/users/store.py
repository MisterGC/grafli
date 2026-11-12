"""Stub source for examples/oauth-callback.grafli, so its @path:line refs
resolve and `grafli diagnose` can check them."""

from users.db import create_user, emit, find_by_provider_id, update_profile


def upsert_user(profile):
    existing = find_by_provider_id(profile.id)
    if existing:
        update_profile(existing, profile)
        return existing
    new = create_user(profile)
    emit("UserCreated", new.id)
    return new
