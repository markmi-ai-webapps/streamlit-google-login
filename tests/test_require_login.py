import os
from unittest.mock import MagicMock

import pytest
import streamlit
from conftest import Rerun, Stopped
from oauthlib.oauth2 import OAuth2Error

import streamlit_google_login as sgl
from streamlit_google_login.config import Config


def make_config(redirect_uri="https://myapp.example.com/callback"):
    return Config("client-id", "client-secret", redirect_uri)


def mock_cookies(monkeypatch, state="expected-state", code_verifier="verifier"):
    monkeypatch.setattr(
        sgl,
        "read_cookies_with_retry",
        lambda key: {
            sgl._STATE_COOKIE_NAME: state,
            sgl._CODE_VERIFIER_COOKIE_NAME: code_verifier,
        },
    )


def mock_successful_flow(monkeypatch, email="user@example.com"):
    fake_flow = MagicMock()
    fake_flow.credentials = MagicMock(token="access-token")
    monkeypatch.setattr(sgl, "_build_flow", lambda *a, **kw: fake_flow)

    fake_response = MagicMock()
    fake_response.json.return_value = {"email": email}
    monkeypatch.setattr(sgl.requests, "get", lambda *a, **kw: fake_response)
    return fake_flow, fake_response


class TestBuildFlow:
    def test_builds_authorization_url_with_pkce(self):
        # Arrange
        config = make_config("https://myapp.example.com/cb")

        # Act
        flow = sgl._build_flow(config, ["openid"], autogenerate_code_verifier=True)
        auth_url, state = flow.authorization_url()

        # Assert
        assert auth_url.startswith("https://accounts.google.com/o/oauth2/auth")
        assert "client_id=client-id" in auth_url
        assert "code_challenge=" in auth_url
        assert state
        assert flow.code_verifier

    def test_reuses_supplied_state_and_code_verifier(self):
        # Arrange
        config = make_config("https://myapp.example.com/cb")

        # Act
        flow = sgl._build_flow(
            config, ["openid"], state="fixed-state", code_verifier="fixed-verifier"
        )

        # Assert
        assert flow.code_verifier == "fixed-verifier"


class TestRejectInsecureRedirectUri:
    def test_allows_https(self, monkeypatch):
        # Arrange
        monkeypatch.delenv("OAUTHLIB_INSECURE_TRANSPORT", raising=False)

        # Act
        sgl._reject_insecure_redirect_uri(make_config("https://myapp.example.com/cb"))

        # Assert
        assert "OAUTHLIB_INSECURE_TRANSPORT" not in os.environ

    def test_allows_localhost_http(self, monkeypatch):
        # Arrange
        monkeypatch.delenv("OAUTHLIB_INSECURE_TRANSPORT", raising=False)

        # Act
        sgl._reject_insecure_redirect_uri(make_config("http://localhost:8501/cb"))

        # Assert
        assert os.environ["OAUTHLIB_INSECURE_TRANSPORT"] == "1"

    def test_rejects_non_localhost_http(self):
        # Act / Assert
        with pytest.raises(RuntimeError, match="must use https"):
            sgl._reject_insecure_redirect_uri(make_config("http://example.com/cb"))

    def test_rejects_file_scheme_with_localhost_authority(self):
        # Act / Assert
        with pytest.raises(RuntimeError, match="must use https"):
            sgl._reject_insecure_redirect_uri(
                make_config("file://localhost/etc/passwd")
            )


class TestHandleSignInError:
    def test_stops_and_clears_params(self):
        # Arrange
        streamlit.query_params["error"] = "access_denied"

        # Act / Assert
        with pytest.raises(Stopped):
            sgl._handle_sign_in_error()
        assert streamlit.query_params == {}


class TestHandleOauthCallback:
    def test_rejects_missing_cookie_state(self, monkeypatch):
        # Arrange
        streamlit.query_params.update({"code": "auth-code", "state": "expected-state"})
        monkeypatch.setattr(sgl, "read_cookies_with_retry", lambda key: {})
        build_flow = MagicMock()
        monkeypatch.setattr(sgl, "_build_flow", build_flow)

        # Act / Assert
        with pytest.raises(Stopped):
            sgl._handle_oauth_callback(make_config(), sgl._BASE_SCOPES, None)
        build_flow.assert_not_called()
        assert streamlit.query_params == {}

    def test_rejects_state_mismatch(self, monkeypatch):
        # Arrange
        streamlit.query_params.update({"code": "auth-code", "state": "attacker-state"})
        mock_cookies(monkeypatch, state="expected-state")
        build_flow = MagicMock()
        monkeypatch.setattr(sgl, "_build_flow", build_flow)

        # Act / Assert
        with pytest.raises(Stopped):
            sgl._handle_oauth_callback(make_config(), sgl._BASE_SCOPES, None)
        build_flow.assert_not_called()

    def test_succeeds_and_stores_session(self, monkeypatch):
        # Arrange
        streamlit.query_params.update({"code": "auth-code", "state": "expected-state"})
        mock_cookies(monkeypatch)
        fake_flow, fake_response = mock_successful_flow(monkeypatch)

        # Act / Assert
        with pytest.raises(Rerun):
            sgl._handle_oauth_callback(make_config(), sgl._BASE_SCOPES, None)
        assert streamlit.session_state["_sgl_email"] == "user@example.com"
        assert streamlit.session_state["_sgl_credentials"] is fake_flow.credentials
        assert streamlit.query_params == {}
        fake_flow.fetch_token.assert_called_once_with(code="auth-code")
        fake_response.raise_for_status.assert_called_once()

    def test_enforces_allowed_domain(self, monkeypatch):
        # Arrange
        streamlit.query_params.update({"code": "auth-code", "state": "expected-state"})
        mock_cookies(monkeypatch)
        mock_successful_flow(monkeypatch, email="user@evil.com")

        # Act / Assert
        with pytest.raises(Stopped):
            sgl._handle_oauth_callback(make_config(), sgl._BASE_SCOPES, "markmi.ai")
        assert "_sgl_credentials" not in streamlit.session_state

    def test_allows_matching_domain(self, monkeypatch):
        # Arrange
        streamlit.query_params.update({"code": "auth-code", "state": "expected-state"})
        mock_cookies(monkeypatch)
        mock_successful_flow(monkeypatch, email="user@markmi.ai")

        # Act / Assert
        with pytest.raises(Rerun):
            sgl._handle_oauth_callback(make_config(), sgl._BASE_SCOPES, "markmi.ai")
        assert streamlit.session_state["_sgl_email"] == "user@markmi.ai"

    def test_catches_oauth_errors(self, monkeypatch):
        # Arrange
        streamlit.query_params.update({"code": "auth-code", "state": "expected-state"})
        mock_cookies(monkeypatch)
        fake_flow = MagicMock()
        fake_flow.fetch_token.side_effect = OAuth2Error("invalid_grant")
        monkeypatch.setattr(sgl, "_build_flow", lambda *a, **kw: fake_flow)

        # Act / Assert
        with pytest.raises(Stopped):
            sgl._handle_oauth_callback(make_config(), sgl._BASE_SCOPES, None)

    def test_does_not_swallow_missing_email_key(self, monkeypatch):
        # Arrange
        streamlit.query_params.update({"code": "auth-code", "state": "expected-state"})
        mock_cookies(monkeypatch)
        fake_flow = MagicMock()
        fake_flow.credentials = MagicMock(token="access-token")
        monkeypatch.setattr(sgl, "_build_flow", lambda *a, **kw: fake_flow)
        fake_response = MagicMock()
        fake_response.json.return_value = (
            {}
        )  # missing "email" -- shouldn't happen given _BASE_SCOPES
        monkeypatch.setattr(sgl.requests, "get", lambda *a, **kw: fake_response)

        # Act / Assert
        with pytest.raises(KeyError):
            sgl._handle_oauth_callback(make_config(), sgl._BASE_SCOPES, None)


class TestShowLoginLink:
    def test_writes_cookies_and_shows_button(self, monkeypatch):
        # Arrange
        fake_flow = MagicMock()
        fake_flow.authorization_url.return_value = (
            "https://accounts.google.com/auth",
            "generated-state",
        )
        fake_flow.code_verifier = "generated-verifier"
        monkeypatch.setattr(sgl, "_build_flow", lambda *a, **kw: fake_flow)
        write_cookie_mock = MagicMock()
        monkeypatch.setattr(sgl, "write_cookie", write_cookie_mock)

        # Act / Assert
        with pytest.raises(Stopped):
            sgl._show_login_link(
                make_config(), sgl._BASE_SCOPES, "select_account", "Please log in"
            )
        assert (
            streamlit.session_state["_sgl_pending_auth_url"]
            == "https://accounts.google.com/auth"
        )
        write_cookie_mock.assert_any_call(
            sgl._STATE_COOKIE_NAME, "generated-state", secure=True
        )
        write_cookie_mock.assert_any_call(
            sgl._CODE_VERIFIER_COOKIE_NAME, "generated-verifier", secure=True
        )

    def test_does_not_regenerate_when_pending_url_exists(self, monkeypatch):
        # Arrange
        streamlit.session_state["_sgl_pending_auth_url"] = (
            "https://accounts.google.com/existing"
        )
        build_flow = MagicMock()
        monkeypatch.setattr(sgl, "_build_flow", build_flow)

        # Act / Assert
        with pytest.raises(Stopped):
            sgl._show_login_link(
                make_config(), sgl._BASE_SCOPES, "select_account", "Please log in"
            )
        build_flow.assert_not_called()


class TestRequireLogin:
    def test_returns_cached_session_without_touching_query_params(self):
        # Arrange
        streamlit.session_state["_sgl_email"] = "user@example.com"
        streamlit.session_state["_sgl_credentials"] = "fake-creds"
        streamlit.query_params["code"] = "should-be-ignored"

        # Act
        result = sgl.require_login(
            [], client_id="id", client_secret="secret", redirect_uri="https://x.com/cb"
        )

        # Assert
        assert result == ("user@example.com", "fake-creds")

    def test_merges_base_scopes_with_additional_scopes(self, monkeypatch):
        # Arrange
        captured = {}

        def fake_show_login_link(config, scopes, prompt, login_prompt):
            captured["scopes"] = scopes
            raise Stopped

        monkeypatch.setattr(sgl, "_show_login_link", fake_show_login_link)

        # Act / Assert
        with pytest.raises(Stopped):
            sgl.require_login(
                ["https://www.googleapis.com/auth/drive.readonly"],
                client_id="id",
                client_secret="secret",
                redirect_uri="https://x.com/cb",
            )
        assert captured["scopes"] == sgl._BASE_SCOPES + [
            "https://www.googleapis.com/auth/drive.readonly"
        ]

    def test_does_not_duplicate_base_scopes(self, monkeypatch):
        # Arrange
        captured = {}

        def fake_show_login_link(config, scopes, prompt, login_prompt):
            captured["scopes"] = scopes
            raise Stopped

        monkeypatch.setattr(sgl, "_show_login_link", fake_show_login_link)

        # Act / Assert
        with pytest.raises(Stopped):
            sgl.require_login(
                list(sgl._BASE_SCOPES),
                client_id="id",
                client_secret="secret",
                redirect_uri="https://x.com/cb",
            )
        assert captured["scopes"] == sgl._BASE_SCOPES

    def test_dispatches_to_error_handler(self, monkeypatch):
        # Arrange
        streamlit.query_params["error"] = "access_denied"
        handler = MagicMock(side_effect=Stopped)
        monkeypatch.setattr(sgl, "_handle_sign_in_error", handler)

        # Act / Assert
        with pytest.raises(Stopped):
            sgl.require_login(
                [],
                client_id="id",
                client_secret="secret",
                redirect_uri="https://x.com/cb",
            )
        handler.assert_called_once()

    def test_dispatches_to_callback_handler(self, monkeypatch):
        # Arrange
        streamlit.query_params["code"] = "auth-code"
        handler = MagicMock(side_effect=Stopped)
        monkeypatch.setattr(sgl, "_handle_oauth_callback", handler)

        # Act
        with pytest.raises(Stopped):
            sgl.require_login(
                [],
                allowed_domain="markmi.ai",
                client_id="id",
                client_secret="secret",
                redirect_uri="https://x.com/cb",
            )

        # Assert
        handler.assert_called_once()
        args, kwargs = handler.call_args
        assert args[2] == "markmi.ai"

    def test_shows_login_link_by_default(self, monkeypatch):
        # Arrange
        handler = MagicMock(side_effect=Stopped)
        monkeypatch.setattr(sgl, "_show_login_link", handler)

        # Act / Assert
        with pytest.raises(Stopped):
            sgl.require_login(
                [],
                client_id="id",
                client_secret="secret",
                redirect_uri="https://x.com/cb",
            )
        handler.assert_called_once()

    def test_rejects_insecure_redirect_uri(self):
        # Act / Assert
        with pytest.raises(RuntimeError, match="must use https"):
            sgl.require_login(
                [],
                client_id="id",
                client_secret="secret",
                redirect_uri="http://example.com/cb",
            )


class TestLogout:
    def test_clears_only_sgl_prefixed_keys(self):
        # Arrange
        streamlit.session_state.update(
            {"_sgl_email": "x", "_sgl_credentials": "y", "other_key": "z"}
        )

        # Act
        sgl.logout()

        # Assert
        assert streamlit.session_state == {"other_key": "z"}
