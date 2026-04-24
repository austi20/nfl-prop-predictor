from __future__ import annotations

import keyring
import keyring.backend
import pytest


class _InMemoryKeyring(keyring.backend.KeyringBackend):
    priority = 100  # beats any system backend in test context

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self._store.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self._store[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self._store.pop((service, username), None)


@pytest.fixture(autouse=True)
def _use_in_memory_keyring(monkeypatch):
    backend = _InMemoryKeyring()
    monkeypatch.setattr(keyring, "get_keyring", lambda: backend)
    monkeypatch.setattr(keyring, "get_password", backend.get_password)
    monkeypatch.setattr(keyring, "set_password", backend.set_password)
    monkeypatch.setattr(keyring, "delete_password", backend.delete_password)
    yield


from api.trading.secrets import delete, load, store  # noqa: E402 — import after monkeypatch fixture


def test_store_and_load_round_trip() -> None:
    store("kalshi", "access_key", "DEMO-KEY-123")
    assert load("kalshi", "access_key") == "DEMO-KEY-123"


def test_load_missing_returns_none() -> None:
    assert load("kalshi", "nonexistent") is None


def test_delete_removes_value() -> None:
    store("kalshi", "access_key", "KEY")
    delete("kalshi", "access_key")
    assert load("kalshi", "access_key") is None


def test_delete_missing_is_noop() -> None:
    delete("kalshi", "does_not_exist")


def test_different_venues_are_isolated() -> None:
    store("kalshi", "access_key", "K-KEY")
    store("polymarket", "access_key", "P-KEY")
    assert load("kalshi", "access_key") == "K-KEY"
    assert load("polymarket", "access_key") == "P-KEY"
