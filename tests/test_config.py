import pytest
import streamlit
from streamlit.errors import StreamlitSecretNotFoundError

from streamlit_google_login.config import Config


class FakeSecrets:
    def __init__(self, data=None, raise_not_found=False):
        self._data = data or {}
        self._raise_not_found = raise_not_found

    def get(self, key, default=None):
        if self._raise_not_found:
            raise StreamlitSecretNotFoundError("no secrets.toml found")
        return self._data.get(key, default)


def test_resolve_uses_explicit_kwargs_over_secrets(monkeypatch):
    # Arrange
    monkeypatch.setattr(streamlit, "secrets", FakeSecrets({"auth": {"client_id": "secret-id"}}))

    # Act
    config = Config.resolve("kwarg-id", "kwarg-secret", "https://x.com/cb")

    # Assert
    assert config == Config("kwarg-id", "kwarg-secret", "https://x.com/cb")


def test_resolve_falls_back_to_secrets(monkeypatch):
    # Arrange
    monkeypatch.setattr(
        streamlit,
        "secrets",
        FakeSecrets({"auth": {"client_id": "id", "client_secret": "secret", "redirect_uri": "https://x.com/cb"}}),
    )

    # Act
    config = Config.resolve(None, None, None)

    # Assert
    assert config == Config("id", "secret", "https://x.com/cb")


def test_resolve_merges_kwargs_and_secrets(monkeypatch):
    # Arrange
    monkeypatch.setattr(
        streamlit,
        "secrets",
        FakeSecrets({"auth": {"client_secret": "secret-from-file", "redirect_uri": "https://x.com/cb"}}),
    )

    # Act
    config = Config.resolve("kwarg-id", None, None)

    # Assert
    assert config == Config("kwarg-id", "secret-from-file", "https://x.com/cb")


def test_resolve_tolerates_missing_secrets_file_when_kwargs_suffice(monkeypatch):
    # Arrange
    monkeypatch.setattr(streamlit, "secrets", FakeSecrets(raise_not_found=True))

    # Act
    config = Config.resolve("id", "secret", "https://x.com/cb")

    # Assert
    assert config == Config("id", "secret", "https://x.com/cb")


def test_resolve_raises_when_nothing_available(monkeypatch):
    # Arrange
    monkeypatch.setattr(streamlit, "secrets", FakeSecrets(raise_not_found=True))

    # Act / Assert
    with pytest.raises(RuntimeError, match="client_id, client_secret, redirect_uri"):
        Config.resolve(None, None, None)


def test_resolve_raises_naming_only_the_missing_fields(monkeypatch):
    # Arrange
    monkeypatch.setattr(streamlit, "secrets", FakeSecrets({"auth": {"client_id": "id"}}))

    # Act / Assert
    with pytest.raises(RuntimeError, match=r"missing OAuth config: client_secret, redirect_uri\."):
        Config.resolve(None, None, None)


@pytest.mark.parametrize(
    "redirect_uri, expected",
    [
        ("https://myapp.example.com/callback", True),
        ("http://localhost:8501", False),
        ("http://example.com/callback", False),
    ],
)
def test_secure(redirect_uri, expected):
    # Arrange
    config = Config("id", "secret", redirect_uri)

    # Act / Assert
    assert config.secure is expected


@pytest.mark.parametrize(
    "redirect_uri, expected",
    [
        ("http://localhost:8501/cb", True),
        ("http://127.0.0.1:8501/cb", True),
        ("http://[::1]:8501/cb", True),
        ("https://myapp.example.com/cb", False),
        ("http://example.com/cb", False),
        ("file://localhost/etc/passwd", False),
        ("javascript:alert(1)", False),
        ("ftp://example.com/x", False),
    ],
)
def test_is_local_http(redirect_uri, expected):
    # Arrange
    config = Config("id", "secret", redirect_uri)

    # Act / Assert
    assert config.is_local_http is expected
