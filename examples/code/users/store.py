"""Stub source for examples/oauth-callback.grafli."""


def upsert_user(profile):
    existing = find_by_provider_id(profile.id)
    if existing:
        update_profile(existing, profile)
        return existing
    new = create_user(profile)
    emit("UserCreated", new.id)
    return new
