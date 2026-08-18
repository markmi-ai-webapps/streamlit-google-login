from unittest.mock import MagicMock

import pytest
import streamlit
from conftest import Rerun

from streamlit_google_login import cookies


def test_write_cookie_passes_expected_args(monkeypatch):
    # Arrange
    manager = MagicMock()
    monkeypatch.setattr(cookies, "_cookie_manager", lambda: manager)

    # Act
    cookies.write_cookie("sgl_oauth_state", "abc123", secure=True)

    # Assert
    manager.set.assert_called_once_with(
        "sgl_oauth_state",
        "abc123",
        key="_sgl_set_sgl_oauth_state",
        max_age=600,
        same_site="lax",
        secure=True,
    )


def test_read_cookies_with_retry_returns_immediately_when_key_present(monkeypatch):
    # Arrange
    manager = MagicMock()
    manager.get_all.return_value = {"sgl_oauth_state": "abc123"}
    monkeypatch.setattr(cookies, "_cookie_manager", lambda: manager)

    # Act
    result = cookies.read_cookies_with_retry("sgl_oauth_state")

    # Assert
    assert result == {"sgl_oauth_state": "abc123"}


def test_read_cookies_with_retry_retries_when_key_missing(monkeypatch):
    # Arrange
    manager = MagicMock()
    manager.get_all.return_value = {}
    monkeypatch.setattr(cookies, "_cookie_manager", lambda: manager)
    monkeypatch.setattr(cookies.time, "sleep", lambda seconds: None)

    # Act / Assert
    with pytest.raises(Rerun):
        cookies.read_cookies_with_retry("sgl_oauth_state")
    assert streamlit.session_state["_sgl_read_attempts_sgl_oauth_state"] == 1


def test_read_cookies_with_retry_gives_up_after_max_retries(monkeypatch):
    # Arrange
    manager = MagicMock()
    manager.get_all.return_value = {}
    monkeypatch.setattr(cookies, "_cookie_manager", lambda: manager)
    monkeypatch.setattr(cookies.time, "sleep", lambda seconds: None)
    streamlit.session_state["_sgl_read_attempts_sgl_oauth_state"] = cookies._MAX_RETRIES

    # Act
    result = cookies.read_cookies_with_retry("sgl_oauth_state")

    # Assert
    assert result == {}


def test_read_cookies_with_retry_treats_none_as_empty(monkeypatch):
    # Arrange
    manager = MagicMock()
    manager.get_all.return_value = None
    monkeypatch.setattr(cookies, "_cookie_manager", lambda: manager)
    monkeypatch.setattr(cookies.time, "sleep", lambda seconds: None)

    # Act / Assert
    with pytest.raises(Rerun):
        cookies.read_cookies_with_retry("sgl_oauth_state")
