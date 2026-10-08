from collections.abc import Callable, Iterator
from contextlib import ExitStack

import pytest
from fastapi.testclient import TestClient

from config import Settings
from main import create_app


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests must not depend on the developer's shell variables."""
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)


def make_settings(**overrides) -> Settings:
    """Settings that ignore backend/.env, so every machine and CI sees the same values."""
    return Settings(_env_file=None, **overrides)


@pytest.fixture
def make_client() -> Iterator[Callable[..., TestClient]]:
    """Builds a TestClient with the lifespan running (models loaded) for the given settings."""
    with ExitStack() as stack:
        def _make(**overrides) -> TestClient:
            return stack.enter_context(TestClient(create_app(make_settings(**overrides))))

        yield _make
