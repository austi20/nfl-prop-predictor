from __future__ import annotations

import keyring

_SERVICE = "nfl-prop-workstation"


def _key(venue: str, key_name: str) -> str:
    return f"{venue}:{key_name}"


def store(venue: str, key_name: str, value: str) -> None:
    keyring.set_password(_SERVICE, _key(venue, key_name), value)


def load(venue: str, key_name: str) -> str | None:
    return keyring.get_password(_SERVICE, _key(venue, key_name))


def delete(venue: str, key_name: str) -> None:
    try:
        keyring.delete_password(_SERVICE, _key(venue, key_name))
    except keyring.errors.PasswordDeleteError:
        pass
