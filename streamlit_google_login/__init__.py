"""
Drop-in Google OAuth login for internal Streamlit data apps.

    from streamlit_google_login import require_login, logout

    email, credentials = require_login(scopes=[], allowed_domain="markmi.ai")
    st.button("Log out", on_click=logout)

scopes are additional scopes beyond identity; openid/userinfo.email are
always requested too (see _BASE_SCOPES).

Config comes from st.secrets["auth"] or kwargs -- no dev-mode fallback,
missing/incomplete config raises.

CSRF state and the PKCE code_verifier are both bound to the browser via
real cookies (see cookies.py), not just signed tokens, so a forwarded
callback URL can't be replayed by someone else. PKCE is used even
though this is a confidential client, per RFC 9700 guidance.
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

import requests
import streamlit as st
from oauthlib.oauth2 import OAuth2Error

from .config import Config
from .cookies import read_cookies_with_retry, write_cookie

if TYPE_CHECKING:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import Flow

_BASE_SCOPES = ["openid", "https://www.googleapis.com/auth/userinfo.email"]
_STATE_COOKIE_NAME = "sgl_oauth_state"
_CODE_VERIFIER_COOKIE_NAME = "sgl_oauth_code_verifier"
_SESSION_PREFIX = "_sgl_"


def logout() -> None:
    for key in list(st.session_state.keys()):
        if key.startswith(_SESSION_PREFIX):
            st.session_state.pop(key, None)


def _build_flow(
    config: Config,
    scopes: list[str],
    state: str | None = None,
    code_verifier: str | None = None,
    autogenerate_code_verifier: bool = False,
) -> Flow:
    from google_auth_oauthlib.flow import Flow

    client_config = {
        "web": {
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [config.redirect_uri],
        }
    }
    return Flow.from_client_config(
        client_config,
        scopes=scopes,
        state=state,
        redirect_uri=config.redirect_uri,
        code_verifier=code_verifier,
        autogenerate_code_verifier=autogenerate_code_verifier,
    )


def _reject_insecure_redirect_uri(config: Config) -> None:
    if config.secure:
        return

    if config.is_local_http:
        os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
        return

    raise RuntimeError(
        "streamlit_google_login.require_login(): redirect_uri "
        f"({config.redirect_uri!r}) must use https://, or http:// for local "
        "development (http://localhost or http://127.0.0.1 only)."
    )


def _handle_sign_in_error() -> None:
    error = st.query_params.get("error")
    st.query_params.clear()
    st.error(f"Google sign-in was not completed ({error}). Please try logging in again.")
    st.stop()


def _handle_oauth_callback(config: Config, scopes: list[str], allowed_domain: str | None) -> None:
    code = st.query_params["code"]
    state = st.query_params.get("state")
    st.query_params.clear()

    cookies = read_cookies_with_retry(_STATE_COOKIE_NAME)
    expected_state = cookies.get(_STATE_COOKIE_NAME)
    code_verifier = cookies.get(_CODE_VERIFIER_COOKIE_NAME)

    if not expected_state or state != expected_state or not code_verifier:
        st.error("Login request expired or was tampered with. Please try logging in again.")
        st.stop()

    try:
        flow = _build_flow(config, scopes, state=state, code_verifier=code_verifier)
        flow.fetch_token(code=code)
        credentials = flow.credentials
        response = requests.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {credentials.token}"},
            timeout=10,
        )
        response.raise_for_status()
    except (OAuth2Error, Warning, requests.exceptions.RequestException):
        st.error("Login failed or the login link expired. Please try logging in again.")
        st.stop()

    # A KeyError here means the _BASE_SCOPES guarantee broke, not a retryable login failure.
    email = response.json()["email"]

    if allowed_domain and not email.lower().endswith(f"@{allowed_domain.lower()}"):
        st.error(f"Access is restricted to @{allowed_domain} accounts. You're logged in as {email}.")
        st.stop()

    st.session_state[f"{_SESSION_PREFIX}credentials"] = credentials
    st.session_state[f"{_SESSION_PREFIX}email"] = email
    st.rerun()


def _show_login_link(config: Config, scopes: list[str], prompt: str, login_prompt: str) -> None:
    st.write(login_prompt)
    if f"{_SESSION_PREFIX}pending_auth_url" not in st.session_state:
        # Guarded by session_state so a rerun (triggered by the cookie
        # write below) doesn't regenerate state/cookie and loop. Fixed
        # cookie names mean two concurrent logins in one browser will
        # race -- fails closed as "expired or tampered with", fine.
        flow = _build_flow(config, scopes, autogenerate_code_verifier=True)
        auth_url, state = flow.authorization_url(include_granted_scopes="true", prompt=prompt)
        write_cookie(_STATE_COOKIE_NAME, state, secure=config.secure)
        write_cookie(_CODE_VERIFIER_COOKIE_NAME, flow.code_verifier, secure=config.secure)
        st.session_state[f"{_SESSION_PREFIX}pending_auth_url"] = auth_url
    st.link_button("Log in with Google", st.session_state[f"{_SESSION_PREFIX}pending_auth_url"])
    st.stop()


def require_login(
    scopes: list[str],
    *,
    allowed_domain: str | None = None,
    client_id: str | None = None,
    client_secret: str | None = None,
    redirect_uri: str | None = None,
    prompt: str = "select_account",
    login_prompt: str = "Please log in with your Google account to continue.",
) -> tuple[str, Credentials]:
    """Returns (email, credentials).

    scopes are additional scopes on top of _BASE_SCOPES, which this
    function always requests for its own use.

    Scope-match enforcement stays strict (no OAUTHLIB_RELAX_TOKEN_SCOPE):
    if fetch_token() raises over a scope Google granted beyond what was
    requested, add it to `scopes` rather than suppressing the check.
    """
    scopes = _BASE_SCOPES + [scope for scope in scopes if scope not in _BASE_SCOPES]
    config = Config.resolve(client_id, client_secret, redirect_uri)
    _reject_insecure_redirect_uri(config)

    if f"{_SESSION_PREFIX}credentials" in st.session_state:
        return st.session_state[f"{_SESSION_PREFIX}email"], st.session_state[f"{_SESSION_PREFIX}credentials"]

    if "error" in st.query_params:
        _handle_sign_in_error()
    elif "code" in st.query_params:
        _handle_oauth_callback(config, scopes, allowed_domain)
    else:
        _show_login_link(config, scopes, prompt, login_prompt)
