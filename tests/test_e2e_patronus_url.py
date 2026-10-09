"""E2E tests must only ever reach staging Patronus: test repos on production disrupt a shared service."""

from __future__ import annotations

import pytest

from .e2e_helpers import staging_patronus_url


def test_returns_configured_staging_url(monkeypatch):
    monkeypatch.setenv("PATRONUS_URL", "https://patronus-staging.labs.jb.gg")
    assert staging_patronus_url() == "https://patronus-staging.labs.jb.gg"


def test_fails_when_unset(monkeypatch):
    monkeypatch.delenv("PATRONUS_URL", raising=False)
    with pytest.raises(pytest.fail.Exception, match="PATRONUS_URL not set"):
        staging_patronus_url()


@pytest.mark.parametrize("url", ["https://patronus.labs.jb.gg", "https://patronus.labs.jb.gg/"])
def test_refuses_production(monkeypatch, url):
    monkeypatch.setenv("PATRONUS_URL", url)
    with pytest.raises(pytest.fail.Exception, match="production"):
        staging_patronus_url()
