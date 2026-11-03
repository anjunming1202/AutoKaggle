"""Legacy fixtures predate explicit storage consent; new tests enable the gate."""
import pytest


@pytest.fixture(autouse=True)
def legacy_storage_consent(monkeypatch):
    monkeypatch.setenv("AUTOKAGGLE_REQUIRE_STORAGE_CONSENT", "0")
